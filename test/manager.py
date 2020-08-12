import socket
import time
from pathlib import Path
from abstract_agent import AgentStatus, Message
from threading import Thread

Path('logs').mkdir(exist_ok=True)

my_socks = {}

my_socks["os1_lidar"] = {'address':('127.0.0.1', 30001), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
#my_socks["os1_imu"] = {'address':('127.0.0.1', 30002), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
#my_socks["gps"] = {'address':('127.0.0.1', 30003), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
#my_socks["camera"] = {'address':('127.0.0.1', 30004), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}
#my_socks["imu"] = {'address': ('127.0.0.1', 30005), 'socket': socket.socket(socket.AF_INET, socket.SOCK_STREAM)}

for item in my_socks.values():
    item['socket'].setblocking(True)


def send_to_all_agents(msg):
    global my_socks
    print(f"Sending {msg} to all agents")
    for item in my_socks.values():
        item['socket'].sendall(msg)


print("Conectadose a agentes")
for name, item in my_socks.items():
    connected = False
    while not connected:
        try:
            item['socket'].connect(item['address'])
            connected = True
            print(f"Conectado a {name}")
            time.sleep(0.2)  # Parece ser necesario
        except ConnectionRefusedError:
            time.sleep(0.1)
            continue

print("Conectado a todos los agentes")

if "gps" in my_socks.keys():
    def gps_reader():
        while True:
            msg = my_socks['gps']['socket'].recv(1024)
            msg = Message.deserialize(msg)
            print(msg.arg)
    gps_thread = Thread(target=gps_reader, daemon=True)
    gps_thread.start()


if "os1_lidar" in my_socks.keys():
    print("Esperando a que lidar esté listo...")
    agent_ready = False
    while not agent_ready:
        my_socks["os1_lidar"]["socket"].sendall(Message.cmd_query_agent_state().serialize())
        rep = my_socks["os1_lidar"]["socket"].recv(1024)
        mes = Message.deserialize(rep)
        if mes.arg == AgentStatus.STAND_BY:
            agent_ready = True
        else:
            print(f"OS1_Lidar status: {mes.arg}")
            time.sleep(0.1)
    print("Lidar listo")
    time.sleep(5)

_dir = f'/home/mich/temp/capture/000'
Path(_dir).mkdir(parents=True, exist_ok=True)
msg = Message.set_folder(_dir).serialize()
send_to_all_agents(msg)

msg = Message.cmd_start_capture().serialize()
send_to_all_agents(msg)

for i in range(1, 10):
    time.sleep(5)
    _dir = f'/home/mich/temp/capture/{i:03d}'
    Path(_dir).mkdir(parents=True, exist_ok=True)
    msg = Message.set_folder(_dir).serialize()
    send_to_all_agents(msg)

time.sleep(1)
msg = Message.cmd_end_capture().serialize()
send_to_all_agents(msg)
time.sleep(1)
