class HWStates:
    """
    Contiene los estados (mutuamente excluyentes) posibles de los equipos de hardware
    En general esto es solo para efectos informativos ya que el mismo agente debe reiniciar o reconectarse en caso de error
    """
    NOMINAL = "NOMINAL"  # Conectado y no se detectan errores
    WARNING = "WARNING"  # Conectado pero con algun tipo de problema. E.g. pérdida de datos, coordenada 0, datos fuera de rango, etc. IMplica que sensor está con capacidades operatuvas reducidas
    ERROR = "ERROR"  # Conectado pero en estado de error. Implica que el sensor no está operativo.
    NOT_CONNECTED = "NOT_CONNECTED"  # No es posible establecer conexión al equipo (No se puede abrir puerto COM, conexión TCP, etc).


class AgentStatus:
    """
    Contiene los estados (mutuamente excluyentes) posibles de los agentes
    """
    STARTING = 'STARTING'  # Iniciando o re-iniciando. En este último caso, presumiblemente porque se produjo un error y está reconectandose al hardware
    STAND_BY = 'STAND_BY'  # Listo para capturar
    CAPTURING = 'CAPTURING'  # Capturando
    NOT_RESPONDING = 'NOT_RESPONDING'  # Agente no responde. A partir de este estado se puede gatillar un evento para reiniciar el agente


