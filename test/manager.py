import socket
import time
from pathlib import Path
import yaml
from hwagent.abstract_agent import AgentStatus, Message, HWStatus
from threading import Thread

Path('logs').mkdir(exist_ok=True)

my_socks = {}

#my_socks["os1_lidar"] = {'address':('127.0.0.1', 30001), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
#my_socks["os1_imu"] = {'address':('127.0.0.1', 30002), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
#my_socks["gps"] = {'address':('127.0.0.1', 30003), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
my_socks["camera"] = {'address':('127.0.0.1', 30004), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
for item in my_socks.values():
    item['socket'].setblocking(True)

def send_to_all_agents(msg):
    global my_socks
    print(f"Sending {msg} to all agents")
    for item in my_socks.values():
        item['socket'].sendall(msg)


print("Conectadose a agentes")
for item in my_socks.values():
    connected = False
    while not connected:
        try:
            item['socket'].connect(item['address'])
            connected = True
            time.sleep(0.1) #Parece ser necesario
        except ConnectionRefusedError:
            time.sleep(0.1)
            continue

print("Conectado a agentes")

if "gps" in my_socks.keys():
    def gps_reader():
        while True:
            msg=my_socks['gps']['socket'].recv(1024)
            msg=Message.from_yaml(msg)
            print(msg.arg)
    gps_thread = Thread(target= gps_reader, daemon=True)
    gps_thread.start()


if "os_lidar" in my_socks.keys():
    agent_ready = False
    while not agent_ready:
        my_socks["os1_lidar"]["socket"].sendall(Message(Message.QUERY_AGENT_STATE).serialize())
        rep = yaml.safe_load(my_socks["os1_lidar"]["socket"].recv(1024).decode('ascii'))
        if rep['arg'] == AgentStatus.STAND_BY:
            agent_ready = True
        else:
            time.sleep(0.1)

    time.sleep(5)

_dir = f'/home/mich/temp/capture/000'
Path(_dir).mkdir(parents=True, exist_ok=True)
msg = Message(Message.SET_FOLDER, _dir).serialize()
send_to_all_agents(msg)

msg = Message(Message.START_CAPTURE).serialize()
send_to_all_agents(msg)

for i in range(1, 20):
    time.sleep(5)
    _dir = f'/home/mich/temp/capture/{i:03d}'
    Path(_dir).mkdir(parents=True, exist_ok=True)
    msg = Message(Message.SET_FOLDER, _dir).serialize()
    send_to_all_agents(msg)

time.sleep(1)
msg = Message(Message.END_CAPTURE).serialize()
send_to_all_agents(msg)
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