# -*- coding: utf-8 -*-
import sqlite3
from enum import Enum
from datetime import datetime
import logging

DB_TABLE = "tramos"


class DBInterface:

    def __init__(self, db_file):
        self.db = db_file

        self.logger = logging.getLogger('fraicap')

    def new_capture(self, timestamp, dir_, lon_ini, lat_ini):
        timestamp = int(timestamp)
        folio = 'F' + datetime.now().strftime("%Y%m%d%H%M%S")
        sql = f"INSERT INTO {DB_TABLE} (num_folio, timestamp, estado, dir, lon_ini, lat_ini) " \
              f" VALUES ('{folio}', {timestamp}, '{EstatusDelTramo.CAPTURING.value}', '{dir_}', {lon_ini}, {lat_ini})"
        try:
            with sqlite3.connect(self.db) as conn:
                conn.execute(sql)
                conn.commit()
            return True
        except Exception as e:
            self.logger.exception(
                f"Error al crear nuevo registro de tramo en base de datos. Query: {sql}. Error: {str(e)}")
            return False

    def capture_done(self, timestamp, estado, duracion, distancia, lon_fin, lat_fin, paq_rec, paq_perd):
        timestamp = int(timestamp)
        if isinstance(estado, EstatusDelTramo):
            estado = estado.value
        sql = f"UPDATE {DB_TABLE} set estado = {estado}, duracion = {duracion}, distancia = {distancia}, " \
              f"lon_fin = {lon_fin}, lat_fin={lat_fin}, paq_recibidos={paq_rec}, paq_perdidos_porcent = {paq_perd:.1f}" \
              f" WHERE timestamp = {timestamp}"
        try:
            with sqlite3.connect(self.db) as conn:
                conn.execute(sql)
                conn.commit()
            return True
        except Exception as e:
            self.logger.exception(
                f"Error al actualizar registro de tramo en base de datos. Query: {sql}. Error: {str(e)}")
            return False

    def get_processed_regs(self):
        sql = f"SELECT dir, timestamp FROM {DB_TABLE} WHERE estado != {EstatusDelTramo.CAPTURING.value}" \
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

    def copy_done(self, timestamp):
        timestamp = int(timestamp)
        sql = f"UPDATE {DB_TABLE} set copiado = {EstatusDeCopia.COPIED_OK.value} WHERE timestamp = {timestamp}"
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
