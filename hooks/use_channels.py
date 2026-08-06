from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from services.serial import brute_force_find_port
from state.channel_state import ChannelState
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_discovery import DiscoveryController

MAX_CHANNELS = 16  # ceiling on how many ports we'll ever probe at once

MANUAL_TIMEOUT_MS = 500
MANUAL_MAX_ATTEMPTS = 6  # re-send the targeted query a few times before giving up


class ChannelManager(QObject):
    """Owns one ChannelController per address - each ChannelController
    brute-force finds and opens its own port fresh for every command it
    sends (see hooks/use_channel.py), rather than this manager keeping a
    persistent connection open per channel. That means two addresses on
    one shared physical adapter don't need an explicit "sharing"
    mechanism - nothing holds the port open between commands, so
    whichever channel needs to send next just opens it when it needs to."""

    channel_added = Signal(int)          # address - seen for the first time this session
    channel_online = Signal(int)         # address - a known channel is live/controllable again
    channel_offline = Signal(int)        # address - a known channel's connection was released
    discovery_progress = Signal(int, int)
    discovery_finished = Signal()
    command_timeout = Signal(str)
    raw_tx = Signal(int, bytes)          # address, bytes sent
    raw_rx = Signal(int, bytes)          # address, bytes received

    def __init__(self, config_service, logger=None):
        super().__init__()
        self.config = config_service
        self.logger = logger
        # All 16 possible channel slots exist from the moment the app
        # starts, not just the ones a Scan has found - the UI shows all
        # of them up front (empty/inactive until something answers),
        # rather than building cards on the fly as they're discovered.
        # controllers[address] staying None is the same "known but not
        # currently connected" state already used for a channel that's
        # gone offline - an unfound slot at startup and a since-
        # disconnected one look and behave identically.
        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController | None] = {}
        for address in range(MAX_CHANNELS):
            self.states[address] = self._make_state(address)
            self.controllers[address] = None
        self._known_ports: set[str] = set()  # ports Scan has already found something on - skip re-probing
        self._address_port: dict[int, str] = {}

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        self._discovery = DiscoveryController(baud, parity, data_bits, MAX_CHANNELS, logger)
        self._discovery.channel_found.connect(self._on_channel_found)
        self._discovery.progress.connect(self.discovery_progress.emit)
        self._discovery.finished.connect(self.discovery_finished.emit)

    def _make_state(self, address: int) -> ChannelState:
        state = ChannelState(address)
        saved = self.config.get_channel(address)
        if saved and "last_level" in saved:
            state.data.last_level = saved["last_level"]
        return state

    def start_discovery(self):
        self._discovery.start(exclude_ports=self._known_ports)

    def disconnect_channel_safely(self, address: int, off_timeout_ms: int = 1000):
        """Turns the module's output off first (if it's currently on),
        waits for that to actually be confirmed, THEN disconnects - so a
        module doesn't stay transmitting after it's been physically
        unplugged mid-swap. Falls straight through to a normal
        disconnect_channel() if it's already off (nothing to wait for),
        or if the off command never gets acknowledged within
        off_timeout_ms - better to still let the user disconnect than
        leave them stuck waiting forever on hardware that isn't
        responding (the same unresponsiveness seen throughout today)."""
        controller = self.controllers.get(address)
        state = self.states.get(address)
        if controller is None or state is None or not state.data.output_on:
            self.disconnect_channel(address)
            return

        timer = QTimer(self)
        timer.setSingleShot(True)

        def finish():
            timer.stop()
            try:
                state.changed.disconnect(on_state_changed)
            except (TypeError, RuntimeError):
                pass
            self.disconnect_channel(address)

        def on_state_changed():
            if not state.data.output_on:
                finish()

        timer.timeout.connect(finish)
        state.changed.connect(on_state_changed)
        timer.start(off_timeout_ms)
        controller.turn_output_off()

    def disconnect_channel(self, address: int):
        """Manually release one channel - lets the user physically swap
        which module is wired to a shared adapter (one module out, the
        other in) and pick the new one up with a plain Scan, without
        restarting the app. The channel's card stays put (greyed out,
        not removed) - once a channel's been seen this session it stays
        visible, whether or not it's the one currently wired in. Does
        not touch the module's own power/output state - it's still
        whatever it was last set to.

        No connection to actually close here - ChannelController never
        holds one open between commands, so this just cancels anything
        mid-flight and marks the channel offline."""
        controller = self.controllers.get(address)
        if controller is None:
            return
        controller.cancel_pending()
        self.controllers[address] = None
        port = self._address_port.pop(address, None)
        if port:
            self._known_ports.discard(port)
        self.channel_offline.emit(address)

    def add_manual_channel(self, address: int):
        """Ask one address directly - skips Scan's broadcast Address
        Query stage entirely, the same "just call the address" approach
        as the senior described. Brute-force searches every available
        port (same "just find one that works" spirit as ChannelController
        and the Query button) instead of requiring a port to be picked
        manually - tries each port in turn, with retries, until one
        answers or all are exhausted. On a real response, hands off to
        the exact same path a normal Scan uses, so it behaves
        identically either way (known address comes back online on its
        existing card, new one gets a fresh card)."""
        if self.controllers.get(address) is not None:
            self.command_timeout.emit(f"Address {address} is already connected.")
            return

        ports = ConnectionController.list_ports()
        if not ports:
            self.command_timeout.emit("Manual ask: no ports available.")
            return

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)

        timer = QTimer(self)
        timer.setSingleShot(True)
        state = {"port_index": -1, "conn": None, "attempts": 0, "raw_seen": False}

        def on_raw_rx(data: bytes):
            # Logged even when nothing parses into a valid frame - tells
            # "truly nothing came back" apart from "something came back
            # but wasn't a legal response," which otherwise look
            # identical from the outside as one generic timeout.
            state["raw_seen"] = True
            port = ports[state["port_index"]]
            if self.logger:
                self.logger.info(f"Manual ask: raw bytes on {port}: {data.hex(' ').upper()}")

        def on_frame(frame: ParsedFrame):
            if frame.type != c.TYPE_STATUS_QUERY or frame.addr != address or len(frame.buf) < 6:
                return
            timer.stop()
            conn = state["conn"]
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            state["conn"] = None
            self._on_channel_found(ports[state["port_index"]], address, conn, frame)

        def send_attempt():
            state["attempts"] += 1
            state["raw_seen"] = False
            port = ports[state["port_index"]]
            if self.logger:
                self.logger.info(
                    f"Manual ask: address {address} on {port} "
                    f"(attempt {state['attempts']}/{MANUAL_MAX_ATTEMPTS})"
                )
            state["conn"].send(commands.query_status(address))
            timer.start(MANUAL_TIMEOUT_MS)

        def try_next_port():
            state["port_index"] += 1
            if state["port_index"] >= len(ports):
                msg = f"No response from address {address} after trying {len(ports)} port(s)."
                if self.logger:
                    self.logger.warning(f"Manual ask: {msg}")
                self.command_timeout.emit(msg)
                return
            port = ports[state["port_index"]]
            conn = ConnectionController()
            if not conn.connect(port, baud, parity, data_bits):
                if self.logger:
                    self.logger.info(f"Manual ask: failed to open {port}, trying next port.")
                try_next_port()
                return
            state["conn"] = conn
            state["attempts"] = 0
            conn.raw_rx.connect(on_raw_rx)
            conn.frame_received.connect(on_frame)
            send_attempt()

        def on_timeout():
            port = ports[state["port_index"]]
            if self.logger:
                status = "bytes came back but never formed a valid response" if state["raw_seen"] else \
                    "zero bytes received, nothing came back at all"
                self.logger.info(f"Manual ask: attempt {state['attempts']} timed out on {port} - {status}.")
            if state["attempts"] < MANUAL_MAX_ATTEMPTS:
                send_attempt()
                return
            conn = state["conn"]
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            conn.disconnect()
            state["conn"] = None
            try_next_port()

        timer.timeout.connect(on_timeout)
        try_next_port()

    def brute_force_query(self, address: int, on: bool):
        """Brute-force finds the port (COM1-16, first one that opens -
        see brute_force_find_port), then sends Output ON/OFF and
        actually waits for and verifies the response, retrying up to
        MANUAL_MAX_ATTEMPTS times like every other real command in this
        app - not a blind fire-and-forget (that was tested and
        disproven: the module's real output didn't change from a blind
        send with both modules wired in). Diagnostic only - doesn't
        touch states/controllers, this isn't a real channel connection."""
        port = brute_force_find_port()
        if port is None:
            self.command_timeout.emit("Brute-force query: no COM port (1-16) opened successfully.")
            return

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        conn = ConnectionController()
        if not conn.connect(port, baud, parity, data_bits):
            self.command_timeout.emit(f"Brute-force query: failed to open {port}.")
            return

        label = "ON" if on else "OFF"
        frame = commands.output_on(address) if on else commands.output_off(address)
        timer = QTimer(self)
        timer.setSingleShot(True)
        attempts = {"count": 0, "raw_seen": False}

        def on_raw_rx(data: bytes):
            attempts["raw_seen"] = True
            if self.logger:
                self.logger.info(f"Brute-force query: raw bytes on {port}: {data.hex(' ').upper()}")

        def send_attempt():
            attempts["count"] += 1
            attempts["raw_seen"] = False
            if self.logger:
                self.logger.info(
                    f"Brute-force query: {label} to address {address} on {port} "
                    f"(attempt {attempts['count']}/{MANUAL_MAX_ATTEMPTS})"
                )
            conn.send(frame)
            timer.start(MANUAL_TIMEOUT_MS)

        def on_frame(response: ParsedFrame):
            if response.type != c.TYPE_OUTPUT_SWITCH or response.addr != address:
                return
            timer.stop()
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            conn.disconnect()
            success = len(response.buf) == 1 and response.buf[0] == c.RESP_SUCCESS
            self.command_timeout.emit(
                f"Brute-force query: {label} to address {address} on {port} - "
                f"{'confirmed' if success else 'device rejected it'} "
                f"(attempt {attempts['count']}/{MANUAL_MAX_ATTEMPTS})."
            )

        def on_timeout():
            if self.logger:
                status = "bytes came back but never formed a valid response" if attempts["raw_seen"] else \
                    "zero bytes received, nothing came back at all"
                self.logger.info(f"Brute-force query: attempt {attempts['count']} timed out on {port} - {status}.")
            if attempts["count"] < MANUAL_MAX_ATTEMPTS:
                send_attempt()
                return
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            conn.disconnect()
            self.command_timeout.emit(
                f"Brute-force query: no response to {label} for address {address} on {port} "
                f"after {MANUAL_MAX_ATTEMPTS} attempts."
            )

        timer.timeout.connect(on_timeout)
        conn.raw_rx.connect(on_raw_rx)
        conn.frame_received.connect(on_frame)
        send_attempt()

    def get_controller(self, address: int) -> ChannelController | None:
        return self.controllers[address]

    def get_state(self, address: int) -> ChannelState:
        return self.states[address]

    def save_all(self):
        for address, state in self.states.items():
            self.config.set_channel(address, {
                "last_level": state.data.last_level,
            })
        self.config.save()

    def turn_off_all(self):
        """Emergency stop: turn off every channel that's currently live -
        an offline channel (not the one physically wired in right now)
        has no connection to send anything over."""
        for controller in self.controllers.values():
            if controller is not None:
                controller.turn_output_off()

    def shutdown(self):
        self._discovery.stop()
        for controller in self.controllers.values():
            if controller is not None:
                controller.cancel_pending()

    def _on_channel_found(self, port: str, address: int, conn: ConnectionController, initial_frame: ParsedFrame):
        if self.controllers.get(address) is not None:
            # Two modules reporting the same address at once (e.g. both
            # still at factory default) - already have one live, so
            # release this redundant connection rather than silently
            # overwriting it.
            if self.logger:
                self.logger.warning(
                    f"Discovery: {port} reports address {address}, already in use by another port - skipping."
                )
            conn.disconnect()
            return

        returning = address in self.states
        if returning:
            # A known channel (one of the 16 pre-built slots, or one
            # physically swapped back in) - reuse its existing state (and
            # card) rather than treating it as new.
            state = self.states[address]
        else:
            # Only reachable for an address outside the 16 pre-built
            # slots (e.g. a +Addr manual ask past MAX_CHANNELS) - those
            # still get a card built on the fly.
            state = self._make_state(address)

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        controller = ChannelController(state, baud, parity, data_bits, self.logger, preferred_port=port)
        controller.command_timeout.connect(self.command_timeout.emit)

        self.states[address] = state
        self.controllers[address] = controller
        self._known_ports.add(port)
        self._address_port[address] = port

        # Seed from the discovery frame itself - it's the exact same
        # Status Query response the doc's plan asks for, no need to send
        # a second, redundant one right after finding the channel.
        controller.handle_frame(initial_frame)
        # The discovery/manual-ask connection was only ever needed to
        # find this channel in the first place - ChannelController
        # brute-force finds and opens its own connection fresh for every
        # command it sends from here on, so this one's done its job.
        conn.disconnect()

        self.channel_online.emit(address) if returning else self.channel_added.emit(address)
