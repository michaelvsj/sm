import json
import logging
import socket
from threading import Thread, Event
import os
import errno
import numpy as np
import sys

import init_agent
from constants import HWStates, AgentStatus
from os1.core import OS1
from os1.lidar_packet import PACKET_SIZE, MAX_FRAME_ID, unpack as unpack_lidar
from os1.utils import build_trig_table, xyz_points_pack
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from helpers import check_ping

CONFIG_FILE = "config.yaml"
LIDAR_UDP_PORT = 7502
AZIMUTH_DIVS = 511
ANGLE_SPAN = 140  # Abanico de captura, en grados
ADMIT_MEAS_ID_MORE_THAN = 16 * round(AZIMUTH_DIVS * (
        180 - ANGLE_SPAN / 2) / 360 / 16)  # sabiendo que intresa solo el hemisferio inferior, y que el lida se monta con el azimut 0 apuntando hacia arriba (conector hacia arriba)
ADMIT_MEAS_ID_LESS_THAN = 16 * round(AZIMUTH_DIVS * (180 + ANGLE_SPAN / 2) / 360 / 16)
LOST_PACKETS_ERROR_THRESHOLD = 5  # Sobre este porcentaje de paquetes perdidos, se pasa a estado de error o warning
INVALID_BLOCKS_ERROR_THRESHOLD = 5  # Sobre este porcentaje de bloques inválidos, se pasa a estado de error o warning


class OS1LiDARAgent(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = True
        self.sensor_ip = ""
        self.host_ip = ""
        self.os1 = None
        self.receive_data = Event()
        self.receive_data.clear()
        self.packets_per_frame = dict()
        self.blocks_valid = 0
        self.blocks_invalid = 0
        self.active_channels = ()
        self.stats_are_valid = False

    def _agent_config(self):
        self.sensor_ip = self.config["sensor_ip"]
        self.host_ip = self.config["host_ip"]
        self.os1 = OS1(self.sensor_ip, self.host_ip, mode="512x10")

    def _agent_check_hw_connected(self):
        return check_ping(self.sensor_ip)

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
        self.__thread_data_receiver.join(0.5)
        self.sock.close()

    def _agent_hw_start(self):
        # Socket para recibir datos desde LiDAR
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.1)
        try:
            self.sock.bind((self.host_ip, LIDAR_UDP_PORT))
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                self.logger.error(f"Dirección ya está en uso: {self.host_ip}:{LIDAR_UDP_PORT}")
            else:
                self.logger.exception("")
            return False

        self.logger.info("Cargando parmámetros desde LiDAR ('beam intrinsics')")
        try:
            beam_intrinsics = json.loads(self.os1.get_beam_intrinsics())
        except OSError as e:
            if e.errno == errno.EHOSTUNREACH:
                self.logger.error(f"No se puede acceder a la IP del LiDAR: 'No route to host'")
            else:
                self.logger.exception(f"Error al intentar obtener beam_intrinsics. Posible desconexion")
            return False
        except json.decoder.JSONDecodeError:
            self.logger.error(f"Error al intentar obtener beam_intrinsics. Posible desconexion")
            return False
        beam_alt_angles = beam_intrinsics['beam_altitude_angles']
        beam_az_angles = beam_intrinsics['beam_azimuth_angles']
        self.logger.info("Construyendo tabla trigonométrica")
        build_trig_table(beam_alt_angles, beam_az_angles)
        self.active_channels = tuple(idx for idx, val in enumerate(beam_alt_angles) if val != 0)
        self.logger.info("Inicializando LiDAR. Esto tarda unos 20 segundos.")
        self.os1.start()
        self.flags.quit.wait(20)  # TODO: consultar estado hasta que sea "running"

        if not self.flags.quit.is_set():
            self.flags.hw_stopped.clear()
            self.__thread_data_receiver = Thread(target=self.__read_from_lidar)
            self.__thread_data_receiver.start()

        return True

    def _agent_hw_stop(self):
        try:
            self.flags.hw_stopped.set()
            self.__thread_data_receiver.join(0.5)
            self.__thread_data_receiver = None
            self.sock.close()
            self.sock = None
        except:
            pass

    def __read_from_lidar(self):
        self.logger.debug("Iniciando __read_from_lidar")
        self.stats_are_valid = False
        os_buffer_size = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)

        # Al iniciar, se salta el primer lote de paquetes que son los que están en el buffer y son "viejos"
        bytes_recvd = 0
        while bytes_recvd < os_buffer_size and not self.flags.quit.is_set() and not self.flags.hw_stopped.is_set():
            try:
                pkt = self.sock.recv(PACKET_SIZE)
                bytes_recvd += len(pkt)
            except:
                pass
        while not self.flags.quit.is_set() and not self.flags.hw_stopped.is_set():
            try:
                packet, address = self.sock.recvfrom(PACKET_SIZE)
                if not self.state == AgentStatus.CAPTURING:
                    continue
                if address[0] == self.sensor_ip and len(packet) == PACKET_SIZE:
                    first_measurement_id = int.from_bytes(packet[8:10], byteorder="little")
                    # Si los datos corresponden al azimuth donde está el conector, preocesa los paquetes
                    if ADMIT_MEAS_ID_MORE_THAN <= first_measurement_id <= ADMIT_MEAS_ID_LESS_THAN:
                        # parsea y pone el paquete parseado en un buffer para su posterior escritura a disco
                        packed, blocks = xyz_points_pack(unpack_lidar(packet), self.active_channels)
                        self.dq_formatted_data.append(packed)

                        # Recopilación de datos para estadística de paquetes
                        self.stats_are_valid = True  # estadísticas solo son válidas mientras se están recopilando
                        frame_id = int.from_bytes(packet[10:12], byteorder="little")
                        try:
                            self.packets_per_frame[frame_id] += 1
                        except KeyError:
                            self.packets_per_frame[frame_id] = 1
                        self.blocks_valid += blocks[0]
                        self.blocks_invalid += blocks[1]
            except socket.timeout:
                pass
            except Exception:
                self.logger.exception("")
        self.stats_are_valid = False

    def _pre_capture_file_update(self):
        if self.state != AgentStatus.CAPTURING or not self.stats_are_valid:
            return

        frames = np.array(list(self.packets_per_frame.keys()))
        num_packets = np.array(list(self.packets_per_frame.values()))
        self.packets_per_frame = dict()  # resetea datos
        if len(num_packets) == 0:
            self.logger.warning("No se recibieron paquetes desde el LiDAR")
            self.hw_state = HWStates.ERROR
            return

        if frames[-1] < frames[0]:  # Ultimo frame recibido es menor que el primero => Ocurrió overflow del frame ID
            num_frames = MAX_FRAME_ID - frames[0] + frames[-1]
        else:
            num_frames = frames[-1] - frames[0]

        expected_packets = num_frames * (1 + round(AZIMUTH_DIVS * ANGLE_SPAN / 360 / 16))
        received_packets = num_packets.sum()
        lost_packets_pc = 100 * (expected_packets - received_packets) / expected_packets if expected_packets > 0 else 0
        lost_packets_pc = max(0, lost_packets_pc)
        self.logger.info(f"Paquetes: recibidos: {received_packets}, perdidos: {lost_packets_pc:.1f} %")

        blocks_total = self.blocks_valid + self.blocks_invalid
        blocks_invalid_pc = self.blocks_invalid / blocks_total * 100
        if blocks_total > 0:
            self.logger.info(f"Bloques de azimuth. "
                             f"Validos: {self.blocks_valid} ({100 - blocks_invalid_pc:.1f} %). "
                             f"Invalidos: {self.blocks_invalid} ({blocks_invalid_pc:.1f} %)")

        # TODO: Considerar enviar al manager las estadísticas:
        #  (received_packets, lost_packets_pc, blocks_total, blocks_valid))
        #  Aunque igual se pueden ver en el log...

        self.blocks_valid, self.blocks_invalid = 0, 0

        if lost_packets_pc > LOST_PACKETS_ERROR_THRESHOLD or blocks_invalid_pc > INVALID_BLOCKS_ERROR_THRESHOLD:
            self.hw_state = HWStates.ERROR
        else:
            self.hw_state = HWStates.NOMINAL

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_run_non_hw_threads(self):
        pass


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    agent = OS1LiDARAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
