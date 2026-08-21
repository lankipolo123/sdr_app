import os

from services.middleware import Token, dispatch_token, dll_log_text
from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from utils.channel_store import load_channel_states, save_channel_states
from utils.signal import Signal, SingleShotTimer
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_port_scheduler import PortScheduler

MAX_CHANNELS = 16

QUERY_TIMEOUT_MS = 300
QUERY_MAX_ATTEMPTS = 4


class ChannelManager:

    def __init__(self, config_service, logger=None):
        self.command_timeout = Signal()
        self.raw_tx = Signal()
        self.raw_rx = Signal()
        self.config = config_service
        self.logger = logger
        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)

        self._channels_path = os.path.join(os.path.dirname(self.config.path), "channels.ini")

        self.port_scheduler = PortScheduler()

        saved_states = load_channel_states(self._channels_path)

        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController] = {}
        # Without Qt's parent-child ownership (previously `parent=manager`),
        # a fire-and-forget _QueryAttempt has no other guaranteed owner
        # across its async lifetime (port_scheduler only holds a reference
        # while genuinely queued, not while e.g. a request is in flight) -
        # keep it alive explicitly here instead of relying on incidental
        # reference chains through its own timer/callbacks.
        self._active_queries: set["_QueryAttempt"] = set()
        for address in range(MAX_CHANNELS):
            state = self._make_state(address, saved_states.get(address))
            controller = ChannelController(
                state, baud, parity, data_bits, self.logger, port_scheduler=self.port_scheduler,
            )
            controller.command_timeout.connect(self.command_timeout.emit)
            controller.raw_tx.connect(lambda data, ctrl=controller: self.raw_tx.emit(ctrl.wire_address, data))
            controller.raw_rx.connect(lambda data, ctrl=controller: self.raw_rx.emit(ctrl.wire_address, data))
            self.states[address] = state
            self.controllers[address] = controller

    def _make_state(self, address: int, saved: dict | None) -> ChannelState:
        state = ChannelState(address)
        if saved:
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

    def send_token(self, token: Token) -> None:
        controller = self.get_controller(token.channel - 1)
        dispatch_token(controller, token)

    def brute_force_query(self, address: int, on: bool):
        ports = ConnectionController.list_ports()
        if not ports:
            self.command_timeout.emit("Query: no ports available.")
            return

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        query = _QueryAttempt(self, address, on, ports, baud, parity, data_bits)
        self._active_queries.add(query)
        query.start()

    def save_all(self):
        save_channel_states(self.states, self._channels_path)

    def shutdown(self):
        for controller in self.controllers.values():
            controller.cancel_pending()


class _QueryAttempt:

    def __init__(self, manager: "ChannelManager", address: int, on: bool,
                 ports: list[str], baud: int, parity: str, data_bits: int):
        self.manager = manager
        self.address = address
        self.ports = ports
        self.baud = baud
        self.parity = parity
        self.data_bits = data_bits
        self.label = "ON" if on else "OFF"
        self.frame = commands.output_on(address) if on else commands.output_off(address)

        self.port_index = -1
        self.conn: ConnectionController | None = None
        self.attempts = 0
        self.raw_seen = False

        self.timer = SingleShotTimer()
        self.timer.timeout.connect(self._on_timeout)

    def start(self):
        self._advance_port()

    def _close_conn(self):
        if self.conn is None:
            return
        self.conn.frame_received.disconnect(self._on_frame)
        self.conn.raw_tx.disconnect(self._on_raw_tx)
        self.conn.raw_rx.disconnect(self._on_raw_rx)
        self.conn.disconnect()
        self.conn = None

    def _on_raw_tx(self, data: bytes):
        self.manager.raw_tx.emit(self.address, data)

    def _on_raw_rx(self, data: bytes):
        self.raw_seen = True
        port = self.ports[self.port_index]
        if self.manager.logger:
            self.manager.logger.info(f"Query: raw bytes on {port}: {dll_log_text(data)}")
        self.manager.raw_rx.emit(self.address, data)

    def _on_frame(self, response: ParsedFrame):
        if response.type != c.TYPE_OUTPUT_SWITCH or response.addr != self.address:
            return
        self.timer.stop()
        self._close_conn()
        self.manager.port_scheduler.release(self)
        success = len(response.buf) == 1 and response.buf[0] == c.RESP_SUCCESS
        port = self.ports[self.port_index]
        self.manager.command_timeout.emit(
            f"Query: {self.label} to address {self.address} on {port} - "
            f"{'confirmed' if success else 'device rejected it'} "
            f"(attempt {self.attempts}/{QUERY_MAX_ATTEMPTS})."
        )
        self.manager._active_queries.discard(self)

    def _request_attempt(self):
        self.manager.port_scheduler.acquire(self, self._on_port_granted)

    def _on_port_granted(self):
        port = self.ports[self.port_index]
        conn = ConnectionController()
        if not conn.connect(port, self.baud, self.parity, self.data_bits):
            if self.manager.logger:
                self.manager.logger.info(f"Query: failed to open {port}, trying next port.")
            self.manager.port_scheduler.release(self)
            self._advance_port()
            return
        self.conn = conn
        conn.raw_tx.connect(self._on_raw_tx)
        conn.raw_rx.connect(self._on_raw_rx)
        conn.frame_received.connect(self._on_frame)
        self._send_attempt()

    def _send_attempt(self):
        self.attempts += 1
        self.raw_seen = False
        port = self.ports[self.port_index]
        if self.manager.logger:
            self.manager.logger.info(
                f"Query: {self.label} to address {self.address} on {port} "
                f"(attempt {self.attempts}/{QUERY_MAX_ATTEMPTS})"
            )
        self.conn.send(self.frame)
        self.timer.start(QUERY_TIMEOUT_MS)

    def _advance_port(self):
        self.port_index += 1
        self.attempts = 0
        if self.port_index >= len(self.ports):
            msg = f"Query: no response from address {self.address} after trying {len(self.ports)} port(s)."
            if self.manager.logger:
                self.manager.logger.warning(msg)
            self.manager.command_timeout.emit(msg)
            self.manager._active_queries.discard(self)
            return
        self._request_attempt()

    def _on_timeout(self):
        port = self.ports[self.port_index]
        if self.manager.logger:
            status = "bytes came back but never formed a valid response" if self.raw_seen else \
                "zero bytes received, nothing came back at all"
            self.manager.logger.info(f"Query: attempt {self.attempts} timed out on {port} - {status}.")
        self._close_conn()
        self.manager.port_scheduler.release(self)
        if self.attempts < QUERY_MAX_ATTEMPTS:
            self._request_attempt()
            return
        self._advance_port()
