# USB ISP Flasher

A stand-in for ProgISP that runs on Linux, macOS and Windows. It works with the blue
zhifengsoft "USBHID" ISP stick (USB `03eb:c8b4`) and the 94 AVR chips from ProgISP's chip list.

## Full embedded bench (flasher + logic analyzer + CAN + serial)

```sh
./setup.sh      # Linux or macOS: installs usbisp, PulseView, sigrok-cli, SavvyCAN, can-utils, tio
embedlab        # one menu for all of them; asks for bitrate / baud rate / pins
```

See **[docs/TOOLS.md](docs/TOOLS.md)** for a beginner's guide to downloading and using each tool.

## Setup

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
python3 usbisp.py write fw.hex --lock 3C       # ...then set lock bits (after verify)
python3 usbisp.py verify fw.hex [--eeprom fw.eep]  # compare only, no writing
python3 usbisp.py blank                         # check flash is erased
python3 usbisp.py read backup.hex
python3 usbisp.py fuses                         # read
python3 usbisp.py fuses FF D9 FF                # write low high ext (careful)
python3 usbisp.py lock                          # read lock bits; `lock 3C` writes them
python3 usbisp.py chips                         # list supported chips
```

PlatformIO (`platformio.ini`):

```ini
upload_protocol = custom
upload_command = python3 /path/to/usbisp.py write $SOURCE
```

## Limits

- Tested on an ATmega328P (128-byte pages, 32 KB). The 64/256-byte page handling and the
  >64 KB address byte follow the protocol's pattern but are untested. Write always verifies,
  so a mismatch shows up as an error instead of a silently bad flash.
- The 8051/SPI-flash/EEPROM-chip modes of ProgISP are not implemented: their USB traffic was never
  captured, so the stick's commands for them are unknown.
- Lock-bit write is untested on hardware. Only bits 0-5 are checked on read-back.
- `chips.json` is generated from ProgISP's `eng/*.xml`.

No-hardware checks: `python test_hex.py && python test_ops.py` (the second uses a fake stick).
