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
from helpers import check_dev

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

    def _agent_run_non_hw_threads(self):
        pass

    def _agent_finalize(self):
        self.__thread_image_cap.join(self.period + 0.5)

    def _agent_hw_start(self):
        if check_dev(self.dev_file):
            self.hw_state = HWStates.NOMINAL
            self.flags.hw_stopped.clear()
            self.__thread_image_cap = Thread(target=self.__capture_image)
            self.__thread_image_cap.start()
            return True
        else:
            self.hw_state = HWStates.NOT_CONNECTED
            return False

    def _agent_hw_stop(self):
        self.flags.hw_stopped.set()
        self.__thread_image_cap.join(1.1)

    def _pre_capture_file_update(self):
        pass

    def __capture_image(self):
        while not self.flags.quit.is_set() and not self.flags.hw_stopped.is_set():
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

    def _agent_check_hw_connected(self):
        return check_dev(self.dev_file)


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    agent = CameraAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
