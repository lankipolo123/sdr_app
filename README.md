# SDR Customer Control (simplified)

A new, simplified app built from the original `sdr_controller` project.
Reuses the parts of that codebase that were already solid (protocol
layer, serial I/O, the `Card` widget, the toggle-sync `blockSignals`
pattern) and drops or rewrites the rest for a customer-facing,
single-page, multi-channel control surface. `ToggleSwitch` was reused
initially but has since been replaced by `PowerButton` (a plain
checkable `QPushButton` with the same API) and removed as dead code.

## What this app is

- **One screen.** No Dashboard / Device Control / Communication pages,
  no sidebar.
- **Multiple channels at once** - one card per hardware channel,
  auto-discovered on the shared RS422 bus (not hardcoded to 16).
- **Per channel, exactly two controls:** an On/Off toggle and a
  4-position Level slider (L0-L3), kept in bidirectional reactive sync
  with each other and with the real hardware state.
- **No Module Address anywhere in the UI.** The customer sees CH00,
  CH01, CH02, ... (display number = real protocol address, no offset -
  an earlier +1 offset was removed after it caused a warning showing
  the raw address to look like it was about a different, missing
  channel from the +1'd card title); the real address is never
  editable, though it is what's actually displayed now.
- **Mode / Frequency / Bandwidth are not customer-adjustable.** On
  discovery, each channel's current Mode/Frequency/Bandwidth is read via
  Status Query and echoed back unchanged on every Power change - the
  app never guesses or hardcodes these values.
- **No temperature/heat monitoring** - no sensor exists on the hardware.

## What changed vs. the original `sdr_controller` repo

| Removed | Rewritten | Reused as-is |
|---|---|---|
| Multi-page nav (`main_window.py`'s `QStackedWidget`, `sidebar.py`) | Discovery (`query_address()` was originally a single-device broadcast against one shared connection; rewritten again since - `DiscoveryController`, `hooks/use_discovery.py`, now probes serial *ports* one at a time, each with its own dedicated `ConnectionController`, since two modules sharing one port/adapter turned out to collide electrically on real hardware - not addresses on a shared bus) | `services/protocol/` (constants, commands, packet builder/parser) |
| Module Address field/buttons (`device_control_page.py`) | State model: one `ChannelState` per channel instead of a single global `DeviceState` | `services/serial/` (manager, thread) |
| Mode radio buttons, Frequency widget, Bandwidth dropdown | Command layer: `ChannelController` (per address) replaces `DeviceController`; no user-driven `apply_signal_settings()`. A protocol-level `set_address()`/`query_address()` still exists and is used internally by discovery. | `components/card.py` |
| `dashboard_page.py`, `communication_page.py` | Config: per-channel JSON (`last_level`) instead of a single `module_address`. TX/RX now shown as a live status bar at the bottom of the window instead of a dedicated page. | `hooks/use_connection.py` (one dedicated serial link per discovered channel, not shared) |
| (Accounts/roles/login/action-log were never actually implemented in the original repo - nothing to remove there) | Level control: 4-position slider replacing the old Power dropdown, mapped in `state/level_map.py` | `utils/logging_service.py`, `styles/theme_colors.py` |

## Open items before this is production-ready

1. **Never-configured factory-fresh module test.** The read-then-echo
   Power flow assumes a fresh module answers a Status Query with sane
   values on its very first query. This hasn't been tested on real
   hardware yet - worth doing before relying on it in the field.
2. **Channel ceiling.** `MAX_CHANNELS = 16` in `hooks/use_channels.py`
   is a UI/practicality choice (also the cap on how many ports discovery
   will probe at once) - the protocol itself
   (`services/protocol/constants.py`, `ADDR_MAX = 199`) supports far
   more. Confirm 16 is still the right ceiling.
3. **Visual style.** Uses a custom-styled frameless window (own title
   bar, rounded corners) and the `Card` look throughout.
4. **Packaging** (PyInstaller + Inno Setup + GitHub Actions) not set up
   in this new repo yet - straightforward to add once functionality is
   signed off, PyArmor intentionally left out for now per request.

## File structure (React-style mapping)

If you're used to a React project, here's how this maps:

| React concept | Folder here | What's in it |
|---|---|---|
| `components/` | `components/` | Reusable UI pieces: `Card`, `PowerButton`, `LevelSlider`, `ChannelCard`, `ConnectionBar`, `ConfirmDialog`, `ManualAddDialog`, `TitleBar`/`ResizableContainer` (custom window chrome) |
| `pages/` | `pages/` | The one screen: `main_page.py` (`MainWindow`) |
| `hooks/` | `hooks/` | Non-UI reactive logic: `use_connection.py` (one serial link per channel), `use_channel.py` (per-channel commands), `use_discovery.py` (per-port scan), `use_channels.py` (ties them together, including manual by-address connect via `add_manual_channel`), `use_app.py` (top-level wiring) |
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
