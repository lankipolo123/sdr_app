from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_port_scheduler import PortScheduler

MAX_CHANNELS = 16  # ceiling on how many addresses the UI shows cards for

QUERY_TIMEOUT_MS = 500
QUERY_MAX_ATTEMPTS = 6  # re-send the targeted query a few times before giving up


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

        # Shared by every channel AND Query - there's only one physical
        # port on the confirmed real wiring, so only one command anywhere
        # is ever allowed to actively use it at a time (see
        # use_port_scheduler.py). Without this, two channels used close
        # together could each try to open the same port at once and
        # collide, repeatedly failing and freezing the GUI while they
        # fought over it.
        self.port_scheduler = PortScheduler()

        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController] = {}
        for address in range(MAX_CHANNELS):
            state = self._make_state(address)
            controller = ChannelController(
                state, baud, parity, data_bits, self.logger, port_scheduler=self.port_scheduler,
            )
            controller.command_timeout.connect(self.command_timeout.emit)
            self.states[address] = state
            self.controllers[address] = controller

    def _make_state(self, address: int) -> ChannelState:
        state = ChannelState(address)
        saved = self.config.get_channel(address)
        if saved and "last_level" in saved:
            state.data.last_level = saved["last_level"]
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

        def on_raw_rx(data: bytes):
            state["raw_seen"] = True
            port = ports[state["port_index"]]
            if self.logger:
                self.logger.info(f"Query: raw bytes on {port}: {data.hex(' ').upper()}")

        def on_frame(response: ParsedFrame):
            if response.type != c.TYPE_OUTPUT_SWITCH or response.addr != address:
                return
            timer.stop()
            conn = state["conn"]
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            conn.disconnect()
            state["conn"] = None
            success = len(response.buf) == 1 and response.buf[0] == c.RESP_SUCCESS
            port = ports[state["port_index"]]
            self.command_timeout.emit(
                f"Query: {label} to address {address} on {port} - "
                f"{'confirmed' if success else 'device rejected it'} "
                f"(attempt {state['attempts']}/{QUERY_MAX_ATTEMPTS})."
            )
            self.port_scheduler.release(query_token)

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

        def try_next_port():
            state["port_index"] += 1
            if state["port_index"] >= len(ports):
                msg = f"Query: no response from address {address} after trying {len(ports)} port(s)."
                if self.logger:
                    self.logger.warning(msg)
                self.command_timeout.emit(msg)
                self.port_scheduler.release(query_token)
                return
            port = ports[state["port_index"]]
            conn = ConnectionController()
            if not conn.connect(port, baud, parity, data_bits):
                if self.logger:
                    self.logger.info(f"Query: failed to open {port}, trying next port.")
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
                self.logger.info(f"Query: attempt {state['attempts']} timed out on {port} - {status}.")
            if state["attempts"] < QUERY_MAX_ATTEMPTS:
                send_attempt()
                return
            conn = state["conn"]
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            conn.disconnect()
            state["conn"] = None
            try_next_port()

        timer.timeout.connect(on_timeout)
        self.port_scheduler.acquire(query_token, try_next_port)

    def save_all(self):
        for address, state in self.states.items():
            self.config.set_channel(address, {
                "last_level": state.data.last_level,
            })
        self.config.save()

    def shutdown(self):
        for controller in self.controllers.values():
            controller.cancel_pending()
