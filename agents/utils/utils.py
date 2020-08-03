# -*- coding: latin-1 -*-
from time import time


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
