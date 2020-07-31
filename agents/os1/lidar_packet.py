import math
import struct
from functools import lru_cache

NUM_USED_CHANNELS = 16 #USamos el OS1-16, que solo posee 16 canales
PACKET_SIZE = 12608
MAX_FRAME_ID = 0xFFFF
TICKS_PER_REVOLUTION = 90112
AZIMUTH_BLOCK_COUNT = 16  # Azimuth blocks per packet
CHANNEL_BLOCK_COUNT = 64  # Channel blocks per Azimuth block
RANGE_BIT_MASK = 0x000FFFFF
CHANNEL_BLOCK = (
    "I"  # Range (20 bits, 12 unused)
    "H"  # Reflectivity (unsigned short, 2 bytes)
    "H"  # Signal photons (unsigned short, 2 bytes)
    "H"  # Noise photons (unsigned short, 2 bytes)
    "H"  # Unused
)
CHANNEL_BLOCK_SIZE = len(CHANNEL_BLOCK)
AZIMUTH_BLOCK = (
    "Q"  # Timestamp (unsigned long, 8 bytes)
    "H"  # Measurement ID (unsigned short, 2 bytes)
    "H"  # Frame ID (unsigned short, 2 bytes)
    "I"  # Encoder Count
    "{}"  # Channel Data
    "I"  # Status
).format(CHANNEL_BLOCK * CHANNEL_BLOCK_COUNT)
AZIMUTH_BLOCK_SIZE = len(AZIMUTH_BLOCK)
PACKET = "<" + (AZIMUTH_BLOCK * AZIMUTH_BLOCK_COUNT)

XYZ_CHANNEL_BLOCK = (
    "B"  # Channel ID, unsigned char, (1 byte)
    "i"  # X, int (4 bytes)
    "i"  # Y, int (4 bytes)
    "i"  # Z, int (4 bytes)
    "H"  # Reflectivity (2 bytes)
)

XYZ_AZIMUTH_BLOCK = (
    "Q"  # Timestamp, unsigned long  (8 bytes)
    "H"  # Measurement ID, unsigned short (2 bytes)
    "H"  # Frame ID, unsigned short (2 bytes)
    "{}"  # Channel Data (channel, x, y, z for each channel)
).format(XYZ_CHANNEL_BLOCK * NUM_USED_CHANNELS)
XYZ_BLOCK = "<" + XYZ_AZIMUTH_BLOCK


RADIANS_360 = 2 * math.pi

# Only compile the format strings once
_unpack = struct.Struct(PACKET).unpack
_xyz_block_pack = struct.Struct(XYZ_BLOCK).pack

def pack_xyz_block(*block_xyz_data):
    return _xyz_block_pack(*block_xyz_data)

def unpack(raw_packet):
    return _unpack(raw_packet)


def azimuth_block(n, packet):
    offset = n * AZIMUTH_BLOCK_SIZE
    return packet[offset : offset + AZIMUTH_BLOCK_SIZE]


def azimuth_timestamp(azimuth_block):
    return azimuth_block[0]


def azimuth_measurement_id(azimuth_block):
    return azimuth_block[1]


def azimuth_frame_id(azimuth_block):
    return azimuth_block[2]


def azimuth_encoder_count(azimuth_block):
    return azimuth_block[3]

def azimuth_angle(azimuth_block):
    return RADIANS_360 * azimuth_block[3] / TICKS_PER_REVOLUTION


@lru_cache(maxsize=2048)
def azimuth_angle_from_encoder(encoder_count):
    return RADIANS_360 * encoder_count / TICKS_PER_REVOLUTION

def azimuth_valid(azimuth_block):
    return azimuth_block[-1] != 0


def channel_block(n, azimuth_block):
    offset = 4 + n * CHANNEL_BLOCK_SIZE
    return azimuth_block[offset : offset + CHANNEL_BLOCK_SIZE]


def channel_range(channel_block):
    return channel_block[0] & RANGE_BIT_MASK


def channel_reflectivity(channel_block):
    return channel_block[1]


def channel_signal_photons(channel_block):
    return channel_block[2]


def channel_noise_photons(channel_block):
    return channel_block[3]
