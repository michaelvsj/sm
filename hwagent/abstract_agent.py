from abc import ABC, abstractmethod
from os import path
import sys
import time
import os, errno
import yaml
import logging, logging.config
from collections import deque
import socket
from threading import Thread, Event
from messaging.messaging import Message
from constants import HWStates, Devices, AgentStatus

TCP_IP = '127.0.0.1'
MGR_COMM_BUFFER = 1024
DEFAULT_CONFIG_FILE = 'config.yaml'


class AbstractHWAgent(ABC):
    def __init__(self, config_section, config_file=DEFAULT_CONFIG_FILE):
        self.logger = logging.getLogger()
        self.output_file_name = ''
        self.output_folder = ''
        self.state = AgentStatus.STARTING
        self.hw_state = HWStates.NOT_CONNECTED
        self.manager_ip_address = ("0.0.0.0", 0)  # (IP, port) del manager que envia los comandos
        self.listen_port = 0  # Puerto TCP donde escuchará los comandos
        self.config_file = config_file
        self.config_section = config_section
        self.config = dict()
        self.flag_quit = Event()    #Bandera para avisar que hay que terminar el programa
        self.dq_from_mgr = deque()  #deque con los comandos provenientes del manager
        self.dq_formatted_data = deque() #Deque que contiene la data formateada lista para escribir a disco
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.local_tcp_port = ''
        self.manager_tcp_port = ''
        self.connection = None
        self.current_folder = ''
        self.output_file_header = ''  # Debe ser redefinido por las clases que implementen la AbstractHWAgent
        self.output_file_is_binary = None
        self.output_file = None

    def set_up(self):
        try:
            self.__configure()  # Los parámetros de comunicación los lee de la config también
            self.logger.info("Aplicación configurada e iniciando")
            try:
                self.__sock.bind((TCP_IP, self.local_tcp_port))
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    self.logger.error(f"Dirección ya está en uso: {TCP_IP}:{self.local_tcp_port}")
                else:
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
        except KeyboardInterrupt:
            sys.exit(0)

    def __hw_connect_insist(self):
        attempts = 0
        while attempts < self.hw_connections_retries:
            if self._agent_connect_hw():
                self.hw_state = HWStates.NOMINAL
                return True
            else:
                attempts += 1
        return False

    def __configure(self):
        full_config = yaml.load(open(self.config_file).read(), Loader=yaml.FullLoader)
        logging.config.dictConfig(full_config["logging"])
        self.manager_ip_address = full_config["manager_ip"]
        self.config = full_config[self.config_section]
        self.manager_tcp_port = self.config["manager_port"]
        self.local_tcp_port = self.config["local_port"]
        self.hw_connections_retries = self.config["hw_connection_retries"]
        try:
            self.output_file_name = self.config["output_file_name"]
        except KeyError:
            pass
        self._agent_config()

    def __update_capture_file(self, new_file_path):
        self.logger.info(f"Cambio de directorio a {new_file_path}")
        self.output_folder = new_file_path
        if not self.output_file_name:   # Si no está definido el nombre de arrchivo (presumiblemente porque no se genera)
            return
        if self.output_file_is_binary is None:
            self.logger.error("Error. Atributo self.output_file_is_binary debe ser True o False")
            print("Error. Atributo self.output_file_is_binary debe ser True o False")
            return
        if self.output_file is not None:
            self.output_file.flush()
            self.output_file.close()
            self._pre_capture_file_update()
        write_mode = 'wb' if self.output_file_is_binary else 'w'
        self.output_file = open(path.join(new_file_path, self.output_file_name), write_mode)
        if self.output_file_header:
            self.output_file.write(self.output_file_header + os.linesep)

    def __file_writer(self):
        while not self.flag_quit.is_set():
            if self.state == AgentStatus.CAPTURING \
                    and self.output_file is not None \
                    and len(self.dq_formatted_data) \
                    and not self.output_file.closed:
                try:
                    if self.output_file_is_binary:
                        self.output_file.write(self.dq_formatted_data.popleft())
                    else:
                        self.output_file.write(self.dq_formatted_data.popleft() + os.linesep)
                except ValueError:  # Archivo se cerró entremedio
                    pass
            else:
                time.sleep(0.1)

    def __manager_connect(self):
        self.logger.info("Esperando conexión de manager")
        connected = False
        while not connected and not self.flag_quit.is_set():
            try:
                self.connection, client_address = self.__sock.accept()
                connected = True
            except socket.timeout:
                self.logger.info("Timeout esperando conexión de manager. Sigo esperando.")
                pass
            except KeyboardInterrupt:
                raise
        self.logger.info("Manager conectado")
        self.state = AgentStatus.STAND_BY

    def __manager_recv(self):
        """
        Este método debe recibir, parsear y colocar las instrucciones desde el manager en un deque para ser leido desde el bucle principal
        :return:
        """
        cmd = b''
        while not self.flag_quit.is_set():
            try:
                bt = self.connection.recv(1)
                if not bt:
                    self.logger.warning(f"Conexión cerrada por manager")
                    self.__manager_connect()  # Intenta reconexión
                elif bt == Message.EOT:
                    self.dq_from_mgr.appendleft(Message.deserialize(cmd))
                    cmd = b''
                else:
                    cmd += bt
            except TimeoutError:
                pass
        self.connection.close()

    def __manager_send(self, msg):
        try:
            self.connection.sendall(msg)
        except BrokenPipeError:
            pass

    def _send_data_to_mgr(self, data):
        msg = Message(_type=Message.DATA, arg=data).serialize()
        self.__manager_send(msg)

    def run(self):
        self.logger.info("Iniciando thread de comunicación con manager")
        mgr_comm = Thread(target=self.__manager_recv, daemon=True)
        mgr_comm.start()

        self.logger.info("Iniciando thread de escritura a disco")
        wrt = Thread(target=self.__file_writer)
        if self.output_file_name:
            wrt.start()

        self.logger.info("Iniciando threads de manejo de datos de hardware")
        self._agent_run_data_threads()
        self.logger.info("Iniciando bucle principal")
        try:
            while True:
                time.sleep(0.01)
                if len(self.dq_from_mgr):
                    msg = self.dq_from_mgr.pop()
                    self.logger.info(f"Comando recibido desde manager: {msg.typ}, {msg.arg}")
                    if msg.arg == Message.CMD_END_CAPTURE:
                        self._agent_stop_streaming()
                        self.state = AgentStatus.STAND_BY
                    elif msg.arg == Message.CMD_START_CAPTURE:
                        self._agent_start_streaming()
                        self.state = AgentStatus.CAPTURING
                    elif msg.arg == Message.CMD_QUERY_AGENT_STATE:
                        self.__manager_send(Message.agent_state(self.state).serialize())
                    elif msg.arg == Message.CMD_QUERY_HW_STATE:
                        self.__manager_send(Message.device_state(self._get_device_name(), self.hw_state).serialize())
                    elif msg.typ == Message.SET_FOLDER:
                        self.__update_capture_file(msg.arg)
                    else: # Todos los demás mensajes deben ser procesados por el agente particular
                        self._agent_process_manager_message(msg)
                if self.hw_state == HWStates.NOT_CONNECTED or self.hw_state == HWStates.ERROR:
                    if self.state == AgentStatus.CAPTURING:
                        self.state = AgentStatus.STARTING
                        self._agent_stop_streaming()
                        self._agent_reset_hw_connection()
                        self._agent_start_streaming()
                    elif self.state == AgentStatus.STAND_BY:
                        self.state = AgentStatus.STARTING
                        self._agent_reset_hw_connection()
        except KeyboardInterrupt:
            self.logger.info("Señal INT recibida")
        except Exception:
            self.logger.exception("")
        finally:
            self.logger.info("Terminando aplicación")
            self.flag_quit.set()
            if wrt.is_alive():
                wrt.join(0.5)
            self._agent_finalize()
            self.connection.close()
            self.__sock.close()
            self.logger.info("Aplicación terminada")

    @abstractmethod
    def _get_device_name(self):
        """

        :return: El identificador del hardware asociado al agente. Debe estar definifo en devices.Devices
        """
        pass

    @abstractmethod
    def _agent_process_manager_message(self, msg: Message):
        """
        Procesa los mensajes del manager que son más especificos del agente
        :return:
        """
        pass

    @abstractmethod
    def _pre_capture_file_update(self):
        """
        Poner aquí codigo que se ejecute justo antes de que se abra el nuevo archivo de salida de datos.
        Por ejemplo, calcular alguna estadistica del archivo de captura anterior o resetear alguna variable que se escriba a archivo
        :return:
        """
        pass

    @abstractmethod
    def _agent_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        pass

    @abstractmethod
    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    @abstractmethod
    def _agent_finalize(self):
        """
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    @abstractmethod
    def _agent_start_streaming(self):
        """
        Inicia stream de datos desde el sensor
        """
        pass

    @abstractmethod
    def _agent_stop_streaming(self):
        """
        Detiene el stream de datos desde el sensor
        """
        pass

    @abstractmethod
    def _agent_connect_hw(self) -> bool:
        """
        Debe salir indicando si la conexión fue exitosa (True) o no (False)
        """
        pass

    @abstractmethod
    def _agent_reset_hw_connection(self):
        pass
