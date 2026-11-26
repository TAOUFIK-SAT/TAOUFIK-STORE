#!/bin/sh
# ============================================================================
#  TAOUFIK STORE (توفيق ستور) + FEED RETROARCH INSTALLER - Enigma2
#  Compatible with OpenATV, OpenPLi, Pure2, Egami, OpenBH, VTi & DreamOS
# ============================================================================

PLUGIN_FOLDER="TFKSatPanel"
BASE_URL="${1:-${TFK_BASE_URL:-https://ais-pre-mzwtesxkumeoh5jjgcgyne-403742694107.europe-west3.run.app/tfk_sat_pro_panel}}"
RETROARCH_FEED_URL="${TFK_RETROARCH_FEED_URL:-}"
TMP_DIR="/tmp/tfk_store_install"
FONT_URL="https://github.com/google/fonts/raw/main/ofl/cairo/static/Cairo-Bold.ttf"

echo "=================================================="
echo "  TAOUFIK STORE + FEED RETROARCH INSTALLER"
echo "=================================================="

# ----------------------------------------------------------------------------
#  Download helper (supports wget & curl with SSL fallback)
# ----------------------------------------------------------------------------
download_file() {
    URL="$1"
    OUT="$2"
    if command -v wget >/dev/null 2>&1; then
        wget --no-check-certificate -q -T 20 -O "$OUT" "$URL" 2>/dev/null && [ -s "$OUT" ] && return 0
        wget -q -T 20 -O "$OUT" "$URL" 2>/dev/null && [ -s "$OUT" ] && return 0
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -skL --connect-timeout 20 -o "$OUT" "$URL" 2>/dev/null && [ -s "$OUT" ] && return 0
    fi
    return 1
}

# ----------------------------------------------------------------------------
#  FEED RETROARCH INSTALLER (opkg feeds + RetroArch + Libretro Cores + uinput)
# ----------------------------------------------------------------------------
install_retroarch_feed() {
    echo "--------------------------------------------------"
    echo "  [FEED RETROARCH INSTALLER]"
    echo "--------------------------------------------------"

    if ! command -v opkg >/dev/null 2>&1; then
        echo "[WARN] opkg package manager not found; skipping feed install."
        return 0
    fi

    ARCH="$(uname -m 2>/dev/null || echo unknown)"
    echo "[*] System architecture: ${ARCH}"

    if [ -n "$RETROARCH_FEED_URL" ]; then
        echo "[*] Registering custom RetroArch feed: ${RETROARCH_FEED_URL}"
        mkdir -p /etc/opkg 2>/dev/null
        echo "src/gz tfk-retroarch ${RETROARCH_FEED_URL}" > /etc/opkg/tfk-retroarch-feed.conf
    fi

    echo "[*] Updating opkg package feeds..."
    opkg update >/tmp/tfk_opkg_update.log 2>&1 || true

    # Install kernel joystick & uinput modules if available
    for kmod in kernel-module-uinput kernel-module-joydev kernel-module-evdev; do
        if opkg list "$kmod" 2>/dev/null | grep -q "^${kmod} "; then
            opkg install "$kmod" >/dev/null 2>&1 || true
        fi
    done

    # Discover & install RetroArch / RetroGaming packages from feeds
    RA_AVAIL="$(opkg list 2>/dev/null | awk '{print $1}')"
    for pkg in \
        retroarch \
        enigma2-plugin-extensions-retroarch \
        enigma2-plugin-extensions-retrogaming \
        retroarch-assets \
        retroarch-joypad-autoconfig \
        libsdl2-2.0-0
    do
        if echo "$RA_AVAIL" | grep -qx "$pkg"; then
            echo "[*] Installing feed package: ${pkg}..."
            opkg install "$pkg" || true
        fi
    done

    # Discover & install Neo Geo / Arcade / MAME libretro cores from feeds
    CORE_LIST="$(echo "$RA_AVAIL" | grep -E '^(libretro-|.*-libretro)' | grep -E 'fbneo|fbalpha|mame2003|mame2000|gngeo|neogeo' | head -n 12)"
    if [ -n "$CORE_LIST" ]; then
        for core_pkg in $CORE_LIST; do
            echo "[*] Installing libretro core: ${core_pkg}..."
            opkg install "$core_pkg" || true
        done
    else
        for core_pkg in \
            libretro-fbneo \
            libretro-fbalpha2012-neogeo \
            libretro-mame2003-plus \
            libretro-mame2003 \
            libretro-mame2000 \
            libretro-gngeo
        do
            if echo "$RA_AVAIL" | grep -qx "$core_pkg"; then
                echo "[*] Installing libretro core: ${core_pkg}..."
                opkg install "$core_pkg" || true
            fi
        done
    fi

    # Prepare BIOS & Save directories if HDD is mounted
    if grep -qs ' /media/hdd ' /proc/mounts 2>/dev/null; then
        mkdir -p /media/hdd/retroarch/bios /media/hdd/retroarch/saves /media/hdd/retroarch/cores 2>/dev/null || true
    fi

    if command -v retroarch >/dev/null 2>&1 || [ -x /usr/bin/retroarch ] || [ -x /usr/local/bin/retroarch ]; then
        echo "[OK] RetroArch binary detected and ready."
    else
        echo "[WARN] RetroArch binary was not found in current image feeds."
        echo "       If your image uses an external feed, export TFK_RETROARCH_FEED_URL=<url> and re-run."
    fi
}

# Allow running only the Feed RetroArch Installer when RETROARCH_FEED_ONLY=1
if [ "${RETROARCH_FEED_ONLY:-0}" = "1" ]; then
    install_retroarch_feed
    exit 0
fi

# 1. Detect Enigma2 Extensions directory
if [ -d "/usr/lib/enigma2/python/Plugins/Extensions" ]; then
    EXT_DIR="/usr/lib/enigma2/python/Plugins/Extensions"
elif [ -d "/usr/lib64/enigma2/python/Plugins/Extensions" ]; then
    EXT_DIR="/usr/lib64/enigma2/python/Plugins/Extensions"
else
    echo "[ERROR] Enigma2 Plugins/Extensions directory not found!"
    exit 1
fi

PLUGIN_DIR="${EXT_DIR}/${PLUGIN_FOLDER}"
echo "[*] Target path: ${PLUGIN_DIR}"

# Remove legacy folder name if it exists to avoid duplicate entries
if [ -d "${EXT_DIR}/TFKSatProPanel" ] && [ "${PLUGIN_FOLDER}" != "TFKSatProPanel" ]; then
    echo "[*] Removing legacy TFKSatProPanel folder..."
    rm -rf "${EXT_DIR}/TFKSatProPanel"
fi

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

# 2. Fetch plugin.py & plugin.png (local folder first, otherwise remote URL)
echo "[*] Preparing TAOUFIK STORE files..."
if [ -n "$SCRIPT_DIR" ] && [ -f "${SCRIPT_DIR}/plugin.py" ]; then
    cp -f "${SCRIPT_DIR}/plugin.py" "${TMP_DIR}/plugin.py"
else
    if ! download_file "${BASE_URL}/plugin.py" "${TMP_DIR}/plugin.py"; then
        echo "[ERROR] Failed to download plugin.py from ${BASE_URL}/plugin.py"
        rm -rf "$TMP_DIR"
        exit 1
    fi
fi

# Verify downloaded plugin.py is genuine Python plugin code
if ! grep -q "def Plugins" "${TMP_DIR}/plugin.py" 2>/dev/null; then
    echo "[ERROR] Downloaded plugin.py appears invalid or incomplete."
    rm -rf "$TMP_DIR"
    exit 1
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "${SCRIPT_DIR}/plugin.png" ]; then
    cp -f "${SCRIPT_DIR}/plugin.png" "${TMP_DIR}/plugin.png"
else
    download_file "${BASE_URL}/plugin.png" "${TMP_DIR}/plugin.png" || true
fi

# 3. Create plugin structure & copy files
mkdir -p "${PLUGIN_DIR}" \
         "${PLUGIN_DIR}/fonts" \
         "${PLUGIN_DIR}/icons" \
         "${PLUGIN_DIR}/data" \
         "${PLUGIN_DIR}/cores" \
         "${PLUGIN_DIR}/roms/neogeo" \
         "${PLUGIN_DIR}/roms/arcade"

cp -f "${TMP_DIR}/plugin.py" "${PLUGIN_DIR}/plugin.py"
chmod 644 "${PLUGIN_DIR}/plugin.py"

if [ -s "${TMP_DIR}/plugin.png" ]; then
    cp -f "${TMP_DIR}/plugin.png" "${PLUGIN_DIR}/plugin.png"
    chmod 644 "${PLUGIN_DIR}/plugin.png"
fi

# Create __init__.py if missing
[ ! -f "${PLUGIN_DIR}/__init__.py" ] && : > "${PLUGIN_DIR}/__init__.py"

# 4. Optional Arabic Cairo-Bold font (non-fatal)
if [ ! -s "${PLUGIN_DIR}/fonts/Cairo-Bold.ttf" ]; then
    echo "[*] Downloading Arabic UI font (Cairo-Bold.ttf)..."
    download_file "$FONT_URL" "${PLUGIN_DIR}/fonts/Cairo-Bold.ttf" || rm -f "${PLUGIN_DIR}/fonts/Cairo-Bold.ttf"
fi

# 5. Run FEED RETROARCH INSTALLER unless skipped
if [ "${SKIP_RETROARCH_FEED:-0}" != "1" ]; then
    install_retroarch_feed
fi

# 6. Enable /dev/uinput for Virtual Remote Gamepad
echo "[*] Checking virtual gamepad kernel support (uinput)..."
modprobe uinput 2>/dev/null || true
if [ -e "/dev/uinput" ]; then
    chmod 666 /dev/uinput 2>/dev/null || true
    echo "[OK] /dev/uinput is ready."
else
    echo "[WARN] /dev/uinput not active yet (keyboard bridge mode still works)."
fi

# 7. Compile & verify Python syntax on the box
if command -v python3 >/dev/null 2>&1; then
    python3 -m py_compile "${PLUGIN_DIR}/plugin.py" || {
        echo "[ERROR] Python 3 syntax check failed!"
        rm -rf "$TMP_DIR"
        exit 1
    }
    python3 -c "import sys; sys.path.insert(0, '${PLUGIN_DIR}'); import plugin; plugin.ensure_plugin_icon()" 2>/dev/null || true
elif command -v python >/dev/null 2>&1; then
    python -m py_compile "${PLUGIN_DIR}/plugin.py" || {
        echo "[ERROR] Python syntax check failed!"
        rm -rf "$TMP_DIR"
        exit 1
    }
fi

rm -rf "$TMP_DIR"
sync

echo "[OK] TAOUFIK STORE + FEED RETROARCH installed successfully!"

# 8. Restart Enigma2 GUI cleanly unless skipped
if [ "${TFK_NO_RESTART:-0}" != "1" ]; then
    echo "[*] Restarting Enigma2 GUI..."
    sleep 2
    if command -v wget >/dev/null 2>&1 && wget -qO- "http://127.0.0.1/web/powerstate?newstate=3" >/dev/null 2>&1; then
        :
    elif command -v curl >/dev/null 2>&1 && curl -sf "http://127.0.0.1/web/powerstate?newstate=3" >/dev/null 2>&1; then
        :
    elif command -v init >/dev/null 2>&1; then
        init 4 2>/dev/null || true
        sleep 2
        init 3 2>/dev/null || true
    else
        killall -9 enigma2 2>/dev/null || true
    fi
fi

exit 0
