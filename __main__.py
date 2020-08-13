"""
Por defecto usa las configuraciones config.yaml de la carpeta actual
y agents/config.yaml para conocer las direcciones IP de los agentes
Estas configs se pueden pisar pasandoselas como argumento de ejecución (en el mismo orden),
por ejemplo para efectos de testing
"""

from manager import FRAICAPManager, DEFAULT_CONFIG_FILE
import sys
import os

if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    sys.path.append(this_path + os.sep + "agents")
    sys.path.append(this_path + os.sep + "hwagents")

    os.makedirs("logs", exist_ok=True)
    manager_config_file = this_path + os.sep + "config.yaml"
    agents_config_file = this_path + os.sep + "agents/config.yaml"
    if len(sys.argv) > 1:
        manager_config_file = sys.argv[1]
    if len(sys.argv) > 2:
        agents_config_file = sys.argv[2]
    manager = FRAICAPManager(manager_config_file, agents_config_file)
    manager.run()

