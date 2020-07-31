import math
import struct

from agents.os1.lidar_packet import (
    AZIMUTH_BLOCK_COUNT,
    CHANNEL_BLOCK_COUNT,
    azimuth_angle_from_encoder,
    azimuth_block,
    azimuth_measurement_id,
    azimuth_timestamp,
    azimuth_valid,
    channel_block,
    channel_range,
    channel_reflectivity,
    unpack as unpack_lidar,
    pack_xyz_block,
    CHANNEL_BLOCK_SIZE, RANGE_BIT_MASK)

from agents.os1.imu_packet import unpack as unpack_imu

OS_64_CHANNELS = tuple(i for i in range(CHANNEL_BLOCK_COUNT))
_unpack = struct.Struct("<I").unpack


class UninitializedTrigTable(Exception):
    def __init__(self):
        msg = (
            "You must build_trig_table prior to calling xyz_point or"
            "xyz_points.\n\n"
            "This is likely because you are in a multiprocessing environment."
        )
        super(UninitializedTrigTable, self).__init__(msg)


_trig_table = []


def build_trig_table(beam_altitude_angles, beam_azimuth_angles):
    if not _trig_table:
        for i in range(CHANNEL_BLOCK_COUNT):
            _trig_table.append(
                [
                    math.sin(beam_altitude_angles[i] * math.radians(1)),
                    math.cos(beam_altitude_angles[i] * math.radians(1)),
                    beam_azimuth_angles[i] * math.radians(1),
                ]
            )


def xyz_point(channel_n, azimuth_block):
    if not _trig_table:
        raise UninitializedTrigTable()

    channel = channel_block(channel_n, azimuth_block)
    table_entry = _trig_table[channel_n]
    range = channel_range(channel)  # range in mm
    reflectivity = channel_reflectivity(channel)
    adjusted_angle = table_entry[2] + azimuth_angle_from_encoder(azimuth_block[3])
    x = -range * table_entry[1] * math.cos(adjusted_angle)
    y = range * table_entry[1] * math.sin(adjusted_angle)
    z = range * table_entry[0]

    return [x, y, z, reflectivity]


def imu_values(packet):
    """
    Returns a tuple of: acceleration (gs) and angular speed (deg/sec) for x, y and z axis
    (ax,ay,az,gx,gy,gz)
    """
    if not isinstance(packet, tuple):
        packet = unpack_imu(packet)

    return tuple(packet)


def xyz_points_pack(packet, channels):
    """
    :param packet: paquete de datos UDP proveniente del lidar
    :param channels: canales activos
    :return: un array de bytes con una estructura similar a la del paquete de datos del lidar, pero en coordenadas cartesianas
    """
    if not isinstance(packet, tuple):
        packet = unpack_lidar(packet)

    packed = bytearray()
    invalid_blocks = 0
    valid_blocks = 0
    for b in range(AZIMUTH_BLOCK_COUNT):
        pkt = []  # empty list
        block = azimuth_block(b, packet)
        if not azimuth_valid(block):
            invalid_blocks += 1
            continue
        valid_blocks += 1
        pkt.extend((block[0], block[1], block[2]))
        coords = []
        for c in channels:
            channel_block = block[4 + c * CHANNEL_BLOCK_SIZE: 4 + (c + 1) * CHANNEL_BLOCK_SIZE]
            table_entry = _trig_table[c]
            dist = channel_block[0] & RANGE_BIT_MASK
            reflectivity = channel_block[1]
            adjusted_angle = table_entry[2] + azimuth_angle_from_encoder(block[3])
            x = -dist * table_entry[1] * math.cos(adjusted_angle)
            y = dist * table_entry[1] * math.sin(adjusted_angle)
            z = dist * table_entry[0]
            point = (c, int(x), int(y), int(z), reflectivity)
            coords.extend(point)
        pkt.extend(coords)
        packed.extend(pack_xyz_block(*pkt))

    return packed, [valid_blocks, invalid_blocks]


def peek_encoder_count(packet):
    return _unpack(packet[12:16])[0]
