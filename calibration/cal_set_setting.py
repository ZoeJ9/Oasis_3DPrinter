"""Send a single GRBL $-setting over raw serial and print the response.

Same rationale as cal_query_settings.py: SerialGRBL.py's Update() loop has
no handler for raw $-prefixed responses, so this bypasses the GRBL class
and talks to the port directly with pyserial.

Usage:
    python cal_set_setting.py --setting 103 --value 922.88 [--port COM5]
"""

import argparse
import time

import serial


def main():
    parser = argparse.ArgumentParser(description="Set a single GRBL $ setting")
    parser.add_argument("--setting", required=True, help="Setting number, e.g. 103 for $103")
    parser.add_argument("--value", required=True, help="New value, e.g. 922.88")
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    conn = serial.Serial(args.port, args.baud, timeout=1)
    time.sleep(2.0)  # GRBL resets on connect, same as SerialGRBL.Connect()
    conn.reset_input_buffer()

    cmd = f"${args.setting}={args.value}"
    print(f"Sending: {cmd}")
    conn.write((cmd + "\n").encode())
    time.sleep(0.5)

    lines = []
    while conn.in_waiting:
        lines.append(conn.readline().decode(errors="ignore").rstrip())
        time.sleep(0.05)

    conn.close()

    if not lines:
        print("No response received. Check the port and that nothing else has it open.")
        return

    print("Response:")
    for line in lines:
        print(f"  {line}")
    if any(line.strip().lower() == "ok" for line in lines):
        print(f"\n${args.setting} set to {args.value}.")
    else:
        print(f"\nNo 'ok' seen — check the response above, the setting may not have been applied.")


if __name__ == "__main__":
    main()
