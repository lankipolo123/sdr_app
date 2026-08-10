"""Full-stack dry run against fake hardware - no real serial port needed.

Exercises the same code path a real run does end to end: AppController,
MainWindow, ChannelManager, ChannelController, ChannelCard, config
persistence, and shutdown safety - all against a FakeModulePort standing
in for a real module, so regressions anywhere in the "command sent ->
state synced -> UI updates" pipeline get caught without needing hardware
on hand.

There is no discovery/Scan/+Addr step anymore - every one of the 16
channel slots gets a real, live ChannelController from the moment the
app starts, and every command it sends is inherently "blind": it
brute-force finds an available port fresh, retries on no response, and
optimistically applies the change on the UI even if nothing ever
acknowledges it (confirmed on real hardware: an unacknowledged command
often still reaches the module).

Run: python tests/dry_run.py
Exits non-zero (and prints a summary of FAILs) if anything's wrong.
"""
import configparser
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

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
    # Qt swallows exceptions raised inside signal handlers by default -
    # without this, a real bug in a slot would print a traceback but
    # otherwise pass silently and this dry run would report false PASSes.
    def excepthook(exc_type, exc_value, exc_tb):
        import traceback
        UNCAUGHT.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.excepthook = excepthook

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    from styles.theme_colors import light_palette, build_global_qss
    app.setPalette(light_palette())
    app.setStyleSheet(build_global_qss())

    from tests.fake_hardware import (
        FakeModulePort, FakePortRegistry, FakeSharedBusPort, FakeAddressedBusPort,
        install_fake_hardware,
    )

    from utils.config_service import ConfigService
    from utils.logging_service import setup_logger
    from hooks.use_channels import ChannelManager, MAX_CHANNELS, QUERY_TIMEOUT_MS, QUERY_MAX_ATTEMPTS
    from hooks.use_channel import RESPONSE_TIMEOUT_MS, RETRY_MAX_ATTEMPTS
    from hooks.use_app import AppController
    from pages.main_page import MainWindow
    from components.confirm_dialog import ConfirmDialog
    from components.channel_card import SLIDER_SEND_DEBOUNCE_MS
    from services.protocol import constants as c
    from services.protocol.packet_parser import ParsedFrame
    from state.level_map import LEVEL_LABELS

    WORST_CASE_MS = RESPONSE_TIMEOUT_MS * RETRY_MAX_ATTEMPTS + 1500  # full retry exhaustion + headroom
    QUERY_WORST_CASE_MS = QUERY_TIMEOUT_MS * QUERY_MAX_ATTEMPTS + 1000
    # Slider sends are now debounced (see channel_card.py) - any test that
    # drags the slider and expects the resulting command to have already
    # gone out needs to wait out the debounce window first.
    SLIDER_SETTLE_MS = SLIDER_SEND_DEBOUNCE_MS + 100

    # Route confirm dialogs straight to "confirmed" - a real modal exec()
    # loop would just hang forever with nothing to click it.
    ConfirmDialog.ask = staticmethod(lambda *a, **k: True)

    def make_app_controller(work_dir: str | None = None):
        # Each call gets its OWN fresh, isolated temp dir by default - two
        # unrelated test sections must never share a config.json/
        # channels.ini, or one section's leftover channel state (now
        # including mode/output, not just last_level) would silently
        # bleed into the next section's "fresh" controller. Only the
        # explicit restart test below passes the SAME work_dir on purpose,
        # to prove state actually survives a real restart.
        work_dir = work_dir or tempfile.mkdtemp(prefix="sdr_dry_run_")
        controller = AppController.__new__(AppController)
        controller.config = ConfigService(path=os.path.join(work_dir, "config.json"))
        controller.logger = setup_logger(os.path.join(work_dir, "logs"))
        controller.channels = ChannelManager(controller.config, controller.logger)
        return controller

    print("=== Run 1: every channel already live at launch, no discovery step ===")
    module = FakeModulePort(address=1)  # wire address (1-16, matches CH01) - not the internal 0-based address card index 0 uses
    registry = FakePortRegistry()
    registry.add("FAKE0", module)
    install_fake_hardware(registry)

    restart_work_dir = tempfile.mkdtemp(prefix="sdr_dry_run_restart_")
    controller = make_app_controller(restart_work_dir)
    window = MainWindow(controller)
    window.show()

    # There's no warning banner in the UI anymore (removed - it gave
    # misleading "no response"/rejection reports even on commands that
    # had actually reached the hardware, on a line where confirmation
    # itself is unreliable). command_timeout still fires and still gets
    # logged - just captured directly here instead of read off a label.
    messages = []
    controller.channels.command_timeout.connect(lambda msg: messages.append(msg))

    check(
        "all 16 controllers live immediately",
        all(controller.channels.controllers.get(a) is not None for a in range(MAX_CHANNELS)),
    )
    check("all 16 channel cards built", len(window._cards) == MAX_CHANNELS)

    card = window._cards[0]
    check("card's display number is address+1 (CH01 for address 0)", card.state.display_number == 1)
    check("initial state: output off (matches fake module default)", not module.output_on)
    check("initial state: toggle unchecked", not card.toggle.isChecked())
    check("initial state: slider at 0 (Off)", card.slider.value() == 0)
    check("no baseline yet - nothing has ever queried status", controller.channels.states[0].data.mode is None)
    check("card starts locked - toggle disabled until tapped", not card.toggle.isEnabled())
    check("card starts locked - slider disabled until tapped", not card.slider.isEnabled())

    print("\n=== Tap-to-arm: locked controls can't send until the card itself is clicked ===")
    card.toggle.click()  # disabled - click() is a no-op on a disabled QPushButton
    pump(100)
    check("a click on a still-locked toggle does nothing", not module.output_on)
    card.arm()
    check("arming enables the toggle", card.toggle.isEnabled())
    check("arming enables the slider", card.slider.isEnabled())

    print("\n=== Arming is exclusive - a second card locks the first back down ===")
    other_card = window._cards[1]
    other_card.arm()
    check("arming CH02 locks CH01 back down", not card.toggle.isEnabled())
    check("CH01's slider is locked too", not card.slider.isEnabled())
    check("CH02 itself is armed", other_card.toggle.isEnabled())
    card.arm()  # switch attention back to CH01 for the rest of this run
    check("re-arming CH01 locks CH02 back down", not other_card.toggle.isEnabled())

    print("\n=== Clicking outside every card locks the armed one back down too ===")
    QTest.mouseClick(window.status_label, Qt.LeftButton)  # a neutral widget, not part of any card
    check("clicking outside CH01 locks it back down", not card.toggle.isEnabled())
    check("no card is armed anymore", window._armed_card is None)
    card.arm()  # re-arm CH01 for the rest of this run

    print("\n=== ON button (single Output ON command - no Signal Control riding along) ===")
    card.toggle.click()
    pump(300)
    check("hardware output turned on", module.output_on)
    check("toggle stayed checked", card.toggle.isChecked())
    check("slider visually resumed to default level 1 (Min) - UI-only sync, no command sent for it", card.slider.value() == 1)
    check("ON alone never touches power_code - still the fake module's untouched default", module.power_code == 0x00)
    check("ON alone doesn't guess Mode/Frequency/Bandwidth - nothing to guess for a bare Output ON", not messages)
    check(
        "the TX/RX log actually populated - raw_tx/raw_rx used to be dead signals, never emitted",
        window.log_list.count() >= 2,  # at least one TX line and one RX line for this command
    )
    check("the log's most recent line is CH01's confirmed ack, not stale/wrong-channel data", "CH01" in window.log_list.item(window.log_list.count() - 1).text())

    print("\n=== Drag slider to Max (the actual first Signal Control - now with guessed defaults) ===")
    card.slider.setValue(3)
    pump(SLIDER_SETTLE_MS + 300)
    check("hardware power_code matches L3 (0x00 / max)", module.power_code == 0x00)
    check("toggle still checked (L3 is not off)", card.toggle.isChecked())
    check("guessed mode used (no real baseline exists)", module.mode == c.BLIND_DEFAULT_MODE)
    check("guessed frequency used", module.freq_mhz == c.BLIND_DEFAULT_FREQ_MHZ)
    check("guessed bandwidth used", module.bandwidth_mhz == c.BLIND_DEFAULT_BANDWIDTH_MHZ)
    check("guessed-defaults send logged a warning (no more UI banner for it)", any("GUESSED" in m for m in messages))
    messages.clear()

    print("\n=== Drag slider to Off (slider -> toggle reactive sync) ===")
    card.slider.setValue(0)
    pump(SLIDER_SETTLE_MS + 300)
    check("hardware output turned off", not module.output_on)
    check("toggle reactively switched off", not card.toggle.isChecked())

    print("\n=== OFF button turned it off - power_code stays whatever the slider last set it to ===")
    card.toggle.click()  # off -> on again: still just a single Output ON command
    pump(300)
    check("hardware output back on", module.output_on)
    check("slider visually resumed to last non-off level (3, Max) - UI-only", card.slider.value() == 3)
    check("power_code untouched by ON alone - unchanged from the slider's last real send", module.power_code == 0x00)

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

    print("\n=== Run 2: restart against the same (still 'plugged in') hardware ===")
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
    window2._cards[0].arm()
    window2._cards[0].toggle.click()  # was restored to on, so this click turns it off this time
    pump(300)
    check("second run's OFF click still reaches the same physical hardware", not module.output_on)
    check(
        "power_code carries over from the module's last real Signal Control - OFF alone doesn't touch it",
        module.power_code == 0x00,
    )
    controller2.shutdown()
    window2.close()
    pump(50)

    print("\n=== Shutdown while a command is still mid-flight (must not crash) ===")
    silent_module = FakeModulePort(address=1, silent=True)  # wire address (matches CH01, card index 0)
    registry_silent = FakePortRegistry()
    registry_silent.add("FAKE_SILENT", silent_module)
    install_fake_hardware(registry_silent)
    controller3 = make_app_controller()
    window3 = MainWindow(controller3)
    window3.show()
    window3._cards[0].arm()
    window3._cards[0].toggle.click()  # sends a command that will never be ack'd
    # Deliberately no pump() here - shut down while the retry/response
    # timer is still running.
    controller3.shutdown()
    window3.close()
    pump(50)
    check("mid-command shutdown completed without raising", True)

    print("\n=== Command timeout (module goes silent), applies optimistically, still logged ===")
    silent_later_module = FakeModulePort(address=1)  # wire address (matches CH01, card index 0)
    registry_timeout = FakePortRegistry()
    registry_timeout.add("FAKE_TIMEOUT", silent_later_module)
    install_fake_hardware(registry_timeout)
    controller6 = make_app_controller()
    window6 = MainWindow(controller6)
    window6.show()
    messages6 = []
    controller6.channels.command_timeout.connect(lambda msg: messages6.append(msg))
    silent_later_module.silent = True  # module "unplugged" - stops answering
    window6._cards[0].arm()
    window6._cards[0].toggle.click()  # sends a command that will never be ack'd
    check("toggle flips immediately (optimistic UI, before any ack)", window6._cards[0].toggle.isChecked())
    pump(WORST_CASE_MS)
    check("command_timeout still fires (no UI banner, but still logged/emitted)", bool(messages6))
    check("timeout message is non-empty", bool(messages6[0]) if messages6 else False)
    check(
        "toggle stays as clicked - applied optimistically since the module often "
        "receives the command even without a readable ack back",
        window6._cards[0].toggle.isChecked(),
    )
    check(
        "but the fake module itself never actually got it this time (genuinely silent)",
        not silent_later_module.output_on,
    )
    controller6.shutdown()
    window6.close()
    pump(50)

    print("\n=== Explicit rejection (RESP_FAILED) reverts the UI ===")
    print("(different from a timeout - the device DID respond, just said no)")
    # There's no discovery to seed the card's starting state from real
    # hardware anymore, so every card always starts unchecked (off).
    # Turn it on first (a normal single-command ON, succeeds), THEN
    # start rejecting - clicking OFF from there is also a single command
    # (turn_output_off), isolating the single-command rejection path
    # cleanly.
    reject_module = FakeModulePort(address=1)  # wire address (matches CH01, card index 0)
    registry_reject = FakePortRegistry()
    registry_reject.add("FAKE_REJECT", reject_module)
    install_fake_hardware(registry_reject)
    controller15 = make_app_controller()
    window15 = MainWindow(controller15)
    window15.show()
    messages15 = []
    controller15.channels.command_timeout.connect(lambda msg: messages15.append(msg))
    window15._cards[0].arm()
    window15._cards[0].toggle.click()  # off -> on: single Output ON command, succeeds normally
    pump(300)
    check("turned on normally first", window15._cards[0].toggle.isChecked())
    check("hardware really turned on", reject_module.output_on)

    reject_module.reject_next = True
    window15._cards[0].toggle.click()  # on -> off: single command (turn_output_off)
    check("toggle flips immediately (optimistic UI)", not window15._cards[0].toggle.isChecked())
    pump(200)  # fake hardware replies near-instantly, no need to wait for the full timeout
    check("toggle reverts back on after an explicit device rejection", window15._cards[0].toggle.isChecked())
    check("hardware itself never actually turned off", reject_module.output_on)
    check("rejection still fires command_timeout (no UI banner, but still logged/emitted)", bool(messages15))

    controller15.shutdown()
    window15.close()
    pump(50)

    print("\n=== resume_output(): if Output ON is rejected, Signal Control")
    print("    succeeding right after must NOT flip output_on back to True ===")
    print("(the ON button itself only ever sends a single Output ON command now -")
    print(" resume_output()'s two-command sequence is only reachable through the")
    print(" slider, when it's dragged to a level while output is currently off)")
    resume_module = FakeModulePort(address=1, output_on=False)  # wire address (matches CH01, card index 0)
    registry_resume = FakePortRegistry()
    registry_resume.add("FAKE_RESUME", resume_module)
    install_fake_hardware(registry_resume)
    controller16 = make_app_controller()
    window16 = MainWindow(controller16)
    window16.show()
    check("starts off, as configured", not window16._cards[0].toggle.isChecked())

    # Only the Output Switch half is rejected - Signal Control (the
    # second command in the resume_output() sequence) goes through
    # normally right after, since reject_next resets itself.
    resume_module.reject_next = True
    window16._cards[0].arm()
    window16._cards[0].slider.setValue(2)  # off -> level 2: resume_output(), 2 commands
    pump(SLIDER_SETTLE_MS + 400)  # both commands round-trip well under this on fake hardware
    check(
        "output stays off - the Signal Control success must not override the Output ON rejection",
        not resume_module.output_on,
    )
    check("card reflects that too, not stuck showing on", not window16._cards[0].toggle.isChecked())

    controller16.shutdown()
    window16.close()
    pump(50)

    print("\n=== Port scheduler: a second channel's command waits its turn, doesn't collide ===")
    print("(channel A now holds the port for one attempt at a time, not its whole")
    print(" retry cycle - channel B gets a fair turn as soon as A's current attempt")
    print(" times out, instead of waiting out A's entire ~5-6s worst case)")
    # One shared port (the real-world case), not two separate ones -
    # _find_and_open_connection() just grabs whichever port opens first
    # without verifying a response actually comes from it, so two
    # separate fake ports would let channel B accidentally latch onto
    # channel A's (wrong) port on its first attempt - a red herring
    # unrelated to the scheduler itself. Wire address 1 (channel A, card
    # index 0) has no module in the bus at all, so it's genuinely never
    # answered - FakeAddressedBusPort.write() finds no target and just
    # drops it, same net effect as "silent" without also bypassing the
    # module's own silent-flag check the way routing straight to
    # _handle() would.
    sched_module_b = FakeModulePort(address=2)  # wire address (matches CH02, card index 1) - answers normally once it gets a turn
    sched_bus = FakeAddressedBusPort([sched_module_b])
    registry_sched = FakePortRegistry()
    registry_sched.add("FAKE_SCHED", sched_bus)
    install_fake_hardware(registry_sched)
    controller19 = make_app_controller()
    window19 = MainWindow(controller19)
    window19.show()

    window19._cards[0].arm()
    window19._cards[0].toggle.click()  # channel A starts its retry cycle (silent module) - holds the port for its 1st attempt
    pump(50)

    window19._cards[1].arm()
    window19._cards[1].toggle.click()  # channel B's command queues behind A's in-flight attempt
    pump(200)
    check(
        "channel B hasn't touched its module yet - A's 1st attempt hasn't timed out yet",
        not sched_module_b.output_on,
    )
    check(
        "channel B's controller is queued, not holding the port itself",
        controller19.channels.controllers[1]._awaiting_port,
    )

    pump(RESPONSE_TIMEOUT_MS + 300)  # A's 1st attempt times out and releases the port - B shouldn't have to wait any longer than that
    check(
        "channel B's command runs and succeeds as soon as A's current attempt releases the port, not after A's whole cycle",
        sched_module_b.output_on,
    )

    pump(WORST_CASE_MS + 500)  # A yielded one attempt to B, so give it that much extra room to finish its own cycle
    check(
        "channel A's own UI still shows optimistically applied (unconfirmed) once its cycle finally exhausts",
        window19._cards[0].toggle.isChecked(),
    )

    controller19.shutdown()
    window19.close()
    pump(50)

    print("\n=== Port scheduler: Query also waits its turn behind a card's command ===")
    print("(Query releases the port between its own attempts too - it only waits")
    print(" out channel A's current attempt, not A's whole retry cycle)")
    query_wait_module_b = FakeModulePort(address=2)  # wire address (matches CH02, card index 1)
    query_wait_bus = FakeAddressedBusPort([query_wait_module_b])  # wire address 1 (channel A, card index 0) has no module - never answered
    registry_query_wait = FakePortRegistry()
    registry_query_wait.add("FAKE_QUERY_WAIT", query_wait_bus)
    install_fake_hardware(registry_query_wait)
    controller20 = make_app_controller()
    window20 = MainWindow(controller20)
    window20.show()

    window20._cards[0].arm()
    window20._cards[0].toggle.click()  # channel A starts its retry cycle (nothing answers) - holds the port for its 1st attempt
    pump(50)

    query_wait_results = []
    controller20.channels.command_timeout.connect(lambda msg: query_wait_results.append(msg))
    controller20.channels.brute_force_query(2, on=True)  # wire address 2 (matches CH02/module_b) - queues behind channel A's in-flight attempt
    pump(200)
    check("Query hasn't touched its module yet - channel A's 1st attempt hasn't timed out yet", not query_wait_module_b.output_on)
    check("Query produced no result yet (still queued)", not query_wait_results)

    pump(RESPONSE_TIMEOUT_MS + 300)  # channel A's 1st attempt times out and releases the port - Query shouldn't have to wait any longer than that
    check("Query runs and confirms as soon as channel A's current attempt releases the port, not after A's whole cycle", query_wait_module_b.output_on)
    check("Query reported a real confirmed result", any("confirmed" in m for m in query_wait_results))

    controller20.shutdown()
    window20.close()
    pump(50)

    print("\n=== One shared port, two colliding modules (the actual confirmed wiring) ===")
    print("(single USB-RS422 adapter driving two modules at once - every write")
    print(" is heard by both, but what comes back is never a clean, parseable")
    print(" response, only collision noise - same as real hardware testing)")
    bus_module_a = FakeModulePort(address=0)
    bus_module_b = FakeModulePort(address=1)
    shared_bus = FakeSharedBusPort([bus_module_a, bus_module_b])
    registry_bus = FakePortRegistry()
    registry_bus.add("FAKE_SHARED_BUS", shared_bus)
    install_fake_hardware(registry_bus)
    controller7 = make_app_controller()
    window7 = MainWindow(controller7)
    window7.show()
    messages7 = []
    controller7.channels.command_timeout.connect(lambda msg: messages7.append(msg))
    window7._cards[0].arm()
    window7._cards[0].toggle.click()  # blind send straight into collision noise
    check("optimistic UI applies immediately, before any response", window7._cards[0].toggle.isChecked())
    pump(WORST_CASE_MS)
    check(
        "still applied after every retry exhausts with no valid response "
        "(optimistic apply-on-timeout - real hardware showed unconfirmed commands often land anyway)",
        window7._cards[0].toggle.isChecked(),
    )
    check("collision still fires command_timeout (no UI banner, but still logged/emitted)", bool(messages7))
    check("no crash/hang against a colliding shared bus", True)
    controller7.shutdown()
    window7.close()
    pump(50)

    print("\n=== A spurious Status-Query-shaped frame must NOT stomp real state ===")
    print("(no checksum in this protocol - collision noise can occasionally parse")
    print(" as a structurally valid frame that was never actually sent. Nothing in")
    print(" the app calls read_status() automatically, so a Status Query response")
    print(" arriving while only a plain Output ON/OFF ack is pending is always")
    print(" either noise or a genuine bug - either way it must be ignored, not")
    print(" trusted at face value)")
    silent_spurious_module = FakeModulePort(address=0, silent=True)
    registry_spurious = FakePortRegistry()
    registry_spurious.add("FAKE_SPURIOUS", silent_spurious_module)
    install_fake_hardware(registry_spurious)
    controller8 = make_app_controller()
    window8 = MainWindow(controller8)
    window8.show()
    card8 = window8._cards[0]
    card8.arm()

    card8.toggle.click()  # ON - module is silent, so this stays genuinely pending
    pump(100)
    check("output not yet confirmed (module hasn't answered)", card8.controller._pending_label is not None)

    spurious = ParsedFrame(
        type=c.TYPE_STATUS_QUERY,
        addr=0,
        buf=bytes([0x00, 0xAA, 0x00, 0x00, 0x03, 0xAB]),  # claims output OFF, power 0xAB - nobody sent this
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

    pump(WORST_CASE_MS)  # let the real (silent) command exhaust retries normally
    check(
        "the real command still resolves normally afterward (optimistic apply, undisturbed)",
        card8.toggle.isChecked(),
    )

    controller8.shutdown()
    window8.close()
    pump(50)

    print("\n=== Standalone Query (retry-verified, separate from the cards) ===")
    print("(type an address directly, brute-force find the port, and actually")
    print(" wait for and verify a REAL response, unlike the cards' blind sends)")
    query_module = FakeModulePort(address=9)
    registry_query = FakePortRegistry()
    registry_query.add("FAKE_QUERY", query_module)
    install_fake_hardware(registry_query)
    controller17 = make_app_controller()
    window17 = MainWindow(controller17)
    window17.show()

    controller_before = controller17.channels.controllers.get(9)
    query_results = []
    controller17.channels.command_timeout.connect(lambda msg: query_results.append(msg))
    controller17.channels.brute_force_query(9, on=True)
    pump(300)
    check("query confirmed a real response", any("confirmed" in m for m in query_results))
    check("query actually turned the module on", query_module.output_on)
    check(
        "Query's own traffic shows in the log too, not just cards'",
        window17.log_list.count() >= 2,
    )
    check(
        "card 9's toggle stayed put - a standalone query doesn't touch it",
        not window17._cards[9].toggle.isChecked(),
    )
    check(
        "a standalone query doesn't replace any card's controller",
        controller17.channels.controllers.get(9) is controller_before,
    )

    query_results.clear()
    controller17.channels.brute_force_query(2, on=True)  # nothing at address 2
    pump(QUERY_WORST_CASE_MS)
    check(
        "querying a wrong address reports no response, not a false confirm",
        any("no response" in m for m in query_results),
    )

    controller17.shutdown()
    window17.close()
    pump(50)

    print("\n=== Two addresses sharing one physical port ===")
    print("(the real-world setup: one adapter, ask address A, then address B on")
    print(" the SAME port - both just blind-send independently, no claiming or")
    print(" disconnecting needed between them anymore)")
    share_a = FakeModulePort(address=5, freq_mhz=2400)  # wire address (matches CH05, card index 4)
    share_b = FakeModulePort(address=7, freq_mhz=5800)  # wire address (matches CH07, card index 6)
    addressed_bus = FakeAddressedBusPort([share_a, share_b])
    registry_share = FakePortRegistry()
    registry_share.add("FAKE_SHARE", addressed_bus)
    install_fake_hardware(registry_share)
    controller13 = make_app_controller()
    window13 = MainWindow(controller13)
    window13.show()

    # Arming is exclusive - only one card unlocked at a time - so each
    # address gets armed right before it's used, same as a real user
    # selecting one card, acting on it, then selecting the next.
    window13._cards[4].arm()
    window13._cards[4].toggle.click()
    pump(300)
    check("CH05 turned on", share_a.output_on)
    check("turning CH05 on doesn't leak into CH07", not share_b.output_on)

    window13._cards[6].arm()
    check("arming CH07 locked CH05 back down", not window13._cards[4].toggle.isEnabled())
    window13._cards[6].toggle.click()
    pump(300)
    check("CH07 also works on the same shared port", share_b.output_on)
    check("CH05 still on, unaffected by CH07's command", share_a.output_on)

    controller13.shutdown()
    window13.close()
    pump(50)

    print("\n=== Modulation dropdown sends Signal Control and persists across restart ===")
    mode_module = FakeModulePort(address=1)  # wire address (matches CH01, card index 0)
    registry_mode = FakePortRegistry()
    registry_mode.add("FAKE_MODE", mode_module)
    install_fake_hardware(registry_mode)

    mode_work_dir = tempfile.mkdtemp(prefix="sdr_dry_run_mode_")
    controller_mode = make_app_controller(mode_work_dir)
    window_mode = MainWindow(controller_mode)
    window_mode.show()
    check("mode dropdown starts on Pseudo Random Noise (the default)", window_mode._cards[0].mode_combo.currentIndex() == 0)

    window_mode._cards[0].arm()
    window_mode._cards[0].mode_combo.setCurrentIndex(1)  # Linear Sweep
    pump(300)
    check(
        "picking a mode alone does NOT send - Confirm is required",
        mode_module.mode != c.MODE_LINEAR_SWEEP,
    )
    window_mode._cards[0].mode_confirm_btn.click()
    pump(300)
    check("Confirm actually changed the hardware mode to Linear Sweep", mode_module.mode == c.MODE_LINEAR_SWEEP)
    check("card's dropdown still shows Linear Sweep selected", window_mode._cards[0].mode_combo.currentIndex() == 1)

    # Regression: a combo box's dropdown list is its own top-level popup,
    # not a child of the card in Qt's widget tree - isAncestorOf() used
    # to see a click on an item in that list as "outside" the card and
    # disarm it mid-selection, disabling the combo box right as the
    # click was supposed to register (reported as "hard to click on it").
    window_mode._cards[0].mode_combo.showPopup()
    pump(50)
    popup = QApplication.activePopupWidget()
    check("mode dropdown's popup actually opened", popup is not None)
    if popup is not None:
        click_on_popup = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        window_mode.eventFilter(popup, click_on_popup)
        check(
            "clicking the open dropdown's own popup does NOT disarm the card mid-selection",
            window_mode._cards[0]._armed,
        )
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
