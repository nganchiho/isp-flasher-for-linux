#!/bin/sh
# Install USB ISP Flasher as a desktop app for the current user (any Linux distro).
#   ./install.sh            install / update
#   ./install.sh --remove   uninstall
set -e
APP="$HOME/.local/share/usbisp"
BIN="$HOME/.local/bin/usbisp"
DESKTOP="$HOME/.local/share/applications/usbisp.desktop"
RULE=/etc/udev/rules.d/99-usbisp.rules

if [ "$1" = "--remove" ]; then
    rm -rf "$APP" "$BIN" "$DESKTOP"
    echo "Removed. (The udev rule $RULE is left in place; delete it with sudo if unwanted.)"
    exit 0
fi

cd "$(dirname "$0")"

# Python dependencies: Tkinter and hidapi
if ! python3 -c 'import tkinter' 2>/dev/null; then
    echo "Tkinter missing, installing it…"
    if   command -v apt-get >/dev/null; then sudo apt-get install -y python3-tk
    elif command -v dnf     >/dev/null; then sudo dnf install -y python3-tkinter
    elif command -v pacman  >/dev/null; then sudo pacman -S --needed --noconfirm tk
    elif command -v zypper  >/dev/null; then sudo zypper install -y python3-tk
    else echo "Install Tkinter for python3 with your package manager, then rerun."; exit 1
    fi
fi
if ! python3 -c 'import hid; hid.device' 2>/dev/null; then
    echo "hidapi missing, installing it with pip…"
    python3 -m pip install --user hidapi 2>/dev/null ||
        python3 -m pip install --user --break-system-packages hidapi
fi

# Access to the stick without root
if [ ! -f "$RULE" ]; then
    echo "Installing udev rule (needs sudo)…"
    sudo tee "$RULE" >/dev/null <<'RULES'
SUBSYSTEM=="usb", ATTR{idVendor}=="03eb", ATTR{idProduct}=="c8b4", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="03eb", ATTRS{idProduct}=="c8b4", MODE="0666"
RULES
    sudo udevadm control --reload && sudo udevadm trigger
    echo "Replug the stick."
fi

mkdir -p "$APP" "$(dirname "$BIN")" "$(dirname "$DESKTOP")"
cp usbisp.py chips.json "$APP/"
cat > "$BIN" <<WRAP
#!/bin/sh
exec python3 "$APP/usbisp.py" "\$@"
WRAP
chmod +x "$BIN"
cat > "$DESKTOP" <<DESK
[Desktop Entry]
Type=Application
Name=USB ISP Flasher
Comment=Build PlatformIO projects and flash AVR chips with the USBHID ISP stick
Exec=$BIN %f
Icon=media-flash
Terminal=false
Categories=Development;Electronics;
MimeType=text/x-hex;application/x-hex;
DESK
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true

echo "Installed. Open \"USB ISP Flasher\" from your app menu, or run: usbisp"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "(Add ~/.local/bin to PATH to use 'usbisp' in a terminal.)";; esac
