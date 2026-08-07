import os

from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from utils.channel_store import load_channel_states, save_channel_states
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_port_scheduler import PortScheduler

MAX_CHANNELS = 16  # ceiling on how many addresses the UI shows cards for

QUERY_TIMEOUT_MS = 300
QUERY_MAX_ATTEMPTS = 4  # re-send the targeted query a few times before giving up


class ChannelManager(QObject):
    """Owns one ChannelController per address, all 16 live from the
    moment the app starts. There's no discovery/scan step and no
    online/offline distinction anymore - every ChannelController already
    brute-force finds and opens its own port fresh for every command it
    sends (see hooks/use_channel.py), with retries and an optimistic
    apply-on-timeout if nothing answers. That's strictly better than
    requiring a prior Scan or +Addr response before a channel becomes
    controllable: on a shared/collision-prone line, waiting for a
    confirmed discovery response first only means waiting for something
    that might never come, when the blind command would have gotten
    through anyway."""

    command_timeout = Signal(str)
    raw_tx = Signal(int, bytes)          # address, bytes sent
    raw_rx = Signal(int, bytes)          # address, bytes received

    def __init__(self, config_service, logger=None):
        super().__init__()
        self.config = config_service
        self.logger = logger
        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)

        # Lives next to config.json, in whatever directory THIS
        # ConfigService instance actually points at - not a fixed global
        # path, or every ConfigService instance (e.g. two isolated test
        # runs, each with their own tmp config dir) would read/write the
        # exact same real channels.ini and cross-contaminate each other's
        # channel state.
        self._channels_path = os.path.join(os.path.dirname(self.config.path), "channels.ini")

        # Shared by every channel AND Query - there's only one physical
        # port on the confirmed real wiring, so only one command anywhere
        # is ever allowed to actively use it at a time (see
        # use_port_scheduler.py). Without this, two channels used close
        # together could each try to open the same port at once and
        # collide, repeatedly failing and freezing the GUI while they
        # fought over it.
        self.port_scheduler = PortScheduler()

        # Every channel's own mode/power/output is persisted to a single
        # flat .ini file (see utils/channel_store.py), not this JSON
        # config - read once up front rather than re-reading the file
        # for every one of the 16 channels being constructed.
        saved_states = load_channel_states(self._channels_path)

        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController] = {}
        for address in range(MAX_CHANNELS):
            state = self._make_state(address, saved_states.get(address))
            controller = ChannelController(
                state, baud, parity, data_bits, self.logger, port_scheduler=self.port_scheduler,
            )
            controller.command_timeout.connect(self.command_timeout.emit)
            self.states[address] = state
            self.controllers[address] = controller

    def _make_state(self, address: int, saved: dict | None) -> ChannelState:
        state = ChannelState(address)
        if saved:
            # UI-only restore - shows the card looking like it did last
            # session (mode dropdown, slider position, toggle state), but
            # nothing here actually sends a command. Matches the app's
            # existing "nothing happens automatically on launch" design
            # (no auto-scan, no auto-query) - a real send only ever
            # follows an explicit tap/interaction with that specific card.
            if "mode" in saved:
                state.data.mode = saved["mode"]
            if "last_level" in saved:
                state.data.last_level = saved["last_level"]
            if "output_on" in saved:
                state.data.output_on = saved["output_on"]
        return state

    def get_controller(self, address: int) -> ChannelController:
        return self.controllers[address]

    def get_state(self, address: int) -> ChannelState:
        return self.states[address]

    def brute_force_query(self, address: int, on: bool):
        """Standalone diagnostic, separate from the cards: type in one
        address, brute-force finds an available port the same way every
        real command does (see ConnectionController.list_ports() /
        ChannelController._find_and_open_connection), sends Output ON/OFF
        to it, and actually waits for and verifies the response -
        retrying up to QUERY_MAX_ATTEMPTS times - instead of firing
        blind. Doesn't touch states/controllers or build a card; this
        isn't a real channel connection, just a one-off check.

        Goes through the same shared port_scheduler every channel does -
        without it, Query could collide with a card's in-flight command
        the exact same way two channels used close together used to
        collide with each other (see PortScheduler)."""
        ports = ConnectionController.list_ports()
        if not ports:
            self.command_timeout.emit("Query: no ports available.")
            return

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        label = "ON" if on else "OFF"
        frame = commands.output_on(address) if on else commands.output_off(address)

        query_token = object()  # unique per-call identity for the scheduler - Query has no persistent object like a ChannelController does
        timer = QTimer(self)
        timer.setSingleShot(True)
        state = {"port_index": -1, "conn": None, "attempts": 0, "raw_seen": False}

        def close_conn():
            conn = state["conn"]
            if conn is None:
                return
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            conn.disconnect()
            state["conn"] = None

        def on_raw_rx(data: bytes):
            state["raw_seen"] = True
            port = ports[state["port_index"]]
            if self.logger:
                self.logger.info(f"Query: raw bytes on {port}: {data.hex(' ').upper()}")

        def on_frame(response: ParsedFrame):
            if response.type != c.TYPE_OUTPUT_SWITCH or response.addr != address:
                return
            timer.stop()
            close_conn()
            self.port_scheduler.release(query_token)
            success = len(response.buf) == 1 and response.buf[0] == c.RESP_SUCCESS
            port = ports[state["port_index"]]
            self.command_timeout.emit(
                f"Query: {label} to address {address} on {port} - "
                f"{'confirmed' if success else 'device rejected it'} "
                f"(attempt {state['attempts']}/{QUERY_MAX_ATTEMPTS})."
            )

        def request_attempt():
            # Asks for the port for exactly ONE attempt (open, send,
            # wait) rather than for this whole address's entire
            # sweep-and-retry cycle - otherwise an unanswering address
            # would hold the shared port for up to QUERY_MAX_ATTEMPTS *
            # len(ports) attempts in a row, freezing every channel card
            # queued behind it for that whole stretch.
            self.port_scheduler.acquire(query_token, on_port_granted)

        def on_port_granted():
            port = ports[state["port_index"]]
            conn = ConnectionController()
            if not conn.connect(port, baud, parity, data_bits):
                if self.logger:
                    self.logger.info(f"Query: failed to open {port}, trying next port.")
                self.port_scheduler.release(query_token)
                advance_port()
                return
            state["conn"] = conn
            conn.raw_rx.connect(on_raw_rx)
            conn.frame_received.connect(on_frame)
            send_attempt()

        def send_attempt():
            state["attempts"] += 1
            state["raw_seen"] = False
            port = ports[state["port_index"]]
            if self.logger:
                self.logger.info(
                    f"Query: {label} to address {address} on {port} "
                    f"(attempt {state['attempts']}/{QUERY_MAX_ATTEMPTS})"
                )
            state["conn"].send(frame)
            timer.start(QUERY_TIMEOUT_MS)

        def advance_port():
            state["port_index"] += 1
            state["attempts"] = 0
            if state["port_index"] >= len(ports):
                msg = f"Query: no response from address {address} after trying {len(ports)} port(s)."
                if self.logger:
                    self.logger.warning(msg)
                self.command_timeout.emit(msg)
                return
            request_attempt()

        def on_timeout():
            port = ports[state["port_index"]]
            if self.logger:
                status = "bytes came back but never formed a valid response" if state["raw_seen"] else \
                    "zero bytes received, nothing came back at all"
                self.logger.info(f"Query: attempt {state['attempts']} timed out on {port} - {status}.")
            close_conn()
            self.port_scheduler.release(query_token)
            if state["attempts"] < QUERY_MAX_ATTEMPTS:
                request_attempt()
                return
            advance_port()

        timer.timeout.connect(on_timeout)
        advance_port()

    def save_all(self):
        save_channel_states(self.states, self._channels_path)

    def shutdown(self):
        for controller in self.controllers.values():
            controller.cancel_pending()
