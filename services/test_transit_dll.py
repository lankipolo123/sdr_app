"""Manual test harness for Transit.dll - run this ON WINDOWS with a
32-bit Python interpreter (the DLL is PE32/x86, confirmed via `file`
and pefile - a 64-bit Python process cannot load a 32-bit DLL at all).

Only AutoConnectSDR's signature below is confirmed, taken directly
from the VB6 Declare statement:
    Private Declare Function AutoConnectSDR Lib "dll\\Transit.dll" _
        (ByVal outBuffer As String, ByVal maxLength As Long) As Long

The other four (CheckConnection, CommandTokens, DisconnectSDR,
SendCommandToSDR) are GUESSES based on their names and the
AutoConnectSDR pattern (out-buffer + length, returning a status code) -
confirm the real signatures against whatever header/docs exist before
trusting this for anything beyond "does it load."

ctypes.WinDLL (not CDLL) because VB6's plain Declare statement only
ever works against __stdcall exports - CDLL would get the stack
cleanup wrong and likely crash or corrupt the stack on return.
"""
import ctypes
import sys

if not sys.platform.startswith("win"):
    sys.exit("This only runs on Windows - Transit.dll is a native Windows DLL.")

DLL_PATH = "dll/Transit.dll"  # matches the "dll\Transit.dll" path hardcoded in the original VB6 Declare statement

dll = ctypes.WinDLL(DLL_PATH)

# --- Confirmed from the VB6 Declare ---
dll.AutoConnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.AutoConnectSDR.restype = ctypes.c_long

# --- Guesses - confirm against real docs before trusting these ---
dll.CheckConnection.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.CheckConnection.restype = ctypes.c_long

dll.DisconnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.DisconnectSDR.restype = ctypes.c_long

# CommandTokens is the "Translate Tokens" function from the whiteboard -
# almost certainly takes a token string in and writes a translated
# command into outBuffer, but the exact shape is unconfirmed.
dll.CommandTokens.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long]
dll.CommandTokens.restype = ctypes.c_long

dll.SendCommandToSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.SendCommandToSDR.restype = ctypes.c_long


def test_auto_connect():
    buf = ctypes.create_string_buffer(256)
    result = dll.AutoConnectSDR(buf, ctypes.sizeof(buf))
    print(f"AutoConnectSDR -> return={result}, buffer={buf.value!r}")
    return result


def test_check_connection():
    buf = ctypes.create_string_buffer(256)
    result = dll.CheckConnection(buf, ctypes.sizeof(buf))
    print(f"CheckConnection -> return={result}, buffer={buf.value!r}")
    return result


def test_disconnect():
    buf = ctypes.create_string_buffer(256)
    result = dll.DisconnectSDR(buf, ctypes.sizeof(buf))
    print(f"DisconnectSDR -> return={result}, buffer={buf.value!r}")
    return result


if __name__ == "__main__":
    print(f"Loaded {DLL_PATH} OK\n")
    print("Step 1: connect")
    test_auto_connect()
    print("\nStep 2: check status")
    test_check_connection()
    print("\nStep 3: disconnect")
    test_disconnect()
