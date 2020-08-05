
class Devices:
    OS1_LIDAR = "OS1_LIDAR"
    OS1_IMU = "OS1_IMU"
    GPS = "GPS"
    IMU = "IMU"
    CAMERA = "CAM"
    MODEM = "MODEM"


class HWStates:
    """
    Contiene los estados (mutuamente excluyentes) posibles de los equipos de hardware
    En general esto es solo para efectos informativos ya que el mismo agente debe reiniciar o reconectarse en caso de error
    """
    NOMINAL = "NOMINAL"  # Conectado y no se detectan errores
    WARNING = "WARNING"  # Conectado pero con algun tipo de problema. E.g. pérdida de datos, coordenada 0, datos fuera de rango, etc. IMplica que sensor está con capacidades operatuvas reducidas
    ERROR = "ERROR"  # Conectado pero en estado de error. Implica que el sensor no está operativo.
    NOT_CONNECTED = "NOT_CONNECTED"  # No es posible establecer conexión al equipo (No se puede abrir puerto COM, conexión TCP, etc).

