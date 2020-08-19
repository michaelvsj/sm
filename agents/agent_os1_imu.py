import errno
import logging
import os
import socket
from threading import Thread
import time
import sys

import init_agent
from constants import AgentStatus
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from helpers import check_ping
from os1.imu_packet import PACKET_SIZE, unpack as unpack_imu

IMU_UDP_PORT = 7503


class OS1IMUAgent(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False
        self.output_file_header = "timestamp_system_(s);timestamp_accel_(us);timestamp_gyro_(us);accel_x_(g);" \
                                  "accel_y_(g);accel_z_(g);gyro_x_(deg/sec);gyro_y_(deg/sec);gyro_z_(deg/sec)"
        self.sensor_ip = ""
        self.host_ip = ""

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_config(self):
        self.sensor_ip = self.config["sensor_ip"]
        self.host_ip = self.config["host_ip"]

    def _agent_run_non_hw_threads(self):
        pass

    def _agent_finalize(self):
        self.flags.quit.set()
        self.__thread_data_receiver.join(0.5)
        self.sock.close()

    def _agent_hw_start(self):
        # Socket para recibir datos desde LiDAR
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.1)
        try:
            self.sock.bind((self.host_ip, IMU_UDP_PORT))
            self.flags.hw_stopped.clear()
            self.__thread_data_receiver = Thread(target=self.__read_from_imu)
            self.__thread_data_receiver.start()
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                self.logger.error(f"Dirección ya está en uso: {self.host_ip}:{IMU_UDP_PORT}")
            else:
                self.logger.exception("")
            return False
        return True

    def _agent_hw_stop(self):
        try:
            self.flags.hw_stopped.set()
            self.__thread_data_receiver.join(0.2)
            self.__thread_data_receiver = None
            self.sock.close()
            self.sock = None
        except:
            pass

    def __read_from_imu(self):
        while not self.flags.quit.is_set() and not self.flags.hw_stopped.is_set():
            try:
                packet, address = self.sock.recvfrom(PACKET_SIZE)
                if not self.state == AgentStatus.CAPTURING:
                    continue
                if address[0] == self.sensor_ip and len(packet) == PACKET_SIZE:
                    ti, ta, tg, ax, ay, az, gx, gy, gz = unpack_imu(packet)
                    f_data = f"{time.time():.3f};{int(ta / 1000)};{int(tg / 1000)};" \
                             f"{ax:.3f};{ay:.3f};{az:.3f};{gx:.3f};{gy:.3f};{gz:.3f}"
                    self.dq_formatted_data.append(f_data)
            except:
                pass

    def _pre_capture_file_update(self):
        pass

    def _agent_check_hw_connected(self):
        return check_ping(self.sensor_ip)


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    agent = OS1IMUAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
