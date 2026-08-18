"""Stands in for Transit.dll so the full app stack (ConnectionController,
ChannelController's queue/retry/optimistic-apply state machine, the UI)
can be exercised without real hardware or a real DLL. Used by
tests/dry_run.py.

Intercepts at services.middleware's DLL wrapper functions
(dll_auto_connect/dll_check_connection/dll_disconnect/dll_send_command)
rather than at the old pyserial port level - ConnectionController
(hooks/use_connection.py) now calls those directly; there is no serial
port layer left underneath it to fake instead.

IMPORTANT LIMITATION, not a testing oversight: there is currently no
confirmed way to receive a real response back through the DLL (see
services/test_transit_dll.py - SendCommandToSDR's signature has no
output buffer, and no "read a response" export has been found).
ConnectionController.frame_received never actually fires in the real
app right now, so this fake doesn't simulate it firing either - every
command hits its real response timeout and falls into the existing
"no response after N attempts - applied anyway, UNCONFIRMED" path
(hooks/use_channel.py's _on_response_timeout), exactly like the real
app does today against real hardware. Scenarios that used to depend on
a confirmed ACK/rejection/collision response arriving are gone along
with the byte-level fake modules that used to produce them - see
tests/dry_run.py's own comments for what that means for coverage.
"""


class FakeSDR:
    """One simulated DLL connection's worth of behavior: whether
    AutoConnectSDR finds something, and what SendCommandToSDR does
    when called. Does NOT simulate protocol content or replies - the
    real DLL calls this stands in for don't have a confirmed way to
    produce those either right now (see module docstring)."""

    def __init__(self, present: bool = True, send_return_code: int = -2):
        # present=False simulates AutoConnectSDR finding nothing - the
        # confirmed -1/"DisConnected" case (nothing attached).
        self.present = present
        # -2 matches the actual, confirmed real return every content
        # format sent to SendCommandToSDR has gotten so far (see
        # services/test_transit_dll.py) - default here is "realistic
        # today", not "success", on purpose: no test should accidentally
        # assume send() confirms anything just because a fake said so.
        self.send_return_code = send_return_code
        self.sent_frames: list[bytes] = []
        self.connect_calls = 0
        self.send_calls = 0

    def auto_connect(self):
        self.connect_calls += 1
        if self.present:
            return 4, "Connected", None
        return -1, "DisConnected", None

    def check_connection(self):
        if self.present:
            return 40, "Connected", None
        return -1, "DisConnected", None

    def disconnect(self):
        return 1, "", None

    def send_command(self, data: bytes):
        self.send_calls += 1
        self.sent_frames.append(bytes(data))
        return self.send_return_code, None


def install_fake_dll(sdr: FakeSDR):
    """Reroutes ConnectionController (hooks/use_connection.py) to the
    given FakeSDR instead of the real DLL wrapper functions. Patches
    the names as imported into hooks.use_connection (Python binds
    those at import time, so services.middleware itself is untouched -
    only this module's local references change for the life of the
    test process) - same technique the old install_fake_hardware()
    used for SerialManager/list_com_ports."""
    import hooks.use_connection as uc

    uc.dll_auto_connect = sdr.auto_connect
    uc.dll_check_connection = sdr.check_connection
    uc.dll_disconnect = sdr.disconnect
    uc.dll_send_command = sdr.send_command
