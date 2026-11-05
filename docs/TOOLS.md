# Embedded bench guide

This guide covers setting up and using a full set of tools for embedded hardware on Linux and macOS:

| Tool | What it's for | Hardware |
|---|---|---|
| **usbisp** (this repo) | Flash AVR chips (ATmega328P etc.) and read/write their fuses | Blue zhifengsoft "USBHID" ISP stick (`03eb:c8b4`) |
| **PulseView** + **sigrok-cli** | Logic analyzer: see digital signals and decode UART, I2C, SPI, CAN and 100+ other protocols | Any sigrok-supported analyzer. The cheap "24 MHz 8-channel" ones (~$10) work fine |
| **SavvyCAN** + **can-utils** | Capture, filter, graph, reverse-engineer and replay CAN bus traffic | CANable / candleLight, PCAN-USB, Kvaser, or a GVRET board (ESP32RET, Macchina M2) |
| **tio** | Serial console: talk to a board's UART | Any USB-UART adapter (CH340, CP2102, FT232) or a dev board's built-in USB |
| **embedlab** | One menu that drives all of the above and asks you for bitrate, baud rate and pins | — |

---

## 1. Install

### Quick install (Linux & macOS)

```sh
git clone https://github.com/nganchiho/isp-flasher-for-linux.git
cd isp-flasher-for-linux
./setup.sh
```

The script asks for your password when it needs it and is safe to run again later to update. It does the following:

| | Linux (Arch, Debian/Ubuntu/Kali, Fedora, openSUSE) | macOS (Intel & Apple Silicon) |
|---|---|---|
| PulseView | distro package | sigrok nightly `.dmg` → `/Applications` (runs under Rosetta on Apple Silicon) |
| sigrok-cli | distro package + `sigrok-firmware-fx2lafw` | Homebrew + fx2lafw firmware into `~/.local/share/sigrok-firmware` |
| SavvyCAN | AUR on Arch (`yay`/`paru`), else the official AppImage → `~/.local/bin/SavvyCAN` | official `.dmg` → `/Applications` |
| can-utils | distro package | — (SocketCAN is Linux-only) |
| tio | distro package | Homebrew |
| usbisp | `./install.sh` (Tkinter, hidapi, udev rule, app-menu entry) | hidapi via pip, `usbisp` command |
| Permissions | adds you to `dialout` (Debian/Fedora) or `uucp` (Arch) for serial ports | nothing needed |

Afterwards:

1. **Log out and back in.** On Linux, your new serial group only takes effect in a new login.
2. **Replug** your USB devices so the new udev rules apply.
3. Run `embedlab status` to check that everything is detected.

If `~/.local/bin` isn't on your `PATH`, the script prints the line to add (bash, zsh or fish).

To uninstall: `./setup.sh --remove`. This removes what the script put in your home folder. System packages and apps in `/Applications` stay.

### Manual install

If you'd rather do it by hand, or the script can't handle your system:

- **PulseView / sigrok-cli:** https://sigrok.org/wiki/Downloads. Linux has distro packages or an AppImage, macOS has a `.dmg`, Windows has an installer.
- **SavvyCAN:** https://github.com/collin80/SavvyCAN/releases. Linux has an AppImage, macOS a `.dmg`, Windows a `.zip`.
- **can-utils:** `sudo apt install can-utils`, `sudo pacman -S can-utils` or `sudo dnf install can-utils`.
- **tio:** `sudo apt install tio`, `sudo pacman -S tio` or `brew install tio`.
- **usbisp:** see the main [README](../README.md).

**Windows:** install PulseView and SavvyCAN from the links above. Cheap fx2lafw logic analyzers also need the WinUSB driver, installed with [Zadig](https://zadig.akeo.ie/). `embedlab` and `setup.sh` don't run on Windows natively; use the GUIs directly, or WSL plus usbipd for the command-line tools.

---

## 2. Using embedlab

```sh
embedlab          # interactive menu
embedlab status   # what's installed and plugged in
```

At every menu you can type the option number or the value itself (`115200`). `q` goes back, and Ctrl+C stops a running capture.

```
━━ embedlab ━━
  1) AVR ISP flasher (usbisp)
  2) Logic analyzer  (PulseView / sigrok decode)
  3) CAN bus         (SavvyCAN / candump)
  4) Serial console  (UART)
  5) Hardware & setup check
```

---

## 3. Flash an AVR (ISP flasher)

**Wiring.** Connect the stick's 10-pin (or 6-pin) ISP header to the chip's MOSI, MISO, SCK, RESET, VCC and GND. On an Arduino Uno/Nano, that's the 6-pin ICSP header next to the ATmega328P.

In embedlab, open **AVR ISP flasher** and choose one of:

- **Detect chip**: reads the signature. Do this first to confirm the wiring.
- **Write flash**: erases, writes and verifies. It suggests the newest `.hex` it can find, including `.pio/build/*/firmware.hex` if you're inside a PlatformIO project.
- **Read flash**: makes a backup before you overwrite someone else's firmware.
- **Read / write fuses**: it shows the current values first and asks before writing.

> **Fuses can brick a chip.** If you turn off `SPIEN`, select an external clock that isn't fitted, or set `RSTDISBL`, the chip can no longer be ISP-programmed. Use a fuse calculator (search "AVR fuse calculator") before writing.

These are the equivalent commands without the menu:

```sh
usbisp detect
usbisp write firmware.hex
usbisp read backup.hex
usbisp fuses
```

The GUI (`usbisp` with no arguments) can also build PlatformIO projects. See the main [README](../README.md).

---

## 4. Logic analyzer (PulseView / sigrok)

### Wiring rules

- **Always connect GND** between the analyzer and the target. If you skip this, you'll capture garbage.
- Cheap 24 MHz analyzers handle **0–5 V logic only**. Never connect them to 12 V, RS-232, RS-485/CAN differential lines or mains.
- Clip one channel (D0, D1…) to each signal you want to see.

### Sample rate

Sample at **at least 4× the signal speed**, and 10× for UART. embedlab picks the rate for you:

| Signal | Typical speed | Sample rate |
|---|---|---|
| UART 115200 baud | 115 kHz | 2 MHz |
| I2C standard / fast | 100 / 400 kHz | 1 / 4 MHz |
| SPI | 1–8 MHz | 4–24 MHz (24 MHz is the max for fx2 analyzers) |

### In embedlab: Logic analyzer

- **Open PulseView**: the full GUI with your device already selected. Click **Run** to capture.
- **Live UART / I2C / SPI decode**: decoded bytes print straight to the terminal. It asks for baud rate or bus speed and channel numbers.
- **Capture N seconds to .sr**: saves a capture you can open in PulseView later or share.

No hardware yet? Say **yes** to the demo device. It generates fake signals so you can practise.

### Decoding in PulseView

1. Choose your device in the toolbar, set the sample rate and sample count, then click **Run**.
2. Click the **yellow-green decoder icon** (Add protocol decoder), e.g. *UART*.
3. Click the new decoder row's label and assign channels (RX = D0) and the baud rate.
4. Zoom with the mouse wheel. Decoded bytes appear above the waveform.

To trigger on an event, click the trigger icon next to a channel name (rising edge, falling edge and so on). The capture then starts at that event instead of immediately.

---

## 5. CAN bus (SavvyCAN / SocketCAN)

### Hardware types

| Adapter | How it shows up | embedlab option |
|---|---|---|
| CANable with **candleLight** firmware, PCAN-USB, Kvaser | `can0` network interface | **SocketCAN** |
| CANable with stock **slcan** firmware | `/dev/ttyACM0` serial port | **slcan** (runs `slcand` for you) |
| ESP32RET, Macchina M2, Due with GVRET | serial port | **GVRET** (configured inside SavvyCAN) |
| None | — | **Virtual vcan0**: fake traffic for practice |

On macOS only serial (GVRET-style) adapters work, because SocketCAN doesn't exist there.

### Bitrate

Every node on a bus uses the same bitrate. If you pick the wrong one, you'll see nothing but error frames.

| Bus | Usual bitrate |
|---|---|
| Car powertrain / OBD-II (2008+) | 500 kbps |
| Car body / comfort bus | 125 kbps (some cars use 100 or 83.3) |
| Trucks, tractors (J1939) | 250 kbps |
| Industrial (CANopen), your own projects | 125 kbps – 1 Mbps |

If you're not sure, try 500k first, then 250k, then 125k.

### Sniffing a car safely

1. Connect to the OBD-II port: **pin 6 = CAN-H, pin 14 = CAN-L, pin 4/5 = GND**.
2. Say **yes to listen-only**. The adapter then never transmits or ACKs, so it can't disturb the car.
3. The car's bus already has termination. Don't add a 120 Ω resistor. You only need termination (120 Ω at each end) on a bench bus you've built yourself.

### In SavvyCAN

1. **Connection → Open Connection Window → Add New Device Connection**.
2. Choose **QT SerialBus Devices → socketcan → can0** for SocketCAN/slcan/vcan, or **Serial Connection (GVRET)** and select the port.
3. Frames appear in the main window. These tools help with reverse engineering:
   - **Overwrite mode** (checkbox): one row per ID with live-updating bytes. Changing bytes stand out.
   - **RE Tools → Sniffer**: highlights bits as they flip. Press a button in the car and watch which ID changes.
   - **RE Tools → Graphing**: plot a byte over time to find things like RPM or speed.
   - **File → Load/Save Log** for `.csv` / candump logs. **Send Frames → Playback** replays them (turn off listen-only first, and never replay into a moving car).

The command-line equivalents are:

```sh
candump -tA -c can0                    # watch all traffic, colorised, with timestamps
candump can0,123:7FF                   # only ID 0x123
cansend can0 123#DEADBEEF              # send one frame (not in listen-only)
cangen vcan0                           # random test traffic
```

---

## 6. Serial console (UART)

1. Plug in your USB-UART adapter. It shows up as `/dev/ttyUSB0` / `/dev/ttyACM0` on Linux, or `/dev/cu.usbserial-*` on macOS.
2. Wire **TX → RX, RX → TX, GND → GND**. Match the voltage: use a 3.3 V adapter for 3.3 V boards.
3. In embedlab, choose **Serial console**, select the port and baud rate, and optionally log to a file.

To quit tio, press **Ctrl+T then Q**.

If you don't know the baud rate, the usual suspects are 115200, 9600, 57600 and 38400. Garbled characters usually mean the baud rate is wrong. Alternatively, put the logic analyzer on the TX pin and measure the narrowest pulse: baud ≈ 1 / pulse width.

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `Permission denied` on `/dev/ttyUSB0` / `ttyACM0` | Log out and back in after setup. `embedlab status` shows whether your serial group is active. |
| Logic analyzer not found | Replug it after installing. Check `sigrok-cli --scan`. On macOS, check that the fx2lafw firmware is in `~/.local/share/sigrok-firmware`. |
| ISP stick `not found` | Linux: replug after `install.sh` added the udev rule. Check `lsusb \| grep 03eb:c8b4`. |
| Detect fails or the signature reads as 00 00 00 / FF FF FF | Check the wiring (MISO/MOSI swapped is common) and that the target is powered. |
| SavvyCAN AppImage won't start | Install `libfuse2` (`libfuse2t64` on Ubuntu 24.04+). The wrapper falls back to extract-and-run without it. |
| PulseView won't open on an Apple Silicon Mac | Install Rosetta: `softwareupdate --install-rosetta`. Then right-click the app → Open the first time. |
| `RTNETLINK answers: Operation not supported` when bringing up CAN | Your adapter isn't SocketCAN. It's probably slcan or GVRET, so pick that option. |
| CAN shows only error frames | Wrong bitrate, CAN-H/CAN-L swapped, or (on a bench bus) missing 120 Ω termination. |
| Garbage on the serial console | Wrong baud rate, or TX/RX swapped, or GND not connected. |
