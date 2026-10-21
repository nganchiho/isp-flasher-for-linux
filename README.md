# USB ISP Flasher

A stand-in for ProgISP that runs on Linux, macOS and Windows. It works with the blue
zhifengsoft "USBHID" ISP stick (USB `03eb:c8b4`) and the 94 AVR chips from ProgISP's chip list.

## Install as an app (Linux)

```sh
./install.sh            # installs deps, udev rule, app menu entry and a `usbisp` command
./install.sh --remove   # uninstall
```

It works on Debian/Ubuntu/Kali, Fedora, Arch and openSUSE. It installs Tkinter with your package
manager and hidapi with pip if they're missing, adds the udev rule (asks for sudo once), and copies
`usbisp.py` + `chips.json` to `~/.local/share/usbisp`. Then open **USB ISP Flasher** from the app
menu, or run `usbisp` (GUI) / `usbisp write fw.hex` (CLI). Rerun it after editing `usbisp.py`.

## GUI

1. **Project:** pick a PlatformIO project folder (the one containing `platformio.ini`, e.g.
   `front_dash`). **Build** runs `pio run` and fills in the Flash path with the new
   `.pio/build/<env>/firmware.hex`; **Build & Write** also flashes it.
2. **Flash / EEPROM:** write or read a `.hex` / `.bin` directly. Write always erases first and
   verifies afterwards.
3. **Fuses:** Read first, edit, then Write (asks before writing).

PlatformIO is found on `PATH` or at `~/.platformio/penv/bin/pio` (where the VS Code extension puts it).

## Manual setup

```sh
pip install hidapi                    # Python 3.8+
python3 usbisp.py                     # opens the GUI
```

- **Linux:** allow non-root access to the stick, then replug it:
  ```sh
  sudo tee /etc/udev/rules.d/99-usbisp.rules <<'EOF'
  SUBSYSTEM=="usb", ATTR{idVendor}=="03eb", ATTR{idProduct}=="c8b4", MODE="0666"
  KERNEL=="hidraw*", ATTRS{idVendor}=="03eb", ATTRS{idProduct}=="c8b4", MODE="0666"
  EOF
  sudo udevadm control --reload && sudo udevadm trigger
  ```
  If Tkinter is missing: `sudo apt install python3-tk`.
- **macOS:** `brew install python-tk` if the GUI fails to start with "No module named _tkinter".
  No driver is needed.

## CLI

```sh
python3 usbisp.py detect                        # read signature, name the chip
python3 usbisp.py write firmware.hex            # erase + write + verify (auto-detects chip)
python3 usbisp.py -c ATmega328P write fw.hex --eeprom fw.eep
python3 usbisp.py read backup.hex
python3 usbisp.py fuses                         # read
python3 usbisp.py fuses FF D9 FF                # write low high ext (careful)
python3 usbisp.py chips                         # list supported chips
```

## PlatformIO

`pio run` writes the hex to `<project>/.pio/build/<env>/firmware.hex` (`front_dash` →
`front_dash/.pio/build/ATmega328P/firmware.hex`). If that folder only contains `idedata.json`,
the project was only indexed by VS Code, never built: press **Build** (✓) in the PlatformIO toolbar,
run `~/.platformio/penv/bin/pio run`, or use the GUI's Build button. `pio` is not on `PATH` by
default when PlatformIO came with the VS Code extension.

To make PlatformIO's **Upload** button use this flasher, put this in `platformio.ini` (`front_dash`
already has it; the path assumes the project sits next to `usbisp.py`):

```ini
upload_protocol = custom
upload_command = python3 $PROJECT_DIR/../usbisp.py write $SOURCE
```

After `./install.sh` you can use `upload_command = usbisp write $SOURCE` from any folder, provided
`~/.local/bin` is on `PATH`.

## Limits

- Tested on an ATmega328P (128-byte pages, 32 KB). The 64/256-byte page handling and the
  >64 KB address byte follow the protocol's pattern but are untested. Write always verifies,
  so a mismatch shows up as an error instead of a silently bad flash.
- Lock bits and the 8051/SPI-flash/EEPROM-chip modes of ProgISP are not implemented.
- `chips.json` is generated from ProgISP's `eng/*.xml`.
