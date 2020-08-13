"""
Agente "trivial" cuya única misión es reportar si hay conexión a la Internet
"""

import logging
import os
import sys
import time
from pathlib import Path
from threading import Thread, Event
import subprocess

import init_agent
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from constants import HWStates, AgentStatus


def check_ping(ip):
    try:
        if os.name == 'posix':
            subprocess.run(["ping", "-c", "1", ip], capture_output=True, check=True)
        elif os.name == 'nt':
            subprocess.run(["ping", "-n", "1", ip], capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


class InetAgent(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        self.interface = self.config["interface"]
        self.ping_ip_1 = self.config["ping_ip_1"]
        self.ping_ip_2 = self.config["ping_ip_2"]

    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        self.__main_thread = Thread(target=self.__check_connectivity)
        self.__main_thread.start()

    def _agent_finalize(self):
        """
        Se prepara para terminar el agente
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        try:
            assert (self.flag_quit.is_set())  # Este flag debiera estar seteado en este punto
        except AssertionError:
            self.logger.error("Se llamó a hw_finalize() sin estar seteado 'self.flag_quit'")
        self.__main_thread.join(0.5)

    def _agent_start_capture(self):
        """
        Inicia stream de datos desde el sensor
        """
        # No aplica
        pass

    def _agent_stop_capture(self):
        """
        Detiene el stream de datos desde el sensor
        """
        # No aplica
        pass

    def _agent_connect_hw(self):
        # No aplica. Conectividad será chequeada en bucle principal
        return True

    def _agent_reset_hw_connection(self):
        self._agent_connect_hw()

    def _pre_capture_file_update(self):
        pass

    def __check_connectivity(self):
        while not self.flag_quit.is_set():
            if check_ping(self.ping_ip_1) or check_ping(self.ping_ip_2):
                self.hw_state = HWStates.NOMINAL
            elif self.__check_iface_inet():
                self.hw_state = HWStates.WARNING
            else:
                self.hw_state = HWStates.ERROR
            time.sleep(5)

    def __check_iface_inet(self):
        if os.name == 'posix':
            return "inet " in subprocess.getoutput(f"ifconfig {self.interface}")
        elif os.name == 'nt':
            self.logger.warning("Función no implementada para Windows. Se asume que existe conexión a router")
            return True


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    Path('logs').mkdir(exist_ok=True)
    agent = InetAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
