import logging
import os
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event

import serial

import init_agent
from constants import AgentStatus, HWStates
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from helpers import check_dev
from yost3space.api import Yost3SpaceAPI, READ_TIMEOUT, BAUD_RATE, unpack

HEADER = "system_time (s);accel_x (g);accel_y (g);accel_z (g);gyro_x (rad/s);gyro_y (rad/s);gyro_z (rad/s);q1;q2;q3;q4"


class IMUAgent(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False
        self.com_port = ""
        self.ser = None
        self.output_file_header = HEADER
        self.__flag_stop = Event()

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        self.com_port = self.config["com_port"]
        self.sample_rate = self.config["sample_rate"]

    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    def _agent_finalize(self):
        """
        Se prepara para terminar el agente
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        try:
            assert (self.flags.quit.is_set())  # Este flag debiera estar seteado en este punto
        except AssertionError:
            self.logger.error("Se llamó a hw_finalize() sin estar seteado 'self.flags.quit'")
        self.__main_thread.join(0.1)
        self.yost_api.disconnect()
        self.yost_api = None

    def _agent_connect_hw(self):
        self.yost_api = Yost3SpaceAPI(self.com_port, self.sample_rate)
        try:
            self.logger.info("Configurando IMU")
            self.yost_api.setup()
            self.logger.info("Iniciando streaming de datos desde IMU")
            self.yost_api.start_streaming()
            self.__flag_stop.clear()
            self.__main_thread = Thread(target=self.__receive_and_pipe_data)
            self.__main_thread.start()
            return True
        except (serial.SerialException, serial.SerialTimeoutException):
            self.logger.error(f"Error al conectarse al puerto {self.com_port}")
            self.yost_api = None
            self.flags.quit.wait(1)
            return False

    def _agent_disconnect_hw(self):
        self.__flag_stop.set()
        self.__main_thread.join(0.2)
        self.yost_api.disconnect()
        self.yost_api = None

    def __receive_and_pipe_data(self):
        while not self.flags.quit.is_set() and not self.__flag_stop.is_set():
            try:
                data = self.yost_api.read_datapoint()
                if data:
                    data_line = f"{time.time():.3f}; {';'.join([format(v, '2.3f') for v in data])}"
                    if self.state == AgentStatus.CAPTURING:
                        self.dq_formatted_data.append(data_line)
                else:
                    if self.hw_state == HWStates.NOMINAL:
                        self.logger.error("Error al leer del acelerómetro vía puerto serial")
                        self.hw_state = HWStates.ERROR
            except Exception:
                self.logger.exception("")
                if self.hw_state == HWStates.NOMINAL:
                    self.hw_state = HWStates.ERROR
        try:
            self.yost_api.stop_streaming()
        except:
            pass

    def _agent_check_hw_connected(self):
        return check_dev(self.com_port)

    def _pre_capture_file_update(self):
        pass


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    agent = IMUAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
