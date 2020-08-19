"""
Agente "trivial" cuya única misión es reportar si hay conexión a la Internet
"""

import logging
import os
import sys
from threading import Thread

import init_agent
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from constants import HWStates
from helpers import check_ping, check_iface_inet


class InetAgent(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_config(self):
        self.interface = self.config["interface"]
        self.ping_ip_1 = self.config["ping_ip_1"]
        self.ping_ip_2 = self.config["ping_ip_2"]

    def _agent_run_non_hw_threads(self):
        self.__main_thread = Thread(target=self.__check_connectivity)
        self.__main_thread.start()

    def _agent_finalize(self):
        self.flags.quit.set()
        self.__main_thread.join(0.5)

    def _agent_start_capture(self):
        # No aplica
        pass

    def _agent_stop_capture(self):
        # No aplica
        pass

    def _agent_hw_start(self):
        # TODO hacer un "sudo ifup"
        return True

    def _agent_hw_stop(self):
        # TODO hacer un "sudo ifdown"
        pass

    def _pre_capture_file_update(self):
        pass

    def _agent_check_hw_connected(self):
        return check_iface_inet(self.interface)

    def __check_connectivity(self):
        while not self.flags.quit.is_set():
            if check_ping(self.ping_ip_1) or check_ping(self.ping_ip_2):
                self.hw_state = HWStates.NOMINAL
            elif check_iface_inet(self.interface):
                self.hw_state = HWStates.ERROR
            self.flags.quit.wait(5)


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    agent = InetAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
