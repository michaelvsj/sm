import yaml
from agents.constants import AgentStatus, HWStates


class Message:
    """
    typ: Tipo de mensaje. Debe ser un elemento de la clase MsgType
    arg: Cualquier string
    """
    # Types
    COMMAND = "COMMAND"
    SYS_STATE = "SYS_STATE"
    HW_STATE = "HW_STATE"
    AGENT_STATE = "AGENT_STATE"
    NEW_CAPTURE = "NEW_CAPTURE"
    END_CAPTURE = "END_CAPTURE"
    DATA = "DATA"   # tipo más bien genérico, donde la estructura del argumento debe ser conocida por el manager y por el agente
    QUIT = "QUIT"
    QUERY_AGENT_STATE = "QUERY_AGENT_STATE"
    QUERY_HW_STATE = "QUERY_HW_STATE"

    # System states
    SYS_ONLINE = "ONLINE"
    SYS_OFFLINE = "OFFLINE"
    SYS_ERROR = "ERROR"
    SYS_CAPTURE_ON = "CAP_ON"
    SYS_CAPTURE_OFF = "CAP_OFF"
    SYS_CAPTURE_PAUSED = "CAP_PAUSED"
    SYS_EXT_DRIVE_IN_USE = "EXT_DRV_IN_USE"
    SYS_EXT_DRIVE_NOT_IN_USE = "EXT_DRV_NOT_IN_USE"
    SYS_EXT_DRIVE_FULL = "SYS_EXT_DRIVE_FULL"

    EOT = b'\x1E'     # Separador de mensajes

    def __init__(self, _type, arg=''):
        self.typ = _type
        self.arg = arg

    def __str__(self):
        return f"typ: {self.typ}, arg: {self.arg}"

    @classmethod
    def deserialize(cls, msg):
        if isinstance(msg, (bytes, bytearray)):
            msg = msg.rstrip(cls.EOT).decode('ascii')
        d = dict(yaml.safe_load(msg))
        return cls(d['type'], d['arg'])

    def __eq__(self, other):
        if isinstance(other, str):
            return self.typ == other
        elif isinstance(other, Message):
            return self.typ == other.typ
        elif isinstance(other, dict):
            return self.typ == other['cmd']
        else:
            return False

    def serialize(self):
        m = yaml.dump({'type': self.typ, 'arg': self.arg}).encode('ascii')
        return m + self.EOT

    @classmethod
    def cmd_quit(cls):
        return cls(cls.QUIT)

    @classmethod
    def cmd_end_capture(cls):
        return cls(cls.END_CAPTURE)

    @classmethod
    def cmd_query_agent_state(cls):
        return cls(cls.QUERY_AGENT_STATE)

    @classmethod
    def cmd_query_hw_state(cls):
        return cls(cls.QUERY_HW_STATE)

    @classmethod
    def new_capture(cls, _dir):
        return cls(cls.NEW_CAPTURE, _dir)

    @classmethod
    def sys_online(cls):
        return cls(cls.SYS_STATE, cls.SYS_ONLINE)

    @classmethod
    def sys_offline(cls):
        return cls(cls.SYS_STATE, cls.SYS_OFFLINE)

    @classmethod
    def sys_error(cls):
        return cls(cls.SYS_STATE, cls.SYS_ERROR)

    @classmethod
    def sys_ext_drive_in_use(cls):
        return cls(cls.SYS_STATE, cls.SYS_EXT_DRIVE_IN_USE)

    @classmethod
    def sys_ext_drive_not_in_use(cls):
        return cls(cls.SYS_STATE, cls.SYS_EXT_DRIVE_NOT_IN_USE)

    @classmethod
    def sys_ext_drive_full(cls):
        return cls(cls.SYS_STATE, cls.SYS_EXT_DRIVE_FULL)

    @classmethod
    def capture_on(cls):
        return cls(cls.SYS_STATE, cls.SYS_CAPTURE_ON)

    @classmethod
    def capture_off(cls):
        return cls(cls.SYS_STATE, cls.SYS_CAPTURE_OFF)

    @classmethod
    def capture_paused(cls):
        return cls(cls.SYS_STATE, cls.SYS_CAPTURE_PAUSED)

    @classmethod
    def agent_hw_state(cls, hwstate):
        assert hwstate in HWStates.__dict__.keys(), "'hwstate' debe estar definido en constants.HWStates"
        return cls(cls.HW_STATE, hwstate)

    @classmethod
    def agent_state(cls, agentstate):
        assert agentstate in AgentStatus.__dict__.keys(), "argumento 'agentstate' debe estar defnido en clase AgentStatus"
        return cls(cls.AGENT_STATE, agentstate)

    @classmethod
    def data_msg(cls, data):
        return cls(cls.DATA, data)
