import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
import subprocess

import init_agent
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from constants import HWStates, AgentStatus

IMAGES_FOLDER = "img"


class CameraAgent(AbstractHWAgent):
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
        self.resolution = self.config["resolution"]
        self.period = self.config["period"]
        self.dev_file = self.config["dev_file"]

    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        self.__image_cap_thread = Thread(target=self.__capture_image)
        self.__image_cap_thread.start()

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
        self.__image_cap_thread.join(self.period + 0.5)

    def _agent_start_capture(self):
        """
        Inicia stream de datos desde el sensor
        """
        self.state = AgentStatus.CAPTURING
        
    def _agent_stop_capture(self):
        """
        Detiene el stream de datos desde el sensor
        """
        self.state = AgentStatus.STAND_BY

    def _agent_connect_hw(self):
        # Todo: verificar que cámara esté conectada
        self.hw_state = HWStates.NOMINAL
        return True

    def _agent_reset_hw_connection(self):
        self._agent_connect_hw()

    def _pre_capture_file_update(self):
        pass

    def __capture_image(self):
        while not self.flag_quit.is_set():
            if not self.output_folder or not self.state == AgentStatus.CAPTURING or self.hw_state == HWStates.NOT_CONNECTED:
                time.sleep(0.1)
                continue
            command_time = time.time()
            try:
                path = os.path.join(self.output_folder, IMAGES_FOLDER)
                Path(path).mkdir(parents=False, exist_ok=True)
                file_name = os.path.join(path, f"{command_time:.1f}.jpeg")
                cp = subprocess.run(["fswebcam", "-r", self.resolution, "--no-banner", "-q", "--save", file_name], capture_output=True)
                if cp.returncode or not os.path.exists(file_name):
                    self.hw_state = HWStates.ERROR
                else:
                    self.hw_state = HWStates.NOMINAL
                elapsed_time = time.time() - command_time
                if elapsed_time > self.period:
                    self.logger.warning(
                        f"El tiempo que se tarda 'fswebcam' en adquirir la imagen ({elapsed_time:.2f} seg) es "
                        f"superior al periodo establecido de {self.period} seg")
                time.sleep(max(self.period - elapsed_time, 0))
            except Exception:
                self.logger.exception("")

if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    agent = CameraAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
