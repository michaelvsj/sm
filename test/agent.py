from pathlib import Path
import time

from abstract_agent import AbstractHWAgent, AgentStatus, Message, __States

CONFIG_FILE = "config.yaml"


class TestAgent(AbstractHWAgent):
    def __init__(self):
        AbstractHWAgent.__init__(self, CONFIG_FILE)
        self.output_file_is_binary = False

    def _agent_run_non_hw_threads(self):
        """
        Levanta los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

    def _agent_finalize(self):
        """
        Termina los threads que reciben data del harwadre, la parsean y la escriben a disco
        :return:
        """
        pass

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

    def _agent_hw_start(self):
        time.sleep(2)
        return True

    def _agent_hw_stop(self):
        pass


if __name__ == "__main__":
    Path('logs').mkdir(exist_ok=True)
    agent = TestAgent()
    try:
        agent.set_up()
        agent.run()
    except KeyboardInterrupt:
        pass
