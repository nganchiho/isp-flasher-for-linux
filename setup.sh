#!/usr/bin/env bash
# One-shot setup for the whole embedded bench, on Linux or macOS:
#   USB ISP flasher (usbisp) · PulseView + sigrok-cli (logic analyzers) · SavvyCAN + can-utils (CAN)
#   tio (serial console) · embedlab (menu launcher for all of the above)
#
#   ./setup.sh          install / update everything
#   ./setup.sh --remove remove what this script put in your home folder (system packages stay)
#
# Safe to rerun. Works with the stock macOS bash 3.2.
set -uo pipefail

cd "$(dirname "$0")"
REPO=$(pwd)
OS=$(uname -s)
ARCH=$(uname -m)
BIN="$HOME/.local/bin"
SHARE="$HOME/.local/share"
SAVVY_TAG=V220   # https://github.com/collin80/SavvyCAN/releases — bump both lines together
SAVVY_APPIMAGE=SavvyCAN-7c576c5-x86_64.AppImage

B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'
step() { printf '\n%s\n' "${B}${C}==>${N}${B} $*${N}"; }
ok()   { printf '%s\n' "${G}✓${N} $*"; }
warn() { printf '%s\n' "${Y}!${N} $*"; }
die()  { printf '%s\n' "${R}✗${N} $*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
FAILED=()

if [ "${1:-}" = "--remove" ]; then
  rm -f "$BIN/embedlab" "$BIN/SavvyCAN"
  rm -rf "$SHARE/savvycan" "$SHARE/applications/savvycan.desktop"
  [ "$OS" = Linux ] && [ -x ./install.sh ] && ./install.sh --remove
  [ "$OS" = Darwin ] && rm -rf "$SHARE/usbisp" "$BIN/usbisp"
  ok "Removed embedlab, usbisp and the SavvyCAN download. System packages and /Applications apps were left alone."
  exit 0
fi

mkdir -p "$BIN" "$SHARE"
have curl || die "curl is required."
[ "$OS" = Linux ] && ! have sudo && die "sudo is required (or run the package installs as root yourself, see docs/TOOLS.md)."

download() { # download url dest
  curl -fL --retry 2 --progress-bar -o "$2.part" "$1" && mv "$2.part" "$2"
}

# ------------------------------------------------------------------------------------------ Linux
linux_packages() {
  local pm pkgs p
  # hidapi comes from the distro too: Arch's python has no pip, and Debian/Ubuntu block pip --user.
  local aur=""
  if   have pacman;  then pm=pacman; pkgs="pulseview sigrok-cli sigrok-firmware-fx2lafw tk python-hidapi"; aur="can-utils tio"
  elif have apt-get; then pm=apt;    pkgs="pulseview sigrok-cli sigrok-firmware-fx2lafw can-utils tio python3-tk python3-hid"
  elif have dnf;     then pm=dnf;    pkgs="pulseview sigrok-cli sigrok-firmware-fx2lafw can-utils tio python3-tkinter python3-hidapi fuse-libs"
  elif have zypper;  then pm=zypper; pkgs="pulseview sigrok-cli sigrok-firmware-fx2lafw can-utils tio python3-tk python3-hidapi libfuse2"
  else warn "Unknown package manager. Install manually: pulseview sigrok-cli sigrok-firmware-fx2lafw can-utils tio"; return
  fi
  step "Installing packages with $pm (asks for your password)"
  [ "$pm" = apt ] && sudo apt-get update -qq
  # One at a time so a package your distro lacks doesn't block the rest.
  for p in $pkgs; do
    case $pm in
      pacman) sudo pacman -S --needed --noconfirm "$p" >/dev/null 2>&1 ;;
      apt)    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" >/dev/null 2>&1 ;;
      dnf)    sudo dnf install -y -q "$p" >/dev/null 2>&1 ;;
      zypper) sudo zypper -q install -y "$p" >/dev/null 2>&1 ;;
    esac && ok "$p" || { warn "$p — not available or failed"; FAILED+=("$p"); }
  done
  # Arch keeps can-utils and tio in the AUR.
  if [ -n "$aur" ]; then
    local h=""; have yay && h=yay; [ -z "$h" ] && have paru && h=paru
    for p in $aur; do
      if pacman -Q "$p" >/dev/null 2>&1; then ok "$p"
      elif [ -n "$h" ] && $h -S --needed --noconfirm "$p" >/dev/null 2>&1; then ok "$p (AUR)"
      else warn "$p — AUR package; install yay or paru, then: yay -S $p"; FAILED+=("$p"); fi
    done
  fi
  # AppImages need libfuse2; the name changed in Ubuntu 24.04 / Debian 13.
  if [ "$pm" = apt ]; then
    sudo apt-get install -y -qq libfuse2t64 >/dev/null 2>&1 || sudo apt-get install -y -qq libfuse2 >/dev/null 2>&1 || true
  fi
}

linux_savvycan() {
  step "SavvyCAN"
  if have SavvyCAN && [ ! -f "$SHARE/savvycan/SavvyCAN.AppImage" ]; then ok "already installed ($(command -v SavvyCAN))"; return; fi
  # Arch: prefer the AUR package if an AUR helper exists.
  if have pacman; then
    local h; for h in yay paru; do
      if have $h; then $h -S --needed --noconfirm savvycan && { ok "savvycan (AUR)"; return; }; fi
    done
    have yay || have paru && warn "AUR build failed — using the AppImage instead."
  fi
  if [ "$ARCH" != x86_64 ]; then
    warn "No SavvyCAN AppImage for $ARCH. Build it from source: https://github.com/collin80/SavvyCAN"
    FAILED+=(SavvyCAN); return
  fi
  local dir="$SHARE/savvycan"
  local url="https://github.com/collin80/SavvyCAN/releases/download/$SAVVY_TAG/$SAVVY_APPIMAGE"
  mkdir -p "$dir"
  download "$url" "$dir/SavvyCAN.AppImage" || { FAILED+=(SavvyCAN); return; }
  chmod +x "$dir/SavvyCAN.AppImage"
  # Wrapper: fall back to extract-and-run when libfuse2 isn't installed.
  cat > "$BIN/SavvyCAN" <<EOF
#!/bin/sh
ls /usr/lib*/libfuse.so.2* /usr/lib/*/libfuse.so.2* >/dev/null 2>&1 || export APPIMAGE_EXTRACT_AND_RUN=1
exec "$dir/SavvyCAN.AppImage" "\$@"
EOF
  chmod +x "$BIN/SavvyCAN"
  mkdir -p "$SHARE/applications"
  cat > "$SHARE/applications/savvycan.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=SavvyCAN
Comment=CAN bus reverse engineering and capture
Exec=$BIN/SavvyCAN
Icon=network-wired
Terminal=false
Categories=Development;Electronics;
EOF
  ok "SavvyCAN $SAVVY_TAG AppImage → $BIN/SavvyCAN"
}

linux_serial_group() {
  step "Serial port access"
  local g; for g in dialout uucp; do getent group "$g" >/dev/null && break; g=""; done
  [ -n "$g" ] || { warn "No dialout/uucp group found — skipping."; return; }
  if getent group "$g" | grep -qw "$USER"; then ok "$USER already in '$g'"
  else sudo usermod -aG "$g" "$USER" && ok "Added $USER to '$g' — log out and back in for it to apply."; fi
}

# ------------------------------------------------------------------------------------------ macOS
mac_dmg_install() { # mac_dmg_install url AppName
  local tmp mnt app
  tmp=$(mktemp -d); mnt="$tmp/mnt"; mkdir -p "$mnt"
  download "$1" "$tmp/app.dmg" || { rm -rf "$tmp"; return 1; }
  hdiutil attach -nobrowse -readonly -quiet -mountpoint "$mnt" "$tmp/app.dmg" || { rm -rf "$tmp"; return 1; }
  app=$(find "$mnt" -maxdepth 2 -name '*.app' | head -1)
  if [ -n "$app" ]; then
    rm -rf "/Applications/$2.app"
    cp -R "$app" "/Applications/$2.app" 2>/dev/null || sudo cp -R "$app" "/Applications/$2.app"
    xattr -dr com.apple.quarantine "/Applications/$2.app" 2>/dev/null || true
  fi
  hdiutil detach -quiet "$mnt"; rm -rf "$tmp"
  [ -n "$app" ]
}

mac_install() {
  have brew || die "Homebrew is required. Install it from https://brew.sh then rerun ./setup.sh"
  step "Homebrew packages"
  local p; for p in sigrok-cli tio python-tk; do
    brew list "$p" >/dev/null 2>&1 && ok "$p" || { brew install "$p" && ok "$p" || { warn "$p failed"; FAILED+=("$p"); }; }
  done

  step "fx2lafw firmware (lets sigrok-cli talk to cheap 24 MHz logic analyzers)"
  local fw="$SHARE/sigrok-firmware"
  if ls "$fw"/fx2lafw-*.fw >/dev/null 2>&1; then ok "already present"
  else
    local tmp; tmp=$(mktemp -d)
    download "https://sigrok.org/download/binary/sigrok-firmware-fx2lafw/sigrok-firmware-fx2lafw-bin-0.1.7.tar.gz" "$tmp/fw.tgz" \
      && mkdir -p "$fw" && tar -xzf "$tmp/fw.tgz" -C "$tmp" && cp "$tmp"/sigrok-firmware-fx2lafw-bin-*/*.fw "$fw/" \
      && ok "installed to $fw" || { warn "firmware download failed"; FAILED+=(fx2lafw-firmware); }
    rm -rf "$tmp"
  fi

  if [ "$ARCH" = arm64 ] && ! /usr/bin/pgrep -q oahd 2>/dev/null; then
    step "Rosetta 2 (PulseView's macOS build is Intel-only)"
    softwareupdate --install-rosetta --agree-to-license || warn "Rosetta install failed — PulseView may not start."
  fi

  step "PulseView"
  if [ -d /Applications/PulseView.app ]; then ok "already in /Applications"
  else mac_dmg_install "https://sigrok.org/download/binary/pulseview/pulseview-NIGHTLY-x86.dmg" PulseView \
         && ok "/Applications/PulseView.app" || { warn "PulseView install failed"; FAILED+=(PulseView); }
  fi

  step "SavvyCAN"
  if [ -d /Applications/SavvyCAN.app ]; then ok "already in /Applications"
  else
    local dmg=SavvyCAN_x64.dmg; [ "$ARCH" = arm64 ] && dmg=SavvyCAN_arm64.dmg
    mac_dmg_install "https://github.com/collin80/SavvyCAN/releases/download/$SAVVY_TAG/$dmg" SavvyCAN \
      && ok "/Applications/SavvyCAN.app" || { warn "SavvyCAN install failed"; FAILED+=(SavvyCAN); }
  fi

  step "USB ISP flasher (usbisp)"
  if ! python3 -c 'import hid; hid.device' 2>/dev/null; then
    python3 -m pip install --user -q hidapi 2>/dev/null || python3 -m pip install --user -q --break-system-packages hidapi \
      || { warn "pip install hidapi failed"; FAILED+=(hidapi); }
  fi
  mkdir -p "$SHARE/usbisp"; cp usbisp.py chips.json "$SHARE/usbisp/"
  printf '#!/bin/sh\nexec python3 "%s/usbisp.py" "$@"\n' "$SHARE/usbisp" > "$BIN/usbisp"; chmod +x "$BIN/usbisp"
  ok "usbisp → $BIN/usbisp (no driver needed on macOS)"
}

# ------------------------------------------------------------------------------------------ main
echo "${B}Embedded bench setup${N} — $OS/$ARCH"
case $OS in
  Linux)
    linux_packages
    linux_savvycan
    linux_serial_group
    step "USB ISP flasher (usbisp: Tkinter, hidapi, udev rule, app menu entry)"
    ./install.sh || { warn "install.sh failed"; FAILED+=(usbisp); }
    ;;
  Darwin) mac_install ;;
  *) die "Unsupported OS: $OS (Windows: see docs/TOOLS.md)" ;;
esac

step "embedlab launcher"
cp "$REPO/embedlab" "$BIN/embedlab" && chmod +x "$BIN/embedlab" && ok "$BIN/embedlab"

echo
case ":$PATH:" in *":$BIN:"*) ;; *)
  warn "$BIN is not on your PATH. Add it:"
  echo "    bash/zsh:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.\${SHELL##*/}rc"
  echo "    fish:      fish_add_path ~/.local/bin" ;;
esac
if [ ${#FAILED[@]} -gt 0 ]; then
  warn "Finished with problems: ${FAILED[*]}  (see docs/TOOLS.md → Troubleshooting)"
else
  ok "All done."
fi
echo "Run ${B}embedlab${N} to start, or ${B}embedlab status${N} to check your hardware."
[ "$OS" = Linux ] && echo "Replug any USB devices so the new udev rules apply."
exit 0
