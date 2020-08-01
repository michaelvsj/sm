import logging
from pathlib import Path
import socket
import time
import json
from threading import Thread, Event
import sys
import numpy as np

from agents.os1.core import OS1
from agents.os1.utils import build_trig_table, xyz_points_pack
from agents.os1.lidar_packet import PACKET_SIZE, MAX_FRAME_ID, _unpack as unpack_lidar
from hwagent.abstract_agent import AbstractHWAgent, AgentStatus, Message, HWStatus

CONFIG_FILE = "config.yaml"
LIDAR_UDP_PORT = 7502
AZIMUTH_DIVS = 511
ANGLE_SPAN = 140  # Abanico de captura, en grados
ADMIT_MEAS_ID_MORE_THAN = 16 * round(AZIMUTH_DIVS * (
        180 - ANGLE_SPAN / 2) / 360 / 16)  # sabiendo que intresa solo el hemisferio inferior, y que el lida se monta con el azimut 0 apuntando hacia arriba (conector hacia arriba)
ADMIT_MEAS_ID_LESS_THAN = 16 * round(AZIMUTH_DIVS * (180 + ANGLE_SPAN / 2) / 360 / 16)
LOST_PACKETS_ERROR_THRESHOLD = 5  # Sobre este porcentaje de paquetes perdidos, se pasa a estado de error o warning
INVALID_BLOCKS_ERROR_THRESHOLD = 5  # Sobre este porcentaje de bloques inválidos, se pasa a estado de error o warning


class LidarAgent(AbstractHWAgent):
    def __init__(self):
        AbstractHWAgent.__init__(self, CONFIG_FILE)
        self.logger = logging.getLogger('os1_lidar')
        self.output_file_is_binary = True
        self.lidar_ip = ""
        self.host_ip = ""
        self.os1 = None
        self.receive_data = Event()
        self.receive_data.clear()
        self.packets_per_frame = dict()
        self.blocks_valid = 0
        self.blocks_invalid = 0
        self.active_channels = ()

    def _hw_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        self.lidar_ip = self.config["lidar_ip"]
        self.host_ip = self.config["host_ip"]

    def _hw_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        self.lidar_receiver = Thread(target=self.__read_from_lidar)
        self.lidar_receiver.start()

    def _hw_finalize(self):
        """
        Se prepara para terminar el agente
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        try:
            assert (self.flag_quit.is_set())  # Este flag debiera estar seteado en este punto
        except AssertionError:
            self.logger.error("Se llamó a hw_finalize() sin estar seteado 'self.flag_quit'")
        self.lidar_receiver.join(0.5)
        self.sock.close()

    def _hw_start_streaming(self):
        """
        Inicia stream de datos desde el sensor
        """
        self.receive_data.set()
        pass

    def _hw_stop_streaming(self):
        """
        Detiene el stream de datos desde el sensor
        """
        self.receive_data.clear()
        self.packets_per_frame = dict()  # resetea datos de estadística
        pass

    def _hw_connect(self):
        self.receive_data.clear()

        # Socket para recibir datos desde LiDAR
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            self.sock.bind((self.host_ip, LIDAR_UDP_PORT))
        except OSError:
            self.logger.exception("")
            return False

        self.os1 = OS1(self.lidar_ip, self.host_ip, mode="512x10")
        self.logger.info("Cargando parmámetros desde LiDAR ('beam intrinsics')")
        try:
            beam_intrinsics = json.loads(self.os1.get_beam_intrinsics())
        except:
            self.logger.exception(f"Error al intentar obtener beam_intrinsics. Posible desconexion")
            return False
        beam_alt_angles = beam_intrinsics['beam_altitude_angles']
        beam_az_angles = beam_intrinsics['beam_azimuth_angles']
        self.logger.info("Construyendo tabla trigonométrica")
        build_trig_table(beam_alt_angles, beam_az_angles)
        self.active_channels = tuple(idx for idx, val in enumerate(beam_alt_angles) if val != 0)
        self.os1.start()
        time.sleep(20)  # TODO: consultar estado hasta que sea "running"
        return True

    def _hw_reset_connection(self):
        self._hw_connect()
        pass

    def __read_from_lidar(self):
        os_buffer_size = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)

        # Al iniciar, se salta el primer lote de paquetes que son los que están en el buffer y son "viejos"
        bytes_recvd = 0
        while bytes_recvd < os_buffer_size:
            pkt = self.sock.recv(PACKET_SIZE)
            bytes_recvd += len(pkt)

        while not self.flag_quit.is_set():
            packet, address = self.sock.recvfrom(PACKET_SIZE)
            if not self.receive_data.is_set():
                continue
            if address[0] == self.lidar_ip and len(packet) == PACKET_SIZE:
                first_measurement_id = int.from_bytes(packet[8:10], byteorder="little")
                # Si los datos corresponden al azimuth donde está el conector, preocesa los paquetes
                if ADMIT_MEAS_ID_MORE_THAN <= first_measurement_id <= ADMIT_MEAS_ID_LESS_THAN:
                    # parsea y pone el paquete parseado en un buffer para su posterior escritura a disco
                    packed, blocks = xyz_points_pack(unpack_lidar(packet), self.active_channels)
                    self.dq_formatted_data.append(packed)

                    # Recopilación de datos para estadística de paquetes
                    frame_id = int.from_bytes(packet[10:12], byteorder="little")
                    try:
                        self.packets_per_frame[frame_id] += 1
                    except KeyError:
                        self.packets_per_frame[frame_id] = 1
                    self.blocks_valid += blocks[0]
                    self.blocks_invalid += blocks[1]

    def _pre_capture_file_update(self):
        frames = np.array(list(self.packets_per_frame.keys()))
        num_packets = np.array(list(self.packets_per_frame.values()))
        self.packets_per_frame = dict()  # resetea datos
        if len(num_packets) == 0:
            self.logger.warning("No se recibieron paquetes desde el LiDAR")
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
            self.hw_state = HWStatus.WARNING
        else:
            self.hw_state = HWStatus.NOMINAL


if __name__ == "__main__":
    Path('logs').mkdir(exist_ok=True)
    agent = LidarAgent()
    agent.set_up()
    agent.run()
