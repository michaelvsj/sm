import time
from datetime import datetime

def get_date_str():
    """
    :return: Fecha en formato yyyy.mm.dd
    """
    ts = time.localtime()
    return ".".join(f"{p:02d}" for p in ts[0:3])

def get_time_str():
    """
    :return: Hora en formato hh:mm:ss
    """
    ts = time.localtime()
    return ".".join(f"{p:02d}" for p in ts[3:6])

def get_new_folio(sys_id):
    return 'A' + sys_id + "-" + datetime.now().strftime("%y%m%d%H%M%S")

class Coords:
    lat: float = 0.0
    lon: float = 0.0
