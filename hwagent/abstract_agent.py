from abc import ABC, abstractmethod, abstractproperty
from os import path
import sys
import time
import json

import yaml
from enum import Enum, auto
import logging, logging.config
from collections import deque
import socket
from threading import Thread, Event

TCP_IP = '127.0.0.1'
MGR_COMM_BUFFER = 1024


class Message:
    START_CAPTURE = 'START_CAPTURE'
    END_CAPTURE = 'END_CAPTURE'
    SET_FOLDER = 'SET_FOLDER'
    QUERY_AGENT_STATE = 'QUERY_AGENT_STATE'
    INFORM_AGENT_STATE = 'INFORM_AGENT_STATE'
    QUERY_HW_STATE = 'QUERY_HW_STATE'
    INFORM_HW_STATE = 'INFORM_HW_STATE'
    DATA = 'DATA'

    def __init__(self, cmd, arg=''):
        self.cmd = cmd
        self.arg = arg

    @classmethod
    def from_yaml(cls, yml):
        if isinstance(yml, (bytes, bytearray)):
            yml = yml.decode('ascii')
        d = dict(yaml.safe_load(yml))
        return cls(d['cmd'], d['arg'])

    def __eq__(self, other):
        if isinstance(other, str):
            return  self.cmd == other
        elif isinstance(other, Message):
            return self.cmd == other.cmd
        elif isinstance(other, dict):
            return self.cmd == other['cmd']
        else:
            return False

    def serialize(self):
        return yaml.dump({'cmd': self.cmd, 'arg': self.arg}).encode('ascii')


class AgentStatus:
    """
    Contiene los estados (mutuamente excluyentes) posibles de los agentes
    """
    STARTING = 'STARTING'  # Iniciando o re-iniciando. En este último caso, presumiblemente porque se produjo un error y está reconectandose al hardware
    STAND_BY = 'STAND_BY'  # Listo para capturar
    CAPTURING = 'CAPTURING'  # Capturando
    NOT_RESPONDING = 'NOT_RESPONDING'  # Agente no responde. A partir de este estado se puede gatillar un evento para reiniciar el agente


class HWStatus:
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
        self.logger = logging.getLogger()
        self.output_file_name = ''
        self.state = AgentStatus.STARTING
        self.hw_state = HWStatus.NOT_CONNECTED
        self.manager_address = ("0.0.0.0", 0)  # (IP, port) del manager que envia los comandos
        self.listen_port = 0  # Puerto TCP donde escuchará los comandos
        self.config_file = config_file
        self.config = dict()
        self.flag_quit = Event()    #Bandera para avisar que hay que terminar el programa
        self.dq_from_mgr = deque()  #deque con los comandos provenientes del manager
        self.dq_formatted_data = deque() #Deque que contiene la data formateada lista para escribir a disco
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.local_tcp_port = ''
        self.manager_port = ''
        self.connection = None
        self.current_folder = ''
        self.output_file_header = ''  # Debe ser redefinido por las clases que implementen la AbstractHWAgent
        self.output_file_is_binary = None
        self.output_file = None

    def set_up(self):
        self.__configure()  # Los parámetros de comunicación los lee de la config también
        self.logger.info("Aplicación configurada e iniciando")
        try:
            self.__sock.bind((TCP_IP, self.local_tcp_port))
        except OSError:
            self.logger.exception("")
            sys.exit(1)
        self.__sock.listen(1)
        self.__sock.setblocking(True)
        self.__manager_connect()
        if self.__hw_connect_insist():
            self.state = AgentStatus.STAND_BY
        else:
            self.logger.error(f"No fue posible conectarse al hardware. Intentos: {self.hw_connections_retries}. "
                              f"Terminando proceso")
            sys.exit(1)

    def __hw_connect_insist(self):
        attempts = 0
        while attempts < self.hw_connections_retries:
            if self.hw_connect():
                self.hw_state = HWStatus.NOMINAL
                return True
            else:
                attempts += 1
        return False

    def __configure(self):
        self.config = yaml.load(open(self.config_file).read(), Loader=yaml.FullLoader)
        logging.config.dictConfig(self.config["logging"])
        self.manager_address = self.config["manager_ip"]
        self.manager_port = self.config["manager_port"]
        self.local_tcp_port = self.config["local_port"]
        self.output_file_name = self.config["output_file_name"]
        self.hw_connections_retries = self.config["hw_connection_retries"]
        self.hw_config()

    def __update_capture_file(self, new_file_path):
        self.logger.info(f"Cambio de directorio a {new_file_path}")
        self.pre_capture_file_update()
        if self.output_file_is_binary is None:
            self.logger.error("Error. Atributo self.output_file_is_binary debe ser True o False")
            print("Error. Atributo self.output_file_is_binary debe ser True o False")
            return
        if self.output_file is not None:
            self.output_file.flush()
            self.output_file.close()
        write_mode = 'wb' if self.output_file_is_binary else 'w'
        self.output_file = open(path.join(new_file_path, self.output_file_name), write_mode)
        if self.output_file_header:
            self.output_file.write(self.output_file_header)

    def __file_writer(self):
        while not self.flag_quit.is_set():
            if self.state == AgentStatus.CAPTURING \
                    and self.output_file is not None \
                    and self.output_file.writable() \
                    and len(self.dq_formatted_data):
                self.output_file.write(self.dq_formatted_data.pop())

    def __manager_connect(self):
        self.logger.info("Esperando conexión de manager")
        connected = False
        self.__sock.settimeout(60)
        while not connected:
            try:
                self.connection, client_address = self.__sock.accept()
                connected = True
            except socket.timeout:
                self.logger.info("Timeout esperando conexión de manager. Sigo esperando.")
                pass
        self.__sock.settimeout(0.1)
        self.logger.info("Manager conectado")
        self.state = AgentStatus.STAND_BY

    def __manager_recv(self):
        """
        Este método debe recibir, parsear y colocar las instrucciones desde el manager en un deque para ser leido desde el bucle principal
        :return:
        """
        while not self.flag_quit.is_set():
            try:
                cmd = self.connection.recv(MGR_COMM_BUFFER)
                if not cmd:  # Se cerró la conexion
                    self.logger.warning("Conexión cerrada por manager")
                    self.__manager_connect() # Intenta reconexión
                else:
                    self.dq_from_mgr.appendleft(cmd)
            except TimeoutError:
                pass
        self.logger.info("Terminando bucle __manager_recv")
        self.connection.close()

    def __manager_send(self, msg):
        self.connection.sendall(msg)

    def run(self):
        self.logger.info("Iniciando thread de comunicación con manager")
        mgr_comm = Thread(target=self.__manager_recv)
        mgr_comm.start()
        self.logger.info("Iniciando thread de escritura a disco")
        wrt = Thread(target=self.__file_writer)
        wrt.start()
        self.logger.info("Iniciando threads de manejo de datos de hardware")
        self.hw_run_data_threads()
        self.logger.info("Iniciando bucle principal")
        try:
            while True:
                if len(self.dq_from_mgr):
                    msg = Message.from_yaml(self.dq_from_mgr.pop())
                    self.logger.info(f"Comando recibido desde manager: {msg.cmd}")
                    if msg == Message.END_CAPTURE:
                        self.hw_stop_streaming()
                        self.state = AgentStatus.STAND_BY
                    elif msg == Message.START_CAPTURE:
                        self.hw_start_streaming()
                        self.state = AgentStatus.CAPTURING
                    elif msg == Message.QUERY_AGENT_STATE:
                        self.__manager_send(Message(Message.INFORM_AGENT_STATE, self.state).serialize())
                    elif msg == Message.QUERY_HW_STATE:
                        self.__manager_send(Message(Message.INFORM_HW_STATE, self.hw_state).serialize())
                    elif msg == Message.SET_FOLDER:
                        self.__update_capture_file(msg.arg)

                if self.hw_state == HWStatus.NOT_CONNECTED or self.hw_state == HWStatus.ERROR:
                    if self.state == AgentStatus.CAPTURING:
                        self.state = AgentStatus.STARTING
                        self.hw_stop_streaming()
                        self.hw_reset_connection()
                        self.hw_start_streaming()
                    elif self.state == AgentStatus.STAND_BY:
                        self.state = AgentStatus.STARTING
                        self.hw_reset_connection()
        except KeyboardInterrupt:
            self.logger.info("Señal INT recibida")
            self.flag_quit.set()
        except Exception:
            self.logger.exception("")
        finally:
            self.logger.info("Terminando aplicación")
            self.flag_quit.set()
            mgr_comm.join(0.5)
            wrt.join(0.5)
            self.hw_finalize()
            self.logger.info("Aplicación terminada")

    @abstractmethod
    def pre_capture_file_update(self):
        """
        Poner aquí codigo que se ejecute justo antes de actualizar el archivo de captura.
        Por ejemplo, enviar al manager estadísticas de la captura en el archivo actual
        :return:
        """
        pass

    @abstractmethod
    def hw_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        pass

    @abstractmethod
    def hw_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    @abstractmethod
    def hw_finalize(self):
        """
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    @abstractmethod
    def hw_start_streaming(self):
        """
        Inicia stream de datos desde el sensor
        """
        pass

    @abstractmethod
    def hw_stop_streaming(self):
        """
        Detiene el stream de datos desde el sensor
        """
        pass

    @abstractmethod
    def hw_connect(self) -> bool:
        """
        Debe salir indicando si la conexión fue exitosa (True) o no (False)
        """
        pass

    @abstractmethod
    def hw_reset_connection(self):
        pass
