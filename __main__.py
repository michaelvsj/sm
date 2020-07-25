"""
La máquina de estados cambia de estado al ocurrir un evento (¿ y/o un cambio de estado en uno de los agentes? )
"""

from threading import Thread, Event
from enum import Enum, auto

class Events:
    """
    Contiene los eventos relevantes para controlar el flujo de captura
    """
    def __init__(self):
        self.vehicle_stopped = Event()  # El vehículo se detuvo. CUIDADO: Solo debe setearse cuando GPS tenga señal. No confundir v=0 real por v=0 porque no hay señal
        self.vehicle_resumed = Event()  # El vehículo comenzó a moverse denuevo
        self.segment_timeout = Event()  # Ha pasado más de T segundos desde que comenzó la captura del segmento
        self.segment_ended = Event()    # El vehículo ya avanzó más de X metros desde que comenzó la captura del segmento
        self.button_pressed = Event()   # El usuario presionó el boton de inicio/fin de captura

class States(Enum):
    """
    Contiene los estados en que puede estar la máquina de estados que coordina la captura
    """
    STARTING = auto()
    STAND_BY = auto()
    CAPTURING = auto()
    PAUSED = auto()



class StateMachine:

    def __init__(self):
        self.events = Events()
        self.state = States.STARTING
        self.initialize()

    def initialize(self):
        """
        Lenanta los agentes
        Levanta los threads de monitoreo de agentes

        :return:
        """

    def run(self):
        pass