## Download

**`robconv.exe`**: Windows 10/11, nothing to install.

- **Drop** an ABB backup folder, a zipped backup or RAPID files **on the icon**, or
- **double-click** it and choose them in the window.

The `.LS` programs and the conversion report (`robconv_report.html`) are written to a
`robconv_<name>` folder next to the input, which opens when the conversion is done.
Everything runs locally: no file leaves the computer.

## First launch: Windows SmartScreen

The executable is not code-signed, so Windows may show *"Windows protected your PC"*.
Click **More info → Run anyway**. To check that the file is the one built from this
repository, compare its SHA-256 with `robconv.exe.sha256` (built by GitHub Actions from the
tagged commit):

```powershell
(Get-FileHash robconv.exe -Algorithm SHA256).Hash
```

Python users can also install from source (`pip install .`) and run `robconv` / `robconv-gui`.
