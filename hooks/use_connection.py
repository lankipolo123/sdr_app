from PySide6.QtCore import QObject, Signal

from services.middleware import dll_auto_connect, dll_check_connection, dll_disconnect, dll_send_command


class ConnectionController(QObject):
    """Talks to Transit.dll directly (AutoConnectSDR/DisconnectSDR/
    SendCommandToSDR) instead of opening a real serial port through
    pyserial - the DLL owns the physical connection entirely
    internally, confirmed via AutoConnectSDR (services/test_transit_dll.py:
    return=4, buffer=b'Connected' with real hardware attached).

    SendCommandToSDR's content format is now CONFIRMED (not
    guessed) to be accepted by the DLL, out of 9 signature/content
    theories tried (services/test_transit_dll.py's SEND_ATTEMPTS): the
    address passed as its own string parameter, separate from the rest
    of the command, returned 1 consistently across 5 real attempts in
    a row - every other theory returned -2 (one crashed). See
    dll_send_command()'s own docstring (services/middleware.py) for the
    exact shape. This confirms the DLL ACCEPTS the call - it does NOT
    yet confirm a real module receives or acts on it, since there is
    still no confirmed way to read a response back (see the next
    paragraph) - that's a known, open gap, not something this class
    papers over.

    There is also no confirmed way to receive a response back through
    the DLL - SendCommandToSDR's signature has no output buffer, and no
    DLL export for "read a response" has been found. frame_received
    below is kept for interface compatibility with every existing
    caller (ChannelController, ChannelManager._QueryAttempt), but it
    never actually fires under this implementation - every command
    will hit its response timeout and fall into the existing "no
    response after N attempts - applied anyway, UNCONFIRMED" path
    (hooks/use_channel.py's _on_response_timeout), the same path a
    real unanswered command already used to hit."""

    connected_changed = Signal(bool)
    frame_received = Signal(object)  # never actually emitted - see class docstring
    raw_rx = Signal(bytes)           # never actually emitted - see class docstring
    raw_tx = Signal(bytes)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._connected = False

    @staticmethod
    def list_ports():
        # AutoConnectSDR owns port discovery entirely internally - no
        # port enumeration exists on this side anymore. One placeholder
        # entry keeps every existing "try every port" loop (see
        # ChannelController._find_and_open_connection, ChannelManager.
        # brute_force_query) working unchanged: it tries this one
        # "port," which really just means "ask the DLL to auto-connect."
        return ["DLL"]

    def connect(self, port_name: str = "DLL", baud: int = 115200, parity: str = "N", data_bits: int = 8) -> bool:
        # port_name/baud/parity/data_bits are vestigial, kept only so
        # every existing caller's own call signature doesn't need to
        # change - AutoConnectSDR takes none of them, it owns the
        # physical connection (port, baud rate, everything) internally.
        return_code, buffer_text, error = dll_auto_connect()
        if return_code is None:
            self.error.emit(f"AutoConnectSDR unreachable: {error}")
            return False
        # "Connected" is the only value ever observed for a real
        # attached module; the confirmed "DisConnected" case (nothing
        # attached) and anything else both count as not connected.
        self._connected = buffer_text == "Connected"
        self.connected_changed.emit(self._connected)
        if not self._connected:
            self.error.emit(f"AutoConnectSDR: not connected (return={return_code}, buffer={buffer_text!r})")
        return self._connected

    def disconnect(self):
        dll_disconnect()
        self._connected = False
        self.connected_changed.emit(False)

    def is_connected(self) -> bool:
        return self._connected

    def check_connection(self):
        """Not called by anything yet - exposed for whoever eventually
        needs a live CheckConnection read (its return-code/buffer
        convention for "connected" vs "not" isn't independently
        confirmed the way AutoConnectSDR's is, see dll_check_connection()'s
        docstring) rather than relying on is_connected()'s locally
        cached flag from the last connect()/disconnect() call."""
        return dll_check_connection()

    def send(self, data: bytes) -> bool:
        if not self.is_connected():
            self.error.emit("Cannot send: not connected")
            return False
        return_code, error = dll_send_command(data)
        if return_code is None:
            self.error.emit(f"SendCommandToSDR unreachable: {error}")
            return False
        # Emitted regardless of return_code - NOT a confirmation the
        # command was correctly received. The call shape itself is now
        # confirmed accepted (see class docstring), but what a given
        # return_code actually MEANS (does 1 mean "success"? does a
        # negative value always mean "rejected"?) is still not
        # independently confirmed. raw_tx here means "this reached the
        # DLL call boundary," the same thing pyserial's write() used to
        # mean (the OS accepted the bytes, not that hardware acked
        # them) - real confirmation only ever came from a later
        # response frame, which nothing currently produces (see
        # frame_received in the class docstring above).
        self.raw_tx.emit(data)
        if return_code < 0:
            self.error.emit(f"SendCommandToSDR returned {return_code} (meaning not confirmed yet)")
        return True
