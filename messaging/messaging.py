import yaml
from hwagent.constants import AgentStatus, Devices, HWStates


class Message:
    """
    typ: Tipo de mensaje. Debe ser un elemento de la clase MsgType
    arg: Cualquier string
    """
    # Types
    COMMAND = "COMMAND"
    SYS_STATE = "SYS_STATE"
    DEVICE_STATE = "DEV_STATE"
    AGENT_STATE = "AGENT_STATE"
    SET_FOLDER = "SET_FOLDER"
    DATA = "DATA"

    # Commands
    CMD_QUIT = "QUIT"
    CMD_START_CAPTURE = "START_CAPTURE"
    CMD_END_CAPTURE = "END_CAPTURE"
    CMD_QUERY_AGENT_STATE = "QUERY_AGENT_STATE"
    CMD_QUERY_HW_STATE = "QUERY_HW_STATE"

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

    def __init__(self, _type, arg):
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
        return cls(cls.COMMAND, cls.CMD_QUIT)

    @classmethod
    def cmd_start_capture(cls):
        return cls(cls.COMMAND, cls.CMD_START_CAPTURE)

    @classmethod
    def cmd_end_capture(cls):
        return cls(cls.COMMAND, cls.CMD_END_CAPTURE)

    @classmethod
    def cmd_query_agent_state(cls):
        return cls(cls.COMMAND, cls.CMD_QUERY_AGENT_STATE)

    @classmethod
    def cmd_query_hw_state(cls):
        return cls(cls.COMMAND, cls.CMD_QUERY_HW_STATE)

    @classmethod
    def set_folder(cls, _dir):
        return cls(cls.SET_FOLDER, _dir)

    @classmethod
    def system_online(cls):
        return cls(cls.SYS_STATE, cls.SYS_ONLINE)

    @classmethod
    def system_offline(cls):
        return cls(cls.SYS_STATE, cls.SYS_OFFLINE)

    @classmethod
    def system_error(cls):
        return cls(cls.SYS_STATE, cls.SYS_ERROR)

    @classmethod
    def system_ext_drive_in_use(cls):
        return cls(cls.SYS_STATE, cls.SYS_EXT_DRIVE_IN_USE)

    @classmethod
    def system_ext_drive_not_in_use(cls):
        return cls(cls.SYS_STATE, cls.SYS_EXT_DRIVE_NOT_IN_USE)

    @classmethod
    def system_ext_drive_full(cls):
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
    def device_state(cls, device, state):
        assert device in Devices.__dict__.keys(), "device debe estar definido en clase devices.Devices"
        assert state in HWStates.__dict__.keys(), "state debe estar definido en devices.HWStates"
        return cls(cls.DEVICE_STATE, {"device": device, "state": state})

    @classmethod
    def agent_state(cls, agentstate):
        assert agentstate in AgentStatus.__dict__.keys(), "argumento 'agentstate' debe estar defnido en clase AgentStatus"
        return cls(cls.AGENT_STATE, agentstate)
