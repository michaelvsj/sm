import logging
import logging.config
import os
import signal
import sys
import time
from enum import Enum, auto
from queue import SimpleQueue
from subprocess import Popen
from threading import Thread, Event

import yaml

from agents.constants import HWStates, Devices
from bdd import DBInterface
from messaging.agents_interface import AgentInterface
from messaging.messaging import Message, AgentStatus
from utils import get_time_str, get_date_str, Coords, get_new_folio

DEFAULT_CONFIG_FILE = 'config.yaml'
LOCALHOST = '127.0.0.1'
KEY_QUIT = 'q'  # Comando de teclado para terminar el programa
KEY_START_STOP = 's'  # para iniciar o detener una sesión de captura
FORCE_START = 'f'  # inicia captura inmediatamente, sin esperar que vehículo inice movimiento

class Flags:
    """
    Contiene los eventos relevantes para controlar el flujo de captura
    """

    def __init__(self):
        self.vehicle_moving = Event()   
        self.segment_timeout = Event()  # Ha pasado más de T segundos desde que comenzó la captura del segmento
        self.segment_ended = Event()  # El vehículo ya avanzó más de X metros desde que comenzó la captura del segmento
        self.new_command = Event()  # El usuario presionó el boton de inicio/fin de captura o una tecla en consola. Como sea, hay un nuevo comando en la cola de comandos
        self.quit = Event() # Para indicar el fin de la aplicación
        self.agents_ready = Event()


class States(Enum):
    """
    Contiene los estados en que puede estar la máquina de estados que coordina la captura
    """
    STARTING = auto()
    STAND_BY = auto()
    CAPTURING = auto()
    WAITING_SPEED = auto()


class AgentProxies:
    """
    ES IMPERATIVO QUE LOS NOMBRES DE LOS AGENTES COINCIDAN CON LOS DE LA CONFIGURACIÓN
    """

    def __init__(self, quit_flag):
        self.OS1_LIDAR = AgentInterface("os1_lidar", quit_flag)
        self.OS1_IMU = AgentInterface("os1_imu", quit_flag)
        self.IMU = AgentInterface("imu", quit_flag)
        self.GPS = AgentInterface("gps", quit_flag)
        self.CAMERA = AgentInterface("camera", quit_flag)
        self.ATMEGA = AgentInterface("atmega", quit_flag)
        self.INET = AgentInterface("inet", quit_flag)
        self.DATA_COPY = AgentInterface("data_copy", quit_flag)

    def items(self):
        return self.__dict__.values()


class FRAICAPManager:
    def __init__(self, manager_config_file, agents_config_file):
        self.flags = Flags()
        self.state = States.STARTING
        self.logger = logging.getLogger("manager")
        self.capture_dir_base = ""
        self.capture_dir = ""
        self.q_user_commands = SimpleQueue()  # Cola de comandos provenientes de de teclado o botonera
        self.agents = AgentProxies(self.flags.quit)
        self.dbi = None
        self.coordinates = Coords()
        self.segment_coords_ini = Coords()
        self.segment_current_length = 0
        self.segment_current_init_time = 0
        self.folio = None
        self.mgr_cfg = dict()
        self.set_up(manager_config_file, agents_config_file)
        self.session = None # Identificador de sesión de captura. La sesión inicia y termina con el apriete del boton (o tecla 's')
        self.segment = 0000 # Identificador del segmento dentro de la sesión. Número correlativo

    def set_up(self, manager_config_file, agents_config_file):
        try:
            with open(manager_config_file, 'r') as config_file:
                self.mgr_cfg = yaml.safe_load(config_file)
        except FileNotFoundError:
            self.logger.error(f"Archivo de configuración {manager_config_file} no encontrado. Terminando.")
            sys.exit(-1)
        logging.config.dictConfig(self.mgr_cfg["logging"])
        self.logger.info("***** INICIA PROGRAMA *****")
        try:
            with open(agents_config_file, 'r') as config_file:
                agents_cfg = yaml.safe_load(config_file)
        except FileNotFoundError:
            self.logger.error(f"Archivo de configuración {agents_config_file} no encontrado. Terminando.")
            sys.exit(1)
        for agt in self.agents.items():
            try:
                assert isinstance(self.mgr_cfg['use_agents'][agt.name], bool)
                try:
                    agt.set_ip_address(LOCALHOST, agents_cfg[f"agent_{agt.name}"]["local_port"])
                    if self.mgr_cfg["use_agents"][agt.name]:
                        agt.enabled = True
                    else:
                        agt.enabled = False
                except KeyError:
                    self.logger.warning(f"No hay configuración para el agente agent_{agt.name} en {agents_config_file}")
                    agt.enabled = False
            except AssertionError as e:
                self.logger.error("Error en configuracion. Parámetro 'use_agents' debe ser True o False")
                continue
            if self.mgr_cfg['use_agents']['os1_imu'] and not self.mgr_cfg['use_agents']['os1_lidar']:
                self.logger.warning("No es posibel habilitar os1_imu sin habilitar también os1_lidar. Se usarán ambos.")
                self.mgr_cfg['use_agents']['os1_lidar'] = True

        for key in self.mgr_cfg.keys():
            self.logger.info(f"Usando config '{key}' : {self.mgr_cfg[key]}")
        self.capture_dir_base = self.mgr_cfg['capture']['output_path']
        os.makedirs(self.capture_dir_base, exist_ok=True)

        # Objeto para interfaz con base de datos
        self.dbi = DBInterface(self.mgr_cfg['sqlite']['db_file'])

    def initialize(self):
        """
        Lenanta los agentes
        Levanta los threads de monitoreo de agentes

        :return:
        """
        self.state = States.STARTING
        if os.name == 'posix':
            python_exec = os.path.join(sys.exec_prefix, 'bin', 'python')
        elif os.name == 'nt':
            python_exec = os.path.join(sys.exec_prefix, 'Scripts', 'pythonw.exe')
        else:
            self.logger.error("No se pudo determinar sistema operativo")
            sys.exit(1)
        agents_working_dir = os.path.dirname(os.path.abspath(__file__)) + os.sep + "agents"
        self.logger.info(f"Manager ejecutandose con PID {os.getpid()}")
        for agt in self.agents.items():
            if agt.enabled:
                pid = Popen([python_exec, f"{agents_working_dir}{os.sep}agent_{agt.name}.py"]).pid
                self.logger.info(f"Agente {agt.name} ejecutandose con PID {pid}")
        time.sleep(0.5)  # Les da tiempo para partir antes de intentar conexión
        for agt in self.agents.items():
            if agt.enabled:
                agt.connect()

        # Espera a que agentes se conecten
        self.logger.info("Esperando conexión a agentes")
        for agt in self.agents.items():
            if agt.enabled:
                self.logger.info(f"Conectando a agente {agt.name}")
                while not agt.is_connected():
                    time.sleep(0.01)
                self.logger.info(f"Agente {agt.name} conectado")
        self.logger.info("Conectado a todos los agentes habilitados")

        self.logger.info("Iniciando thread de reporte de estado de agentes")
        Thread(target=self.check_agents_ready, name="check_agents_ready", daemon=True).start()

        self.logger.info("Esperando que agentes estén listos para capturar")
        while not self.flags.agents_ready.is_set():
            time.sleep(0.1)
        self.logger.info("Agentes listos")

        self.logger.info("Iniciando thread de reporte de estado de hardware")
        Thread(target=self.check_hw, name="check_hw", daemon=True).start()

        self.logger.info("Iniciando threads generadores de eventos")
        self.logger.info("--Iniciando thread de lectura de teclado")
        Thread(target=self.get_keyboard_input, name="get_keyboard_input", daemon=True).start()

        if self.agents.ATMEGA.enabled:
            self.logger.info("--Iniciando thread de lectura de botones")
            Thread(target=self.get_buttons, name="get_buttons", daemon=True).start()

        self.logger.info("--Iniciando thread de monitoreo de avance y tiempo")
        Thread(target=self.check_spacetime, name="check_spacetime", daemon=True).start()

    def check_hw(self):
        while not self.flags.quit.is_set():
            if self.agents.OS1_LIDAR.enabled:
                self.agents.ATMEGA.send_data({"device": Devices.OS1, "status": self.agents.OS1_LIDAR.hw_status})
            if self.agents.IMU.enabled:
                self.agents.ATMEGA.send_data({"device": Devices.IMU, "status": self.agents.IMU.hw_status})
            if self.agents.CAMERA.enabled:
                self.agents.ATMEGA.send_data({"device": Devices.CAMERA, "status": self.agents.CAMERA.hw_status})
            if self.agents.GPS.enabled:
                self.agents.ATMEGA.send_data({"device": Devices.GPS, "status": self.agents.GPS.hw_status})
            if self.agents.INET.enabled:
                self.agents.ATMEGA.send_data({"device": Devices.ROUTER, "status": self.agents.INET.hw_status})
            for agt in self.agents.items():
                if agt.enabled and agt.hw_status != HWStates.NOMINAL:
                    self.logger.warning(f"Agente {agt.name} reporta hardware en estado {agt.hw_status}")
            self.flags.quit.wait(10)

    def check_spacetime(self):
        while not self.flags.quit.is_set():
            self.flags.quit.wait(0.01)
            if self.state == States.CAPTURING and time.time() > self.segment_current_init_time + \
                    self.mgr_cfg['capture']['splitting_time']:
                self.logger.debug(
                    f"Tiempo acumulado en útlimo tramo: {time.time() - self.segment_current_init_time:.1f} segundos. "
                    f"Seteando bandera para generar nuevo tramo")
                self.flags.segment_ended.set()
                continue

            gps_datapoint = self.agents.GPS.get_data()
            if gps_datapoint is not None:
                self.coordinates.lat = gps_datapoint["latitude"]
                self.coordinates.lon = gps_datapoint["longitude"]
                dist = float(gps_datapoint['distance_delta'])
                speed = float(gps_datapoint['spd_over_grnd'])
                self.segment_current_length += dist
                self.logger.debug(
                    f"GPS: Dist: {dist}, Speed:{speed}, "
                    f"Lon: {self.coordinates.lon:.5f}, Lat:{self.coordinates.lat:.5f}")

                # Pausa por detención
                if speed < self.mgr_cfg['capture']['pause_speed']:
                    self.flags.vehicle_moving.clear()

                # Reactivación post-detención
                if speed > self.mgr_cfg['capture']['resume_speed']:
                    self.flags.vehicle_moving.set()

                # División de captura en tramos, por distancia
                if self.segment_current_length > self.mgr_cfg['capture']['splitting_distance']:
                    self.flags.segment_ended.set()

    def get_buttons(self):
        while not self.flags.quit.is_set():
            b = self.agents.ATMEGA.get_data()
            if b is not None:
                self.q_user_commands.put(b)
            time.sleep(0.1)

    def check_agents_ready(self):
        while not self.flags.quit.is_set():
            all_ready = True
            for agt in self.agents.items():
                if agt.enabled:
                    if agt.agent_status != AgentStatus.STAND_BY and agt.agent_status != AgentStatus.CAPTURING:
                        all_ready = False
                        self.logger.debug(f"Agente de {agt.name} reporta estado {agt.agent_status}")
                        time.sleep(1)
            if all_ready:
                self.flags.agents_ready.set()
            else:
                self.flags.agents_ready.clear()
            self.flags.quit.wait(0.2)

    def get_keyboard_input(self):
        while not self.flags.quit.is_set():
            k = input()
            if k:
                self.q_user_commands.put(k[0])
                self.flags.new_command.set()
            if k == KEY_QUIT:
                break

    def start_capture(self):
        self.new_segment()
        for agt in self.agents.items():
            if agt.enabled:
                agt.send_msg(Message.cmd_start_capture())

    def end_capture(self):
        for agt in self.agents.items():
            if agt.enabled:
                agt.send_msg(Message.cmd_end_capture())

    def new_segment(self):
        self.segment_coords_ini = self.coordinates
        self.segment_current_length = 0
        self.segment_current_init_time = time.time()
        self.folio = get_new_folio()
        self.segment += 1
        self.capture_dir = self.get_new_capture_folder()
        self.logger.info(f"Nuevo segmento: {self.session}/{self.segment:04d}")
        for agt in self.agents.items():
            if agt.enabled:
                agt.send_msg(Message.set_folder(self.capture_dir))

    def update_segment_record(self):
        """
        Una vez finalizada la captura del tramo, actualiza el registro con la info de finalización"
        Esto se debe ejecutar ANTES de iniciar el nuevo tramo, ya que ahí se resetean las variables
        :return:
        """
        self.logger.debug("Actulizando registro de BDD con datos del último tramo")
        duracion = int(time.time() - self.segment_current_init_time)
        distancia = self.segment_current_length
        lon_fin = self.coordinates.lon
        lat_fin = self.coordinates.lat
        lon_ini = self.segment_coords_ini.lon
        lat_ini = self.segment_coords_ini.lat
        self.logger.debug(f"Folio: {self.folio}, duración: {duracion}, distancia: {distancia}")
        self.dbi.save_capture(folio=self.folio,
                              carpeta=self.capture_dir,
                              duracion=duracion,
                              distancia=distancia,
                              lon_ini=lon_ini,
                              lat_ini=lat_ini,
                              lon_fin=lon_fin,
                              lat_fin=lat_fin)

    def get_new_capture_folder(self):
        str_seg = f"{self.segment:04d}"
        folder = os.path.join(os.path.join(os.path.join(self.capture_dir_base, get_date_str()), self.session), str_seg)
        os.makedirs(folder, exist_ok=True)
        return folder

    def end_agents(self):
        for agt in self.agents.items():
            if agt.enabled:
                agt.send_msg(Message.cmd_quit())

    def new_session(self):
        self.session = get_time_str()
        self.segment = 0
        self.logger.info(f"Nueva sesión de captura: {self.session}")

    def run(self):
        try:
            self.initialize()
        except KeyboardInterrupt:
            sys.exit(0)

        # Informa al agent_data_copy la ubicación de la base de datos
        self.agents.DATA_COPY.send_msg(Message(Message.DATA, self.mgr_cfg['sqlite']['db_file']))

        #  Aquí se implementa la lógica de alto nivel de la máquina de estados, basada en estados y eventos
        self.logger.info("Esperando eventos")
        self.state = States.STAND_BY
        while not self.flags.quit.is_set():
            try:
                if self.flags.new_command.is_set():
                    cmd = self.q_user_commands.get()
                    self.logger.info(f"Procesando comando de usuario: '{cmd}'")
                    if self.q_user_commands.empty():
                        self.flags.new_command.clear()
                    if cmd == KEY_QUIT:
                        self.flags.quit.set()
                    elif cmd == KEY_START_STOP:
                        if self.state == States.CAPTURING or self.state == States.WAITING_SPEED:
                            self.logger.info("Sesión de captura finalizada por usuario")
                            self.end_capture()
                            self.state = States.STAND_BY
                        elif self.state == States.STAND_BY:
                            self.logger.info("Sesión de captura iniciada por usuario. Esperando movimiento del vehículo")
                            self.new_session()
                            self.state = States.WAITING_SPEED
                    elif cmd == FORCE_START:
                        if self.state == States.STAND_BY:
                            self.logger.info(
                                "Sesión de captura forzada (sin esperar velocidad) iniciada por usuario por el usuario.")
                            self.new_session()
                            self.start_capture()
                            self.state = States.CAPTURING
                elif self.flags.segment_ended.isSet():
                    if self.state == States.CAPTURING:
                        self.update_segment_record()
                        self.new_segment()
                    self.flags.segment_ended.clear()
                else:
                    if self.flags.vehicle_moving.is_set():
                        if self.state == States.WAITING_SPEED:
                            self.logger.info("Vehículo en movimiento. Inicia/reinicia captura")
                            self.start_capture()
                            self.state = States.CAPTURING
                    else:
                        if self.state == States.CAPTURING:
                            self.logger.info("Vehículo detenido. Captura en pausa hasta que vehiculo comience a moverse")
                            self.end_capture()
                            self.state = States.WAITING_SPEED
                time.sleep(0.001)
            except KeyboardInterrupt:
                self.flags.quit.set()

        self.logger.info("Terminando interfaces a agentes")
        for agt in self.agents.items():
            if agt.enabled:
                agt.quit()
        self.logger.info("Enviando mensaje de término a los agentes")
        self.end_agents()
        self.logger.info("Aplicación terminada. Que tengas un buen día =)\n\n\n\n\n")
