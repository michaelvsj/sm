import socket
import time
from pathlib import Path
import yaml
from hwagent.abstract_agent import AgentStatus, Message, HWStatus

Path('logs').mkdir(exist_ok=True)

agent_address = ('127.0.0.1', 30001)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setblocking(True)

connected = False
while not connected:
    try:
        sock.connect(agent_address)
        connected = True
    except ConnectionRefusedError:
        time.sleep(0.1)


agent_ready = False
while not agent_ready:
    sock.sendall(Message(Message.QUERY_AGENT_STATE).serialize())
    rep = yaml.safe_load(sock.recv(1024).decode('ascii'))
    if rep['arg'] == AgentStatus.STAND_BY:
        agent_ready = True
    else:
        time.sleep(0.1)

dir = '/home/mich/temp/capture/002'
Path(dir).mkdir(parents=True, exist_ok=True)
sock.sendall(Message(Message.SET_FOLDER, dir).serialize())

sock.sendall(Message(Message.START_CAPTURE).serialize())
time.sleep(5)
sock.sendall(Message(Message.END_CAPTURE).serialize())

