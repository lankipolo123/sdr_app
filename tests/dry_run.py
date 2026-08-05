"""Full-stack dry run against fake hardware - no real serial port needed.

Exercises the same code path a real run does end to end: AppController,
MainWindow, ChannelManager, DiscoveryController, ChannelController,
ChannelCard, ConnectionBar, bulk "Set all", Emergency Stop, Close App,
config persistence, and shutdown safety - all against a FakeModulePort
standing in for a real module, so regressions anywhere in the
"channel found -> command sent -> state synced -> UI updates" pipeline
get caught without needing hardware on hand.

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


def wait_for(signal, timeout_ms: int = 3000):
    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
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
        FakeModulePort, FakePortRegistry, FakeSharedBusPort, install_fake_hardware,
    )

    registry = FakePortRegistry()
    module = FakeModulePort(address=0)
    registry.add("FAKE0", module)
    install_fake_hardware(registry)

    work_dir = tempfile.mkdtemp(prefix="sdr_dry_run_")
    config_path = os.path.join(work_dir, "config.json")

    from utils.config_service import ConfigService
    from utils.logging_service import setup_logger
    from hooks.use_channels import ChannelManager
    from hooks.use_app import AppController
    from pages.main_page import MainWindow
    from components.confirm_dialog import ConfirmDialog
    from state.level_map import LEVEL_TO_DB

    # Route confirm dialogs straight to "confirmed" - a real modal exec()
    # loop would just hang forever with nothing to click it.
    ConfirmDialog.ask = staticmethod(lambda *a, **k: True)

    def make_app_controller():
        controller = AppController.__new__(AppController)
        controller.config = ConfigService(path=config_path)
        controller.logger = setup_logger(os.path.join(work_dir, "logs"))
        controller.channels = ChannelManager(controller.config, controller.logger)
        return controller

    print("=== Run 1: fresh discovery ===")
    controller = make_app_controller()
    window = MainWindow(controller)
    window.show()

    # No more auto-scan on launch - discovery only ever starts from an
    # explicit click (the Scan button) now, so tests trigger it manually,
    # same as a real user would.
    check("no auto-scan on launch (nothing found yet)", len(controller.channels.states) == 0)
    window.rescan_btn.click()
    wait_for(controller.channels.discovery_finished)
    check("discovery finds the fake module", 0 in controller.channels.states)
    check("exactly one channel discovered (no duplicates)", len(controller.channels.states) == 1)
    check("channel card created in the UI", 0 in window._cards)

    if 0 not in window._cards:
        print("Cannot continue - channel wasn't discovered at all.")
        controller.shutdown()
        sys.exit(1)

    card = window._cards[0]
    check("card's display number is CH01", card.state.display_number == 1)
    check("initial state: output off (matches fake module default)", not module.output_on)
    check("initial state: toggle unchecked", not card.toggle.isChecked())
    check("initial state: slider at 0 (Off)", card.slider.value() == 0)

    print("\n=== Toggle on (UI -> hardware) ===")
    card.toggle.click()
    pump(200)
    check("hardware output turned on", module.output_on)
    check("toggle stayed checked", card.toggle.isChecked())
    check("slider resumed to default level 1 (Min)", card.slider.value() == 1)
    check("hardware power_db matches L1 (-12dB)", module.power_db == -12)

    print("\n=== Drag slider to Max (UI -> hardware, and back: hardware ack -> UI resync) ===")
    card.slider.setValue(3)
    pump(200)
    check("hardware power_db matches L3 (0dB / max)", module.power_db == 0)
    check("toggle still checked (L3 is not off)", card.toggle.isChecked())

    print("\n=== Drag slider to Off (slider -> toggle reactive sync) ===")
    card.slider.setValue(0)
    pump(200)
    check("hardware output turned off", not module.output_on)
    check("toggle reactively switched off", not card.toggle.isChecked())

    print("\n=== Toggle back on (should resume to last non-off level, L3) ===")
    card.toggle.click()
    pump(200)
    check("hardware output back on", module.output_on)
    check("slider resumed to last non-off level (3, Max)", card.slider.value() == 3)
    check("hardware power_db matches L3 again", module.power_db == 0)

    print("\n=== Bulk 'Set all' -> Med ===")
    med_btn = window.bulk_buttons[2]
    check("bulk button 2 is labeled Med", med_btn.text() == "Med")
    med_btn.click()
    pump(200)
    check("hardware power_db matches L2 (-6dB)", module.power_db == -6)
    check("card slider resynced to level 2", card.slider.value() == 2)

    print("\n=== Rescan (port already claimed - must not duplicate) ===")
    window._on_rescan()
    wait_for(controller.channels.discovery_finished)
    check("still exactly one channel after rescan", len(controller.channels.states) == 1)
    check("still exactly one card after rescan", len(window._cards) == 1)

    print("\n=== Emergency Stop ===")
    window.stop_btn.click()
    pump(200)
    check("emergency stop turned hardware off", not module.output_on)
    check("emergency stop reflected in UI (toggle unchecked)", not card.toggle.isChecked())

    last_level_before_shutdown = controller.channels.states[0].data.last_level
    print(f"\n=== Shutdown (last_level={last_level_before_shutdown} should persist) ===")
    controller.shutdown()
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
    window2.rescan_btn.click()
    wait_for(controller2.channels.discovery_finished)
    check("second run rediscovers the channel", 0 in controller2.channels.states)
    if 0 in controller2.channels.states:
        check(
            "restored last_level from config, not the hard-coded default",
            controller2.channels.states[0].data.last_level == last_level_before_shutdown,
        )
    controller2.shutdown()
    pump(50)

    print("\n=== Shutdown while a scan is still mid-flight (must not crash) ===")
    module2 = FakeModulePort(address=0)
    registry2 = FakePortRegistry()
    registry2.add("FAKE1", module2)
    install_fake_hardware(registry2)
    controller3 = make_app_controller()
    window3 = MainWindow(controller3)
    window3.show()
    window3.rescan_btn.click()
    # Deliberately no wait_for() here - shut down while the scan is still running.
    controller3.shutdown()
    pump(50)
    check("mid-scan shutdown completed without raising", True)

    print("\n=== Two modules on two separate ports (the actual real-world fix) ===")
    module_a = FakeModulePort(address=0)
    module_b = FakeModulePort(address=1)
    registry_multi = FakePortRegistry()
    registry_multi.add("FAKE_A", module_a)
    registry_multi.add("FAKE_B", module_b)
    install_fake_hardware(registry_multi)
    controller4 = make_app_controller()
    window4 = MainWindow(controller4)
    window4.show()
    window4.rescan_btn.click()
    wait_for(controller4.channels.discovery_finished)
    check("both modules discovered", len(controller4.channels.states) == 2)
    check("both channel cards created", len(window4._cards) == 2)
    check("address 0 present", 0 in controller4.channels.states)
    check("address 1 present", 1 in controller4.channels.states)
    controller4.shutdown()
    pump(50)

    print("\n=== A dead port mixed with a good one (must skip dead, find good) ===")
    dead_module = FakeModulePort(address=0, silent=True)
    good_module = FakeModulePort(address=5)
    registry_mixed = FakePortRegistry()
    registry_mixed.add("FAKE_DEAD", dead_module)
    registry_mixed.add("FAKE_GOOD", good_module)
    install_fake_hardware(registry_mixed)
    controller5 = make_app_controller()
    window5 = MainWindow(controller5)
    window5.show()
    window5.rescan_btn.click()
    wait_for(controller5.channels.discovery_finished, timeout_ms=4000)
    check("exactly one channel found (the live one)", len(controller5.channels.states) == 1)
    check("it's the good module's address (5), not the dead one's", 5 in controller5.channels.states)
    controller5.shutdown()
    pump(50)

    print("\n=== Command timeout (module goes silent mid-session) surfaces in the UI ===")
    silent_later_module = FakeModulePort(address=0)
    registry_timeout = FakePortRegistry()
    registry_timeout.add("FAKE_TIMEOUT", silent_later_module)
    install_fake_hardware(registry_timeout)
    controller6 = make_app_controller()
    window6 = MainWindow(controller6)
    window6.show()
    window6.rescan_btn.click()
    wait_for(controller6.channels.discovery_finished)
    check("timeout-test channel discovered", 0 in window6._cards)
    check("warning label starts hidden", not window6.warning_label.isVisible())
    if 0 in window6._cards:
        silent_later_module.silent = True  # module "unplugged" - stops answering
        window6._cards[0].toggle.click()  # sends a command that will never be ack'd
        pump(2300)  # RESPONSE_TIMEOUT_MS in hooks/use_channel.py is 2000ms
        check("command_timeout reached the UI (warning now visible)", window6.warning_label.isVisible())
        check("warning text is non-empty", bool(window6.warning_label.text()))
    controller6.shutdown()
    pump(50)

    print("\n=== One COM port, many addresses (real-world current test rig) ===")
    print("(one shared line, two modules both trying to answer - the exact")
    print(" wiring confirmed in testing: single USB-RS422 adapter driving")
    print(" two modules at once)")
    bus_module_a = FakeModulePort(address=0)
    bus_module_b = FakeModulePort(address=1)
    shared_bus = FakeSharedBusPort([bus_module_a, bus_module_b])
    registry_bus = FakePortRegistry()
    registry_bus.add("FAKE_SHARED_BUS", shared_bus)
    install_fake_hardware(registry_bus)
    controller7 = make_app_controller()
    window7 = MainWindow(controller7)
    window7.show()
    window7.rescan_btn.click()
    wait_for(controller7.channels.discovery_finished, timeout_ms=4000)
    check("no phantom channel built from collision noise", len(controller7.channels.states) == 0)
    check("status reflects nothing found, not a false success",
          "No devices found" in window7.status_label.text())
    check("no crash/hang scanning a colliding shared bus", True)
    controller7.shutdown()
    pump(50)

    print("\n=== Manual disconnect + physical swap (reach both, one at a time, no purchase) ===")
    print("(module A wired in, controlled, disconnected in-app; module B")
    print(" physically wired into the SAME port in its place; a plain")
    print(" rescan picks it up - the zero-cost 'swap which module is")
    print(" plugged in' workflow, using only what's already on hand)")
    swap_module_a = FakeModulePort(address=0)
    registry_swap = FakePortRegistry()
    registry_swap.add("FAKE_SWAP", swap_module_a)
    install_fake_hardware(registry_swap)
    controller10 = make_app_controller()
    window10 = MainWindow(controller10)
    window10.show()
    window10.rescan_btn.click()
    wait_for(controller10.channels.discovery_finished)
    check("module A discovered first", 0 in controller10.channels.states)
    check("module A has a card", 0 in window10._cards)

    if 0 in window10._cards:
        window10._cards[0].disconnect_requested.emit(0)
        check("channel released after manual disconnect", 0 not in controller10.channels.states)
        check("card removed from the UI", 0 not in window10._cards)

        # Physically swap: module A comes off the shared port, module B
        # goes on in its place (same fake port name = same physical wire).
        swap_module_b = FakeModulePort(address=1)
        registry_swap.modules["FAKE_SWAP"] = swap_module_b
        window10._on_rescan()
        wait_for(controller10.channels.discovery_finished)
        check("module B discovered after the swap", 1 in controller10.channels.states)
        check("module B has a card", 1 in window10._cards)

    controller10.shutdown()
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
