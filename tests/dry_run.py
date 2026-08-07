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
    from services.protocol import constants as c

    WORST_CASE_MS = RESPONSE_TIMEOUT_MS * RETRY_MAX_ATTEMPTS + 1500  # full retry exhaustion + headroom
    QUERY_WORST_CASE_MS = QUERY_TIMEOUT_MS * QUERY_MAX_ATTEMPTS + 1000

    # Route confirm dialogs straight to "confirmed" - a real modal exec()
    # loop would just hang forever with nothing to click it.
    ConfirmDialog.ask = staticmethod(lambda *a, **k: True)

    work_dir = tempfile.mkdtemp(prefix="sdr_dry_run_")
    config_path = os.path.join(work_dir, "config.json")

    def make_app_controller():
        controller = AppController.__new__(AppController)
        controller.config = ConfigService(path=config_path)
        controller.logger = setup_logger(os.path.join(work_dir, "logs"))
        controller.channels = ChannelManager(controller.config, controller.logger)
        return controller

    print("=== Run 1: every channel already live at launch, no discovery step ===")
    module = FakeModulePort(address=0)
    registry = FakePortRegistry()
    registry.add("FAKE0", module)
    install_fake_hardware(registry)

    controller = make_app_controller()
    window = MainWindow(controller)
    window.show()

    check(
        "all 16 controllers live immediately",
        all(controller.channels.controllers.get(a) is not None for a in range(MAX_CHANNELS)),
    )
    check("all 16 channel cards built", len(window._cards) == MAX_CHANNELS)

    card = window._cards[0]
    check("card's display number matches its address (CH00, no +1 offset)", card.state.display_number == 0)
    check("initial state: output off (matches fake module default)", not module.output_on)
    check("initial state: toggle unchecked", not card.toggle.isChecked())
    check("initial state: slider at 0 (Off)", card.slider.value() == 0)
    check("no baseline yet - nothing has ever queried status", controller.channels.states[0].data.mode is None)

    print("\n=== Toggle on (blind send -> hardware, guessed defaults since there's no baseline) ===")
    card.toggle.click()
    pump(300)
    check("hardware output turned on", module.output_on)
    check("toggle stayed checked", card.toggle.isChecked())
    check("slider resumed to default level 1 (Min)", card.slider.value() == 1)
    check("hardware power_code matches L1 (0x02)", module.power_code == 0x02)
    check("guessed mode used (no real baseline exists)", module.mode == c.BLIND_DEFAULT_MODE)
    check("guessed frequency used", module.freq_mhz == c.BLIND_DEFAULT_FREQ_MHZ)
    check("guessed bandwidth used", module.bandwidth_mhz == c.BLIND_DEFAULT_BANDWIDTH_MHZ)
    check("guessed-defaults send surfaced a warning", window.warning_label.isVisible())

    print("\n=== Drag slider to Max (UI -> hardware) ===")
    card.slider.setValue(3)
    pump(300)
    check("hardware power_code matches L3 (0x00 / max)", module.power_code == 0x00)
    check("toggle still checked (L3 is not off)", card.toggle.isChecked())

    print("\n=== Drag slider to Off (slider -> toggle reactive sync) ===")
    card.slider.setValue(0)
    pump(300)
    check("hardware output turned off", not module.output_on)
    check("toggle reactively switched off", not card.toggle.isChecked())

    print("\n=== Toggle back on (should resume to last non-off level, L3) ===")
    card.toggle.click()
    pump(300)
    check("hardware output back on", module.output_on)
    check("slider resumed to last non-off level (3, Max)", card.slider.value() == 3)
    check("hardware power_code matches L3 again", module.power_code == 0x00)

    last_level_before_shutdown = controller.channels.states[0].data.last_level
    print(f"\n=== Shutdown (last_level={last_level_before_shutdown} should persist) ===")
    controller.shutdown()
    window.close()
    pump(50)

    with open(config_path) as f:
        import json
        saved = json.load(f)
    check("config file has channel 0's state", "0" in saved.get("channels", {}))
    check(
        "persisted last_level matches in-memory value",
        saved.get("channels", {}).get("0", {}).get("last_level") == last_level_before_shutdown,
    )

    print("\n=== Run 2: restart against the same (still 'plugged in') hardware ===")
    controller2 = make_app_controller()
    window2 = MainWindow(controller2)
    window2.show()
    check(
        "restored last_level from config, not the hard-coded default",
        controller2.channels.states[0].data.last_level == last_level_before_shutdown,
    )
    window2._cards[0].toggle.click()  # off -> on: resumes to the restored last_level (3, Max)
    pump(300)
    check("second run's blind toggle still reaches the same physical hardware", module.output_on)
    check("resumed to the level restored from config (L3 / max)", module.power_code == 0x00)
    controller2.shutdown()
    window2.close()
    pump(50)

    print("\n=== Shutdown while a command is still mid-flight (must not crash) ===")
    silent_module = FakeModulePort(address=0, silent=True)
    registry_silent = FakePortRegistry()
    registry_silent.add("FAKE_SILENT", silent_module)
    install_fake_hardware(registry_silent)
    controller3 = make_app_controller()
    window3 = MainWindow(controller3)
    window3.show()
    window3._cards[0].toggle.click()  # sends a command that will never be ack'd
    # Deliberately no pump() here - shut down while the retry/response
    # timer is still running.
    controller3.shutdown()
    window3.close()
    pump(50)
    check("mid-command shutdown completed without raising", True)

    print("\n=== Command timeout (module goes silent) surfaces in the UI, applies optimistically ===")
    silent_later_module = FakeModulePort(address=0)
    registry_timeout = FakePortRegistry()
    registry_timeout.add("FAKE_TIMEOUT", silent_later_module)
    install_fake_hardware(registry_timeout)
    controller6 = make_app_controller()
    window6 = MainWindow(controller6)
    window6.show()
    check("warning label starts hidden", not window6.warning_label.isVisible())
    silent_later_module.silent = True  # module "unplugged" - stops answering
    window6._cards[0].toggle.click()  # sends a command that will never be ack'd
    check("toggle flips immediately (optimistic UI, before any ack)", window6._cards[0].toggle.isChecked())
    pump(WORST_CASE_MS)
    check("command_timeout reached the UI (warning now visible)", window6.warning_label.isVisible())
    check("warning text is non-empty", bool(window6.warning_label.text()))
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
    # Turn it on first (a normal resume_output(), succeeds), THEN start
    # rejecting - clicking it off from there sends exactly one command
    # (turn_output_off), isolating the single-command rejection path
    # cleanly (clicking on-from-off instead would go through
    # resume_output()'s two-command sequence and reject_next only
    # rejects the first of the two).
    reject_module = FakeModulePort(address=0)
    registry_reject = FakePortRegistry()
    registry_reject.add("FAKE_REJECT", reject_module)
    install_fake_hardware(registry_reject)
    controller15 = make_app_controller()
    window15 = MainWindow(controller15)
    window15.show()
    window15._cards[0].toggle.click()  # off -> on: resume_output(), succeeds normally
    pump(300)
    check("turned on normally first", window15._cards[0].toggle.isChecked())
    check("hardware really turned on", reject_module.output_on)

    reject_module.reject_next = True
    window15._cards[0].toggle.click()  # on -> off: single command (turn_output_off)
    check("toggle flips immediately (optimistic UI)", not window15._cards[0].toggle.isChecked())
    pump(200)  # fake hardware replies near-instantly, no need to wait for the full timeout
    check("toggle reverts back on after an explicit device rejection", window15._cards[0].toggle.isChecked())
    check("hardware itself never actually turned off", reject_module.output_on)
    check("rejection surfaced as a warning too", window15.warning_label.isVisible())

    controller15.shutdown()
    window15.close()
    pump(50)

    print("\n=== resume_output(): if Output ON is rejected, Signal Control")
    print("    succeeding right after must NOT flip output_on back to True ===")
    resume_module = FakeModulePort(address=0, output_on=False)
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
    window16._cards[0].toggle.click()  # off -> on: resume_output(), 2 commands
    pump(400)  # both commands round-trip well under this on fake hardware
    check(
        "output stays off - the Signal Control success must not override the Output ON rejection",
        not resume_module.output_on,
    )
    check("card reflects that too, not stuck showing on", not window16._cards[0].toggle.isChecked())

    controller16.shutdown()
    window16.close()
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
    window7._cards[0].toggle.click()  # blind send straight into collision noise
    check("optimistic UI applies immediately, before any response", window7._cards[0].toggle.isChecked())
    pump(WORST_CASE_MS)
    check(
        "still applied after every retry exhausts with no valid response "
        "(optimistic apply-on-timeout - real hardware showed unconfirmed commands often land anyway)",
        window7._cards[0].toggle.isChecked(),
    )
    check("collision surfaced as a warning", window7.warning_label.isVisible())
    check("no crash/hang against a colliding shared bus", True)
    controller7.shutdown()
    window7.close()
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
    share_a = FakeModulePort(address=4, freq_mhz=2400)
    share_b = FakeModulePort(address=6, freq_mhz=5800)
    addressed_bus = FakeAddressedBusPort([share_a, share_b])
    registry_share = FakePortRegistry()
    registry_share.add("FAKE_SHARE", addressed_bus)
    install_fake_hardware(registry_share)
    controller13 = make_app_controller()
    window13 = MainWindow(controller13)
    window13.show()

    window13._cards[4].toggle.click()
    pump(300)
    check("address 4 turned on", share_a.output_on)
    check("turning address 4 on doesn't leak into address 6", not share_b.output_on)

    window13._cards[6].toggle.click()
    pump(300)
    check("address 6 also works on the same shared port", share_b.output_on)
    check("address 4 still on, unaffected by address 6's command", share_a.output_on)

    controller13.shutdown()
    window13.close()
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
