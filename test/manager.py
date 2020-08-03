import socket
import time
from pathlib import Path
import yaml
from hwagent.abstract_agent import AgentStatus, Message, HWStatus

Path('logs').mkdir(exist_ok=True)

lidar_agent_address = ('127.0.0.1', 30001)
lidar_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
lidar_sock.setblocking(True)

imu_agent_address = ('127.0.0.1', 30002)
imu_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
imu_sock.setblocking(True)

connected = False
while not connected:
    try:
        lidar_sock.connect(lidar_agent_address)
        connected = True
    except ConnectionRefusedError:
        time.sleep(0.1)
        continue

connected = False
while not connected:
    try:
        imu_sock.connect(imu_agent_address)
        connected = True
    except ConnectionRefusedError:
        time.sleep(0.1)
        continue


agent_ready = False
while not agent_ready:
    lidar_sock.sendall(Message(Message.QUERY_AGENT_STATE).serialize())
    rep = yaml.safe_load(lidar_sock.recv(1024).decode('ascii'))
    if rep['arg'] == AgentStatus.STAND_BY:
        agent_ready = True
    else:
        time.sleep(0.1)

time.sleep(5)

_dir = f'/home/mich/temp/capture/000'
Path(_dir).mkdir(parents=True, exist_ok=True)
msg = Message(Message.SET_FOLDER, _dir).serialize()
lidar_sock.sendall(msg)
imu_sock.sendall(msg)

msg = Message(Message.START_CAPTURE).serialize()
lidar_sock.sendall(msg)
imu_sock.sendall(msg)

for i in range(1, 30):
    time.sleep(3)
    _dir = f'/home/mich/temp/capture/{i:03d}'
    Path(_dir).mkdir(parents=True, exist_ok=True)
    msg = Message(Message.SET_FOLDER, _dir).serialize()
    lidar_sock.sendall(msg)
    imu_sock.sendall(msg)

time.sleep(1)
msg = Message(Message.END_CAPTURE).serialize()
lidar_sock.sendall(msg)
imu_sock.sendall(msg)
time.sleep(1)

"""
_dir = f'/home/mich/temp/capture/000'
Path(_dir).mkdir(parents=True, exist_ok=True)
sock.sendall(Message(Message.SET_FOLDER, _dir).serialize())
sock.sendall(Message(Message.START_CAPTURE).serialize())
for i in range(1, 5):
    time.sleep(3)
    _dir = f'/home/mich/temp/capture/{i:03d}'
    Path(_dir).mkdir(parents=True, exist_ok=True)
    sock.sendall(Message(Message.SET_FOLDER, _dir).serialize())

time.sleep(3)
sock.sendall(Message(Message.END_CAPTURE).serialize())
time.sleep(2)
"""