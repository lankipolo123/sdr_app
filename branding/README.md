# branding/

Drop a custom `icon.png` here (next to the installed app - see
`branding_icon_path()` in `utils/app_paths.py`), or use the in-app
"Change Logo…" button (top-right of the title bar), to override the
app/window/taskbar icon. Checked at startup and applied immediately by
Change Logo; no file here, no effect - the app falls back to its
built-in default icon (`assets/icons/app_icon.png`).

In dev, "next to the app" means this folder, at the repo root. In a
packaged `--onedir` install it means `branding/` next to
`TX Controller.exe` - the per-user install directory (see
`installer.iss`'s `PrivilegesRequired=lowest`) is writable without
elevation, so this works post-install too.

This overrides the *running* app's icon only - not the packaged
`.exe` file's own icon as shown in Windows Explorer, or the
installer/uninstaller icon. Those are baked in at build time
(`build_exe.py` / `installer.iss`'s `SetupIconFile`) and need a
rebuild to change.

`icon.png` itself is never committed here - same reasoning as
`dll/Transit.dll`: a portable, per-install override, not something to
ship a default value for.
