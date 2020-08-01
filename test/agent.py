from pathlib import Path
import time

from hwagent.abstract_agent import AbstractHWAgent, AgentStatus, Message, HWStatus

CONFIG_FILE = "config.yaml"


class TestAgent(AbstractHWAgent):
    def __init__(self):
        AbstractHWAgent.__init__(self, CONFIG_FILE)
        self.output_file_is_binary = False

    def _hw_run_data_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    def _hw_finalize(self):
        """
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    def _hw_start_streaming(self):
        """
        Inicia stream de datos desde el sensor
        """
        pass

    def _hw_stop_streaming(self):
        """
        Detiene el stream de datos desde el sensor
        """
        pass

    def _hw_connect(self):
        time.sleep(2)
        return True

    def _hw_reset_connection(self):
        pass


if __name__ == "__main__":
    Path('logs').mkdir(exist_ok=True)
    agent = TestAgent()
    try:
        agent.set_up()
        agent.run()
    except KeyboardInterrupt:
        pass
