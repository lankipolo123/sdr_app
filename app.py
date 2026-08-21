import json
import os

import webview

from hooks import AppController
from hooks.use_channels import MAX_CHANNELS
from services.middleware import dll_decode_frame
from services.protocol import constants as c
from state.level_map import HEX_TO_LEVEL, LEVEL_LABELS, LEVEL_LABELS_FULL, LEVEL_TO_HEX
from utils.app_paths import resource_path
from utils.logging_service import clear_log

WEB_DIR = resource_path("web")
ICON_PATH = resource_path("assets", "icons", "app_icon.ico")


def _decode(data: bytes) -> str:
    value, _ = dll_decode_frame(data)
    return value if value is not None else "[middleware unavailable]"


def _channel_payload(address: int, state) -> dict:
    d = state.data
    return {
        "address": address,
        "displayNumber": address + 1,
        "outputOn": d.output_on,
        "mode": d.mode,
        "powerCode": d.power_code,
        "lastLevel": d.last_level,
        "level": 0 if not d.output_on else HEX_TO_LEVEL.get(d.power_code, d.last_level),
    }


class Api:
    """Exposed to the page as `pywebview.api.*` - every method here is
    called from JS. State changes flow back the other way (Python -> JS)
    separately, via _push() below, since nothing here returns live state -
    the original Qt version was signal-driven for exactly the same reason
    (a command's real effect only lands once the device answers or the
    request times out, not synchronously with the click that sent it)."""

    def __init__(self, app_controller: AppController):
        self.app = app_controller
        self.window = None  # set once create_window() returns

    def get_init_data(self):
        channels = self.app.channels
        return {
            "maxChannels": MAX_CHANNELS,
            "modes": [{"code": code, "name": name} for code, name in c.MODE_NAMES.items()],
            "levelLabels": [LEVEL_LABELS[i] for i in range(4)],
            "levelLabelsFull": [LEVEL_LABELS_FULL[i] for i in range(4)],
            "channels": [_channel_payload(a, channels.get_state(a)) for a in range(MAX_CHANNELS)],
        }

    def turn_on(self, address: int):
        self.app.channels.get_controller(address).turn_output_on()

    def turn_off(self, address: int):
        self.app.channels.get_controller(address).turn_output_off()

    def set_level(self, address: int, level: int):
        controller = self.app.channels.get_controller(address)
        code = LEVEL_TO_HEX[level]
        if code is None:
            controller.turn_output_off()
        elif self.app.channels.get_state(address).data.output_on:
            controller.set_power(code)
        else:
            controller.resume_output(code)

    def set_mode(self, address: int, mode: int):
        self.app.channels.get_controller(address).set_mode(mode)

    def query(self, address: int, on: bool):
        self.app.channels.brute_force_query(address, on)

    def clear_log(self):
        clear_log(self.app.logger)

    def close_app(self):
        self.window.destroy()

    def minimize(self):
        self.window.minimize()

    def toggle_maximize(self):
        if self.window.maximized:
            self.window.restore()
        else:
            self.window.maximize()

    def get_window_position(self):
        return [self.window.x, self.window.y]

    def move_window(self, x: int, y: int):
        # Backs the titlebar's own drag-to-move (JS mousemove -> here) -
        # easy_drag=False because pywebview's built-in drag starts on any
        # mouse-down anywhere in the page with no exclusion for buttons/
        # sliders, which this UI is full of.
        if not self.window.maximized:
            self.window.move(x, y)


def _push(window, fn_name: str, *args):
    # window.evaluate_js takes raw JS source, not (name, args) - build a
    # call expression by hand. Guard with `window.fn &&` since this can
    # fire before the page's own <script> has finished registering its
    # handlers (channel state loads and starts emitting almost
    # immediately on construction).
    payload = json.dumps(list(args))
    window.evaluate_js(f"window.{fn_name} && window.{fn_name}(...{payload})")


def run():
    app_controller = AppController()
    api = Api(app_controller)

    window = webview.create_window(
        "TX Controller",
        url=os.path.join(WEB_DIR, "index.html"),
        js_api=api,
        width=1040,
        height=780,
        min_size=(1000, 700),
        frameless=True,
        easy_drag=False,
        transparent=True,
    )
    api.window = window

    channels = app_controller.channels
    channels.command_timeout.connect(lambda msg: _push(window, "onCommandTimeout", msg))
    channels.raw_tx.connect(lambda addr, data: _push(window, "onRawTx", addr, _decode(data)))
    channels.raw_rx.connect(lambda addr, data: _push(window, "onRawRx", addr, _decode(data)))
    for address in range(MAX_CHANNELS):
        state = channels.get_state(address)
        controller = channels.get_controller(address)
        state.changed.connect(lambda a=address, s=state: _push(window, "onChannelChanged", _channel_payload(a, s)))
        controller.busy_changed.connect(lambda busy, a=address: _push(window, "onBusyChanged", a, busy))

    window.events.closed += app_controller.shutdown

    webview.start(icon=ICON_PATH if os.path.exists(ICON_PATH) else None)
