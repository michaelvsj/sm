import socket
import time
from pathlib import Path

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

dir = '\\mnt\\data\\capture\\002'
Path(dir).mkdir(exist_ok=True)
try:
    while True:
        sock.sendall(Message(Message.QUERY_AGENT_STATE).serialize())
        print(sock.recv(1024).decode('ascii'))
        time.sleep(1)
        sock.sendall(Message(Message.SET_FOLDER, dir).serialize())
except KeyboardInterrupt:
    pass
except Exception as e:
    print(str(e))
