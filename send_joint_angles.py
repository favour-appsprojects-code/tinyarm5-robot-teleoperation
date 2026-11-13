"""TA protocol reference, changed to DRY RUN ONLY for integration safety.

Original example constants and packing are retained. Importing or running
this file never opens a socket. Use python/hardware_demo.py for mock tests.
"""
import struct

# Receiver address. Use its IP address if it runs on another computer.
HOST = "192.168.1.244"
PORT = 5005

# One angle per arm motor, in radians, in the receiver's --ids order.
# Example: receiver --ids 1 2 3 4 5 8 means these angles go to IDs 1-5.
JOINT_ANGLES = [0.0, 0.2, -0.1, 0.0, 0.3]

# Set to None if ID 8 is not in the receiver's --ids. Otherwise this is the
# gripper's raw encoder position: 3000 is open, 2500 is closed. The receiver
# clamps values to that range. ID 8's value always follows the arm angles.
GRIPPER_POSITION = 3000

def main():
    values = JOINT_ANGLES.copy()
    if GRIPPER_POSITION is not None:
        values.append(GRIPPER_POSITION)
    # Header-free little-endian float32, unchanged from the TA example.
    packet = struct.pack(f"<{len(values)}f", *values)
    print(f"REFERENCE DRY RUN ONLY: {values}; destination example {HOST}:{PORT}")
    print(f"{len(packet)} bytes: {packet.hex()}; NO PACKET TRANSMITTED")


if __name__ == '__main__':
    main()
