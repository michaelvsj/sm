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
from agents.constants import HWStates, AgentStatus

TCP_IP = '127.0.0.1'
MGR_COMM_BUFFER = 1024
DEFAULT_CONFIG_FILE = 'config.yaml'

class Flags:
    """
    Contiene los eventos relevantes para controlar el flujo
    """

    def __init__(self):
        self.start_capture = Event()  # Manager solicita iniciar captura
        self.end_capture = Event()  # Manager solicita detener captura
        self.new_folder = Event()  # Manager pide cambio de directorio
        self.quit = Event() # Para indicar el fin de la aplicación


class AbstractHWAgent(ABC):
    def __init__(self, config_section, config_file=DEFAULT_CONFIG_FILE):
        self.logger = logging.getLogger()
        self.output_file_name = ''
        self.output_folder = ''
        self.flags = Flags()
        self.state = AgentStatus.STARTING
        self.hw_state = HWStates.NOT_CONNECTED
        self.manager_ip_address = ("0.0.0.0", 0)  # (IP, port) del manager que envia los comandos
        self.listen_port = 0  # Puerto TCP donde escuchará los comandos
        self.config_file = config_file
        self.config_section = config_section
        self.config = dict()
        self.flag_quit = Event()    #Bandera para avisar que hay que terminar el programa
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
                    self.logger.error(f"Dirección ya está en uso: {TCP_IP}:{self.local_tcp_port}. Termina programa. \nFIN\n")
                else:
                    self.logger.exception("")
                sys.exit(1)
            self.__sock.listen(1)
            self.__sock.setblocking(True)
        except KeyboardInterrupt:
            sys.exit(0)

    def __hw_connect_insist(self):
        attempts = 0
        while attempts < self.hw_connections_retries and not self.flags.quit.is_set():
            if self._agent_connect_hw():
                self.hw_state = HWStates.NOMINAL
                return True
            else:
                self.flags.quit.wait(1)
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
        while not self.flags.quit.is_set():
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
        try:
            self.output_file.close()
        except:
            pass

    def __manager_connect(self):
        connected = False
        while not connected and not self.flags.quit.is_set():
            try:
                self.logger.info("Esperando conexión de manager")
                self.connection, client_address = self.__sock.accept()
                connected = True
                self.logger.info("Manager conectado")
            except socket.timeout:
                self.logger.info("Timeout esperando conexión de manager.")
                pass
            except KeyboardInterrupt:
                raise

    def __manager_recv(self):
        cmd = b''
        while not self.flags.quit.is_set():
            try:
                bt = self.connection.recv(1)
                if not bt:
                    self.logger.warning(f"Conexión cerrada por manager")
                    self.flag_quit.wait(0.5)
                    raise ConnectionResetError
                elif bt == Message.EOT:
                    self.__process_incoming_message(Message.deserialize(cmd))
                    cmd = b''
                else:
                    cmd += bt
            except TimeoutError:
                pass
            except ConnectionResetError:
                self.__manager_connect()

    def __manager_send(self, msg):
        try:
            self.connection.sendall(msg)
        except BrokenPipeError:
            pass
        except OSError as e:
            if e.errno == errno.EBADF:
                if not self.flags.quit.is_set():
                    self.logger.warning(f"No se pudo enviar mensje {msg} al manager. Se perdió la conexión.")
            else:
                self.logger.exception("")

    def __process_incoming_message(self, msg: Message):
        if msg.arg == Message.CMD_QUERY_AGENT_STATE:
            self.__manager_send(Message.agent_state(self.state).serialize())
        elif msg.arg == Message.CMD_QUERY_HW_STATE:
            self.__manager_send(Message.agent_hw_state(self.hw_state).serialize())
        elif msg.arg == Message.CMD_QUIT:
            self.logger.info(f"Comando {msg.arg} recibido desde manager. Seteando bandera self.flags.quit")
            self.flags.quit.set()
        elif msg.typ == Message.SET_FOLDER:
            self.__update_capture_file(msg.arg)
        elif msg.arg == Message.CMD_END_CAPTURE:
            self.flags.end_capture.set()
        elif msg.arg == Message.CMD_START_CAPTURE:
            self.flags.start_capture.set()
        else:  # Todos los demás mensajes deben ser procesados por el agente particular
            self._agent_process_manager_message(msg)

    def __hw_check(self):
        while not self.flags.quit.is_set():
            if not self._agent_check_hw_connected():
                self.hw_state = HWStates.NOT_CONNECTED
            self.flags.quit.wait(1)

    def _send_data_to_mgr(self, data):
        msg = Message(_type=Message.DATA, arg=data).serialize()
        self.__manager_send(msg)

    def _send_msg_to_mgr(self, msg: Message):
        self.__manager_send(msg.serialize())

    def run(self):
        wrt = Thread(target=self.__file_writer)
        mgr_comm = Thread(target=self.__manager_recv)
        hw_check = Thread(target=self.__hw_check)
        try:
            self.__manager_connect()

            self.logger.info("Iniciando thread de verificación de HW conectado")
            hw_check.start()

            self.logger.info("Iniciando thread de comunicación con manager")
            mgr_comm.start()

            if self.__hw_connect_insist():
                self.state = AgentStatus.STAND_BY
            else:
                self.logger.error(f"No fue posible conectarse al hardware. Intentos: {self.hw_connections_retries}. "
                                  f"Terminando proceso")
                sys.exit(1)

            self.logger.info("Iniciando thread de escritura a disco")
            if self.output_file_name:
                wrt.start()

            self.logger.info("Iniciando threads de manejo de datos de hardware")
            self._agent_run_data_threads()

            self.logger.info("Iniciando bucle principal")
            while not self.flags.quit.is_set():
                time.sleep(0.01)
                if self.flags.start_capture.is_set():
                    self.flags.start_capture.clear()
                    self.state = AgentStatus.CAPTURING
                    self.logger.info(f"Cambiando estado a {self.state}")
                if self.flags.end_capture.is_set():
                    self.flags.end_capture.clear()
                    self.state = AgentStatus.STAND_BY
                    self.logger.info(f"Cambiando estado a {self.state}")
                if self.hw_state == HWStates.NOT_CONNECTED or self.hw_state == HWStates.ERROR:
                    self.logger.error(f"Hardware en estado {self.hw_state}. Se intentará reconexion.")
                    self.state = AgentStatus.STARTING
                    self.logger.info(f"Cambiando estado a {self.state}")
                    self._agent_disconnect_hw()
                    if self.__hw_connect_insist():
                        self.state = AgentStatus.STAND_BY
                        self.logger.info(f"Cambiando estado a {self.state}")
                    else:
                        self.logger.error(f"No fue posible conectarse al hardware. Intentos: {self.hw_connections_retries}. \nFIN\n")
                        break
        except KeyboardInterrupt:
            self.logger.info("Señal INT recibida")
        except Exception:
            self.logger.exception("")
        finally:
            self.logger.info("Terminando aplicación")
            self.flags.quit.set()
            if wrt.is_alive():
                wrt.join(0.1)
            if mgr_comm.is_alive():
                mgr_comm.join(0.1)
            if hw_check.is_alive():
                hw_check.join(0.1)
            self._agent_finalize()
            self.logger.info("Aplicación terminada\nFIN\n")

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
    def _agent_connect_hw(self) -> bool:
        """
        Debe salir indicando si la conexión fue exitosa (True) o no (False)
        """
        pass

    @abstractmethod
    def _agent_disconnect_hw(self):
        pass

    @abstractmethod
    def _agent_check_hw_connected(self) -> bool:
        """
        Debe retornar True si el hardware está conectado o false de lo contrario
        """
        pass
