import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event

import pynmea2
import serial
from pyproj import Geod

import init_agent
from constants import HWStates, AgentStatus
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from helpers import check_dev

APP_FIELDS = ["sys_timestamp", "distance_delta"]
RMC_FIELDS = ["latitude", "longitude", "timestamp", "spd_over_grnd", "true_course"]
GGA_FIELDS = ["gps_qual", "num_sats", "horizontal_dil"]
READ_TIMEOUT = 1.5


class GPSAgent(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False
        self.com_port = ""
        self.baudrate = ""
        self.ser = serial.Serial()
        self.last_coords = None
        self.datapoint = dict.fromkeys(APP_FIELDS + RMC_FIELDS + GGA_FIELDS)
        self.output_file_header = ";".join([k for k in self.datapoint.keys()])
        self.sim_acceleration_sign = 1  # Usado para simular aceleración y frenado
        self.geod = Geod(ellps='WGS84')

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        self.com_port = self.config["com_port"]
        self.baudrate = self.config["baudrate"]
        self.simulate = bool(self.config["simulate"])

    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        self.sensor_data_receiver = Thread(target=self.__receive_and_pipe_data)
        self.sensor_data_receiver.start()

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
        self.sensor_data_receiver.join(1.1)
        self.ser.close()

    def _agent_connect_hw(self):
        self.logger.info(f"Abriendo puerto serial '{self.com_port}'. Velocidad = {self.baudrate} bps")
        if isinstance(self.ser, serial.Serial) and self.ser.is_open:
            return True
        try:
            self.ser = serial.Serial(self.com_port, self.baudrate, timeout=READ_TIMEOUT)
            return True
        except (serial.SerialException, serial.SerialTimeoutException):
            self.logger.exception(f"Error al conectarse al puerto {self.com_port}")
            return False

    def _agent_disconnect_hw(self):
        self.ser.close()

    def __receive_and_pipe_data(self):
        while not self.flags.quit.is_set():
            if self.simulate:
                r = self.__read_from_simulator()
            else:
                r = self.__read_from_gps()
            if r:
                if self.__update_data():
                    self._send_data_to_mgr(self.datapoint)
                    if self.state == AgentStatus.CAPTURING:
                        self.dq_formatted_data.append(";".join(str(val) for val in self.datapoint.values()))

    def __read_from_simulator(self):
        while not self.flags.quit.is_set():
            # Inicialización
            if not isinstance(self.datapoint["longitude"], float):
                self.datapoint["longitude"] = -73.22029516666667
                self.datapoint["latitude"] = -37.218540833333336
                self.datapoint["spd_over_grnd"] = 5
            azimuth = 45
            sp_delta = 0.5
            prev_spd = self.datapoint["spd_over_grnd"]

            if prev_spd <= 0:
                self.sim_acceleration_sign = 1
            if prev_spd >= 15:
                self.sim_acceleration_sign = -1
            speed = max((prev_spd + self.sim_acceleration_sign * sp_delta), 0)
            dist = speed  # ya que se lee cada 1 segundo

            longitude, latitude, az = self.geod.fwd(lons=self.datapoint["longitude"], lats=self.datapoint["latitude"],
                                                    az=azimuth, dist=dist)
            timestring = datetime.utcfromtimestamp(time.time()).strftime('%H:%M:%S')
            self.datapoint["latitude"] = latitude
            self.datapoint["longitude"] = longitude
            self.datapoint["timestamp"] = timestring
            self.datapoint["spd_over_grnd"] = speed
            self.datapoint["true_course"] = azimuth
            self.datapoint["gps_qual"] = 2
            self.datapoint["num_sats"] = 4

            time.sleep(1)

            return True

    def __read_from_gps(self):
        """
        Devuelve True cuando pudo actualizar la coordenada y false de lo contrario
        """
        while not self.flags.quit.is_set():
            try:
                bytes_in = self.ser.readline()
            except (serial.SerialException, serial.SerialTimeoutException):
                self.logger.exception(f"Error al leer del GPS. Reseteando conexión")
                self._agent_disconnect_hw()
                continue
            if len(bytes_in):
                try:
                    decoded = bytes_in.decode('ASCII')
                    if self.__parse_nmea(decoded):
                        return True
                except UnicodeDecodeError:
                    self.logger.exception("")

    def __parse_nmea(self, _msg):
        try:
            msg = pynmea2.parse(_msg)
            if msg.sentence_type == "GGA":
                for attr in GGA_FIELDS:
                    str_value = str(getattr(msg, attr))
                    self.datapoint[attr] = "0" if str_value == 'None' else str_value
                return False  # No hubo actualización de coordenada
            if msg.sentence_type == "RMC":
                for attr in RMC_FIELDS:
                    str_value = str(getattr(msg, attr))
                    self.datapoint[attr] = "0.0" if str_value == 'None' else str_value
                    try:
                        self.datapoint[attr] = float(self.datapoint[attr])
                    except ValueError:  # en general puede convertir a floar, salvo en campos como "timestamp"
                        pass
                return True  # Sí hubo actualización de coordenada
        except UnicodeDecodeError:
            return False
        except pynmea2.nmea.ParseError:
            return False

    def __update_data(self):
        """
        Actualiza distancia recorrida y agrega timestamp de sistema
        Encola mensajes de datos GPS para el manager y para el escritor a archiv
        :return:
        True cuando logra actualizar los datos
        False cuando no
        """
        self.datapoint["sys_timestamp"] = round(time.time(), 3)  # 3 decimales basta
        self.datapoint["distance_delta"] = 0
        try:
            if int(self.datapoint["latitude"]) != 0:
                current_coords = [float(self.datapoint["longitude"]), float(self.datapoint["latitude"])]
                if self.last_coords is None:
                    self.last_coords = current_coords
                    return False
                az12, az21, dist = self.geod.inv(current_coords[0], current_coords[1], self.last_coords[0],
                                                 self.last_coords[1])
                self.last_coords = current_coords
                self.datapoint["distance_delta"] = round(dist, 1)  # 1 decimal basta
                self.logger.debug(f"Actualizando status a: {self.datapoint} ")
                return True
            else:
                return False
        except Exception:
            self.logger.exception("")
            return False

    def _agent_check_hw_connected(self):
        return check_dev(self.com_port)

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

    agent = GPSAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
