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

_dir = f'/home/mich/temp/capture/000'
Path(_dir).mkdir(parents=True, exist_ok=True)
sock.send(Message(Message.SET_FOLDER, _dir).serialize())
sock.send(Message(Message.START_CAPTURE).serialize())
for i in range(1, 3):
    time.sleep(3)
    _dir = f'/home/mich/temp/capture/{i:03d}'
    Path(_dir).mkdir(parents=True, exist_ok=True)
    sock.send(Message(Message.SET_FOLDER, _dir).serialize())

sock.sendall(Message(Message.END_CAPTURE).serialize())
time.sleep(2)
