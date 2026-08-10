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
4. **Packaging.** PyInstaller `.exe` build is set up (`build_exe.py`,
   see "Building a standalone .exe" below) - verified end-to-end
   (asset bundling + frozen path resolution) via a Linux build in
   this environment, but the actual Windows `.exe` still needs a real
   build-and-run on Windows to confirm. Inno Setup installer script
   (`installer.iss`, see "Building the installer" below) is written
   but genuinely untested - Inno Setup has no Linux/Mac port at all,
   so unlike the `.exe` this couldn't be verified by an actual
   compile in this environment. GitHub Actions (CI automation) not
   set up yet. PyArmor intentionally left out for now per request.

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

## Building a standalone .exe

PyInstaller builds for whatever OS it runs on - there's no
cross-compiling a Windows `.exe` from Linux/Mac, so this has to run on
a real Windows machine:

```
pip install -r requirements-build.txt
python build_exe.py
```

Output lands in `dist/TX Controller.exe` - one file, no console
window, app icon and the `assets/` folder (icons) bundled inside it.
`dist/`, `build/`, and `*.spec` are all gitignored - `build_exe.py`
(not a checked-in `.spec` file) is what stays reproducible in version
control.

A splash screen (`components/splash_screen.py`) shows while
`AppController`/`MainWindow` are being built - both happen
synchronously before the Qt event loop starts, so it's a static
loading screen, not an animated one (real animation would need
threaded construction, which is a bigger change than this called
for).

Any code that reads a bundled asset (icons) needs
`utils/app_paths.py`'s `resource_path()`, not a plain
`os.path.dirname(__file__)` join - PyInstaller's onefile mode
extracts bundled data to a temp dir (`sys._MEIPASS`) at runtime, and
that helper is what resolves correctly in both that frozen case and
running straight from source. Writable runtime files (config/logs)
go through the separate `user_data_dir()` instead, since a onefile
build re-extracts to a fresh temp dir every launch - anything written
there is gone the moment the process exits.

## Building the installer

The `.exe` above is a bare executable - double-click and it runs, but
there's no install wizard, no Start Menu/Desktop shortcuts, and
nothing registered in Windows' "Add or Remove Programs" for a real
uninstall. `installer.iss` wraps it into an actual installer, using
[Inno Setup](https://jrsoftware.org/isinfo.php) - Windows-only, no
Linux/Mac port, so unlike `build_exe.py` this couldn't be verified by
an actual build in this environment; it's written to known-correct
Inno Setup syntax, but you'll be the first one to actually compile
it.

```
python build_exe.py
iscc installer.iss
```

(or open `installer.iss` in the Inno Setup Compiler GUI and click
Compile - same result). `build_exe.py` has to run first; the
installer script just packages whatever's already sitting in
`dist\TX Controller.exe`, it doesn't build it itself. Output lands in
`installer_output\TX Controller Setup.exe`.

`AppId` in `installer.iss` is a fixed GUID generated once for this
project - it must never change between releases, since that's what
Inno Setup uses to recognize "this is an upgrade of the same install"
rather than a separate app living alongside the old one.
