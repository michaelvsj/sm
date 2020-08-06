import errno
import logging
import os
import socket
from pathlib import Path
from threading import Thread, Event
import time
import sys
import init_agent
from constants import Devices, HWStates, AgentStatus
from hwagent.abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
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
        self.receive_data = Event()
        self.receive_data.clear()

    def _get_device_name(self):
        return Devices.OS1_IMU

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        self.sensor_ip = self.config["sensor_ip"]
        self.host_ip = self.config["host_ip"]

    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        self.sensor_data_receiver = Thread(target=self.__read_from_imu)
        self.sensor_data_receiver.start()

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
        self.sensor_data_receiver.join(0.5)
        self.sock.close()

    def _agent_start_streaming(self):
        """
        Inicia stream de datos desde el sensor
        """
        self.receive_data.set()
        pass

    def _agent_stop_streaming(self):
        """
        Detiene el stream de datos desde el sensor
        """
        self.receive_data.clear()
        pass

    def _agent_connect_hw(self):
        self.receive_data.clear()
        # Socket para recibir datos desde LiDAR
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((self.host_ip, IMU_UDP_PORT))
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                self.logger.error(f"Dirección ya está en uso: {self.host_ip}:{self.local_tcp_port}")
            else:
                self.logger.exception("")
            return False
        return True

    def _agent_reset_hw_connection(self):
        self.sock.close()
        self._agent_connect_hw()

    def __read_from_imu(self):
        while not self.flag_quit.is_set():
            packet, address = self.sock.recvfrom(PACKET_SIZE)
            if not self.receive_data.is_set():
                continue
            if address[0] == self.sensor_ip and len(packet) == PACKET_SIZE:
                ti, ta, tg, ax, ay, az, gx, gy, gz = unpack_imu(packet)
                f_data = f"{time.time():.3f};{int(ta / 1000)};{int(tg / 1000)};" \
                         f"{ax:.3f};{ay:.3f};{az:.3f};{gx:.3f};{gy:.3f};{gz:.3f}"
                self.dq_formatted_data.append(f_data)


    def _pre_capture_file_update(self):
        pass
        # TODO: setear estatus según estadísticas de paquetes. Esto tambien se puede hacer en un thread que corra cada 1 segundo o algo así
        """Ejemplo: 
        if lost_packets_pc > LOST_PACKETS_ERROR_THRESHOLD or blocks_invalid_pc > INVALID_BLOCKS_ERROR_THRESHOLD:
            self.hw_state = HWStatus.WARNING
        else:
            self.hw_state = HWStatus.NOMINAL
        """


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    Path('logs').mkdir(exist_ok=True)
    agent = OS1IMUAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
