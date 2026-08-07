# SDR Customer Control (simplified)

A new, simplified app built from the original `sdr_controller` project.
Reuses the parts of that codebase that were already solid (protocol
layer, serial I/O, the `Card` widget, the reactive-sync `blockSignals`
pattern) and drops or rewrites the rest for a customer-facing,
single-page, multi-channel control surface. `ToggleSwitch` was reused
initially, replaced by a checkable `PowerButton`, then replaced again
by the current `PowerButton` - two plain ON/OFF buttons instead of one
toggle, each sending exactly one command (see `components/power_button.py`).

## What this app is

- **One screen.** No Dashboard / Device Control / Communication pages,
  no sidebar.
- **Multiple channels at once** - one card per address, all 16 slots
  live from launch. There is no Scan/discovery step and no +Addr manual
  ask: every card already has a real `ChannelController` from startup,
  and every command it sends is "blind" - it brute-force finds an
  available serial port fresh, retries on no response, and applies the
  change optimistically even if nothing ever acknowledges it. This was a
  deliberate choice after real hardware testing: two modules sharing one
  USB-RS422 adapter collide electrically (RS422 has no DE/RE tri-state
  pin), so the collision is probabilistic, not a hard wall - waiting on
  a confirmed discovery response before allowing any control only means
  sometimes waiting on something that never comes, when the blind
  command would likely have gotten through anyway.
- **Per channel, exactly two controls:** explicit ON/OFF buttons and a
  4-position Level slider (L0-L3), kept in bidirectional reactive sync
  with each other and with whatever the last confirmed (or optimistically
  applied) hardware state is. Each card starts locked - the slider and
  ON/OFF buttons are disabled until the card itself is tapped once, and
  only one card is ever armed at a time (tapping a different card locks
  the previous one back down) - a guard against an accidental
  drag/scroll firing a real command on hardware that's already
  unpredictable enough on a shared line.
- **A separate "Query" diagnostic** (top Controls bar) exists alongside
  the cards - type in a specific address, and unlike a card's blind
  send, it actually brute-force finds the port and waits for/verifies a
  real confirmed response (retrying up to `QUERY_MAX_ATTEMPTS` times)
  before reporting success or failure. Useful for confirming what
  address a physical module is really configured to before relying on
  that address's card.
- **No Module Address anywhere in the UI.** The customer sees CH00,
  CH01, CH02, ... (display number = real protocol address, no offset -
  an earlier +1 offset was removed after it caused a warning showing
  the raw address to look like it was about a different, missing
  channel from the +1'd card title); the real address is never
  editable, though it is what's actually displayed now.
- **Mode / Frequency / Bandwidth are not customer-adjustable.** A
  channel's current Mode/Frequency/Bandwidth is echoed back unchanged on
  every Power change once a real baseline exists (from a confirmed
  Status Query response). Since there's no discovery step anymore,
  that baseline usually doesn't exist yet - in that case Power falls
  back to guessed defaults (`BLIND_DEFAULT_MODE`/`FREQ_MHZ`/
  `BANDWIDTH_MHZ` in `services/protocol/constants.py`) rather than
  refusing to send. This is an explicitly accepted risk (a wrong
  frequency/bandwidth is a real RF behavior change, unlike an
  unconfirmed Output ON/OFF) so Power can still be blind-sent to a
  channel with no baseline, same as Output ON/OFF already could.
- **No temperature/heat monitoring** - no sensor exists on the hardware.

## What changed vs. the original `sdr_controller` repo

| Removed | Rewritten | Reused as-is |
|---|---|---|
| Multi-page nav (`main_window.py`'s `QStackedWidget`, `sidebar.py`); Scan/discovery and the +Addr manual-ask dialog (`DiscoveryController`, `hooks/use_discovery.py`, `ManualAddDialog`) - removed once real hardware testing showed a "blind" command (no prior confirmed response required) reaches the module about as reliably as a discovered one, so gating controls behind a discovery step only added a wait for something that might never come | Command layer: every `ChannelController` now brute-force finds and opens its own port fresh per command instead of relying on a connection a discovery step found earlier | `services/protocol/` (constants, commands, packet builder/parser) |
| Module Address field/buttons (`device_control_page.py`) | State model: one `ChannelState` per channel instead of a single global `DeviceState` | `services/serial/` (manager, thread) |
| Mode radio buttons, Frequency widget, Bandwidth dropdown | Command layer: `ChannelController` (per address) replaces `DeviceController`; no user-driven `apply_signal_settings()`. A protocol-level `set_address()`/`query_address()` still exists in `services/protocol/commands.py` but has no caller now that discovery is gone - kept as complete protocol coverage, not currently used by the app. | `components/card.py` |
| `dashboard_page.py`, `communication_page.py` | Config: per-channel JSON (`last_level`) instead of a single `module_address`. TX/RX now shown as a live status bar at the bottom of the window instead of a dedicated page. | `hooks/use_connection.py` (one dedicated serial link per discovered channel, not shared) |
| (Accounts/roles/login/action-log were never actually implemented in the original repo - nothing to remove there) | Level control: 4-position slider replacing the old Power dropdown, mapped in `state/level_map.py` | `utils/logging_service.py`, `styles/theme_colors.py` |

## Open items before this is production-ready

1. **Guessed Mode/Frequency/Bandwidth defaults on Power, always.**
   Nothing calls `read_status()` automatically anymore (no discovery
   step left to trigger it), so a channel's real Mode/Frequency/
   Bandwidth baseline is essentially never populated in practice - every
   Power command falls back to `BLIND_DEFAULT_MODE`/`FREQ_MHZ`/
   `BANDWIDTH_MHZ` (`services/protocol/constants.py`). This is an
   explicitly accepted risk, not a bug, but worth confirming those
   specific defaults are actually safe for the real modules in the
   field.
2. **Channel ceiling.** `MAX_CHANNELS = 16` in `hooks/use_channels.py`
   is a UI/practicality choice (how many channel cards/controllers get
   built at launch) - the protocol itself
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
| `components/` | `components/` | Reusable UI pieces: `Card`, `PowerButton`, `LevelSlider`, `ChannelCard`, `ConfirmDialog`, `TitleBar`/`ResizableContainer` (custom window chrome) |
| `pages/` | `pages/` | The one screen: `main_page.py` (`MainWindow`) |
| `hooks/` | `hooks/` | Non-UI reactive logic: `use_connection.py` (opens/sends on one port at a time), `use_channel.py` (per-channel commands - brute-force finds its own port fresh per command, retries, optimistic apply-on-timeout), `use_channels.py` (owns one live `ChannelController` per address from launch, no discovery step), `use_app.py` (top-level wiring) |
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

No real hardware connected? Cards will send blind and just never get
confirmed (retries exhaust, the state applies optimistically anyway -
see `hooks/use_channel.py`) - there's no discovery step to report "no
devices found" up front anymore. `logs/sdr_controller.log` still
records every send/timeout/rejection even though the UI no longer
shows a warning banner for them.
