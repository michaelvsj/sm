import socket
import time
from threading import Thread, Event
import logging
from queue import SimpleQueue
from messaging.messaging import Message
from agents.constants import HWStates, AgentStatus


class AgentInterface:
    def __init__(self, name, quit_flag: Event, ip_addr='', ip_port=0):
        self.name = name
        self.__flaq_quit = quit_flag
        self.__ip_adress = ip_addr
        self.__ip_port = ip_port
        self.__connection = None
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.__sock.setblocking(True)
        self.__connected = False
        self.q_data_in = SimpleQueue()
        self.agent_status = AgentStatus.STARTING
        self.hw_status = HWStates.NOT_CONNECTED
        self.enabled = False
        self.logger = logging.getLogger("manager")

    def set_ip_address(self, addr, port):
        self.__ip_adress = addr
        self.__ip_port = port

    def connect(self):
        if not self.__ip_port or not self.__ip_adress:
            self.logger.error(f"Primero se debe setear la direccion y puerto IP del agente {self.name}")
            return
        Thread(target=self.__connect_insist, name=f"AgentInterface({self.name}).__connect_insist", daemon=True).start()
        Thread(target=self.__receive, name=f"AgentInterface({self.name}).__receive", daemon=True).start()
        Thread(target=self.__check_state, name=f"AgentInterface({self.name}).__check_state", daemon=True).start()

    def __check_state(self):
        while not self.__flaq_quit.is_set():
            if self.__connected:
                self.send_msg(Message.cmd_query_agent_state())
                if not self.__flaq_quit.wait(1):
                    self.send_msg(Message.cmd_query_hw_state())
                    self.__flaq_quit.wait(1)

    def __connect_insist(self):
        error = False
        while not self.__connected and not self.__flaq_quit.is_set():
            try:
                self.__sock.connect((self.__ip_adress, self.__ip_port))
                self.__connected = True
            except ConnectionRefusedError:
                if not error:
                    error = True
                    self.logger.warning(f"Conexión rechazada a agente {self.name}. {self.__ip_adress}:{self.__ip_port}. Reintentando.")
                self.__flaq_quit.wait(1)
            except Exception:
                if not error:
                    error = True
                self.logger.exception(f"Fallo de conexión a {self.__ip_adress}:{self.__ip_port}. Reintentando")
                self.__flaq_quit.wait(1)

    def __receive(self):
        cmd = b''
        while not self.__flaq_quit.is_set():
            if self.__connected:
                try:
                    bt = self.__sock.recv(1)
                    if not bt:
                        self.logger.warning(f"Conexión cerrada por agente {self.name}. Reintenta conexión.")
                        self.__flaq_quit.wait(0.1)
                        self.__connect_insist()  # Intenta reconexión
                    elif bt == Message.EOT:
                        msg = Message.deserialize(cmd)
                        if msg.typ == Message.AGENT_STATE:
                            self.agent_status = msg.arg
                        elif msg.typ == Message.HW_STATE:
                            self.hw_status = msg.arg
                        elif msg.typ == Message.DATA:
                            self.q_data_in.put(msg.arg)
                        cmd = b''
                    else:
                        cmd += bt
                except TimeoutError:
                    pass
                except ConnectionResetError:
                    self.__connect_insist()

    def disconnect(self):
        self.__sock.close()
        self.__connected = False

    def is_connected(self):
        return self.__connected

    def get_data(self, block=False):
        if block:
            return self.q_data_in.get()
        else:
            if not self.q_data_in.empty():
                return self.q_data_in.get()
            else:
                return None

    def send_data(self, data):
        self.send_msg(Message.data_msg(data))

    def send_msg(self, msg: Message):
        if self.__connected:
            try:
                self.__sock.sendall(msg.serialize())
                return True
            except BrokenPipeError:
                self.logger.error(f"No se pudo enviar el mensaje al puerto {self.__ip_port}: BrokenPipe.")
            except ConnectionResetError:
                self.logger.error(f"Agente desconectado")
        else:
            return False

    def quit(self):
        self.__flaq_quit.set()
