# SDR Customer Control (simplified)

A new, simplified app built from the original `sdr_controller` project.
Reuses the parts of that codebase that were already solid (protocol
layer, serial I/O, the `Card` widget, the reactive-sync `blockSignals`
pattern) and drops or rewrites the rest for a customer-facing,
single-page, multi-channel control surface.

## What this app is

- **One screen.** No Dashboard / Device Control / Communication pages,
  no sidebar.
- **Multiple channels at once** - one card per address, all 16 slots
  live from launch. There is no Scan/discovery step: every card already
  has a real `ChannelController` from startup, and every command it
  sends is "blind" - it finds an available serial port fresh, retries
  on no response, and applies the change optimistically even if
  nothing ever acknowledges it. This is deliberate: two modules
  sharing one USB-RS422 adapter can collide electrically (RS422 has no
  DE/RE tri-state pin), so a collision is probabilistic, not certain -
  gating control behind a confirmed discovery response would mean
  sometimes waiting on something that never comes, when the blind
  command usually gets through anyway.
- **Per channel, exactly two controls:** explicit ON/OFF buttons and a
  4-position Level slider (L0-L3), kept in bidirectional sync with
  each other and with the last confirmed (or optimistically applied)
  hardware state. Each card starts locked - the slider and ON/OFF
  buttons are disabled until the card is tapped once, and only one
  card is armed at a time (tapping a different card locks the
  previous one back down), guarding against an accidental drag/scroll
  firing a real command.
- **A separate "Query" diagnostic** (top Controls bar): type in an
  address and, unlike a card's blind send, it brute-force finds the
  port and waits for/verifies a real confirmed response (retrying up
  to `QUERY_MAX_ATTEMPTS` times) before reporting success or failure.
  Useful for confirming what address a physical module is really
  configured to before relying on that address's card.
- **No Module Address anywhere in the UI.** The customer sees CH00,
  CH01, CH02, ... where the display number is the real protocol
  address (no offset); the address itself is never editable.
- **Mode / Frequency / Bandwidth are not customer-adjustable.** A
  channel's current Mode/Frequency/Bandwidth is echoed back unchanged
  on every Power change once a real baseline exists (from a confirmed
  Status Query response). Since there's no discovery step, that
  baseline usually doesn't exist yet, so Power falls back to guessed
  defaults (`BLIND_DEFAULT_MODE`/`FREQ_MHZ`/`BANDWIDTH_MHZ` in
  `services/protocol/constants.py`) rather than refusing to send. This
  is an accepted risk - a wrong frequency/bandwidth is a real RF
  behavior change, unlike an unconfirmed Output ON/OFF - but it keeps
  Power usable on a channel with no baseline yet.
- **No temperature/heat monitoring** - no sensor exists on the hardware.

## What changed vs. the original `sdr_controller` repo

| Removed | Rewritten | Reused as-is |
|---|---|---|
| Multi-page nav (`main_window.py`'s `QStackedWidget`, `sidebar.py`); Scan/discovery and the +Addr manual-ask dialog (`DiscoveryController`, `hooks/use_discovery.py`, `ManualAddDialog`) - removed once hardware testing showed a blind command (no prior confirmed response required) reaches the module about as reliably as a discovered one | Command layer: every `ChannelController` now finds and opens its own port fresh per command instead of relying on a connection a discovery step found earlier | `services/protocol/` (constants, commands, packet builder/parser) |
| Module Address field/buttons (`device_control_page.py`) | State model: one `ChannelState` per channel instead of a single global `DeviceState` | `services/serial/` (manager, thread) |
| Mode radio buttons, Frequency widget, Bandwidth dropdown | Command layer: `ChannelController` (per address) replaces `DeviceController`; no user-driven `apply_signal_settings()`. A protocol-level `set_address()`/`query_address()` still exists in `services/protocol/commands.py` but has no caller now that discovery is gone - kept as complete protocol coverage. | `components/card.py` |
| `dashboard_page.py`, `communication_page.py` | Config: per-channel JSON (`last_level`) instead of a single `module_address`. TX/RX now shown as a live status bar at the bottom of the window instead of a dedicated page. | `hooks/use_connection.py` (one dedicated serial link per discovered channel, not shared) |
| (Accounts/roles/login/action-log were never implemented in the original repo) | Level control: 4-position slider replacing the old Power dropdown, mapped in `state/level_map.py` | `utils/logging_service.py`, `styles/theme_colors.py` |

## Open items before this is production-ready

1. **Guessed Mode/Frequency/Bandwidth defaults on Power, always.**
   Nothing calls `read_status()` automatically anymore (no discovery
   step left to trigger it), so a channel's real Mode/Frequency/
   Bandwidth baseline is essentially never populated in practice -
   every Power command falls back to `BLIND_DEFAULT_MODE`/`FREQ_MHZ`/
   `BANDWIDTH_MHZ` (`services/protocol/constants.py`). Accepted risk,
   not a bug, but worth confirming those defaults are actually safe
   for the real modules in the field.
2. **Channel ceiling.** `MAX_CHANNELS = 16` in `hooks/use_channels.py`
   is a UI/practicality choice (how many channel cards/controllers get
   built at launch) - the protocol itself
   (`services/protocol/constants.py`, `ADDR_MAX = 199`) supports far
   more. Confirm 16 is still the right ceiling.
3. **Visual style.** Uses a custom-styled frameless window (own title
   bar, rounded corners) and the `Card` look throughout.
4. **Packaging.** PyInstaller `.exe` build is set up (`build_exe.py`,
   see "Building a standalone .exe" below). GitHub Actions now builds
   it on a real Windows runner and publishes it to GitHub Releases on
   every version tag (see "Releasing a build" below). The Inno Setup
   installer script (`installer.iss`, see "Building the installer"
   below) is written but still untested on a real Windows machine, and
   not yet wired into the release workflow - Inno Setup has no
   Linux/Mac port, so it can't be built or verified from this repo's
   own dev tooling. PyArmor intentionally left out for now per
   request.

## File structure (React-style mapping)

If you're used to a React project, here's how this maps:

| React concept | Folder here | What's in it |
|---|---|---|
| `components/` | `components/` | Reusable UI pieces: `Card`, `PowerButton`, `LevelSlider`, `ChannelCard`, `ConfirmDialog`, `TitleBar`/`ResizableContainer` (custom window chrome) |
| `pages/` | `pages/` | The one screen: `main_page.py` (`MainWindow`) |
| `hooks/` | `hooks/` | Non-UI reactive logic: `use_connection.py` (opens/sends on one port at a time), `use_channel.py` (per-channel commands - finds its own port fresh per command, retries, optimistic apply-on-timeout), `use_channels.py` (owns one live `ChannelController` per address from launch, no discovery step), `use_app.py` (top-level wiring) |
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
devices found" up front. `logs/sdr_controller.log` still records every
send/timeout/rejection even though the UI doesn't show a warning
banner for them.

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
`AppController`/`MainWindow` are being built - it's a static loading
screen, not animated, since both happen synchronously before the Qt
event loop starts.

Any code that reads a bundled asset (icons) needs
`utils/app_paths.py`'s `resource_path()`, not a plain
`os.path.dirname(__file__)` join - PyInstaller's onefile mode
extracts bundled data to a temp dir (`sys._MEIPASS`) at runtime, and
that helper resolves correctly both in that frozen case and when
running straight from source. Writable runtime files (config/logs) go
through the separate `user_data_dir()` instead, since a onefile build
re-extracts to a fresh temp dir every launch - anything written there
is gone the moment the process exits.

## Building the installer

The `.exe` above is a bare executable - double-click and it runs, but
there's no install wizard, no Start Menu/Desktop shortcuts, and
nothing registered in Windows' "Add or Remove Programs" for a real
uninstall. `installer.iss` wraps it into an actual installer using
[Inno Setup](https://jrsoftware.org/isinfo.php) - Windows-only, no
Linux/Mac port, so it hasn't been build-verified yet; it's written to
known-correct Inno Setup syntax but still needs a first real compile.

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

## Releasing a build

`.github/workflows/release.yml` builds the `.exe` on a real
`windows-latest` GitHub Actions runner and publishes it to a GitHub
Release automatically - nothing to upload by hand. It only fires on a
pushed version tag, not on every commit to `main`:

```
git tag v1.0.0
git push origin v1.0.0
```

That creates a release named after the tag with `TX Controller.exe`
and a `TX Controller.exe.sha256` checksum file attached. Bump the tag
(`v1.0.1`, `v1.1.0`, ...) for each subsequent release - re-pushing the
same tag doesn't retrigger a clean run.

**About the Windows SmartScreen warning:** this `.exe` isn't
code-signed, so Windows shows an "Unknown Publisher" warning the first
time anyone runs it ("More info" -> "Run anyway" to proceed - this is
expected, not a sign of a problem). Removing that warning requires a
paid code-signing certificate (a standard one still needs enough
installs to build reputation with SmartScreen before the warning
stops; only an EV certificate suppresses it immediately, and those
cost more and require business identity verification) - a cost/process
decision for whoever owns this project, not something the build itself
can route around. The checksum file lets anyone confirm their download
matches exactly what this workflow built, and since the source is
public, anyone who doesn't want to trust the binary can build it
themselves with `build_exe.py`.

The Inno Setup installer (`installer.iss`) isn't part of this workflow
yet - only add it to the release pipeline once someone has run `iscc
installer.iss` on real Windows and confirmed it produces a working
installer.
