# SDR Customer Control (simplified)

A new, simplified app built from the original `sdr_controller` project.
Reuses the parts of that codebase that were already solid (protocol
layer, serial I/O, `Card`/`ToggleSwitch` widgets, the toggle-sync
`blockSignals` pattern) and drops or rewrites the rest for a
customer-facing, single-page, multi-channel control surface.

## What this app is

- **One screen.** No Dashboard / Device Control / Communication pages,
  no sidebar.
- **Multiple channels at once** - one card per hardware channel,
  auto-discovered on the shared RS422 bus (not hardcoded to 16).
- **Per channel, exactly two controls:** an On/Off toggle and a
  4-position Level slider (L0-L3), kept in bidirectional reactive sync
  with each other and with the real hardware state.
- **No Module Address anywhere in the UI.** The customer sees CH01,
  CH02, ... (display number = real protocol address + 1); the real
  address is never shown or editable.
- **Mode / Frequency / Bandwidth are not customer-adjustable.** On
  discovery, each channel's current Mode/Frequency/Bandwidth is read via
  Status Query and echoed back unchanged on every Power change - the
  app never guesses or hardcodes these values.
- **No temperature/heat monitoring** - no sensor exists on the hardware.

## What changed vs. the original `sdr_controller` repo

| Removed | Rewritten | Reused as-is |
|---|---|---|
| Multi-page nav (`main_window.py`'s `QStackedWidget`, `sidebar.py`) | Discovery (`query_address()` was a single-device broadcast; new `DiscoveryController` probes addresses one at a time via addressed Status Query) | `protocol/` (constants, commands, packet builder/parser) |
| Module Address field/buttons (`device_control_page.py`) | State model: one `ChannelState` per channel instead of a single global `DeviceState` | `serial_io/` (manager, thread) |
| Mode radio buttons, Frequency widget, Bandwidth dropdown | Command layer: `ChannelController` (per address) replaces `DeviceController`; no `set_address()`/`query_address()`, no user-driven `apply_signal_settings()` | `ui/widgets/card.py`, `toggle_switch.py` |
| `dashboard_page.py`, `communication_page.py`, TX/RX hex displays | Config: per-channel JSON (`last_level`) instead of a single `module_address` | `controller/connection_controller.py` (one shared serial link) |
| (Accounts/roles/login/action-log were never actually implemented in the original repo - nothing to remove there) | Level control: 4-position slider replacing the old Power dropdown, mapped in `models/level_map.py` | `services/logging_service.py`, `app_paths.py`, `ui/theme_colors.py` |

## Open items before this is production-ready

1. **Never-configured factory-fresh module test.** The read-then-echo
   Power flow assumes a fresh module answers a Status Query with sane
   values on its very first query. This hasn't been tested on real
   hardware yet - worth doing before relying on it in the field.
2. **Channel ceiling.** `MAX_CHANNELS = 16` in
   `controller/channel_manager.py` is a UI/practicality choice - the
   protocol itself (`protocol/constants.py`, `ADDR_MAX = 199`) supports
   far more. Confirm 16 is still the right ceiling.
3. **Visual style.** Currently reuses the original `Card`/`ToggleSwitch`
   look. Restyling closer to a dark 16-channel reference dashboard is a
   styling pass, not a blocker.
4. **Packaging** (PyInstaller + Inno Setup + GitHub Actions) not set up
   in this new repo yet - straightforward to add once functionality is
   signed off, PyArmor intentionally left out for now per request.

## File structure (React-style mapping)

If you're used to a React project, here's how this maps:

| React concept | Folder here | What's in it |
|---|---|---|
| `components/` | `components/` | Reusable UI pieces: `Card`, `ToggleSwitch`, `LevelSlider`, `ChannelCard`, `ConnectionBar`, `ComboBox` |
| `pages/` | `pages/` | The one screen: `main_page.py` (`MainWindow`) |
| `hooks/` | `hooks/` | Non-UI reactive logic: `use_connection.py` (serial link), `use_channel.py` (per-channel commands), `use_discovery.py` (address scan), `use_channels.py` (ties them together), `use_app.py` (top-level wiring) |
| `state/` | `state/` | Data models: `channel_state.py`, `level_map.py` |
| external API layer | `services/` | Hardware communication: `services/protocol/` (frame format) + `services/serial/` (transport) |
| misc utilities | `utils/` | `config_service.py`, `logging_service.py`, `app_paths.py` |
| `styles/` | `styles/` | `theme_colors.py` |
| `index.js` | `main.py` | Entry point |
| `App.js` | `app.py` | Sets up the QApplication, theme, launches the main page |

## Running it

```
pip install -r requirements.txt
python main.py
```

No real hardware connected? The app will show "No channels responded"
after scanning - that's expected, it just means no module answered the
discovery probe.
