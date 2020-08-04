import struct
import serial

DATA_BLOCK = (
    "f"  # acceleration in x-axis (g)
    "f"  # acceleration in y-axis (g)
    "f"  # acceleration in z-axis (g)
    "f"  # angular velocity about in x-axis (rad per sec)
    "f"  # angular velocity about in y-axis (rad per sec)
    "f"  # angular velocity about in z-axis (rad per sec)
    "f"  # quaternion 1-st component
    "f"  # quaternion 2-nd component
    "f"  # quaternion 3-rd component
    "f"  # quaternion 4-th component
)

BAUD_RATE = 115200
READ_TIMEOUT = 0.1
MAX_SAMPLE_RATE = 200

PACKET = ">" + DATA_BLOCK  # Big endian
_unpack = struct.Struct(PACKET).unpack  # Only compile the format string once


def unpack(raw_packet):
    return _unpack(raw_packet)


def build_packet(command, arguments, inc_resp_header=False):
    start_byte = b'\xF7'
    if inc_resp_header:
        start_byte = b'\xF9'
    checksum = 0
    for val in command + arguments:
        checksum += val
    checksum = bytes([checksum % 0x100])
    return start_byte + command + arguments + checksum


class Yost3SpaceAPI():
    def __init__(self, serial_con, sample_rate):
        """

        :param serial_con: An open serial connection
        :param sample_rate: Desired mample rate in Hz
        """
        self.ser = serial_con
        self.sample_rate = min(sample_rate, MAX_SAMPLE_RATE)

    # saves settings to non-volatile memory
    def commit_settings(self):
        command = b'\xE1'
        arguments = b''
        packet = build_packet(command, arguments, False)
        self.ser.write(packet)

    def set_response_header(self):
        command = b'\xDD'  # setup response header. Bitfield
        arguments = b'\x00\x00\x00\x02'  # output Timestamp in microseconds, 4 bytes
        packet = build_packet(command, arguments, False)
        self.ser.write(packet)

    def start_streaming(self):
        packet = build_packet(b'\x55', b'', False)
        self.ser.write(packet)

    def stop_streaming(self):
        packet = build_packet(b'\x56', b'', False)
        self.ser.write(packet)

    def get_raw_accel(self):
        packet = build_packet(b'\x42', b'', False)
        self.ser.write(packet)

    # Configura que datos se generan en streaming
    def set_streaming_slots(self):
        command = b'\x50'
        arguments = b'\x27\x26\x00\xFF\xFF\xFF\xFF\xFF'  # get corrected accelerometer (27), gyro (26) and orientation (quaternions) (00) values.
        packet = build_packet(command, arguments, False)
        self.ser.write(packet)

    # Configura intervalo de envio, diración y delay
    def set_streaming_timing(self):
        command = b'\x52'
        interval_us = (int(1e6 / self.sample_rate)).to_bytes(4, byteorder='big')
        duration_us = b'\xFF\xFF\xFF\xFF'  # Sin fin. Solo termina con el comando de deteción
        delay_us = b'\x00\x00\x00\x00'  # Sin delay
        packet = build_packet(command, interval_us + duration_us + delay_us, False)
        self.ser.write(packet)
