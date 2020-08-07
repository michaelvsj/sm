import socket
import time
from threading import Thread
import logging
from queue import SimpleQueue
from messaging.messaging import Message, AgentStatus
from constants import HWStates

class AgentInterface:
    def __init__(self, ip_addr, ip_port):
        self.__ip_adress = ip_addr
        self.__ip_port = ip_port
        self.__connection = None
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.__sock.setblocking(True)
        self.__connected = False
        self.q_msg_in = SimpleQueue()
        self.agent_status = AgentStatus.NOT_RESPONDING
        self.hw_status = HWStates.NOT_CONNECTED
        self.enabled = False
        self.logger = logging.getLogger("AgentInterface")

    def connect(self):
        ct = Thread(target=self.__connect_insist)
        ct.start()
        rt = Thread(target=self.__receive, daemon=True)
        rt.start()
        st = Thread(target=self.__check_state, daemon=True)
        st.start()

    def __check_state(self):
        while True:
            if self.__connected:
                self.send_msg(Message.cmd_query_agent_state().serialize())
                time.sleep(1)
                self.send_msg(Message.cmd_query_hw_state().serialize())
                time.sleep(1)

    def __connect_insist(self):
        error = False
        while not self.__connected:
            try:
                self.__sock.connect((self.__ip_adress, self.__ip_port))
                self.__connected = True
            except ConnectionRefusedError:
                if not error:
                    error = True
                    self.logger.warning(f"Conection rechazada a {self.__ip_adress}:{self.__ip_port}. Reintentando")
                time.sleep(1)
            except Exception:
                if not error:
                    error = True
                self.logger.exception(f"Fallo de conexión a {self.__ip_adress}:{self.__ip_port}. Reintentando")
                time.sleep(1)

    def __receive(self):
        cmd = b''
        while True:
            if self.__connected:
                try:
                    bt = self.__sock.recv(1)
                    if not bt:
                        self.logger.warning(f"Conexión cerrada por manager")
                        self.__connect_insist()  # Intenta reconexión
                    elif bt == Message.EOT:
                        msg = Message.deserialize(cmd)
                        if msg.typ == Message.AGENT_STATE:
                            self.agent_status = msg.arg
                        elif msg.typ == Message.DEVICE_STATE:
                            self.hw_status = msg.arg
                        elif msg.typ == Message.DATA:
                            self.q_msg_in.put(msg.arg)
                        cmd = b''
                    else:
                        cmd += bt
                except TimeoutError:
                    pass

    def disconnect(self):
        self.__sock.close()
        self.__connected = False

    def is_connected(self):
        return self.__connected

    def get_msg(self, block=False):
        if block:
            return self.q_msg_in.get()
        else:
            if not self.q_msg_in.empty():
                return self.q_msg_in.get()
            else:
                return None

    def send_msg(self, msg: Message):
        if self.__connected:
            self.__sock.sendall(msg.serialize())
            return True
        else:
            return False
