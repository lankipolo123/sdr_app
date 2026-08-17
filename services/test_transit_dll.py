"""Manual test harness for Transit.dll - run this ON WINDOWS with a
Python interpreter matching the DLL's own bitness (confirm with `file`/
pefile - a 64-bit Python process cannot load a 32-bit DLL or vice versa).

AutoConnectSDR/CheckConnection/DisconnectSDR's signatures - a string
buffer + a length, returning a status code - are now CONFIRMED working
against the real 64-bit DLL (loaded clean, no crash, sensible output:
AutoConnectSDR returned -1/"DisConnected" with no real hardware
attached, exactly the expected behavior). AutoConnectSDR's shape was
originally taken from the VB6 Declare statement:
    Private Declare Function AutoConnectSDR Lib "dll\\Transit.dll" _
        (ByVal outBuffer As String, ByVal maxLength As Long) As Long

CommandTokens and SendCommandToSDR are still UNCONFIRMED GUESSES -
CommandTokens especially, since its real input format (whatever token
vocabulary ends up finalized) isn't settled yet. test_command_tokens()
below just probes it with a placeholder string to see if it crashes or
returns something legible - not a real test of correct behavior until
the actual token format is confirmed.

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


def test_command_tokens(token: bytes = b"TEST"):
    # Placeholder input - the real token vocabulary isn't finalized yet
    # (see services/middleware.py's Token/Action for the current Python-
    # side design). This just checks CommandTokens doesn't crash and
    # shows what comes back for an arbitrary string, not a real
    # correctness test.
    out = ctypes.create_string_buffer(256)
    result = dll.CommandTokens(token, out, ctypes.sizeof(out))
    print(f"CommandTokens({token!r}) -> return={result}, buffer={out.value!r}")
    return result


def test_send_command(command: bytes = b"TEST"):
    # Also a placeholder - real usage almost certainly needs a
    # successful AutoConnectSDR first, and a real command string in
    # whatever format CommandTokens is meant to produce.
    result = dll.SendCommandToSDR(command, len(command))
    print(f"SendCommandToSDR({command!r}) -> return={result}")
    return result


if __name__ == "__main__":
    print(f"Loaded {DLL_PATH} OK\n")
    print("Step 1: connect")
    test_auto_connect()
    print("\nStep 2: check status")
    test_check_connection()
    print("\nStep 3: translate a placeholder token (exploratory - format unconfirmed)")
    test_command_tokens()
    print("\nStep 4: send a placeholder command (exploratory - format unconfirmed)")
    test_send_command()
    print("\nStep 5: disconnect")
    test_disconnect()
