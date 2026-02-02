#!/usr/bin/env python3
"""
Create a FIT workout file for Wahoo devices.
This script generates a 1-hour cycling workout at 150W constant power.
"""

import struct
import datetime
import os

# FIT Protocol constants
FIT_HEADER_SIZE = 14
FIT_PROTOCOL_VERSION = 0x20  # Protocol version 2.0
FIT_PROFILE_VERSION = 2140   # Profile version 21.40

# Message types
MESG_FILE_ID = 0
MESG_WORKOUT = 26
MESG_WORKOUT_STEP = 27

# Field types
FIT_ENUM = 0x00
FIT_SINT8 = 0x01
FIT_UINT8 = 0x02
FIT_SINT16 = 0x83
FIT_UINT16 = 0x84
FIT_SINT32 = 0x85
FIT_UINT32 = 0x86
FIT_STRING = 0x07
FIT_FLOAT32 = 0x88
FIT_FLOAT64 = 0x89
FIT_UINT8Z = 0x0A
FIT_UINT16Z = 0x8B
FIT_UINT32Z = 0x8C
FIT_BYTE = 0x0D

# CRC lookup table
CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400
]


def calculate_crc(data, crc=0):
    """Calculate CRC-16 for FIT file."""
    for byte in data:
        # Compute checksum of lower four bits of byte
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[byte & 0xF]
        # Compute checksum of upper four bits of byte
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def fit_timestamp(dt=None):
    """Convert datetime to FIT timestamp (seconds since 1989-12-31 00:00:00 UTC)."""
    if dt is None:
        dt = datetime.datetime.utcnow()
    fit_epoch = datetime.datetime(1989, 12, 31, 0, 0, 0)
    return int((dt - fit_epoch).total_seconds())


def encode_string(s, length):
    """Encode a string to fixed-length bytes."""
    encoded = s.encode('utf-8')[:length-1]
    return encoded + b'\x00' * (length - len(encoded))


class FitWriter:
    """Write FIT files."""

    def __init__(self):
        self.data = bytearray()
        self.local_message_types = {}
        self.next_local_id = 0

    def write_file_header(self):
        """Write the FIT file header (will be updated with data size later)."""
        header = struct.pack('<BBHI4s',
            FIT_HEADER_SIZE,        # Header size
            FIT_PROTOCOL_VERSION,   # Protocol version
            FIT_PROFILE_VERSION,    # Profile version
            0,                      # Data size (placeholder)
            b'.FIT'                 # Data type
        )
        # Calculate header CRC
        header_crc = calculate_crc(header)
        header += struct.pack('<H', header_crc)
        return bytearray(header)

    def define_message(self, global_mesg_num, fields):
        """Write a definition message."""
        local_id = self.next_local_id
        self.next_local_id += 1
        self.local_message_types[global_mesg_num] = local_id

        # Definition message header: 0x40 | local_id
        header = 0x40 | local_id

        # Reserved byte, architecture (0=little endian), global message number, number of fields
        definition = struct.pack('<BBBHB',
            header,
            0,              # Reserved
            0,              # Architecture (0 = little endian)
            global_mesg_num,
            len(fields)
        )

        # Field definitions
        for field_def_num, field_size, field_type in fields:
            definition += struct.pack('<BBB', field_def_num, field_size, field_type)

        self.data.extend(definition)
        return local_id

    def write_data_message(self, global_mesg_num, *values):
        """Write a data message."""
        local_id = self.local_message_types[global_mesg_num]
        self.data.append(local_id)  # Data message header
        for value in values:
            if isinstance(value, bytes):
                self.data.extend(value)
            else:
                self.data.extend(value)

    def finalize(self):
        """Finalize the FIT file with header and CRC."""
        # Create header with correct data size
        header = struct.pack('<BBHI4s',
            FIT_HEADER_SIZE,
            FIT_PROTOCOL_VERSION,
            FIT_PROFILE_VERSION,
            len(self.data),
            b'.FIT'
        )
        header_crc = calculate_crc(header)
        header += struct.pack('<H', header_crc)

        # Calculate data CRC
        data_crc = calculate_crc(self.data)

        # Combine all parts
        return bytearray(header) + self.data + struct.pack('<H', data_crc)


def create_workout_fit(filename, workout_name, duration_seconds, target_power_watts):
    """
    Create a FIT workout file.

    Args:
        filename: Output filename
        workout_name: Name of the workout
        duration_seconds: Duration in seconds
        target_power_watts: Target power in watts
    """
    writer = FitWriter()

    # File ID message definition
    # Fields: type (0), manufacturer (1), product (2), serial_number (3), time_created (4)
    writer.define_message(MESG_FILE_ID, [
        (0, 1, FIT_ENUM),      # type
        (1, 2, FIT_UINT16),    # manufacturer
        (2, 2, FIT_UINT16),    # product
        (3, 4, FIT_UINT32Z),   # serial_number
        (4, 4, FIT_UINT32),    # time_created
    ])

    # Write File ID data
    # type=5 (workout), manufacturer=1 (Garmin compatible), product=1, serial=12345
    timestamp = fit_timestamp()
    writer.write_data_message(MESG_FILE_ID,
        struct.pack('<B', 5),           # type = workout
        struct.pack('<H', 1),           # manufacturer = Garmin
        struct.pack('<H', 1),           # product
        struct.pack('<I', 12345),       # serial number
        struct.pack('<I', timestamp),   # time created
    )

    # Workout message definition
    # Fields: sport (4), capabilities (5), num_valid_steps (6), wkt_name (8)
    workout_name_bytes = encode_string(workout_name, 24)
    writer.define_message(MESG_WORKOUT, [
        (4, 1, FIT_ENUM),       # sport
        (5, 4, FIT_UINT32Z),    # capabilities
        (6, 2, FIT_UINT16),     # num_valid_steps
        (8, 24, FIT_STRING),    # wkt_name
    ])

    # Write Workout data
    # sport=2 (cycling), capabilities=32 (power target), num_valid_steps=1
    writer.write_data_message(MESG_WORKOUT,
        struct.pack('<B', 2),           # sport = cycling
        struct.pack('<I', 32),          # capabilities = power target support
        struct.pack('<H', 1),           # num_valid_steps
        workout_name_bytes,             # workout name
    )

    # Workout Step message definition
    # Fields: message_index (254), wkt_step_name (0), duration_type (1), duration_value (2),
    #         target_type (3), target_value (4), custom_target_low (5), custom_target_high (6), intensity (7)
    step_name = encode_string("150W Steady", 16)
    writer.define_message(MESG_WORKOUT_STEP, [
        (254, 2, FIT_UINT16),   # message_index
        (0, 16, FIT_STRING),    # wkt_step_name
        (1, 1, FIT_ENUM),       # duration_type
        (2, 4, FIT_UINT32),     # duration_value
        (3, 1, FIT_ENUM),       # target_type
        (4, 4, FIT_UINT32),     # target_value
        (5, 4, FIT_UINT32),     # custom_target_value_low
        (6, 4, FIT_UINT32),     # custom_target_value_high
        (7, 1, FIT_ENUM),       # intensity
    ])

    # Write Workout Step data
    # duration_type=0 (time), target_type=3 (power), intensity=0 (active)
    # duration_value is in milliseconds
    # For power target: target_value=0 (custom), then use custom_target_low/high
    writer.write_data_message(MESG_WORKOUT_STEP,
        struct.pack('<H', 0),                   # message_index
        step_name,                              # step name
        struct.pack('<B', 0),                   # duration_type = time
        struct.pack('<I', duration_seconds * 1000),  # duration in milliseconds
        struct.pack('<B', 3),                   # target_type = power
        struct.pack('<I', 0),                   # target_value = 0 (use custom)
        struct.pack('<I', target_power_watts),  # custom_target_value_low
        struct.pack('<I', target_power_watts),  # custom_target_value_high (same for constant)
        struct.pack('<B', 0),                   # intensity = active
    )

    # Finalize and write file
    fit_data = writer.finalize()

    with open(filename, 'wb') as f:
        f.write(fit_data)

    return filename


def main():
    """Create the cycling workout FIT file."""
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(output_dir, "wahoo_1hour_150w_workout.fit")

    # Create 1-hour (3600 seconds) workout at 150W
    duration_seconds = 3600  # 1 hour
    target_power = 150       # 150 watts
    workout_name = "1h 150W Steady"

    create_workout_fit(output_file, workout_name, duration_seconds, target_power)

    print(f"Created workout file: {output_file}")
    print(f"Workout: {workout_name}")
    print(f"Duration: {duration_seconds // 60} minutes")
    print(f"Target Power: {target_power}W")
    print("\nTo use with Wahoo:")
    print("1. Connect your phone to your computer")
    print("2. Copy the .fit file to your Wahoo app's workout folder")
    print("   - iOS: Use Files app or iTunes file sharing")
    print("   - Android: Copy to Wahoo Fitness folder")
    print("3. Or email the file to yourself and open with Wahoo app")


if __name__ == "__main__":
    main()
