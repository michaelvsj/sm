from abc import ABC, abstractmethod, abstractproperty
from os import path

import yaml
from enum import Enum, auto
import logging, logging.config
from collections import deque
import socket
from threading import Thread, Event

TCP_IP = '127.0.0.1'
MGR_COMM_BUFFER = 1024

class Commands:
    START_CAPTURE = 'c'
    STOP_CAPTURE = 'd'
    SET_FOLDER = 'f'
    QUERY_AGENT_STATE = 'q'
    QUERY_HW_STATE = 'h'


class AgentStatus:
    """
    Contiene los estados (mutuamente excluyentes) posibles de los agentes
    """
    STARTING = 'STARTING'  # Iniciando o re-iniciando. En este último caso, presumiblemente porque se produjo un error y está reconectandose al hardware
    STAND_BY = 'STAND_BY'  # Listo para capturar
    CAPTURING = 'CAPTURING'  # Capturando
    NOT_RESPONDING = 'NOT_RESPONDING'  # Agente no responde. A partir de este estado se puede gatillar un evento para reiniciar el agente


class HWStatus(Enum):
    """
    Contiene los estados (mutuamente excluyentes) posibles de los equipos de hardware
    En general esto es solo para efectos informativos ya que el mismo agente debe reiniciar o reconectarse en caso de error
    """
    NOMINAL = 'NOMINAL'  # Conectado y no se detectan errores
    WARNING = 'WARNING'  # Conectado pero con algun tipo de problema. E.g. pérdida de datos, coordenada 0, datos fuera de rango, etc. IMplica que sensor está con capacidades operatuvas reducidas
    ERROR = 'ERROR'  # Conectado pero en estado de error. Implica que el sensor no está operativo.
    NOT_CONNECTED = 'NOT_CONNECTED'  # No es posible establecer conexión al equipo (No se puede abrir puerto COM, conexión TCP, etc).


class AbstractHWAgent(ABC):
    def __init__(self, config_file):
        self.logger = logging.getLogger()  # TODO Puedo configurarlo a posteriori?????????????
        self.output_file_name = ''
        self.state = AgentStatus.STARTING
        self.hw_state = HWStatus.DISCONNECTED
        self.manager_address = ("0.0.0.0", 0)  # (IP, port) del manager que envia los comandos
        self.listen_port = 0  # Puerto TCP donde escuchará los comandos
        self.config_file = config_file
        self.config = dict()
        self.flag_quit = Event()    #Bandera para avisar que hay que terminar el programa
        self.dq_from_mgr = deque()  #deque con los comandos provenientes del manager
        self.dq_to_mgr = deque() #deque con datos hacia el manager
        self.dq_formatted_data = deque() #Deque que contiene la data formateada lista para escribir a disco
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.local_tcp_port = ''
        self.manager_port = ''
        self.connection = None
        self.current_folder = ''
        self.output_file_header = ''  # Debe ser redefinido por las clases que implementen la AbstractHWAgent
        self.output_file_is_binary = None
        self.output_file = None


    def set_up(self):
        self.configure()  # Los parámetros de comunicación los lee de la config también
        self.connect_to_manager()
        self.connect_hw()
        self.state = AgentStatus.STAND_BY

    def configure(self):
        self.config = yaml.load(open(self.config_file).read(), Loader=yaml.FullLoader)
        logging.config.dictConfig(self.config['logging'])
        self.manager_address = self.config["manager_address"]
        self.manager_port = self.config["manager_port"]
        self.local_tcp_port = self.config["local_port"]
        self.output_file_name = self.config["output_file_name"]

    def run(self):
        mgr_comm = Thread(target=self.manager_comm)
        mgr_comm.run()
        wrt = Thread(target=self.writer)
        wrt.start()

        self.run_hw_data_threads()
        try:
            while True:
                if len(self.dq_from_mgr):
                    mgr_command = self.dq_from_mgr.pop()
                    print("Command from manager: {mgr_command}")
                    if mgr_command == Commands.STOP_CAPTURE:
                        self.stop_capture()
                        self.state = AgentStatus.STAND_BY
                    elif mgr_command == Commands.START_CAPTURE:
                        self.start_capture()
                        self.state = AgentStatus.CAPTURING
                    elif mgr_command == Commands.QUERY_AGENT_STATE:
                        self.dq_to_mgr.appendleft(self.state)
                    elif mgr_command == Commands.QUERY_HW_STATE:
                        self.dq_to_mgr.appendleft(self.hw_state)
                if self.hw_state == HWStatus.DISCONNECTED or self.hw_state == HWStatus.ERROR:
                    if self.state == AgentStatus.CAPTURING:
                        self.state = AgentStatus.STARTING
                        self.stop_capture()
                        self.reset_hw_connection()
                        self.start_capture()
                    elif self.state == AgentStatus.STAND_BY:
                        self.state = AgentStatus.STARTING
                        self.reset_hw_connection()

        except KeyboardInterrupt:
            self.stop_hw_data_threads()

    def update_capture_file(self, new_file_path):
        self.output_file.flush()
        self.output_file.close()
        if self.output_file_is_binary is None:
            print("Error. Atributo self.output_file_is_binary debe ser True o False")
            return
        output_write_mode = 'wb' if self.output_file_is_binary else 'w'
        self.output_file = open(path.join(new_file_path, self.output_file_name), output_write_mode)
        if self.output_file_header:
            self.output_file.write(self.output_file_header)

    def writer(self):
        while not self.flag_quit.is_set():
            if self.state == AgentStatus.CAPTURING and self.output_file is not None and self.output_file.writable():
                self.output_file.write(self.dq_formatted_data.pop())

    @abstractmethod
    def run_hw_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    @abstractmethod
    def stop_hw_data_threads(self):
        """
        Lecanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    @abstractmethod
    def start_capture(self):
        """
        Inicia el guardado de datos a disco. Puede ser algo tan simple como setear un flag
        """
        pass

    @abstractmethod
    def stop_capture(self):
        """
        Detiene el guardado de datos a disco. Puede ser algo tan simple como setear un flag
        """
        pass

    @abstractmethod
    def connect_hw(self):
        pass

    @abstractmethod
    def reset_hw_connection(self):
        pass

    def connect_to_manager(self):
        self.sock.bind((TCP_IP, self.local_tcp_port))
        self.sock.listen(1)
        self.sock.setblocking(True)
        self.connection, client_address = self.sock.accept()
        self.logger.info("Manger connected !!!")
        self.state = AgentStatus.STAND_BY

    def manager_comm(self):
        """
        Este método debe recibir, parsear y colocar las instrucciones desde el manager en un deque para ser leido desde el bucle principal
        :return:
        """
        while not self.flag_quit.is_set():
            data = self.connection.recv(MGR_COMM_BUFFER)
            if not data:  # Se cerró la conexion
                self.logger.warning("Connection reset by manager")
            else:
                cmd = data.decode("ascii")
                self.dq_from_mgr.appendleft(cmd)
            if len(self.dq_to_mgr):
                self.connection.send(self.dq_to_mgr.pop())
        self.connection.close()


"""--------------------------------------------------------------"""

CONFIG_FILE = "config.yaml"


class TestAgent(AbstractHWAgent):
    def __init__(self):
        AbstractHWAgent.__init__(self, CONFIG_FILE)

    def connect_hw(self):
        pass

    def disconnect_hw(self):
        pass

    def reset_hw_connection(self):
        pass

    def connect_to_manager(self):
        pass

    def disconnect_from_manager(self):
        pass

    def reconnect_to_manager(self):
        pass

    def run(self):
        print(self.manager_address)


if __name__ == "__main__":
    agent = TestAgent()
    agent.set_up()
    agent.run()
