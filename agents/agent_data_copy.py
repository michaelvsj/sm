import logging
import os
import shutil
import sys
import time
from threading import Thread
from os import walk, path, sync

import init_agent
from abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from constants import AgentStatus
from messaging.messaging import Message
from bdd import DBInterface


def _copyfileobj_patched(fsrc, fdst, length=8*1024*1024):
    """Patches shutil method to hugely improve copy speed"""
    while 1:
        buf = fsrc.read(length)
        if not buf:
            break
        fdst.write(buf)


shutil.copyfileobj = _copyfileobj_patched


class DataCopy(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False
        self.database = ''
        self.dbi = None
        self.drive_connected = False

    def _agent_process_manager_message(self, msg):
        if msg.typ == Message.DATA:
            self.database = msg.arg

    def _agent_config(self):
        self.usb_mount_path = self.config["usb_mount_path"]

    def _agent_run_non_hw_threads(self):
        Thread(target=self.__check_drive_connected, name="__check_drive_connected", daemon=True).start()
        self.__main_thread = Thread(target=self.__copy_data, name="__copy_data")
        self.__main_thread.start()

    def __check_drive_connected(self):
        while not self.flags.quit.is_set():
            if not path.exists(self.usb_mount_path):
                if self.drive_connected:
                    self.logger.info("Unidad externa desconectada")
                self.drive_connected = False
            else:
                for (dirpath, dirnames, filenames) in walk(self.usb_mount_path):
                    if dirnames:
                        if not self.drive_connected:    # Unidad estaba desconectada y ahora se conectó
                            # La ruta de destino es la primera unidad USB que encuentra montada
                            self.destination = path.join(self.usb_mount_path, dirnames[0])
                            self.logger.info("Unidad externa conectada")
                            self.space_available = True  # Asume que hay espacio suficiente
                            self.drive_connected = True
                    else:
                        if self.drive_connected:
                            self.logger.info("Unidad externa desconectada")
                            self.drive_connected = False
                    break
            time.sleep(0.1)
        
    def _agent_finalize(self):
        self.flags.quit.set()
        self.__main_thread.join(1)

    def _agent_hw_start(self):
        #No aplica para este agente, ya que no hay un sensor que envie datos
        return True

    def _agent_hw_stop(self):
        #No aplica para este agente, ya que no hay un sensor que envie datos
        pass
    
    def _pre_capture_file_update(self):
        pass

    def _agent_check_hw_connected(self):
        #No aplica para este agente, ya que no hay un sensor que envie datos
        return True

    def __copy_data(self):
        self.logger.info("Esperando que manager informe la base de datos")
        while not self.database and not self.flags.quit.is_set():
            time.sleep(0.1)
        self.logger.info(f"Base de datos informada: {self.database}")
        self.dbi = DBInterface(self.database, self.logger)
        while not self.flags.quit.is_set():
            records = self.dbi.get_copy_pending()  # Lee los registros pendientes de copiar
            if self.drive_connected and self.space_available and records:  # Si están dadas las condiciones...
                self.logger.info("Condiciones de copia reunidas. Iniciando respaldo de archivos")
                self.logger.info(f"Tramos pendientes por copiar: {len(records)}")
                self._send_msg_to_mgr(Message.sys_ext_drive_in_use())
                for row in records:
                    # Verifica que no se haya levantado el flag de fin
                    if self.flags.quit.is_set():
                        break
                    folio = row[1]
                    dest = path.join(self.destination, *row[0].split(path.sep)[-4:])
                    # Si directorio de destino ya existe (e.g. si un tramo quedó a medio copiar), lo borra antes de
                    # terminar la copia
                    if path.exists(dest) and path.isdir(dest):
                        shutil.rmtree(dest)
                    try:
                        self.logger.debug(f"Copiando {row[0]}")
                        shutil.copytree(row[0], dest)
                        sync()
                        self.dbi.copy_done(folio)
                        self.logger.debug(f"Archivos copiados a {dest}")
                    except OSError as e:
                        if e.errno == 28:  # No queda espacio en el dispositivo
                            self.logger.error("No hay espacio suficiente en el pendrive")
                            self.space_available = False
                            self._send_msg_to_mgr(Message.sys_ext_drive_full())
                        if e.errno == 13:  # Permision denied
                            self.logger.error(f"Sin permisos de escirtura en {self.destination}")
                            self.drive_connected = False
                        break
                    except:
                        self.logger.exception("")
                    # Vuelve a verificar estado luego de copiar los datos de cada registro
                    if not self.drive_connected:  # Si ya no están dadas las condiciones
                        break  # Sale de bucle que recorre registros
                if not self.flags.quit.is_set():
                    self._send_msg_to_mgr(Message.sys_ext_drive_not_in_use())  # Avisa que terminó de copiar
            self.flags.quit.wait(1)


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    agent = DataCopy(config_file=cfg_file)
    agent.set_up()
    agent.run()
