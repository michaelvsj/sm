# -*- coding: latin-1 -*-
from time import time
import subprocess
import os
import re


def reset_usb_device(usb_id, password):
    if os.name == 'posix':
        devs = _get_usb_bus_device_from_id(usb_id)
        if len(devs) == 0:
            return False
        for dev in devs:
            try:
                cp = subprocess.run(["echo", f"{password}", "|", "sudo", "-S", "usbreset", f"{dev}"], check=True,
                                    stdout=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                return False
        return True
    else:
        raise NotImplementedError


def _get_usb_bus_device_from_id(usb_id):
    devices = []
    device_re = re.compile("Bus\s+(?P<bus>\d+)\s+Device\s+(?P<device>\d+).+ID\s(?P<id>\w+:\w+)\s(?P<tag>.+)$", re.I)
    try:
        r = subprocess.check_output(["lsusb", "-d", f"{usb_id}"])
    except subprocess.CalledProcessError:
        return devices
    if len(r):
        r = r.decode('utf8').split('\n')
        for dev in r:
            info = device_re.match(dev)
            if info:
                dinfo = info.groupdict()
                bus = f"/dev/bus/usb/{dinfo['bus']}/{dinfo['device']}"
                devices.append(bus)
    return devices


def check_device_connected(dev_path='', dev_ip='', dev_usb_id='', dev_iface=''):
    if dev_ip != '':
        return check_ping(dev_ip)
    elif dev_path != '':
        return check_dev(dev_path)
    elif dev_usb_id != '':
        return check_usb_id(dev_usb_id)
    elif dev_iface != '':
        return check_iface_inet(dev_iface)
    else:
        return False


def check_iface_inet(iface):
    if os.name == 'posix':
        return "inet" in subprocess.getoutput(f"ifconfig {iface}")
    elif os.name == 'nt':
        return True
        # raise NotImplementedError


def check_ping(ip):
    try:
        if os.name == 'posix':
            subprocess.check_output(["ping", "-c", "1", ip])
        elif os.name == 'nt':
            subprocess.check_output(["ping", "-n", "1", ip])
        return True
    except subprocess.CalledProcessError:
        return False


def check_dev(path):
    if os.name == 'posix':
        return os.path.exists(path)
    elif os.name == 'nt':
        return True
        # raise NotImplementedError


def check_usb_id(id):
    if os.name == 'posix':
        return id in subprocess.getoutput("lsusb")
    elif os.name == 'nt':
        return True
        # raise NotImplementedError


class limited_time_update():
    """
    Devuelve el tiempo, solamente si ha pasado más update_seconds desde la última vez que se llamó
    :return:
    """

    def __init__(self, update_period=1, decimal_places=0):
        self.prev_time = 0
        self.update_seconds = update_period
        self.decimal_places = decimal_places

    def reset(self):
        self.prev_time = 0

    def get_time(self):
        actual_time = time()
        if actual_time - self.prev_time >= self.update_seconds:
            self.prev_time = actual_time
            return "{:.{decimal_places}f}".format(actual_time, decimal_places=self.decimal_places)
        else:
            return ""
