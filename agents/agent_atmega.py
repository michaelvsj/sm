import logging
import os
import sys
import time
from pathlib import Path
from threading import Thread, Event
from collections import deque
import serial

from hwagent.abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from messaging.messaging import Message
from devices import Devices, HWStates

DEFAULT_COM_PORT = '/dev/ttyARD0'
DEFAULT_BAUDRATE = 115200
STABILITY_THRESHOLD = 0.05
LED_ONLINE = b'\x04'
LED_OFFLINE = b'\x05'
LED_CAPTURING = b'\x03'
LED_BUT_FDBK = b'\x02'
LED_EXT_DRIVE = b'\x06'
LED_DEV_OS1 = b'\x07'
LED_DEV_GPS = b'\x08'
LED_DEV_IMU = b'\x09'
LED_DEV_CAM = b'\x0A'
LED_DEV_MODEM = b'\x0B'
START_OF_TEXT = b'\xFF'
OFF = b'\x00'
ON = b'\x01'
BLINK = b'\x02'
TOLERANCE = 0.1
ADC_VALUE_TO_VOLTS = 5.0 / 1023.0

BUTTONS = ('bNoButton', 'bSingleButton', 'b+', 'b-', 'b<', 'b>', 'bMute', 'bGPS', 'bStop', 'bPickup', 'bHangup', 'bM')

class AtmegaAgent(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False
        self.write_data = Event()
        self.write_data.clear()
        self.q_buttons: Queue = _but_queue  # TODO encolar botonoes como mensajes para manager
        self.d_volts = deque()  # Cola para almacenar voltajes leidos
        self.com_port = ""
        self.baudrate = ""
        self.ser = None
        self.last_stable_volts = []
        self.devices_leds = dict()
        self.quitting = False
        self.keys = dict()
        self.devices_leds[Devices.OS1_LIDAR] = LED_DEV_OS1
        self.devices_leds[Devices.GPS] = LED_DEV_GPS
        self.devices_leds[Devices.IMU] = LED_DEV_IMU
        self.devices_leds[Devices.CAMERA] = LED_DEV_CAM
        self.devices_leds[Devices.MODEM] = LED_DEV_MODEM

    def _agent_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        self.com_port = self.config["com_port"]
        self.baudrate = self.config["baudrate"]

    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        self.__agent_main_thread = Thread(target=self.__main_loop)
        self.__agent_main_thread.start()
        buttons_thread = Thread(target=self.__read_buttons, daemon=True)
        buttons_thread.start()

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
        self.__agent_main_thread.join(0.1)
        self.ser.close()

    def _agent_start_streaming(self):
        """
        Inicia stream de datos desde el sensor
        """
        self.logger.info("Enviando comando a IMU para que inicie streaming de datos")
        self.write_data.set()

    def _agent_stop_streaming(self):
        """
        Detiene el stream de datos desde el sensor
        """
        self.write_data.clear()

    def _agent_connect_hw(self):
        self.write_data.clear()
        self.logger.info(f"Abriendo puerto serial '{self.com_port}'. Velocidad = {self.baudrate} bps")
        if isinstance(self.ser, serial.Serial) and self.ser.is_open:
            return True
        try:
            self.ser = serial.Serial(self.com_port, self.baudrate)
            return True
        except (serial.SerialException, serial.SerialTimeoutException):
            self.logger.exception(f"Error al conectarse al puerto {self.com_port}")
            return False

    def _agent_reset_hw_connection(self):
        self.ser.close()
        self._agent_connect_hw()

    def __main_loop(self):
        self.__turn_off_leds_now()
        while not self.flag_quit.is_set():
            try:
                # Busca encabezado
                s = self.ser.read(1)
                while s != START_OF_TEXT:
                    s = self.ser.read(1)
                # Lee datos:
                v1 = int.from_bytes(self.ser.read(2), byteorder='little', signed=True) * ADC_VALUE_TO_VOLTS
                v2 = int.from_bytes(self.ser.read(2), byteorder='little', signed=True) * ADC_VALUE_TO_VOLTS
                self.d_volts.appendleft([v1, v2])
            except TimeoutError:
                self.logger.warning("Tiemout leyendo del puerto serial conectado a CPU ATMega")
                continue
            except KeyboardInterrupt:  # Apaga los leds
                self.__turn_off_leds_now()
            except Exception as e:
                raise
        self.__turn_off_leds_now()

    def _pre_capture_file_update(self):
        pass
        # TODO: setear estatus según estadísticas de paquetes. Esto tambien se puede hacer en un thread que corra cada 1 segundo o algo así
        """Ejemplo: 
        if lost_packets_pc > LOST_PACKETS_ERROR_THRESHOLD or blocks_invalid_pc > INVALID_BLOCKS_ERROR_THRESHOLD:
            self.hw_state = HWStatus.WARNING
        else:
            self.hw_state = HWStatus.NOMINAL
        """

    def __ping_button_feedback(self):
        """
        Le indica al ATmega que destelle el LED para indicar que se ha leido el click de un boton
        :return: Nothing
        """
        self.ser.write(START_OF_TEXT + LED_BUT_FDBK + ON)
        time.sleep(0.05)
        self.ser.write(START_OF_TEXT + LED_BUT_FDBK + OFF)

    def __get_key_from_values(self, volts):
        for key_name, key_v in self.keys.items():
            if abs(volts[0] - key_v[0]) < TOLERANCE and abs(volts[1] - key_v[1]) < TOLERANCE:
                return key_name
        return 'bUnknown'

    def __read_buttons(self):
        """
        Trata de interpretar los voltajes como botones y añade el boton presionado a la cola
        Usa filtros e histeresis para evitar falsos positivos
        :return:
        """
        unpressed = True  # Inicia sin boton presionado
        while not self.flag_quit.is_set():
            time.sleep(0.002)
            prev_volts = self.d_volts.pop()
            stability_count = -1
            while stability_count < 3:
                time.sleep(0.002)
                volts = self.d_volts.pop()
                stability_count += 1
                for val1, val2 in zip(volts, prev_volts):
                    if abs(val1 - val2) > STABILITY_THRESHOLD:
                        stability_count -= 1
                        stability_count = max(stability_count, 0)  # Lo acotamos en 0, no menos
                        break
                prev_volts = volts

            # Voltaje estable, continua...
            if __name__ == "__main__":
                print(f"V1={volts[0]:0.2f}, V2={volts[1]:0.2f}")
            self.last_stable_volts = volts
            button = self.__get_key_from_values(volts)
            if button != 'bUnknown':
                if button == 'bNoButton':  # No va a registrar otro boton hasta que no pase por estado de ningun boton presionado
                    unpressed = True
                elif unpressed:
                    unpressed = False
                    self.logger.debug(f"Boton {button} detectado")
                    self.q_buttons.put(button)
                    self.__ping_button_feedback()

    def _agent_process_manager_message(self, msg: Message):
        #LEDs de estado de sistema
        if msg.typ == Message.SYS_STATE:
            if msg.arg == Message.SYS_OFFLINE:
                self.ser.write(START_OF_TEXT + LED_ONLINE + OFF)
                self.ser.write(START_OF_TEXT + LED_OFFLINE + ON)
            elif msg.arg == Message.SYS_ONLINE:
                self.ser.write(START_OF_TEXT + LED_ONLINE + ON)
                self.ser.write(START_OF_TEXT + LED_OFFLINE + OFF)
            elif msg.arg == Message.SYS_ERROR:
                self.ser.write(START_OF_TEXT + LED_ONLINE + ON)
                self.ser.write(START_OF_TEXT + LED_OFFLINE + ON)
                self.ser.write(START_OF_TEXT + LED_ONLINE + BLINK)
            elif msg.arg == Message.SYS_CAPTURE_OFF:
                self.ser.write(START_OF_TEXT + LED_CAPTURING + OFF)
            elif msg.arg == Message.SYS_CAPTURE_ON:
                self.ser.write(START_OF_TEXT + LED_CAPTURING + ON)
            elif msg.arg == Message.SYS_CAPTURE_PAUSED:
                self.ser.write(START_OF_TEXT + LED_CAPTURING + BLINK)
            elif msg.arg == Message.EXT_DRIVE_IN_USE:
                self.ser.write(START_OF_TEXT + LED_EXT_DRIVE + ON)
            elif msg.arg == Message.EXT_DRIVE_NOT_IN_USE:
                self.ser.write(START_OF_TEXT + LED_EXT_DRIVE + OFF)
        # LEDs de status de equipos
        elif msg.typ == Message.DEVICE_STATE:
            device = msg.arg["device"]
            status = msg.arg["state"]
            if status == HWStates.NOT_CONNECTED:  # Si no está conectado
                self.ser.write(START_OF_TEXT + self.devices_leds[device] + ON)  # Enciende LED
            elif status == HWStates.ERROR:  # Si está conectado, pero con error
                self.ser.write(
                    START_OF_TEXT + self.devices_leds[device] + BLINK)  # Hace pestañar el LED
            else:  # Si está conectado y sin error
                self.ser.write(START_OF_TEXT + self.devices_leds[device] + OFF)  # Apaga el LED

    def __turn_off_leds_now(self):
        self.ser.write(START_OF_TEXT + LED_ONLINE + OFF)
        self.ser.write(START_OF_TEXT + LED_OFFLINE + OFF)
        self.ser.write(START_OF_TEXT + LED_CAPTURING + OFF)
        self.ser.write(START_OF_TEXT + LED_BUT_FDBK + OFF)
        self.ser.write(START_OF_TEXT + LED_EXT_DRIVE + OFF)
        for led in self.devices_leds.values():
            self.ser.write(START_OF_TEXT + led + OFF)


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    Path('logs').mkdir(exist_ok=True)
    agent = AtmegaAgent(config_file=cfg_file)
    agent.set_up()
    agent.run()
