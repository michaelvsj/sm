import math
import struct

PACKET_SIZE = 48

DATA_BLOCK = (
    "Q"  # IMU read time (ns, monotonic system time since boot)
    "Q"  # accelerometer read time (ns, relative to timestamp_mode)
    "Q"  # gyroscope read time (ns, relative to timestamp_mode)
    "f"  # acceleration in x-axis (g)
    "f"  # acceleration in y-axis (g)
    "f"  # acceleration in z-axis (g)
    "f"  # angular velocity about in x-axis (deg per sec)
    "f"  # angular velocity about in y-axis (deg per sec)
    "f"  # angular velocity about in z-axis (deg per sec)
)

PACKET = "<" + DATA_BLOCK

# Only compile the format string once
_unpack = struct.Struct(DATA_BLOCK).unpack


def unpack(raw_packet):
    return _unpack(raw_packet)