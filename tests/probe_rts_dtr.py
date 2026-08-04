"""Standalone hardware probe - NOT part of the app, doesn't touch any app
code. Run this directly against the real JT-24X COM port to check
whether its RTS and/or DTR control lines are actually wired out to
anything (a spare terminal screw, an unused wire in the bundle, etc.)
before wiring any transistor/relay switching circuit based on them.

Put a multimeter (DC volts, or continuity/logic mode) on each
suspected spare wire while this runs. If a wire's voltage flips
between roughly 0V and 3-5V in time with the printed RTS/DTR state,
that wire is that control line - a real, physically confirmed signal
you can build the switching circuit around. If nothing changes on any
wire, these lines aren't broken out on this converter, and this
approach is a dead end - worth knowing before soldering anything.

Usage:
    python tests/probe_rts_dtr.py COM5
    (replace COM5 with whatever port Windows shows for the JT-24X -
    check Device Manager > Ports, or run this with no argument to list
    what's available)
"""
import sys

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pyserial isn't installed here. Run: pip install pyserial")
    sys.exit(1)


def list_ports():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports found at all.")
        return
    print("Available ports:")
    for p in ports:
        print(f"  {p.device}  -  {p.description}")


def probe(port_name: str):
    print(f"Opening {port_name}...")
    try:
        ser = serial.Serial(port_name, 115200, timeout=0.5)
    except Exception as e:
        print(f"Couldn't open {port_name}: {e}")
        sys.exit(1)

    print("Port open. Put a multimeter on each suspected spare wire now.")
    print("Watch for voltage changing in step with the states printed below.")
    print("Press Ctrl+C to stop.\n")

    try:
        state = 0
        while True:
            # Cycle through all 4 combinations slowly enough to read on a
            # multimeter by eye - fast toggling would just look like noise.
            rts = bool(state & 1)
            dtr = bool(state & 2)
            ser.rts = rts
            ser.dtr = dtr
            print(f"RTS={'HIGH' if rts else 'low '}   DTR={'HIGH' if dtr else 'low '}   "
                  f"(watch your meter now - holding for 3 seconds)")
            import time
            time.sleep(3)
            state = (state + 1) % 4
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("No port given.\n")
        list_ports()
        print("\nRun again as: python tests/probe_rts_dtr.py <PORT>")
        sys.exit(0)
    probe(sys.argv[1])
