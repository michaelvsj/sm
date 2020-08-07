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
from messaging.agent_interface import AgentInterface
from queue import SimpleQueue

DEFAULT_CONFIG_FILE = 'config.yaml'
LOCALHOST = '127.0.0.1'
AGENT_NAMES = ("os1_lidar", "os1_imu", "imu", "gps", "camera", "atmega", "inet")
KEY_QUIT = 'q'  # Comando de teclado para terminar el programa
KEY_START_STOP = ' ' # espacio: para iniciar o detener una sesión de captura

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


class FRAICAPManager:

    def __init__(self, manager_config_file, agents_config_file):
        self.flag_quit = Event()
        self.events = Events()
        self.state = States.STARTING
        self.logger = logging.getLogger("manager")
        self.capture_dir_base = ""
        self.q_user_commands = SimpleQueue()  # Cola de comandos provenientes de de teclado o botonera
        self.agents = dict()
        self.dbi = None
        self.flag_agents_ready = Event()
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
        for agt in AGENT_NAMES:
            try:
                assert isinstance(self.mgr_cfg['use_agents'][agt], bool)
                try:
                    self.agents[agt] = AgentInterface(LOCALHOST, agents_cfg[f"agent_{agt}"]["local_port"])
                    if self.mgr_cfg["use_agents"][agt]:
                        self.agents[agt].enabled = True
                    else:
                        self.agents[agt].enabled = False
                except KeyError:
                    self.logger.warning(f"No hay configuración para el agente agent_{agt} en {agents_config_file}")
                    self.agents[agt] = AgentInterface('', '')
                    self.agents[agt].enabled = False
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
        for agt in AGENT_NAMES:
            if self.agents[agt].enabled:
                pid = Popen([python_exec, f"{agents_working_dir}{os.sep}agent_{agt}.py"]).pid
                self.logger.info(f"Agente {agt} ejecutandose con PID {pid}")
                self.agents[agt].connect()

        # Espera a que agentes se conecten
        self.logger.info("Esperando conexión a agentes")
        for name, agt in self.agents.items():
            if agt.enabled:
                self.logger.info(f"Conectando a agente {name}")
                while not agt.is_connected():
                    time.sleep(0.01)
                self.logger.info(f"Agente {name} conectado")
        self.logger.info("Conectado a todos los agentes habilitados")

        self.logger.info("Iniciando thread de reporte de estado de hardware")
        self.thread_agents_monitor = Thread(target=self.monitor_agents, daemon=True)
        self.thread_agents_monitor.start()

        self.logger.info("INICIANDO THREADS GENERADORES DE EVENTOS")
        self.logger.info("Iniciando thread de lectura de teclado")
        kt = Thread(target=self.get_keyboard_input, daemon=True)
        kt.start()

        self.logger.info("Iniciando thread de lectura de botones")

        self.logger.info("Iniciando thread de monitoreo de avance y tiempo")

        self.logger.info("Iniciando thread de reporte de estado de hardware")

    def monitor_agents(self):
        while not self.flag_quit.is_set():
            all_ready = True
            for name, agt in self.agents.items():
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
            k = input()[0]
            self.q_user_commands.put(k)
            self.events.new_command.set()

    def start_capture_session(self):
        pass

    def end_capture_session(self):
        pass

    def new_segment(self):
        pass

    def pause_capture_session(self):
        pass

    def run(self):
        self.initialize()

        self.logger.info("Esperando que agentes estén listos para capturar")
        try:
            while not self.flag_agents_ready.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            sys.exit(0)

        #  Aquí se implementa la lógica de alto nivel de la máquina de estados, basada en estados y eventos
        self.logger.info("Esperando eventos")
        self.state = States.STAND_BY
        while not self.flag_quit.is_set():
            try:
                if self.events.new_command.is_set():
                    cmd = self.q_user_commands.get()
                    self.logger.info(f"Processing user input: {cmd}")
                    if self.q_user_commands.empty():
                        self.events.new_command.clear()
                    if cmd == KEY_QUIT:
                        self.flag_quit.set()
                    elif cmd == KEY_START_STOP:
                        if self.state == States.CAPTURING or self.state == States.PAUSED:
                            self.end_capture_session()
                        if self.state == States.STAND_BY:
                            self.start_capture_session()
                elif self.events.segment_ended.isSet():
                    self.new_segment()
                    self.events.segment_ended.clear()
                elif self.events.vehicle_stopped.is_set():
                    self.pause_capture_session()
                    self.events.vehicle_stopped.clear()
                elif self.events.vehicle_resumed.is_set():
                    self.pause_capture_session()
                    self.events.vehicle_resumed.clear()

            except KeyboardInterrupt:
                self.flag_quit.set()

