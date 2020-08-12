"""
La máquina de estados cambia de estado al ocurrir un evento (¿ y/o un cambio de estado en uno de los agentes? )
"""
import time
from subprocess import Popen

import yaml
import sys
from threading import Thread, Event
from enum import Enum, auto
import logging, logging.config
import os

from bdd import DBInterface, EstatusDelTramo
from messaging.messaging import Message, AgentStatus
from messaging.agents_interface import AgentInterface
from hwagent.constants import HWStates, Devices
from queue import SimpleQueue
from utils import get_time_str, get_date_str, Coords, get_new_folio

DEFAULT_CONFIG_FILE = 'config.yaml'
LOCALHOST = '127.0.0.1'
KEY_QUIT = 'q'  # Comando de teclado para terminar el programa
KEY_START_STOP = 's'  # para iniciar o detener una sesión de captura


class Events:
    """
    Contiene los eventos relevantes para controlar el flujo de captura
    """

    def __init__(self):
        self.vehicle_stopped = Event()  # El vehículo se detuvo. CUIDADO: Solo debe setearse cuando GPS tenga señal. No confundir v=0 real por v=0 porque no hay señal
        self.vehicle_resumed = Event()  # El vehículo comenzó a moverse denuevo
        self.segment_timeout = Event()  # Ha pasado más de T segundos desde que comenzó la captura del segmento
        self.segment_ended = Event()  # El vehículo ya avanzó más de X metros desde que comenzó la captura del segmento
        self.new_command = Event()  # El usuario presionó el boton de inicio/fin de captura o una tecla en consola. Como sea, hay un nuevo comando en la cola de comandos


class States(Enum):
    """
    Contiene los estados en que puede estar la máquina de estados que coordina la captura
    """
    STARTING = auto()
    STAND_BY = auto()
    CAPTURING = auto()
    PAUSED = auto()


class AgentProxies:
    """
    ES IMPERATIVO QUE LOS NOMBRES DE LOS AGENTES COINCIDAN CON LOS DE LA CONFIGURACIÓN
    """

    def __init__(self):
        self.OS1_LIDAR = AgentInterface("os1_lidar")
        self.OS1_IMU = AgentInterface("os1_imu")
        self.IMU = AgentInterface("imu")
        self.GPS = AgentInterface("gps")
        self.CAMERA = AgentInterface("camera")
        self.ATMEGA = AgentInterface("atmega")
        self.INET = AgentInterface("inet")
        self.DATA_COPY = AgentInterface("data_copy")

    def items(self):
        return self.__dict__.values()


class FRAICAPManager:
    def __init__(self, manager_config_file, agents_config_file):
        self.flag_quit = Event()
        self.events = Events()
        self.state = States.STARTING
        self.logger = logging.getLogger("manager")
        self.capture_dir_base = ""
        self.capture_dir = ""
        self.q_user_commands = SimpleQueue()  # Cola de comandos provenientes de de teclado o botonera
        self.agents = AgentProxies()
        self.dbi = None
        self.flag_agents_ready = Event()
        self.coordinates = Coords()
        self.segment_coords_ini = Coords()
        self.segment_current_length = 0
        self.segment_current_init_time = 0
        self.segment_current_id = None
        self.mgr_cfg = dict()
        self.set_up(manager_config_file, agents_config_file)

    def set_up(self, manager_config_file, agents_config_file):
        try:
            with open(manager_config_file, 'r') as config_file:
                self.mgr_cfg = yaml.safe_load(config_file)
        except FileNotFoundError:
            self.logger.error(f"Archivo de configuración {manager_config_file} no encontrado. Terminando.")
            sys.exit(-1)
        logging.config.dictConfig(self.mgr_cfg["logging"])
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
        for agt in self.agents.items():
            if agt.enabled:
                pid = Popen([python_exec, f"{agents_working_dir}{os.sep}agent_{agt.name}.py"]).pid
                self.logger.info(f"Agente {agt.name} ejecutandose con PID {pid}")
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

        self.logger.info("Iniciando thread de reporte de estado de hardware")
        Thread(target=self.check_agents_ready, name="check_agents_ready", daemon=True).start()

        self.logger.info("INICIANDO THREADS GENERADORES DE EVENTOS")
        self.logger.info("Iniciando thread de lectura de teclado")
        Thread(target=self.get_keyboard_input, name="get_keyboard_input", daemon=True).start()

        if self.agents.ATMEGA.enabled:
            self.logger.info("Iniciando thread de lectura de botones")
            Thread(target=self.get_buttons, name="get_buttons", daemon=True).start()

        self.logger.info("Iniciando thread de monitoreo de avance y tiempo")
        Thread(target=self.check_spacetime, name="check_spacetime", daemon=True).start()

    def check_hw(self):
        while not self.flag_quit.is_set():
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
            time.sleep(1)

    def check_spacetime(self):
        was_moving = False
        while not self.flag_quit.is_set():
            if self.state == States.CAPTURING and time.time() > self.segment_current_init_time + \
                    self.mgr_cfg['capture']['splitting_time']:
                self.logger.debug(
                    f"Tiempo acumulado en útlimo tramo: {time.time() - self.segment_current_init_time:.1f} segundos. "
                    f"Seteando bandera para generar nuevo tramo")
                self.events.segment_ended.set()
                time.sleep(0.01)
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
                if speed < self.mgr_cfg['capture']['pause_speed'] and was_moving:
                    was_moving = False
                    self.events.vehicle_stopped.set()

                # Reactivación post-detención
                if speed > self.mgr_cfg['capture']['resume_speed'] and not was_moving:
                    was_moving = True
                    self.events.vehicle_resumed.set()

                # División de captura en tramos, por distancia
                if self.segment_current_length > self.mgr_cfg['capture']['splitting_distance']:
                    self.events.segment_ended.set()

                time.sleep(0.01)

    def get_buttons(self):
        while not self.flag_quit.is_set():
            b = self.agents.ATMEGA.get_data()
            if b is not None:
                self.q_user_commands.put(b)
            time.sleep(0.1)

    def check_agents_ready(self):
        while not self.flag_quit.is_set():
            all_ready = True
            for agt in self.agents.items():
                if agt.enabled:
                    if agt.agent_status != AgentStatus.STAND_BY and agt.agent_status != AgentStatus.CAPTURING:
                        all_ready = False
            if all_ready:
                self.flag_agents_ready.set()
            else:
                self.flag_agents_ready.clear()
            time.sleep(0.2)

    def get_keyboard_input(self):
        while not self.flag_quit.is_set():
            k = input()
            if k:
                self.q_user_commands.put(k[0])
                self.events.new_command.set()

    def start_capture(self):
        self.logger.info("Iniciando captura")
        self.new_segment()
        for agt in self.agents.items():
            if agt.enabled:
                agt.send_msg(Message.cmd_start_capture())

    def end_capture(self):
        self.logger.info("Terminando captura")
        for agt in self.agents.items():
            if agt.enabled:
                agt.send_msg(Message.cmd_end_capture())

    def new_segment(self):
        self.segment_coords_ini = self.coordinates
        self.segment_current_length = 0
        self.segment_current_init_time = time.time()
        self.segment_current_id = get_new_folio()
        self.capture_dir = self.get_new_capture_folder()
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
        self.logger.debug(f"Folio: {self.segment_current_id}, duración: {duracion}, distancia: {distancia}")
        self.dbi.save_capture(folio=self.segment_current_id,
                              carpeta=self.capture_dir,
                              duracion=duracion,
                              distancia=distancia,
                              lon_ini=lon_ini,
                              lat_ini=lat_ini,
                              lon_fin=lon_fin,
                              lat_fin=lat_fin)

    def get_new_capture_folder(self):
        folder = os.path.join(os.path.join(self.capture_dir_base, get_date_str()), get_time_str())
        os.makedirs(folder, exist_ok=True)
        self.logger.info(f"Nueva carpeta de destino: {folder}")
        return folder

    def end_agents(self):
        for agt in self.agents.items():
            if agt.enabled:
                agt.send_msg(Message.cmd_quit())

    def run(self):
        try:
            self.initialize()
        except KeyboardInterrupt:
            sys.exit(0)

        self.logger.info("Esperando que agentes estén listos para capturar")
        try:
            while not self.flag_agents_ready.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            sys.exit(0)

        self.logger.info("Iniciando thread de reporte de estado de hardware")
        Thread(target=self.check_hw, name="check_hw", daemon=True).start()

        # Informa al agent_data_copy la ubicación de la base de datos
        self.agents.DATA_COPY.send_msg(Message(Message.DATA, self.mgr_cfg['sqlite']['db_file']))

        #  Aquí se implementa la lógica de alto nivel de la máquina de estados, basada en estados y eventos
        self.logger.info("Esperando eventos")
        self.state = States.STAND_BY
        while not self.flag_quit.is_set():
            try:
                if self.events.new_command.is_set():
                    cmd = self.q_user_commands.get()
                    self.logger.info(f"Procesando comando de usuario: '{cmd}'")
                    if self.q_user_commands.empty():
                        self.events.new_command.clear()
                    if cmd == KEY_QUIT:
                        self.flag_quit.set()
                    elif cmd == KEY_START_STOP:
                        if self.state == States.CAPTURING or self.state == States.PAUSED:
                            self.end_capture()
                            self.state = States.STAND_BY
                        elif self.state == States.STAND_BY:
                            self.start_capture()
                            self.state = States.CAPTURING
                elif self.events.segment_ended.isSet():
                    if self.state == States.CAPTURING:
                        self.update_segment_record()
                        self.new_segment()
                    self.events.segment_ended.clear()
                elif self.events.vehicle_stopped.is_set():
                    if self.state == States.CAPTURING:
                        self.end_capture()
                        self.state = States.PAUSED
                    self.events.vehicle_stopped.clear()
                elif self.events.vehicle_resumed.is_set():
                    if self.state == States.PAUSED:
                        self.start_capture()
                        self.state = States.CAPTURING
                    self.events.vehicle_resumed.clear()
                time.sleep(0.001)
            except KeyboardInterrupt:
                self.flag_quit.set()

        self.end_agents()
