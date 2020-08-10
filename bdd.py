# -*- coding: utf-8 -*-
import sqlite3
from enum import Enum
import logging
import time

DB_TABLE = "tramos"


class DBInterface:

    def __init__(self, db_file):
        self.db = db_file
        self.logger = logging.getLogger()

    def save_capture(self, folio, carpeta, duracion, distancia, lon_ini, lat_ini, lon_fin, lat_fin):
        timestamp = int(time.time())
        sql = f"INSERT INTO {DB_TABLE} " \
              f"(num_folio, timestamp, estado, dir, duracion, distancia, lon_ini, lat_ini, lon_fin, lat_fin) " \
              f" VALUES " \
              f"('{folio}', {timestamp}, '{EstatusDelTramo.CAP_OK}', '{carpeta}', {duracion}, {distancia}, " \
              f"{lon_ini}, {lat_ini}, {lon_fin}, {lat_fin})"
        try:
            with sqlite3.connect(self.db) as conn:
                conn.execute(sql)
                conn.commit()
            return True
        except Exception:
            self.logger.exception(
                f"Error al crear nuevo registro de tramo en base de datos. Query: {sql}")
            return False

    def get_copy_pending(self):
        sql = f"SELECT dir, num_folio FROM {DB_TABLE} WHERE estado != {EstatusDelTramo.CAPTURING.value}" \
              f" AND (copiado != {EstatusDeCopia.COPIED_OK.value} OR copiado ISNULL)"
        try:
            with sqlite3.connect(self.db) as conn:
                cur = conn.execute(sql)
                records = list(cur.fetchall())
            return records
        except Exception as e:
            self.logger.exception(
                f"Error al obtener registros desde base de datos. Query: {sql}. Error: {str(e)}")
            return False

    def copy_done(self, num_folio):
        sql = f"UPDATE {DB_TABLE} set copiado = {EstatusDeCopia.COPIED_OK.value} WHERE num_folio = {num_folio}"
        try:
            with sqlite3.connect(self.db) as conn:
                conn.execute(sql)
                conn.commit()
            return True
        except Exception as e:
            self.logger.exception(
                f"Error al actualizar registro en base de datos. Query: {sql}. Error: {str(e)}")
            return False


class EstatusDelTramo(Enum):
    CAPTURING = 0
    CAP_FAILED = -1
    CAP_OK = 1
    ANALISIS_FAILED = -2
    ANALISIS_OK = 2
    CHECKED_BY_ITR = 3
    UPLOAD_FAILED = -4
    UPLOAD_OK = 4


class EstatusDeCopia(Enum):
    COPIED_OK = 1
    NOT_COPIED = 0
