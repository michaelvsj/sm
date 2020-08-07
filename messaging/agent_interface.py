import socket
import time
from threading import Thread
import logging


class AgentInterface:
    def __init__(self, ip_addr, ip_port):
        self.__ip_adress = ip_addr
        self.__ip_port = ip_port
        self.__connection = None
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.__sock.setblocking(True)
        self.__connected = False
        self.enabled = False
        self.logger = logging.getLogger("AgentInterface")

    def connect(self):
        ct = Thread(target=self.__connect_insist)
        ct.start()

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

    def disconnect(self):
        self.__sock.close()
        self.__connected = False

    def is_connected(self):
        return self.__connected
