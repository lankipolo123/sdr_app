# Noise Controller

Desktop control application for a multi-channel SDR module setup over
RS422 - a simplified, customer-facing rebuild of the original
`sdr_controller` project.

[![Download for Windows](https://img.shields.io/github/v/release/lankipolo123/sdr_app?label=Download%20for%20Windows&style=for-the-badge)](../../releases/latest)

## Install (Windows)

1. Click the download badge above (or go to the repo's
   [Releases](../../releases) page) and download `Noise Controller.exe`.
2. Windows will show an "Unknown Publisher" SmartScreen warning the
   first time you run it - expected, since the build isn't
   code-signed, not a sign anything's wrong. Click "More info" then
   "Run anyway".
3. That's it. It's a single portable `.exe` - no installer, no Start
   Menu entry yet. Double-click it to launch any time.

No Python, no terminal, nothing else to install. Each release also
includes `Noise Controller.exe.sha256`, a checksum you can compare
against if you want to confirm your download matches exactly what was
built.

## Development setup

```bash
pip install -r requirements.txt
python main.py
```

## Layout

```
main.py / app.py            entry point + bootstrap
components/                 reusable UI pieces (Card, PowerButton, LevelSlider,
                             ChannelCard, ConfirmDialog, custom window chrome)
pages/                       main_page.py — the one screen (MainWindow)
hooks/                       non-UI reactive logic
  use_connection.py            opens/sends on one serial port at a time
  use_channel.py                per-channel commands: finds its own port fresh
                                 per command, retries, optimistic apply-on-timeout
  use_channels.py               owns one live ChannelController per address
                                 from launch — no discovery step
  use_app.py                    top-level wiring
state/                       channel_state.py, level_map.py — data models
services/
  protocol/                    binary RS422 frame format (constants, commands,
                                 packet builder/parser)
  serial/                       transport (manager, thread)
utils/                       config_service.py, logging_service.py, app_paths.py
styles/                       theme_colors.py
build_exe.py                 PyInstaller build script
installer.iss                Inno Setup script that wraps the build into an installer
.github/workflows/           CI that builds the .exe on a real Windows runner
```

## What this app is

- **One screen.** No Dashboard / Device Control / Communication pages,
  no sidebar.
- **All 16 channels live from launch**, one card per address, no
  Scan/discovery step. Every command is sent "blind" - it finds an
  available serial port fresh, retries on no response, and applies
  the change optimistically even without acknowledgment. This is
  deliberate: two modules sharing one USB-RS422 adapter can collide
  electrically (RS422 has no DE/RE tri-state pin), so a collision is
  probabilistic, not certain - gating control behind a confirmed
  discovery response would mean sometimes waiting on something that
  never comes, when the blind command usually gets through anyway.
- **Per channel, exactly two controls:** ON/OFF buttons and a
  4-position Level slider (L0-L3), synced with each other and with
  the last confirmed (or optimistically applied) hardware state. Each
  card starts locked until tapped once, and only one card is armed at
  a time, guarding against an accidental drag/scroll firing a real
  command.
- **A separate "Query" diagnostic** (top Controls bar) looks up a
  specific address and, unlike a card's blind send, waits for and
  verifies a real confirmed response before reporting success or
  failure - useful for confirming what address a physical module is
  really configured to.
- **No Module Address anywhere in the UI.** CH00, CH01, CH02, ... map
  directly to the real protocol address (no offset); the address
  itself is never editable.
- **Mode / Frequency / Bandwidth are not customer-adjustable.** They're
  echoed back unchanged on every Power change once a real baseline
  exists; without one (the normal case, since there's no discovery
  step), Power falls back to guessed defaults
  (`services/protocol/constants.py`) rather than refusing to send -
  an accepted risk, since a wrong frequency/bandwidth is a real RF
  behavior change unlike an unconfirmed Output ON/OFF.
- **No temperature/heat monitoring** - no sensor exists on the hardware.

## What changed vs. the original `sdr_controller` repo

| Removed | Rewritten | Reused as-is |
|---|---|---|
| Multi-page nav, Scan/discovery and the +Addr manual-add dialog - removed once hardware testing showed a blind command reaches the module about as reliably as a discovered one | Command layer: every `ChannelController` finds and opens its own port fresh per command instead of relying on a connection discovery found earlier | `services/protocol/` (constants, commands, packet builder/parser) |
| Module Address field/buttons | State model: one `ChannelState` per channel instead of a single global `DeviceState` | `services/serial/` (manager, thread) |
| Mode radio buttons, Frequency widget, Bandwidth dropdown | `ChannelController` (per address) replaces `DeviceController`; no user-driven signal-settings apply | `components/card.py` |
| Dashboard/Communication pages | Config: per-channel JSON instead of a single `module_address`. TX/RX shown as a live status bar instead of a dedicated page | `hooks/use_connection.py` (one dedicated serial link per channel, not shared) |
| (Accounts/roles/login were never implemented in the original repo) | Level control: 4-position slider replacing the old Power dropdown | `utils/logging_service.py`, `styles/theme_colors.py` |

## Building it yourself

PyInstaller builds for whatever OS it runs on, so a Windows `.exe`
has to be built on a real Windows machine:

```bash
pip install -r requirements-build.txt
python build_exe.py
```

Output lands in `dist/Noise Controller.exe` - one file, no console
window, icon and `assets/` bundled inside. To also produce a proper
installer (Start Menu/Desktop shortcuts, uninstall entry) via
[Inno Setup](https://jrsoftware.org/isinfo.php):

```bash
python build_exe.py
iscc installer.iss
```

Output lands in `installer_output/Noise Controller Setup.exe`. Inno
Setup is Windows-only, so this step can't be run or verified from
Linux/Mac.

### Releasing automatically

`.github/workflows/release.yml` builds `Noise Controller.exe` on a real
Windows GitHub Actions runner and publishes it to a GitHub Release.
Two ways to trigger it:

- **Push a version tag:**
  ```bash
  git tag v1.0.0
  git push origin v1.0.0
  ```
  Bump the tag (`v1.0.1`, `v1.1.0`, ...) for each subsequent release.
- **No git access needed:** go to the **Actions** tab -> "Build and
  release Windows .exe" -> **Run workflow**, type the version
  (e.g. `v1.0.0`), and run it. Same build, same release, just
  triggered by a button instead of a tag push.
The Inno Setup installer isn't part of this workflow yet - see Known
open items below.

## Known open items

- **Guessed Mode/Frequency/Bandwidth defaults on Power, always.**
  With no discovery step, a channel's real baseline is essentially
  never populated, so Power always falls back to
  `BLIND_DEFAULT_MODE`/`FREQ_MHZ`/`BANDWIDTH_MHZ`
  (`services/protocol/constants.py`). Accepted risk, not a bug, but
  worth confirming those defaults are safe for the real modules in
  the field.
- **Channel ceiling.** `MAX_CHANNELS = 16` (`hooks/use_channels.py`)
  is a UI/practicality choice - the protocol itself supports up to
  `ADDR_MAX = 199`. Confirm 16 is still the right ceiling.
- **Installer not in CI yet.** `installer.iss` is written but
  untested on real Windows and not wired into the release workflow.
  The reference `sdr_controller` project runs Inno Setup on its CI
  runner via `choco install innosetup`, which is a viable path here
  too once someone verifies the installer manually first.
- **Not code-signed.** Windows SmartScreen will flag the `.exe` as
  from an unknown publisher until a code-signing certificate is
  bought and wired into the build (see Install section above).
- PyArmor intentionally left out for now, per request.
