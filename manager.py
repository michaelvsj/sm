import logging
import logging.config
import os
import sys
import time
from enum import Enum, auto
from queue import SimpleQueue
from subprocess import Popen, DEVNULL, STDOUT
from threading import Thread, Event

import yaml

from agents.constants import HWStates, Devices
from bdd import DBInterface
from agents_interface import AgentInterface
from messaging.messaging import Message, AgentStatus
from utils import get_time_str, get_date_str, Coords, get_new_folio

DEFAULT_CONFIG_FILE = 'config.yaml'
LOCALHOST = '127.0.0.1'
KEY_QUIT = 'q'  # Comando de teclado para terminar el programa
KEY_START_STOP = 's'  # para iniciar o detener una sesión de captura
FORCE_START = 'f'  # inicia captura inmediatamente, sin esperar que vehículo inice movimiento
SINGLE_BUTTON = 'bSingleButton'


class Flags:
    """
    Contiene los eventos relevantes para controlar el flujo de captura
    """

    def __init__(self):
        self.vehicle_moving = Event()   
        self.segment_timeout = Event()  # Ha pasado más de T segundos desde que comenzó la captura del segmento
        self.segment_ended = Event()  # El vehículo ya avanzó más de X metros desde que comenzó la captura del segmento
        self.quit = Event()  # Para indicar el fin de la aplicación
        self.critical_agents_ready = Event()


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
        self.sys_id = 'NNN'

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
                self.logger.warning("No es posible habilitar os1_imu sin habilitar también os1_lidar. Se usarán ambos.")
                self.mgr_cfg['use_agents']['os1_lidar'] = True

        for key in self.mgr_cfg.keys():
            self.logger.info(f"Usando config '{key}' : {self.mgr_cfg[key]}")
        self.capture_dir_base = self.mgr_cfg['capture']['output_path']
        os.makedirs(self.capture_dir_base, exist_ok=True)

        # Objeto para interfaz con base de datos
        self.dbi = DBInterface(self.mgr_cfg['sqlite']['db_file'], self.logger)

    def initialize(self):
        """
        Lenanta los agentes
        Levanta los threads de monitoreo de agentes

        :return:
        """
        self.sys_id = self.dbi.get_system_id()
        if not self.sys_id:
            self.logger.warning(f"No fue posible obtener 'sys_id' de la base de datos. Usando valor '{self.sys_id}'.")
        self.change_state(States.STARTING)
        if os.name == 'posix':
            python_exec = os.path.join(sys.exec_prefix, 'bin', 'python')
        elif os.name == 'nt':
            python_exec = os.path.join(sys.exec_prefix, 'Scripts', 'pythonw.exe')
        else:
            self.logger.error("No se pudo determinar sistema operativo")
            sys.exit(1)
        agents_working_dir = os.path.dirname(os.path.abspath(__file__)) + os.sep + "agents"
        self.logger.info(f"Manager ejecutandose con PID {os.getpid()}")
        for agt in self.get_enabled_agents():
            pid = Popen([python_exec, f"{agents_working_dir}{os.sep}agent_{agt.name}.py"], stdin=DEVNULL, stdout=DEVNULL, stderr=STDOUT).pid
            self.logger.info(f"Agente {agt.name} ejecutandose con PID {pid}")
        self.flags.quit.wait(1)  # Les da tiempo para partir antes de intentar conexión
        for agt in self.get_enabled_agents():
            agt.connect()

        # Espera a que agentes se conecten
        self.logger.info("Esperando conexión a agentes")
        for agt in self.get_enabled_agents():
            self.logger.info(f"Conectando a agente {agt.name}")
            while not agt.is_connected():
                self.flags.quit.wait(0.01)
            self.logger.info(f"Agente {agt.name} conectado")
        self.logger.info("Conectado a todos los agentes habilitados")

        self.logger.info("Iniciando thread de reporte de estado de hardware")
        Thread(target=self.check_hw, name="check_hw", daemon=True).start()

        self.logger.info("Iniciando thread de reporte de estado de agentes")
        Thread(target=self.check_critical_agents_ready, name="check_agents_ready", daemon=True).start()

        self.logger.info("Esperando que agentes críticos esten listos para capturar")
        self.flags.critical_agents_ready.wait()
        self.logger.info("Agentes críticos están listos")

        self.logger.info("Iniciando thread de lectura de teclado")
        Thread(target=self.get_keyboard_input, name="get_keyboard_input", daemon=True).start()

        if self.agents.ATMEGA.enabled:
            self.logger.info("Iniciando thread de lectura de botones")
            Thread(target=self.get_buttons, name="get_buttons", daemon=True).start()
            if self.agents.DATA_COPY.enabled:
                self.logger.info("Iniciando thread de estado de copia a pendrive")
                Thread(target=self.check_data_copy, name="check_data_copy", daemon=True).start()

        self.logger.info("--Iniciando thread de monitoreo de avance y tiempo")
        Thread(target=self.check_spacetime, name="check_spacetime", daemon=True).start()

    def check_hw(self):
        # Primero espera 25 segundos que es un poco más que lo que el lidar debiera tardarse en partir
        # Así no da una falsa alarma al usuario
        self.flags.quit.wait(25)
        agents = [self.agents.OS1_LIDAR, self.agents.IMU, self.agents.CAMERA, self.agents.GPS, self.agents.INET]
        devices = [Devices.OS1, Devices.IMU, Devices.CAMERA, Devices.GPS, Devices.ROUTER]
        while not self.flags.quit.is_set():
            offline = False
            error = False
            for a, d in zip(agents, devices):
                if a.enabled:
                    self.agents.ATMEGA.send_data({"device": d, "status": a.hw_status})
                    if a.hw_status == HWStates.NOT_CONNECTED:
                        offline = True
                    elif a.hw_status == HWStates.ERROR:
                        error = True
            if offline:
                self.agents.ATMEGA.send_msg(Message.sys_offline())
            elif error:
                self.agents.ATMEGA.send_msg(Message.sys_error())
            else:
                self.agents.ATMEGA.send_msg(Message.sys_online())

            for agt in self.get_enabled_agents():
                if agt.is_connected and agt.hw_status != HWStates.NOMINAL:
                    self.logger.warning(f"Agente {agt.name} reporta hardware en estado {agt.hw_status}")
                elif not agt.is_connected():
                    self.logger.warning(f"Agente {agt.name} desconectado de manager")

            self.flags.quit.wait(5)

    def check_data_copy(self):
        while not self.flags.quit.is_set():
            state = self.agents.DATA_COPY.get_sys_state()
            if state:
                self.agents.ATMEGA.send_msg(Message(Message.SYS_STATE, state))
            self.flags.quit.wait(0.1)

    def check_spacetime(self):
        while not self.flags.quit.is_set():
            self.flags.quit.wait(0.01)
            if self.state == States.CAPTURING and time.time() > self.segment_current_init_time + \
                    self.mgr_cfg['capture']['splitting_time']:
                self.logger.debug(
                    f"Tiempo en útlimo tramo: {time.time() - self.segment_current_init_time:.1f} s. "
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
                if speed < self.mgr_cfg['capture']['pause_speed']:
                    self.logger.debug(f"GPS speed:{speed}")
                    self.flags.vehicle_moving.clear()
                if speed > self.mgr_cfg['capture']['resume_speed']:
                    self.logger.debug(f"GPS speed:{speed}")
                    self.flags.vehicle_moving.set()
                if self.segment_current_length > self.mgr_cfg['capture']['splitting_distance']:
                    self.logger.debug(f"GPS Dist. acum.: {self.segment_current_length}")
                    self.flags.segment_ended.set()

    def get_buttons(self):
        while not self.flags.quit.is_set():
            b = self.agents.ATMEGA.get_data()
            if b is not None:
                self.logger.debug(f"Boton {b} presionado")
                if b == SINGLE_BUTTON:
                    self.q_user_commands.put(KEY_START_STOP)
            time.sleep(0.1)

    def check_critical_agents_ready(self):
        critical_agents = [self.agents.OS1_LIDAR, self.agents.ATMEGA]
        while not self.flags.quit.is_set():
            all_ready = True
            for agt in critical_agents:
                if agt.enabled:
                    if agt.agent_status != AgentStatus.STAND_BY and agt.agent_status != AgentStatus.CAPTURING:
                        all_ready = False
                        self.flags.critical_agents_ready.clear()
                        self.logger.debug(f"Agente de {agt.name} reporta estado {agt.agent_status}")
                        self.flags.quit.wait(1)
            if all_ready:
                self.flags.critical_agents_ready.set()
            self.flags.quit.wait(0.1)

    def get_keyboard_input(self):
        while not self.flags.quit.is_set():
            k = input()
            if k:
                self.q_user_commands.put(k[0])
            if k == KEY_QUIT:
                break

    def end_capture(self):
        for agt in self.get_enabled_agents():
            agt.send_msg(Message.cmd_end_capture())

    def new_segment(self):
        self.segment_coords_ini = self.coordinates
        self.segment_current_length = 0
        self.segment_current_init_time = time.time()
        self.folio = get_new_folio(self.sys_id)
        self.segment += 1
        self.capture_dir = self.get_new_capture_folder()
        self.logger.info(f"Nuevo segmento: {self.session}/{self.segment:04d}")
        for agt in self.get_enabled_agents():
            agt.send_msg(Message.new_capture(self.capture_dir))

    def update_segment_record(self):
        """
        Una vez finalizada la captura del tramo, actualiza el registro con la info de finalización"
        Esto se debe ejecutar ANTES de iniciar el nuevo tramo, ya que ahí se resetean las variables
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
        rel_dir = self.sys_id + os.sep + get_date_str() + os.sep + self.session + os.sep + f"{self.segment:04d}"
        folder = os.path.join(self.capture_dir_base, rel_dir)
        os.makedirs(folder, exist_ok=True)
        return folder

    def end_agents(self):
        [agt.send_msg(Message.cmd_quit()) for agt in self.get_enabled_agents()]

    def new_session(self):
        self.session = get_time_str()
        self.segment = 0
        self.logger.info(f"Nueva sesión de captura: {self.session}")

    def change_state(self, state):
        self.state = state
        if state == States.CAPTURING:
            self.agents.ATMEGA.send_msg(Message.capture_on())
        elif state == States.WAITING_SPEED:
            self.agents.ATMEGA.send_msg(Message.capture_paused())
        else:
            self.agents.ATMEGA.send_msg(Message.capture_off())

    def get_enabled_agents(self):
        return (agt for agt in self.agents.items() if agt.enabled)

    def run(self):
        try:
            self.initialize()
        except KeyboardInterrupt:
            sys.exit(0)

        # Informa al agent_data_copy la ubicación de la base de datos
        self.agents.DATA_COPY.send_data(self.mgr_cfg['sqlite']['db_file'])

        #  Aquí se implementa la lógica de alto nivel de la máquina de estados, basada en estados y eventos
        self.logger.info("Esperando eventos")
        self.change_state(States.STAND_BY)
        while not self.flags.quit.is_set():
            try:
                if not self.q_user_commands.empty():
                    cmd = self.q_user_commands.get()
                    self.logger.debug(f"Procesando comando de usuario: '{cmd}'")
                    if cmd == KEY_QUIT:
                        self.flags.quit.set()
                    elif cmd == KEY_START_STOP:
                        if self.state == States.CAPTURING or self.state == States.WAITING_SPEED:
                            self.logger.info("Sesión de captura finalizada por usuario")
                            self.end_capture()
                            self.change_state(States.STAND_BY)
                        elif self.state == States.STAND_BY:
                            self.logger.info("Sesión de captura iniciada por usuario. Esperando movimiento del vehículo")
                            self.new_session()
                            self.change_state(States.WAITING_SPEED)
                    elif cmd == FORCE_START:
                        if self.state == States.STAND_BY:
                            self.logger.info(
                                "Sesión de captura forzada (sin esperar velocidad) iniciada por el usuario.")
                            self.flags.vehicle_moving.set()
                            self.new_session()
                            self.new_segment()
                            self.change_state(States.CAPTURING)
                elif self.flags.segment_ended.isSet():
                    if self.state == States.CAPTURING:
                        self.update_segment_record()
                        self.new_segment()
                    self.flags.segment_ended.clear()
                else:
                    if self.flags.vehicle_moving.is_set():
                        if self.state == States.WAITING_SPEED:
                            self.logger.info("Vehículo en movimiento. Inicia/reinicia captura")
                            self.new_segment()
                            self.change_state(States.CAPTURING)
                    else:
                        if self.state == States.CAPTURING:
                            self.logger.info("Vehículo detenido. Captura en pausa hasta que comience a moverse")
                            self.end_capture()
                            self.change_state(States.WAITING_SPEED)
                time.sleep(0.01)
            except KeyboardInterrupt:
                self.flags.quit.set()

        self.logger.info("Terminando interfaces a agentes")
        for agt in self.get_enabled_agents():
            agt.quit()
        self.logger.info("Enviando mensaje de término a los agentes")
        self.end_agents()
        time.sleep(1)
        self.logger.info("Aplicación terminada. Que tengas un buen día =)\nFIN\n\n\n")
