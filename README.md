# SDR Customer Control (simplified)

Desktop control application for a multi-channel SDR module setup over
RS422 - a simplified, customer-facing rebuild of the original
`sdr_controller` project.

[![Download for Windows](https://img.shields.io/github/v/release/lankipolo123/sdr_app?label=Download%20for%20Windows&style=for-the-badge)](../../releases/latest)

## Install (Windows)

Two ways to get it:

- **Installer** (recommended): run `TX Controller Setup.exe`
  (built via `installer.iss` - see "Building it yourself" below) for
  a real install wizard with a Start Menu entry and uninstaller.
- **Portable zip**: click the download badge above (or go to the repo's
  [Releases](../../releases) page), download `TX Controller.zip`,
  and extract it anywhere. Launch `TX Controller.exe` from inside
  the extracted folder - no installer, no Start Menu entry, but
  nothing to install either.

Either way, Windows will show an "Unknown Publisher" SmartScreen
warning the first time you run it - expected, since the build isn't
code-signed, not a sign anything's wrong. Click "More info" then "Run
anyway".

No Python, no terminal, nothing else to install. Each release also
includes `TX Controller.zip.sha256`, a checksum you can compare
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
  the last confirmed (or optimistically applied) hardware state. The
  ON/OFF buttons are always live; the slider stays locked until the
  channel is actually powered on, guarding against an accidental
  drag/scroll firing a real level change while the channel is off.
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

`build_exe.py` first runs `build_encrypt.py`, which AES-encrypts the
app's own source (`app.py`, `components/`, `hooks/`, `pages/`,
`services/`, `state/`, `styles/`, `utils/`) into `app_encrypted.pyz` -
third-party packages (PySide6) and stdlib aren't touched, just this
repo's own code. PyInstaller then bundles that archive
instead of plain `.py`/`.pyc` files; `crypto_loader.py` decrypts it in
memory at launch (only when frozen - `python main.py` from source
runs the plain files directly, unaffected). `app_encrypted.pyz` is
gitignored and regenerated on every build, not something to commit.

Output lands in `dist/TX Controller/` - a folder build (`--onedir`,
so launch is fast - no self-extraction on every start like
`--onefile` would need), with `TX Controller.exe`, its icon, and
`assets/` all alongside each other.

`build_exe.py` doesn't pass PyInstaller its options on the command
line - it hands it `tx_controller.spec` instead, which is what
actually calls `Analysis()`/`EXE()`/`COLLECT()` (`pyi-makespec` would
normally generate this file fresh from CLI flags each build, but a
checked-in one is what lets `prune_qt_extras()` below reach in and
drop individual files that no CLI flag can target).

#### Shrinking the build further

Two things `build_exe.py` does beyond a plain PyInstaller build,
both of which only matter/take effect on Windows:

- **`prune_qt_extras()`** (in `build_exe.py`, applied from
  `tx_controller.spec`) deletes files PyInstaller's PySide6 hooks
  collect unconditionally but this app never uses: the ANGLE/
  software-OpenGL DLLs (`libEGL.dll`, `libGLESv2.dll`,
  `d3dcompiler_*.dll`, `opengl32sw.dll` - pulled in for QtQuick/QML
  apps, irrelevant to this Fusion-styled QWidgets app, and usually
  the single largest chunk of a PySide6 build), ICU DLLs if present,
  a handful of unused Qt plugin folders (`iconengines`,
  `platforminputcontexts`, `platformthemes`, `generic`, `styles` -
  see the comment above `_PRUNE_PLUGIN_DIRS` for why each one is
  safe to drop), and every Qt translation file (the app never loads
  a `QTranslator`, so `qtbase_*.qm` for 50-odd languages was dead
  weight). It prints how many files and MiB it dropped on every
  build. Set `PRUNE_QT_EXTRAS=0` before running `build_exe.py` to
  turn this off and get PyInstaller's untouched default collection -
  useful if something in the built app misbehaves and you want to
  rule this out first.
- **UPX** (optional, not installed by `requirements-build.txt`)
  compresses the executable and DLLs PyInstaller collects, on top of
  the pruning above. Grab a Windows build from
  [github.com/upx/upx/releases](https://github.com/upx/upx/releases)
  (a `upx-<version>-win64.zip` - just an `upx.exe`, nothing to
  install), unzip it anywhere, then point `build_exe.py` at it:
  ```bash
  set UPX_DIR=C:\path\to\upx-4.2.4-win64
  python build_exe.py
  ```
  (`$env:UPX_DIR = "..."` in PowerShell, `export UPX_DIR=...` in a
  bash-like shell). Leave it unset and UPX is skipped entirely - it's
  a real trade-off, not a free win: it noticeably slows down (a few
  seconds added to) every launch since each DLL has to decompress
  into memory first, and compressed executables are a pattern some
  antivirus/SmartScreen heuristics flag on sight, which this
  already-unsigned build can't afford more of. `UPX_EXCLUDE` in
  `build_exe.py` leaves `qwindows.dll` and the Python/MSVC runtime
  DLLs uncompressed regardless, since UPX has a history of corrupting
  exactly those and turning it into a silent "app won't start" with
  no error dialog. The GitHub Actions release workflow installs a
  pinned UPX version and enables it automatically, so this is only
  something to set up for a local build.

**After building with either of these on**, actually launch
`dist/TX Controller/TX Controller.exe` and check the basics before
trusting the build: the frameless/translucent main window and splash
screen render normally (no black/blank window - the main risk from
the ANGLE/plugin pruning above, since this app uses
`WA_TranslucentBackground`), the channel cards' dropdowns/checkboxes/
spin-box arrows still show their icons, and log lines still append.
None of this can be verified from Linux/Mac - PyInstaller only builds
for the OS it runs on.

To also produce a proper installer (Start Menu/Desktop shortcuts,
uninstall entry) via [Inno Setup](https://jrsoftware.org/isinfo.php):

```bash
python build_exe.py
iscc installer.iss
```

Output lands in `installer_output/TX Controller Setup.exe`. Inno
Setup is Windows-only, so this step can't be run or verified from
Linux/Mac.

### Releasing automatically

`.github/workflows/release.yml` builds `TX Controller.exe` on a real
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
- **Source protection is AES encryption of the shipped bytecode
  (`crypto_loader.py`/`build_encrypt.py`), not real obfuscation.**
  PyArmor was considered and intentionally skipped - its free tier's
  terms prohibit commercial use, and this is a real commercial build.
  The AES key ships inside the binary itself (has to, for the app to
  decrypt its own code at launch), so this stops casual inspection of
  the shipped `.exe`, not a determined reverse-engineering effort.
