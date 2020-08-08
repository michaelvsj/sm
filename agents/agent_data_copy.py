import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event
from os import walk, path, sync

import init_agent
from hwagent.abstract_agent import AbstractHWAgent, DEFAULT_CONFIG_FILE
from hwagent.constants import Devices, HWStates, AgentStatus


class DataCopy(AbstractHWAgent):
    def __init__(self, config_file):
        self.agent_name = os.path.basename(__file__).split(".")[0]
        AbstractHWAgent.__init__(self, config_section=self.agent_name, config_file=config_file)
        self.logger = logging.getLogger(self.agent_name)
        self.output_file_is_binary = False

    def _get_device_name(self):
        return Devices.PENDRIVE

    def _agent_process_manager_message(self, msg):
        pass

    def _agent_config(self):
        """
        Lee la config específica de hw del agente
        :return:
        """
        self.usb_mount_path = self.config["usb_mount_path"]
        self.sync_every = self.config["sync_every"]

    def _agent_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        Thread(target=self.__check_drive_connected, name="__check_drive_connected", daemon=True).start()
        self.__main_thread = Thread(target=self.__copy_data, name="__copy_data")
        self.__main_thread.start()

    def __check_drive_connected(self):
        while not self.flag_quit.is_set():
            if not path.exists(self.usb_mount_path):
                if self.drive_connected:
                    self.logger.info("Unidad externa desconectada")
                self.drive_connected = False
            else:
                for (dirpath, dirnames, filenames) in walk(self.usb_mount_path):
                    if dirnames:
                        # La ruta de destino es la primera unidad USB que encuentra montada
                        self.destination = path.join(self.usb_mount_path, dirnames[0])
                        if not self.drive_connected:    # Unidad estaba desconectada y ahora se conectó
                            self.logger.info("Unidad externa conectada")
                            self.space_available = True  # Asume que hay espacio suficiente
                        self.drive_connected = True
                    else:
                        if self.drive_connected:
                            self.logger.info("Unidad externa desconectada")
                        self.drive_connected = False
                    break
            time.sleep(0.5)
        
    def _agent_finalize(self):
        """
        Se prepara para terminar el agente
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        try:
            assert (self.flag_quit.is_set())  # Este flag debiera estar seteado en este punto
        except AssertionError:
            self.logger.error("Se llamó a hw_finalize() sin estar seteado 'self.flag_quit'")
        self.__main_thread.join(1)

    def _agent_start_capture(self):
        """
        Inicia stream de datos desde el sensor
        """
        pass

    def _agent_stop_capture(self):
        """
        Detiene el stream de datos desde el sensor
        """
        pass

    def _agent_connect_hw(self):
        pass

    def _agent_reset_hw_connection(self):
        pass
    
    def _pre_capture_file_update(self):
        pass

    def __copy_data(self):
        while not self.flag_quit.is_set():
            records = self.dbi.get_processed_regs()  # Lee los registros pendientes de copiar
            if self.drive_connected and self.space_available and records:  # Si están dadas las condiciones...
                self.logger.info("Condiciones de copia reunidas. Iniciando respaldo de archivos")
                self.logger.info(f"Tramos pendientes por copiar: {len(records)}")
                self.pipe_conn.send(Pcom(Pcom.Mensaje.COPY_STARTED))  # Inicia copiado
                aux_conunter = 0
                for row in records:
                    # Verifica que no se haya levantado el flag de fin
                    if self.flag_quit.is_set():
                        break
                    timestamp = row[1]
                    dest = path.join(self.destination, row[0].split(path.sep)[-2], row[0].split(path.sep)[-1])
                    self.logger.debug(f"Copiando data a {dest}")
                    # Si directorio de destino ya existe (e.g. si un tramo quedó a medio copiar), lo borra antes de terminar la copia
                    if path.exists(dest):
                        if path.isdir(dest):
                            shutil.rmtree(dest)
                    try:
                        shutil.copytree(row[0], dest)
                    except OSError as e:
                        if e.errno == 28:  # No queda espacio en el dispositivo
                            self.logger.error("No hay espacio suficiente en el pendrive")
                            self.space_available = False
                            break
                    except:
                        self.logger.exception("")
                        pass
                    aux_conunter += 1
                    if aux_conunter >= self.sync_every:
                        sync()
                        aux_conunter = 0
                    self.dbi.copy_done(timestamp)
                    # Vuelve a verificar estado luego de copiar los datos de cada registro
                    if not (self.copy_allowed and self.drive_connected):  # Si ya no están dadas las condiciones
                        self.logger.info(
                            "Ya no están las condiciones para copiar. Termino bucle hasta que se pueda copiar nuevamente")
                        break  # Sale de bucle que recorre registros
                sync()
                self.pipe_conn.send(Pcom(Pcom.Mensaje.COPY_ENDED))  # Avisa que terminó de copiar
            while not (self.copy_allowed and self.drive_connected and self.space_available) and not self.quitting:
                time.sleep(0.1)  # Si no están las condiciones, reintenta en 0.1 segundo


if __name__ == "__main__":
    cfg_file = DEFAULT_CONFIG_FILE
    if len(sys.argv) > 1:
        cfg_file = sys.argv[1]

    Path('logs').mkdir(exist_ok=True)
    agent = DataCopy(config_file=cfg_file)
    agent.set_up()
    agent.run()
