import time

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

