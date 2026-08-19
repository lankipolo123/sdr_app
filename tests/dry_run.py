import configparser
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer

FAILURES = []
UNCAUGHT = []


def check(label: str, condition: bool):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        FAILURES.append(label)


def pump(ms: int):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    def excepthook(exc_type, exc_value, exc_tb):
        import traceback
        UNCAUGHT.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.excepthook = excepthook

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    from styles.theme_colors import light_palette, build_global_qss
    app.setPalette(light_palette())
    app.setStyleSheet(build_global_qss())

    from tests.fake_hardware import FakeSDR, install_fake_dll

    from utils.config_service import ConfigService
    from utils.logging_service import setup_logger
    from hooks.use_channels import ChannelManager, MAX_CHANNELS, QUERY_TIMEOUT_MS, QUERY_MAX_ATTEMPTS
    from hooks.use_channel import RESPONSE_TIMEOUT_MS, RETRY_MAX_ATTEMPTS
    from hooks.use_app import AppController
    from pages.main_page import MainWindow
    from components.confirm_dialog import ConfirmDialog
    from components.channel_card import SLIDER_SEND_DEBOUNCE_MS
    from services.protocol import commands, constants as c
    from services.protocol.packet_parser import ParsedFrame
    from state.level_map import LEVEL_LABELS, LEVEL_TO_HEX

    WORST_CASE_MS = RESPONSE_TIMEOUT_MS * RETRY_MAX_ATTEMPTS + 1500
    QUERY_WORST_CASE_MS = QUERY_TIMEOUT_MS * QUERY_MAX_ATTEMPTS + 1000
    SLIDER_SETTLE_MS = SLIDER_SEND_DEBOUNCE_MS + 100

    ConfirmDialog.ask = staticmethod(lambda *a, **k: True)

    def make_app_controller(work_dir: str | None = None):
        work_dir = work_dir or tempfile.mkdtemp(prefix="sdr_dry_run_")
        controller = AppController.__new__(AppController)
        controller.config = ConfigService(path=os.path.join(work_dir, "config.json"))
        controller.logger = setup_logger(os.path.join(work_dir, "logs"))
        controller.channels = ChannelManager(controller.config, controller.logger)
        return controller

    print("=== Run 1: every channel already live at launch, no discovery step ===")
    sdr = FakeSDR(present=True)
    install_fake_dll(sdr)

    restart_work_dir = tempfile.mkdtemp(prefix="sdr_dry_run_restart_")
    controller = make_app_controller(restart_work_dir)
    window = MainWindow(controller)
    window.show()

    messages = []
    controller.channels.command_timeout.connect(lambda msg: messages.append(msg))

    check(
        "all 16 controllers live immediately",
        all(controller.channels.controllers.get(a) is not None for a in range(MAX_CHANNELS)),
    )
    check("all 16 channel cards built", len(window._cards) == MAX_CHANNELS)

    card = window._cards[0]
    check("card's display number is address+1 (CH01 for address 0)", card.state.display_number == 1)
    check("initial state: toggle unchecked", not card.toggle.isChecked())
    check("initial state: slider at 0 (Off)", card.slider.value() == 0)
    check("no baseline yet - nothing has ever queried status", controller.channels.states[0].data.mode is None)
    check("toggle is clickable immediately - no arming step needed", card.toggle.isEnabled())
    check("slider starts locked - only unlocks once output is on", not card.slider.isEnabled())

    print("\n=== ON button (single Output ON command) - no confirmed response path, applies optimistically ===")
    card.toggle.click()
    pump(WORST_CASE_MS)
    check("toggle stayed checked (applied optimistically after the retry cycle exhausted)", card.toggle.isChecked())
    check("slider unlocked now that output is on", card.slider.isEnabled())
    check("slider visually resumed to default level 1 (Min) - UI-only sync, no command sent for it", card.slider.value() == 1)
    check("the correct Output ON frame was actually sent", sdr.sent_frames and sdr.sent_frames[-1] == commands.output_on(1))
    check("ON alone doesn't guess Mode/Frequency/Bandwidth - nothing to guess for a bare Output ON", not any("GUESSED" in m for m in messages))
    check("command_timeout fired - nothing can confirm this command yet (see module docstring)", any("UNCONFIRMED" in m for m in messages))
    check(
        "the TX log actually populated - raw_tx used to be a dead signal, never emitted",
        window.logs_panel.list.count() >= 1,
    )
    check(
        "the log's most recent line is CH01's TX, not stale/wrong-channel data",
        "CH01" in window.logs_panel.list.item(window.logs_panel.list.count() - 1).text(),
    )
    messages.clear()

    print("\n=== Drag slider to Max (the actual first Signal Control - now with guessed defaults) ===")
    card.slider.setValue(3)
    pump(SLIDER_SETTLE_MS + WORST_CASE_MS)
    expected_max_frame = commands.set_signal(
        1, c.BLIND_DEFAULT_MODE, c.BLIND_DEFAULT_FREQ_MHZ, c.BLIND_DEFAULT_BANDWIDTH_MHZ, LEVEL_TO_HEX[3],
    )
    check("toggle still checked (L3 is not off)", card.toggle.isChecked())
    check("the correct Signal Control frame (guessed defaults, L3 power) was sent", sdr.sent_frames and sdr.sent_frames[-1] == expected_max_frame)
    check("guessed-defaults send logged a warning (no more UI banner for it)", any("GUESSED" in m for m in messages))
    messages.clear()

    print("\n=== Drag slider to Off (slider -> toggle reactive sync) ===")
    card.slider.setValue(0)
    pump(SLIDER_SETTLE_MS + WORST_CASE_MS)
    check("toggle reactively switched off", not card.toggle.isChecked())
    check("slider re-locks now that output is off again", not card.slider.isEnabled())
    check("the correct Output OFF frame was sent", sdr.sent_frames and sdr.sent_frames[-1] == commands.output_off(1))

    print("\n=== OFF button turned it off - power_code stays whatever the slider last set it to ===")
    card.toggle.click()
    pump(WORST_CASE_MS)
    check("hardware back on (optimistic apply)", card.toggle.isChecked())
    check("slider visually resumed to last non-off level (3, Max) - UI-only", card.slider.value() == 3)
    check("the correct Output ON frame was sent (power_code untouched by ON alone)", sdr.sent_frames and sdr.sent_frames[-1] == commands.output_on(1))

    last_level_before_shutdown = controller.channels.states[0].data.last_level
    print(f"\n=== Shutdown (last_level={last_level_before_shutdown} should persist) ===")
    controller.shutdown()
    window.close()
    pump(50)

    saved = configparser.ConfigParser()
    saved.read(os.path.join(restart_work_dir, "channels.ini"))
    check("channels.ini has CH01's state", saved.has_section("CH01"))
    check(
        "persisted power level matches in-memory value",
        saved.get("CH01", "power", fallback=None) == LEVEL_LABELS[last_level_before_shutdown],
    )

    print("\n=== Run 2: restart, same fake DLL connection still 'plugged in' ===")
    controller2 = make_app_controller(restart_work_dir)
    window2 = MainWindow(controller2)
    window2.show()
    check(
        "restored last_level from config, not the hard-coded default",
        controller2.channels.states[0].data.last_level == last_level_before_shutdown,
    )
    check(
        "restored output_on too - card already shows on before any interaction this run",
        window2._cards[0].toggle.isChecked(),
    )
    window2._cards[0].toggle.click()
    pump(WORST_CASE_MS)
    check("second run's OFF click applies optimistically", not window2._cards[0].toggle.isChecked())
    check("the correct Output OFF frame was sent", sdr.sent_frames and sdr.sent_frames[-1] == commands.output_off(1))
    controller2.shutdown()
    window2.close()
    pump(50)

    print("\n=== Shutdown while a command is still mid-flight (must not crash) ===")
    mid_flight_sdr = FakeSDR(present=True)
    install_fake_dll(mid_flight_sdr)
    controller3 = make_app_controller()
    window3 = MainWindow(controller3)
    window3.show()
    window3._cards[0].toggle.click()
    controller3.shutdown()
    window3.close()
    pump(50)
    check("mid-command shutdown completed without raising", True)

    print("\n=== Command timeout: applies optimistically, still logged as UNCONFIRMED ===")
    timeout_sdr = FakeSDR(present=True)
    install_fake_dll(timeout_sdr)
    controller6 = make_app_controller()
    window6 = MainWindow(controller6)
    window6.show()
    messages6 = []
    controller6.channels.command_timeout.connect(lambda msg: messages6.append(msg))
    window6._cards[0].toggle.click()
    check("toggle flips immediately (optimistic UI, before any confirmation)", window6._cards[0].toggle.isChecked())
    pump(WORST_CASE_MS)
    check("command_timeout fires (no UI banner, but still logged/emitted)", bool(messages6))
    check("timeout message says UNCONFIRMED, not a false confirm", any("UNCONFIRMED" in m for m in messages6))
    check("toggle stays as clicked - applied optimistically", window6._cards[0].toggle.isChecked())
    check("the command was actually sent, even though nothing can confirm it landed", timeout_sdr.sent_frames and timeout_sdr.sent_frames[-1] == commands.output_on(1))
    controller6.shutdown()
    window6.close()
    pump(50)

    print("\n=== resume_output(): dragging the slider from Off sends Output ON, then Signal Control, in order ===")
    print("(the slider is disabled/locked while output is off, so a real user can no longer")
    print(" trigger this from the mouse - this calls setValue() directly, which still fires")
    print(" valueChanged regardless of enabled state, to confirm the underlying logic is")
    print(" still correct even though it's currently unreachable through the real UI)")
    resume_sdr = FakeSDR(present=True)
    install_fake_dll(resume_sdr)
    controller16 = make_app_controller()
    window16 = MainWindow(controller16)
    window16.show()
    check("starts off, as configured", not window16._cards[0].toggle.isChecked())

    window16._cards[0].slider.setValue(2)
    pump(SLIDER_SETTLE_MS + WORST_CASE_MS * 2 + 300)
    expected_resume_signal = commands.set_signal(
        1, c.BLIND_DEFAULT_MODE, c.BLIND_DEFAULT_FREQ_MHZ, c.BLIND_DEFAULT_BANDWIDTH_MHZ, LEVEL_TO_HEX[2],
    )
    check(
        "Output ON was sent before Signal Control, in that order",
        commands.output_on(1) in resume_sdr.sent_frames
        and expected_resume_signal in resume_sdr.sent_frames
        and resume_sdr.sent_frames.index(commands.output_on(1)) < resume_sdr.sent_frames.index(expected_resume_signal),
    )
    check("card ends up showing on (optimistic apply of both commands)", window16._cards[0].toggle.isChecked())

    controller16.shutdown()
    window16.close()
    pump(50)

    print("\n=== Port scheduler: a second channel's command waits its turn, doesn't collide ===")
    print("(channel A holds the port for one attempt at a time, not its whole retry cycle -")
    print(" channel B gets a fair turn as soon as A's current attempt times out)")
    sched_sdr = FakeSDR(present=True)
    install_fake_dll(sched_sdr)
    controller19 = make_app_controller()
    window19 = MainWindow(controller19)
    window19.show()

    window19._cards[0].toggle.click()
    pump(50)

    window19._cards[1].toggle.click()
    pump(200)
    check(
        "channel B hasn't sent anything yet - A's 1st attempt hasn't timed out yet",
        not any(f == commands.output_on(2) for f in sched_sdr.sent_frames),
    )
    check(
        "channel B's controller is queued, not holding the port itself",
        controller19.channels.controllers[1]._awaiting_port,
    )

    pump(RESPONSE_TIMEOUT_MS + 300)
    check(
        "channel B's command actually goes out as soon as A's current attempt releases the port, not after A's whole cycle",
        any(f == commands.output_on(2) for f in sched_sdr.sent_frames),
    )

    pump(WORST_CASE_MS + 500)
    check(
        "channel A's own UI still shows optimistically applied (unconfirmed) once its cycle finally exhausts",
        window19._cards[0].toggle.isChecked(),
    )

    controller19.shutdown()
    window19.close()
    pump(50)

    print("\n=== Port scheduler: Query also waits its turn behind a card's command ===")
    query_wait_sdr = FakeSDR(present=True)
    install_fake_dll(query_wait_sdr)
    controller20 = make_app_controller()
    window20 = MainWindow(controller20)
    window20.show()

    window20._cards[0].toggle.click()
    pump(50)

    query_wait_results = []
    controller20.channels.command_timeout.connect(lambda msg: query_wait_results.append(msg))
    controller20.channels.brute_force_query(2, on=True)
    pump(200)
    check(
        "Query hasn't sent anything yet - channel A's 1st attempt hasn't timed out yet",
        not any(f == commands.output_on(2) for f in query_wait_sdr.sent_frames),
    )
    check("Query produced no result yet (still queued)", not query_wait_results)

    pump(RESPONSE_TIMEOUT_MS + 300)
    check(
        "Query's command actually goes out as soon as channel A's current attempt releases the port, not after A's whole cycle",
        any(f == commands.output_on(2) for f in query_wait_sdr.sent_frames),
    )

    pump(QUERY_WORST_CASE_MS)
    check(
        "Query eventually reports no response - there is no confirmed response path yet (see module docstring)",
        any("no response" in m for m in query_wait_results),
    )

    controller20.shutdown()
    window20.close()
    pump(50)

    print("\n=== A spurious Status-Query-shaped frame must NOT stomp real state ===")
    print("(no checksum in this protocol - collision noise can occasionally parse")
    print(" as a structurally valid frame that was never actually sent. This calls")
    print(" ChannelController.handle_frame() directly - it's still real, unremoved")
    print(" code, exercised in isolation from the transport it doesn't currently")
    print(" have a way to actually receive through)")
    spurious_sdr = FakeSDR(present=True)
    install_fake_dll(spurious_sdr)
    controller8 = make_app_controller()
    window8 = MainWindow(controller8)
    window8.show()
    card8 = window8._cards[0]

    card8.toggle.click()
    pump(100)
    check("output not yet resolved (command still pending)", card8.controller._pending_label is not None)

    spurious = ParsedFrame(
        type=c.TYPE_STATUS_QUERY,
        addr=0,
        buf=bytes([0x00, 0xAA, 0x00, 0x00, 0x03, 0xAB]),
        raw=b"\x7E\x7E\xFF\x00\x06\x00\xAA\x00\x00\x03\xAB\x0A\x0D",
    )
    card8.controller.handle_frame(spurious)
    check(
        "power_code NOT overwritten by the unrequested Status Query frame's bytes",
        controller8.channels.states[0].data.power_code != 0xAB,
    )
    check(
        "mode NOT overwritten either",
        controller8.channels.states[0].data.mode != 0xAA,
    )
    check(
        "the real pending ON command is still tracked (wasn't wiped out by the spurious frame)",
        card8.controller._pending_label is not None,
    )

    pump(WORST_CASE_MS)
    check(
        "the real command still resolves normally afterward (optimistic apply, undisturbed)",
        card8.toggle.isChecked(),
    )

    controller8.shutdown()
    window8.close()
    pump(50)

    print("\n=== Standalone Query (separate from the cards) ===")
    print("(type an address directly, brute-force find the connection, send - there is")
    print(" no confirmed response path yet, so this always ends up reporting no response,")
    print(" same as every other command right now; what's still verified is that the")
    print(" right frame actually goes out and cards/controllers are left untouched)")
    query_sdr = FakeSDR(present=True)
    install_fake_dll(query_sdr)
    controller17 = make_app_controller()
    window17 = MainWindow(controller17)
    window17.show()

    controller_before = controller17.channels.controllers.get(9)
    query_results = []
    controller17.channels.command_timeout.connect(lambda msg: query_results.append(msg))
    controller17.channels.brute_force_query(9, on=True)
    pump(QUERY_WORST_CASE_MS)
    check("the correct Output ON frame was sent for the queried address", commands.output_on(9) in query_sdr.sent_frames)
    check("query eventually reports no response - no confirmed response path yet", any("no response" in m for m in query_results))
    check(
        "Query's own traffic shows in the log too, not just cards'",
        window17.logs_panel.list.count() >= 1,
    )
    check(
        "card 9's toggle stayed put - a standalone query doesn't touch it",
        not window17._cards[9].toggle.isChecked(),
    )
    check(
        "a standalone query doesn't replace any card's controller",
        controller17.channels.controllers.get(9) is controller_before,
    )

    controller17.shutdown()
    window17.close()
    pump(50)

    print("\n=== Modulation dropdown sends Signal Control and persists across restart ===")
    mode_sdr = FakeSDR(present=True)
    install_fake_dll(mode_sdr)

    mode_work_dir = tempfile.mkdtemp(prefix="sdr_dry_run_mode_")
    controller_mode = make_app_controller(mode_work_dir)
    window_mode = MainWindow(controller_mode)
    window_mode.show()
    check("mode dropdown starts on Pseudo Random Noise (the default)", window_mode._cards[0].mode_combo.currentIndex() == 0)

    window_mode._cards[0].mode_combo.setCurrentIndex(1)
    pump(300)
    check("picking a mode alone does NOT send - Set is required", not mode_sdr.sent_frames)
    window_mode._cards[0].mode_set_btn.click()
    pump(WORST_CASE_MS)
    expected_mode_frame = commands.set_signal(
        1, c.MODE_LINEAR_SWEEP, c.BLIND_DEFAULT_FREQ_MHZ, c.BLIND_DEFAULT_BANDWIDTH_MHZ, LEVEL_TO_HEX[1],
    )
    check("Set actually sent the Linear Sweep Signal Control frame", mode_sdr.sent_frames and mode_sdr.sent_frames[-1] == expected_mode_frame)
    check("card's dropdown still shows Linear Sweep selected", window_mode._cards[0].mode_combo.currentIndex() == 1)

    window_mode._cards[0].mode_combo.showPopup()
    pump(50)
    popup = QApplication.activePopupWidget()
    check("mode dropdown's popup actually opened", popup is not None)
    if popup is not None:
        popup.close()

    controller_mode.shutdown()
    window_mode.close()
    pump(50)

    mode_saved = configparser.ConfigParser()
    mode_saved.read(os.path.join(mode_work_dir, "channels.ini"))
    check(
        "mode persisted to channels.ini as a human-readable name",
        mode_saved.get("CH01", "mode", fallback=None) == "Linear Sweep",
    )

    print("\n=== Modulation mode restored on relaunch, still no auto-send ===")
    controller_mode2 = make_app_controller(mode_work_dir)
    mode_messages2 = []
    controller_mode2.channels.command_timeout.connect(lambda msg: mode_messages2.append(msg))
    window_mode2 = MainWindow(controller_mode2)
    window_mode2.show()
    pump(100)
    check(
        "dropdown shows the restored mode immediately, before any interaction",
        window_mode2._cards[0].mode_combo.currentIndex() == 1,
    )
    check(
        "nothing sent automatically just from restoring - matches the app's no-auto-anything-on-launch design",
        not mode_messages2,
    )
    controller_mode2.shutdown()
    window_mode2.close()
    pump(50)

    print("\n=== Uncaught exceptions during the run ===")
    check("no uncaught exceptions in any Qt slot", len(UNCAUGHT) == 0)
    for tb in UNCAUGHT:
        print(tb)

    print(f"\n{'=' * 60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
