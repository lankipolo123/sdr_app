"""Full-stack dry run against fake hardware - no real serial port needed.

Exercises the same code path a real run does end to end: AppController,
MainWindow, ChannelManager, DiscoveryController, ChannelController,
ChannelCard, ConnectionBar, Close App,
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
        FakeModulePort, FakePortRegistry, FakeSharedBusPort, FakeAddressedBusPort,
        install_fake_hardware,
    )

    registry = FakePortRegistry()
    module = FakeModulePort(address=0)
    registry.add("FAKE0", module)
    install_fake_hardware(registry)

    work_dir = tempfile.mkdtemp(prefix="sdr_dry_run_")
    config_path = os.path.join(work_dir, "config.json")

    from utils.config_service import ConfigService
    from utils.logging_service import setup_logger
    from hooks.use_channels import ChannelManager, MAX_CHANNELS
    from hooks.use_app import AppController
    from pages.main_page import MainWindow
    from components.confirm_dialog import ConfirmDialog

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
    check(
        "no auto-scan on launch (nothing found yet)",
        all(c is None for c in controller.channels.controllers.values()),
    )
    window.rescan_btn.click()
    wait_for(controller.channels.discovery_finished)
    check("discovery finds the fake module", controller.channels.controllers.get(0) is not None)
    check(
        "exactly one channel discovered (no duplicates)",
        sum(1 for c in controller.channels.controllers.values() if c is not None) == 1,
    )
    check("channel card created in the UI", 0 in window._cards)

    if controller.channels.controllers.get(0) is None:
        print("Cannot continue - channel wasn't discovered at all.")
        controller.shutdown()
        sys.exit(1)

    card = window._cards[0]
    check("card's display number matches its address (CH00, no +1 offset)", card.state.display_number == 0)
    check("initial state: output off (matches fake module default)", not module.output_on)
    check("initial state: toggle unchecked", not card.toggle.isChecked())
    check("initial state: slider at 0 (Off)", card.slider.value() == 0)

    print("\n=== Toggle on (UI -> hardware) ===")
    card.toggle.click()
    pump(200)
    check("hardware output turned on", module.output_on)
    check("toggle stayed checked", card.toggle.isChecked())
    check("slider resumed to default level 1 (Min)", card.slider.value() == 1)
    check("hardware power_code matches L1 (0x02)", module.power_code == 0x02)

    print("\n=== Drag slider to Max (UI -> hardware, and back: hardware ack -> UI resync) ===")
    card.slider.setValue(3)
    pump(200)
    check("hardware power_code matches L3 (0x00 / max)", module.power_code == 0x00)
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
    check("hardware power_code matches L3 again", module.power_code == 0x00)

    print("\n=== Rescan (port already claimed - must not duplicate) ===")
    window._on_rescan()
    wait_for(controller.channels.discovery_finished)
    check(
        "still exactly one channel after rescan",
        sum(1 for c in controller.channels.controllers.values() if c is not None) == 1,
    )
    check("still all 16 slots present, no duplicate cards", len(window._cards) == MAX_CHANNELS)

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
    window2.rescan_btn.click()
    wait_for(controller2.channels.discovery_finished)
    check("second run rediscovers the channel", controller2.channels.controllers.get(0) is not None)
    check(
        "restored last_level from config, not the hard-coded default",
        controller2.channels.states[0].data.last_level == last_level_before_shutdown,
    )
    controller2.shutdown()
    window2.close()
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
    window3.close()
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
    check(
        "both modules discovered",
        sum(1 for c in controller4.channels.controllers.values() if c is not None) == 2,
    )
    check("all 16 channel cards present", len(window4._cards) == MAX_CHANNELS)
    check("address 0 present", controller4.channels.controllers.get(0) is not None)
    check("address 1 present", controller4.channels.controllers.get(1) is not None)
    controller4.shutdown()
    window4.close()
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
    # The dead port alone now retries the primary baud PROBE_RETRY_ATTEMPTS
    # times before sweeping the fallback bauds once each - (6 * 750ms) +
    # (4 * 750ms) = ~7500ms worst case, then the good port still needs its
    # own round trip on top of that - give it real headroom.
    wait_for(controller5.channels.discovery_finished, timeout_ms=10000)
    check(
        "exactly one channel found (the live one)",
        sum(1 for c in controller5.channels.controllers.values() if c is not None) == 1,
    )
    check(
        "it's the good module's address (5), not the dead one's",
        controller5.channels.controllers.get(5) is not None,
    )
    controller5.shutdown()
    window5.close()
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
    check("timeout-test channel discovered", controller6.channels.controllers.get(0) is not None)
    check("warning label starts hidden", not window6.warning_label.isVisible())
    if controller6.channels.controllers.get(0) is not None:
        silent_later_module.silent = True  # module "unplugged" - stops answering
        window6._cards[0].toggle.click()  # sends a command that will never be ack'd
        check("toggle flips immediately (optimistic UI, before any ack)", window6._cards[0].toggle.isChecked())
        # RETRY_MAX_ATTEMPTS (6) * RESPONSE_TIMEOUT_MS (800ms) = worst case
        # ~4800ms before it actually gives up now that a silent module
        # gets retried instead of failing after one attempt.
        pump(5200)
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

    print("\n=== Explicit rejection (RESP_FAILED) also reverts the UI ===")
    print("(different from a timeout - the device DID respond, just said no.")
    print(" Previously this path did nothing at all: no revert, no warning,")
    print(" untestable since the fake always replied success)")
    # Starts already ON, so clicking the toggle to turn it OFF sends
    # exactly one command (turn_output_off) - isolates the single-command
    # rejection path cleanly, since clicking on-from-off instead would go
    # through resume_output()'s two-command sequence (Output ON, then
    # Signal Control) and reject_next only rejects the first of the two.
    reject_module = FakeModulePort(address=0, output_on=True, power_code=0x00)
    registry_reject = FakePortRegistry()
    registry_reject.add("FAKE_REJECT", reject_module)
    install_fake_hardware(registry_reject)
    controller15 = make_app_controller()
    window15 = MainWindow(controller15)
    window15.show()
    window15.rescan_btn.click()
    wait_for(controller15.channels.discovery_finished)
    check("rejection-test channel discovered", controller15.channels.controllers.get(0) is not None)
    if controller15.channels.controllers.get(0) is not None:
        check("starts on, as configured", window15._cards[0].toggle.isChecked())

    if controller15.channels.controllers.get(0) is not None:
        reject_module.reject_next = True
        window15._cards[0].toggle.click()  # turns OFF - single command (turn_output_off)
        check("toggle flips immediately (optimistic UI)", not window15._cards[0].toggle.isChecked())
        pump(200)  # fake hardware replies near-instantly, no need to wait for the 2000ms timeout
        check("toggle reverts back on after an explicit device rejection", window15._cards[0].toggle.isChecked())
        check("hardware itself never actually turned off", reject_module.output_on)
        check("rejection surfaced as a warning too", window15.warning_label.isVisible())

    controller15.shutdown()
    window15.close()
    pump(50)

    print("\n=== resume_output(): if Output ON is rejected, Signal Control")
    print("    succeeding right after must NOT flip output_on back to True ===")
    print("(the two-command sequence behind turning a channel back on -")
    print(" set_power() used to unconditionally claim output_on=True on")
    print(" its own success, even when the Output ON half of the same")
    print(" sequence had just failed)")
    resume_module = FakeModulePort(address=0, output_on=False)
    registry_resume = FakePortRegistry()
    registry_resume.add("FAKE_RESUME", resume_module)
    install_fake_hardware(registry_resume)
    controller16 = make_app_controller()
    window16 = MainWindow(controller16)
    window16.show()
    window16.rescan_btn.click()
    wait_for(controller16.channels.discovery_finished)
    check("resume-test channel discovered", controller16.channels.controllers.get(0) is not None)
    if controller16.channels.controllers.get(0) is not None:
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
    # Collision noise never resolves into a valid response, so this now
    # exhausts every retry at the primary baud plus each fallback baud
    # once - same ~7500ms worst case as the dead-port test, give headroom.
    wait_for(controller7.channels.discovery_finished, timeout_ms=10000)
    check(
        "no phantom channel built from collision noise",
        all(c is None for c in controller7.channels.controllers.values()),
    )
    check("status reflects nothing found, not a false success",
          "No devices found" in window7.status_label.text())
    check("no crash/hang scanning a colliding shared bus", True)
    controller7.shutdown()
    window7.close()
    pump(50)

    print("\n=== Manual disconnect + physical swap (see both, control one at a time) ===")
    print("(module A wired in, controlled, disconnected in-app; module B")
    print(" physically wired into the SAME port in its place; a plain")
    print(" rescan picks it up - both cards stay visible the whole time,")
    print(" only the currently-wired one is live, using only what's")
    print(" already on hand, no purchase)")
    swap_module_a = FakeModulePort(address=0)
    registry_swap = FakePortRegistry()
    registry_swap.add("FAKE_SWAP", swap_module_a)
    install_fake_hardware(registry_swap)
    controller10 = make_app_controller()
    window10 = MainWindow(controller10)
    window10.show()
    window10.rescan_btn.click()
    wait_for(controller10.channels.discovery_finished)
    check("module A discovered first", controller10.channels.controllers.get(0) is not None)
    check("module A has a card", 0 in window10._cards)
    check("module A's card starts enabled (live)", window10._cards[0].toggle.isEnabled())

    if controller10.channels.controllers.get(0) is not None:
        window10._cards[0].disconnect_requested.emit(0)
        check("controller cleared after manual disconnect", controller10.channels.controllers.get(0) is None)
        check("card A stays visible (not removed) after disconnect", 0 in window10._cards)
        check("card A's controls disabled while offline", not window10._cards[0].toggle.isEnabled())

        # Physically swap: module A comes off the shared port, module B
        # goes on in its place (same fake port name = same physical wire).
        swap_module_b = FakeModulePort(address=1)
        registry_swap.modules["FAKE_SWAP"] = swap_module_b
        window10._on_rescan()
        wait_for(controller10.channels.discovery_finished)
        check("module B discovered after the swap", controller10.channels.controllers.get(1) is not None)
        check("module B has its own new card", 1 in window10._cards)
        check("both cards visible at once now", 0 in window10._cards and 1 in window10._cards)
        check("card B is live", window10._cards[1].toggle.isEnabled())
        check("card A is still offline (not silently reconnected)", not window10._cards[0].toggle.isEnabled())

        # Swap back to module A - it should come back online on its
        # SAME pre-existing card, not spawn a duplicate. Has to release
        # B's port first, same as any other swap.
        window10._cards[1].disconnect_requested.emit(1)
        registry_swap.modules["FAKE_SWAP"] = swap_module_a
        window10._on_rescan()
        wait_for(controller10.channels.discovery_finished)
        check("module A back online reuses its original card", window10._cards[0].toggle.isEnabled())
        check("still all 16 slots present, no duplicate cards", len(window10._cards) == MAX_CHANNELS)

    controller10.shutdown()
    window10.close()
    pump(50)

    print("\n=== Disconnecting mid-command must not leave a stale timeout ===")
    print("(a command sent right before Disconnect is clicked has no ack")
    print(" coming - its response timer used to keep running on the")
    print(" abandoned controller and fire a misleading warning later)")
    stale_module = FakeModulePort(address=0)
    registry_stale = FakePortRegistry()
    registry_stale.add("FAKE_STALE", stale_module)
    install_fake_hardware(registry_stale)
    controller11 = make_app_controller()
    window11 = MainWindow(controller11)
    window11.show()
    window11.rescan_btn.click()
    wait_for(controller11.channels.discovery_finished)
    check("stale-test channel discovered", controller11.channels.controllers.get(0) is not None)

    stale_fired = []
    controller11.channels.command_timeout.connect(lambda msg: stale_fired.append(msg))

    if controller11.channels.controllers.get(0) is not None:
        stale_module.silent = True  # module stops answering - the next command never gets ack'd
        window11._cards[0].toggle.click()  # sends a command, starts its 2000ms pending timer
        pump(50)  # let the send go out, nowhere near the 2000ms timeout yet
        controller11.channels.disconnect_channel(0)  # released mid-flight
        pump(2300)  # past RESPONSE_TIMEOUT_MS - must NOT fire from the abandoned controller
        check("no stale command_timeout fired after disconnecting mid-command", len(stale_fired) == 0)

    controller11.shutdown()
    window11.close()
    pump(50)

    print("\n=== Manual ask (+Addr): targeted, no broadcast ===")
    print("(type a specific address, ask it directly - proves this path")
    print(" behaves identically to a normal Scan discovery once it gets")
    print(" a real response, including reusing a known channel's card)")
    ask_module = FakeModulePort(address=3)
    registry_ask = FakePortRegistry()
    registry_ask.add("FAKE_ASK", ask_module)
    install_fake_hardware(registry_ask)
    controller12 = make_app_controller()
    window12 = MainWindow(controller12)
    window12.show()

    # Address 3 is one of the 16 pre-built slots (see ChannelManager), so
    # finding it now comes through as channel_online, not channel_added -
    # channel_added only fires for an address outside that range.
    controller12.channels.add_manual_channel(3)
    wait_for(controller12.channels.channel_online, timeout_ms=3000)
    check("manual ask found the address", controller12.channels.controllers.get(3) is not None)
    check("manual ask created a card", 3 in window12._cards)

    if controller12.channels.controllers.get(3) is not None:
        window12._cards[3].disconnect_requested.emit(3)
        check("disconnect works the same after a manual ask", controller12.channels.controllers.get(3) is None)

        controller12.channels.add_manual_channel(3)
        wait_for(controller12.channels.channel_online, timeout_ms=3000)
        check("asking the same address again reuses its existing card", window12._cards[3].toggle.isEnabled())
        check("still all 16 slots present, no duplicate cards", len(window12._cards) == MAX_CHANNELS)

    wrong_ask_fired = []
    controller12.channels.command_timeout.connect(lambda msg: wrong_ask_fired.append(msg))
    controller12.channels.add_manual_channel(7)  # nothing at this address
    wait_for(controller12.channels.command_timeout, timeout_ms=4000)
    check(
        "asking a wrong address fails cleanly, no phantom live channel",
        controller12.channels.controllers.get(7) is None,
    )

    controller12.shutdown()
    window12.close()
    pump(50)

    print("\n=== +Addr sharing one port: two addresses, no disconnect needed ===")
    print("(the actual real-world ask: one physical adapter, ask address A,")
    print(" then ask address B on the SAME port without disconnecting A -")
    print(" both should end up live at once, no cross-talk between them)")
    share_a = FakeModulePort(address=4, freq_mhz=2400)
    share_b = FakeModulePort(address=6, freq_mhz=5800)
    addressed_bus = FakeAddressedBusPort([share_a, share_b])
    registry_share = FakePortRegistry()
    registry_share.add("FAKE_SHARE", addressed_bus)
    install_fake_hardware(registry_share)
    controller13 = make_app_controller()
    window13 = MainWindow(controller13)
    window13.show()

    controller13.channels.add_manual_channel(4)
    wait_for(controller13.channels.channel_online, timeout_ms=3000)
    check("first address found on the shared port", controller13.channels.controllers.get(4) is not None)

    controller13.channels.add_manual_channel(6)
    wait_for(controller13.channels.channel_online, timeout_ms=3000)
    check(
        "second address found on the SAME port, without disconnecting the first",
        controller13.channels.controllers.get(6) is not None,
    )
    check("both addresses stayed live at once", controller13.channels.controllers.get(4) is not None)
    check(
        "both addresses are recognized as being on the same physical port",
        controller13.channels._address_port[4] == controller13.channels._address_port[6],
    )

    if controller13.channels.controllers.get(4) is not None and controller13.channels.controllers.get(6) is not None:
        window13._cards[4].toggle.click()
        pump(200)
        check("turning address 4 on doesn't leak into address 6", not share_b.output_on)
        check("address 4 actually turned on", share_a.output_on)

        window13._cards[4].disconnect_requested.emit(4)
        pump(300)  # disconnect now turns output off first (was on) and waits for that ack
        check("address 4 turned off before disconnecting", not share_a.output_on)
        check("address 4 actually disconnected", controller13.channels.controllers.get(4) is None)
        check(
            "disconnecting one shared address doesn't kill the connection the other still needs",
            controller13.channels.controllers.get(6) is not None,
        )
        window13._cards[6].toggle.click()
        pump(200)
        check("address 6 still works after address 4 disconnected", share_b.output_on)

    controller13.shutdown()
    window13.close()
    pump(50)

    print("\n=== Safe disconnect: falls through if the off command never acks ===")
    print("(module was on, then goes silent - matches the unresponsive-")
    print(" hardware pattern seen throughout today. Must not leave the")
    print(" user stuck waiting forever to disconnect)")
    silent_off_module = FakeModulePort(address=8)
    registry_silent_off = FakePortRegistry()
    registry_silent_off.add("FAKE_SILENT_OFF", silent_off_module)
    install_fake_hardware(registry_silent_off)
    controller14 = make_app_controller()
    window14 = MainWindow(controller14)
    window14.show()
    window14.rescan_btn.click()
    wait_for(controller14.channels.discovery_finished)
    check("silent-off test channel discovered", controller14.channels.controllers.get(8) is not None)

    if controller14.channels.controllers.get(8) is not None:
        window14._cards[8].toggle.click()
        pump(200)
        check("output turned on before going silent", silent_off_module.output_on)

        silent_off_module.silent = True  # stops answering anything, including the off command
        window14._cards[8].disconnect_requested.emit(8)
        pump(1300)  # past the 1000ms fallback timeout in disconnect_channel_safely
        check(
            "disconnects anyway once the off command times out, doesn't hang forever",
            controller14.channels.controllers.get(8) is None,
        )

    controller14.shutdown()
    window14.close()
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
