"""
Por defecto usa las configuraciones config.yml de la carpeta actual
y agents/config.yml para conocer las direcciones IP de los agentes
Estas configs se pueden pisar pasandoselas como argumento de ejecución (en el mismo orden),
por ejemplo para efectos de testing
"""

from manager import FRAICAPManager, DEFAULT_CONFIG_FILE
import sys

if __name__ == "__main__":
    manager_config_file = "config.yaml"
    agents_config_file = "agents/config.yml"
    if len(sys.argv) > 1:
        manager_config_file = sys.argv[1]
    if len(sys.argv) > 2:
        agents_config_file = sys.argv[2]
    manager = FRAICAPManager()
    manager.set_up(manager_config_file, agents_config_file)
    manager.run()
