"""Query and print GRBL's full $$ settings over raw serial.

SerialGRBL.py's Update() loop only parses ok/error/alarm/[...]/<status
responses — it has no handler for raw $-prefixed replies, so $$ output is
silently dropped if sent through the GRBL class. This bypasses GRBL
entirely and talks to the port directly with pyserial.

Usage:
    python cal_query_settings.py [--port COM5]
"""

import argparse
import time

import serial


def main():
    parser = argparse.ArgumentParser(description="Query GRBL $$ settings")
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    conn = serial.Serial(args.port, args.baud, timeout=1)
    time.sleep(2.0)  # GRBL resets on connect, same as SerialGRBL.Connect()
    conn.reset_input_buffer()

    conn.write(b"$$\n")
    time.sleep(1.0)

    lines = []
    while conn.in_waiting:
        lines.append(conn.readline().decode(errors="ignore").rstrip())
        time.sleep(0.05)

    conn.close()

    if not lines:
        print("No response received. Check the port and that nothing else has it open.")
        return

    print(f"GRBL settings on {args.port}:")
    for line in lines:
        print(f"  {line}")


if __name__ == "__main__":
    main()
