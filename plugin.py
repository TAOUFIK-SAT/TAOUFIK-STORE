# -*- coding: utf-8 -*-
# ============================================================================
#  توفيق ستور TAOUFIK STORE  +  VIRTUAL REMOTE GAMEPAD & JOYSTICK ENGINE
#  نسخة احترافية مُحسّنة:
#   - جسر الريموت كعصا تحكم حقيقية (Virtual Gamepad /dev/uinput EV_ABS + BTN)
#   - دعم الأوضاع الثلاثة: عصا تحكم (Gamepad) / لوحة مفاتيح (Kbd) / هجين (Hybrid)
#   - خدمة خلفية لتشغيل الريموت كعصا تحكم على مستوى النظام + شاشة اختبار فوري
#   - إصلاح خريطة الأزرار، معالجة إغلاق RetroArch، توافق Python 3، وأنظمة متعددة
# ============================================================================
import errno
import fcntl
import glob
import json
import math
import os
import re
import select
import shlex
import shutil
import signal
import socket
import struct
import threading
import time
import zlib

from enigma import addFont, eConsoleAppContainer, eRCInput, eTimer, getDesktop
from skin import parseColor
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.Console import Console
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Tools.LoadPixmap import LoadPixmap

try:
    from Screens.Standby import TryQuitMainloop
except Exception:
    TryQuitMainloop = None

# ============================================================================
#  المسارات والإعدادات العامة
# ============================================================================
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
EXTERNAL_DATA_FILE = "/etc/enigma2/pro_panel_items.json"
LOCAL_DATA_FILE = os.path.join(PLUGIN_DIR, "data", "items.json")
FAVS_FILE = "/etc/enigma2/pro_panel_favs.json"
SETTINGS_FILE = "/etc/enigma2/pro_panel_settings.json"
BACKUP_DIR = "/tmp/pro_panel_backup"
FONT_PATH = os.path.join(PLUGIN_DIR, "fonts", "Cairo-Bold.ttf")
TEMP_SERVER_SCRIPT = "/tmp/Taoufik_Free_Server.sh"

DEFAULT_THEME_IDX = 8
WELCOME_SECONDS = 4
DEFAULT_TOP_SECTION_KEY = "golden_age"

RA_CFG = "/tmp/retroarch_pro.cfg"
RA_LOG = "/tmp/retroarch_pro.log"
RA_AUTOCONFIG_DIR = "/tmp/retroarch_autoconfig"

CORE_DIRS = [
    "/usr/lib/libretro",
    "/usr/lib/retroarch/cores",
    "/usr/local/lib/libretro",
    "/usr/share/libretro/cores",
    "/media/hdd/retroarch/cores",
    "/media/usb/retroarch/cores",
    "/media/hdd/cores",
    os.path.join(PLUGIN_DIR, "cores"),
]

ENABLE_ARABIC_SHAPING = False

# ============================================================================
#  جسر الريموت كعصا تحكم حقيقية + لوحة مفاتيح (/dev/uinput)
# ============================================================================
V_KBD_NAME = "TFK SAT Remote Kbd"
V_GAMEPAD_NAME = "TFK SAT Remote Gamepad"

# Linux input event types & ioctls
EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
EVIOCGRAB = 0x40044590

# Linux Gamepad axes
ABS_X = 0x00
ABS_Y = 0x01
ABS_HAT0X = 0x10
ABS_HAT0Y = 0x11

# Linux Gamepad buttons
BTN_SOUTH = 0x130   # 304 -> A
BTN_EAST = 0x131    # 305 -> B
BTN_NORTH = 0x133   # 307 -> X
BTN_WEST = 0x134    # 308 -> Y
BTN_TL = 0x136      # 310 -> L1
BTN_TR = 0x137      # 311 -> R1
BTN_TL2 = 0x138     # 312 -> L2
BTN_TR2 = 0x139     # 313 -> R2
BTN_SELECT = 0x13A  # 314 -> Select / Coin
BTN_START = 0x13B   # 315 -> Start
BTN_MODE = 0x13C    # 316 -> Home / RetroArch Menu
BTN_DPAD_UP = 0x220
BTN_DPAD_DOWN = 0x221
BTN_DPAD_LEFT = 0x222
BTN_DPAD_RIGHT = 0x223

# Keyboard codes (for keyboard / hybrid shortcuts)
KEY_ESC = 1
KEY_ENTER = 28
KEY_Q = 16
KEY_W = 17
KEY_A = 30
KEY_S = 31
KEY_Z = 44
KEY_X = 45
KEY_RSHIFT = 54
KEY_SPACE = 57
KEY_F1 = 59
KEY_F2 = 60
KEY_F4 = 62
KEY_UP = 103
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_DOWN = 108


def check_uinput_ready():
    """تجهيز وحدة uinput وصلاحيات الوصول اللازمة لجسر الريموت."""
    if not os.path.exists("/dev/uinput"):
        os.system("modprobe uinput 2>/dev/null")
    if os.path.exists("/dev/uinput"):
        try:
            os.chmod("/dev/uinput", 0o666)
        except Exception:
            pass
        return True
    return False


def get_joystick_nodes():
    """إرجاع أجهزة عصا التحكم المكتشفة حالياً في النظام."""
    nodes = []
    for js in sorted(glob.glob("/dev/input/js[0-9]*")):
        base = os.path.basename(js)
        name_path = "/sys/class/input/%s/device/name" % base
        name = base
        try:
            if os.path.exists(name_path):
                with open(name_path, "r", encoding="utf-8", errors="ignore") as f:
                    name = f.read().strip() or base
        except Exception:
            pass
        nodes.append((js, name))
    return nodes


class VirtualRemoteGamepad:
    """عصا تحكم افتراضية حقيقية (Joystick / Gamepad) عبر /dev/uinput."""
    EV_FMT = "llHHi"
    GAMEPAD_KEYS = (
        BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST,
        BTN_TL, BTN_TR, BTN_TL2, BTN_TR2,
        BTN_SELECT, BTN_START, BTN_MODE,
        BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT,
    )
    GAMEPAD_AXES = (ABS_X, ABS_Y, ABS_HAT0X, ABS_HAT0Y)

    def __init__(self, stick_mode="both"):
        self.fd = None
        self.stick_mode = stick_mode  # "both", "analog", "dpad"
        self._pressed_keys = set()
        self._dir_state = {"up": False, "down": False, "left": False, "right": False}

    def open(self):
        if not check_uinput_ready():
            return False
        try:
            self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
            for k in self.GAMEPAD_KEYS:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, k)
            for ax in self.GAMEPAD_AXES:
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, ax)

            absmax = [0] * 64
            absmin = [0] * 64
            absfuzz = [0] * 64
            absflat = [0] * 64

            for ax in (ABS_X, ABS_Y):
                absmin[ax] = -32767
                absmax[ax] = 32767
                absfuzz[ax] = 0
                absflat[ax] = 128

            for ax in (ABS_HAT0X, ABS_HAT0Y):
                absmin[ax] = -1
                absmax[ax] = 1
                absfuzz[ax] = 0
                absflat[ax] = 0

            dev_struct = struct.pack(
                "80sHHHHI256i",
                V_GAMEPAD_NAME.encode("utf-8")[:79],
                0x03,   # BUS_USB
                0x045E, # Virtual X-Input style vendor
                0x028E, # Virtual Gamepad product
                0x0110, # version
                0,
                *(absmax + absmin + absfuzz + absflat)
            )
            os.write(self.fd, dev_struct)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
            time.sleep(0.2)
            return True
        except Exception:
            self.close()
            return False

    def _write_events(self, events):
        if self.fd is None or not events:
            return
        try:
            now = time.time()
            sec = int(now)
            usec = int((now - sec) * 1000000)
            payload = bytearray()
            for ev_type, code, val in events:
                payload += struct.pack(self.EV_FMT, sec, usec, int(ev_type), int(code), int(val))
            payload += struct.pack(self.EV_FMT, sec, usec, EV_SYN, 0, 0)
            os.write(self.fd, bytes(payload))
        except Exception:
            pass

    def send_button(self, code, value):
        if self.fd is None:
            return
        val = 1 if value in (1, 2) else 0
        if val:
            self._pressed_keys.add(code)
        else:
            self._pressed_keys.discard(code)
        self._write_events([(EV_KEY, code, 1 if value == 1 else (2 if value == 2 else 0))])

    def send_direction(self, direction, value):
        if self.fd is None or direction not in self._dir_state:
            return
        is_down = value in (1, 2)
        self._dir_state[direction] = is_down

        dx = int(self._dir_state["right"]) - int(self._dir_state["left"])
        dy = int(self._dir_state["down"]) - int(self._dir_state["up"])

        events = []
        if self.stick_mode in ("both", "analog"):
            events.append((EV_ABS, ABS_X, dx * 32767))
            events.append((EV_ABS, ABS_Y, dy * 32767))
        if self.stick_mode in ("both", "dpad"):
            events.append((EV_ABS, ABS_HAT0X, dx))
            events.append((EV_ABS, ABS_HAT0Y, dy))
            dpad_map = {
                "up": BTN_DPAD_UP,
                "down": BTN_DPAD_DOWN,
                "left": BTN_DPAD_LEFT,
                "right": BTN_DPAD_RIGHT,
            }
            btn = dpad_map[direction]
            if is_down:
                self._pressed_keys.add(btn)
            else:
                self._pressed_keys.discard(btn)
            events.append((EV_KEY, btn, 1 if is_down else 0))

        self._write_events(events)

    def reset_state(self):
        if self.fd is None:
            return
        events = [
            (EV_ABS, ABS_X, 0),
            (EV_ABS, ABS_Y, 0),
            (EV_ABS, ABS_HAT0X, 0),
            (EV_ABS, ABS_HAT0Y, 0),
        ]
        for k in list(self._pressed_keys):
            events.append((EV_KEY, k, 0))
        self._pressed_keys.clear()
        for d in self._dir_state:
            self._dir_state[d] = False
        self._write_events(events)

    def close(self):
        if self.fd is not None:
            self.reset_state()
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            except Exception:
                pass
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None


class VirtualRemoteKbd:
    """لوحة مفاتيح وهمية تُنشأ عبر uinput لدعم اختصارات النظام ولوحة المفاتيح."""
    EV_FMT = "llHHi"
    TARGET_KEYS = (
        KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT,
        KEY_X, KEY_Z, KEY_S, KEY_A, KEY_Q, KEY_W,
        KEY_ENTER, KEY_RSHIFT, KEY_F1, KEY_F2, KEY_F4, KEY_SPACE, KEY_ESC,
    )

    def __init__(self):
        self.fd = None
        self._pressed = set()

    def open(self):
        if not check_uinput_ready():
            return False
        try:
            self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for k in self.TARGET_KEYS:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, k)
            dev_struct = struct.pack(
                "80sHHHHI256i",
                V_KBD_NAME.encode("utf-8")[:79],
                0x03, 0x1234, 0x5678, 1, 0,
                *([0] * 256)
            )
            os.write(self.fd, dev_struct)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
            time.sleep(0.15)
            return True
        except Exception:
            self.close()
            return False

    def send_key(self, code, value):
        if self.fd is None:
            return
        try:
            if value in (1, 2):
                self._pressed.add(code)
            else:
                self._pressed.discard(code)
            now = time.time()
            sec = int(now)
            usec = int((now - sec) * 1000000)
            ev_key = struct.pack(self.EV_FMT, sec, usec, EV_KEY, int(code), int(value))
            ev_syn = struct.pack(self.EV_FMT, sec, usec, EV_SYN, 0, 0)
            os.write(self.fd, ev_key + ev_syn)
        except Exception:
            pass

    def close(self):
        if self.fd is not None:
            for k in list(self._pressed):
                self.send_key(k, 0)
            self._pressed.clear()
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            except Exception:
                pass
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None


class RemoteBridgeWatcher:
    """يراقب الريموت الفيزيائي ويحوّله إلى عصا تحكم (Gamepad) أو لوحة مفاتيح."""
    EV_FMT = "llHHi"
    EV_SIZE = struct.calcsize(EV_FMT)
    EXIT_CODES = {1, 128, 158, 174}  # ESC, STOP, BACK, EXIT (ترك زر POWER للنظام)

    DIR_CODES = {
        103: "up",
        108: "down",
        105: "left",
        106: "right",
    }

    # خريطة أزرار الجيمباد (عصا التحكم الحقيقية)
    GAMEPAD_MAP_COLORS = {
        398: BTN_SOUTH,   # Red -> A
        399: BTN_EAST,    # Green -> B
        400: BTN_NORTH,   # Yellow -> X
        401: BTN_WEST,    # Blue -> Y
        2: BTN_SOUTH,     # 1 -> A
        3: BTN_EAST,      # 2 -> B
        4: BTN_NORTH,     # 3 -> X
        5: BTN_WEST,      # 4 -> Y
        6: BTN_START,     # 5 -> Start (إصلاح الخريطة)
        352: BTN_START,   # OK -> Start
        28: BTN_START,    # Enter -> Start
        11: BTN_SELECT,   # 0 -> Select / Coin
        402: BTN_TL,      # CH+ -> L1
        104: BTN_TL,      # PageUp -> L1
        403: BTN_TR,      # CH- -> R1
        109: BTN_TR,      # PageDown -> R1
        8: BTN_TL2,       # 7 -> L2
        9: BTN_TR2,       # 8 -> R2
        139: BTN_MODE,    # MENU -> Home/Menu
    }

    GAMEPAD_MAP_NUMBERS = {
        2: BTN_SOUTH,     # 1 -> A
        3: BTN_EAST,      # 2 -> B
        4: BTN_NORTH,     # 3 -> X
        5: BTN_WEST,      # 4 -> Y
        6: BTN_START,     # 5 -> Start
        352: BTN_START,   # OK -> Start
        28: BTN_START,    # Enter -> Start
        11: BTN_SELECT,   # 0 -> Select
        8: BTN_TL,        # 7 -> L1
        9: BTN_TR,        # 8 -> R1
        402: BTN_TL,      # CH+ -> L1
        104: BTN_TL,      # PageUp -> L1
        403: BTN_TR,      # CH- -> R1
        109: BTN_TR,      # PageDown -> R1
        10: BTN_MODE,     # 9 -> Menu/Mode
        139: BTN_MODE,    # MENU -> Menu/Mode
        398: BTN_TL2,     # Red -> L2
        399: BTN_TR2,     # Green -> R2
    }

    # خريطة لوحة المفاتيح الوهمية + اختصارات المحاكي
    KBD_MAP_COLORS = {
        103: KEY_UP, 108: KEY_DOWN, 105: KEY_LEFT, 106: KEY_RIGHT,
        398: KEY_X, 399: KEY_Z, 400: KEY_S, 401: KEY_A,
        2: KEY_X, 3: KEY_Z, 4: KEY_S, 5: KEY_A,
        6: KEY_ENTER, 352: KEY_ENTER, 28: KEY_ENTER,  # 5 / OK = Start
        11: KEY_RSHIFT,                                # 0 = Select
        402: KEY_Q, 104: KEY_Q,
        403: KEY_W, 109: KEY_W,
        139: KEY_F1,
        208: KEY_SPACE, 168: KEY_F4, 167: KEY_F2,      # FF -> Turbo, REW -> Load, REC -> Save
    }

    KBD_MAP_NUMBERS = {
        103: KEY_UP, 108: KEY_DOWN, 105: KEY_LEFT, 106: KEY_RIGHT,
        2: KEY_X, 3: KEY_Z, 4: KEY_S, 5: KEY_A,
        6: KEY_ENTER, 352: KEY_ENTER, 28: KEY_ENTER,
        11: KEY_RSHIFT,
        8: KEY_Q, 9: KEY_W,
        402: KEY_Q, 104: KEY_Q, 403: KEY_W, 109: KEY_W,
        10: KEY_F1, 139: KEY_F1,
        208: KEY_SPACE, 168: KEY_F4, 167: KEY_F2,
    }

    # اختصارات إضافية تُمرّر للوحة المفاتيح في الوضع الهجين
    HYBRID_SHORTCUTS = {
        139: KEY_F1,     # MENU -> RetroArch RGUI
        208: KEY_SPACE,  # FastForward -> Turbo
        168: KEY_F4,     # Rewind -> Load State
        167: KEY_F2,     # Record -> Save State
    }

    def __init__(self, get_pid_fn=None, enable_pad=True, layout="colors",
                 bridge_mode="hybrid", stick_mode="both", allow_exit_kill=True,
                 grab_remote=False, on_exit_cb=None, on_event_cb=None):
        self.get_pid_fn = get_pid_fn
        self.enable_pad = enable_pad
        self.layout = layout
        self.bridge_mode = bridge_mode  # "gamepad", "keyboard", "hybrid"
        self.stick_mode = stick_mode    # "both", "analog", "dpad"
        self.allow_exit_kill = allow_exit_kill
        self.grab_remote = grab_remote
        self.on_exit_cb = on_exit_cb
        self.on_event_cb = on_event_cb

        self.gamepad_map = (self.GAMEPAD_MAP_NUMBERS if layout == "numbers"
                            else self.GAMEPAD_MAP_COLORS)
        self.kbd_map = (self.KBD_MAP_NUMBERS if layout == "numbers"
                        else self.KBD_MAP_COLORS)

        self.running = False
        self.user_exited = False
        self.exit_reason = ""
        self._thread = None
        self._wake_r, self._wake_w = None, None
        self._gamepad = (VirtualRemoteGamepad(stick_mode=stick_mode)
                         if (enable_pad and bridge_mode in ("gamepad", "hybrid")) else None)
        self._vkbd = (VirtualRemoteKbd()
                      if (enable_pad and bridge_mode in ("keyboard", "hybrid")) else None)
        self.last_error = ""

    def start(self):
        if self.running:
            return
        self.running = True
        self.user_exited = False
        self.exit_reason = ""
        try:
            self._wake_r, self._wake_w = os.pipe()
        except Exception:
            self._wake_r, self._wake_w = None, None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._wake_w is not None:
            try:
                os.write(self._wake_w, b"x")
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=0.8)
            except Exception:
                pass
        for fd in (self._wake_r, self._wake_w):
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
        self._wake_r, self._wake_w = None, None

    def _is_pid_alive(self, pid):
        if not pid or pid <= 1:
            return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _terminate_retroarch(self, reason=""):
        self.user_exited = True
        self.exit_reason = reason or "remote_exit"
        if reason:
            try:
                with open(RA_LOG, "a", encoding="utf-8") as f:
                    f.write("\n[TFK] Remote exit triggered: %s\n" % reason)
            except Exception:
                pass
        if self.on_exit_cb:
            try:
                self.on_exit_cb()
            except Exception:
                pass
        pid = 0
        if self.get_pid_fn:
            try:
                pid = self.get_pid_fn()
            except Exception:
                pid = 0
        if pid and pid > 1:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        os.system("killall -TERM retroarch 2>/dev/null")

        time.sleep(0.15)
        if pid and pid > 1 and self._is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        os.system("killall -KILL retroarch 2>/dev/null")

    def _is_physical_remote(self, ev_dev):
        base = os.path.basename(ev_dev)
        # استبعاد الأجهزة التي لا تدعم EV_KEY أصلاً (مثل حساسات الحركة أو اللمس)
        for ev_cap in (
            "/sys/class/input/%s/device/capabilities/ev" % base,
            "/sys/class/input/%s/device/device/capabilities/ev" % base,
        ):
            try:
                if os.path.exists(ev_cap):
                    with open(ev_cap, "r", encoding="utf-8", errors="ignore") as f:
                        caps = int(f.read().strip().split()[-1], 16)
                    if (caps & (1 << EV_KEY)) == 0:
                        return False
                    break
            except Exception:
                pass
        name = ""
        for p in (
            "/sys/class/input/%s/device/name" % base,
            "/sys/class/input/%s/device/device/name" % base,
        ):
            try:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        name = f.read().strip()
                    if name:
                        break
            except Exception:
                pass
        if not name:
            # محاولة قراءة الاسم مباشرة عبر ioctl EVIOCGNAME(256)
            try:
                fd = os.open(ev_dev, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    buf = bytearray(256)
                    fcntl.ioctl(fd, 0x81004506, buf)
                    name = buf.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
                finally:
                    os.close(fd)
            except Exception:
                pass
        if name:
            if name in (V_KBD_NAME, V_GAMEPAD_NAME):
                return False
            nl = name.lower()
            if any(k in nl for k in (
                "gamepad", "joystick", "xbox", "playstation",
                "dualshock", "dualsense", "8bitdo", "logitech", "tfk sat remote"
            )):
                return False
        return True

    def _dispatch_event(self, code, val, gamepad_ok, vkbd_ok):
        if self.on_event_cb:
            try:
                self.on_event_cb(code, val)
            except Exception:
                pass

        if gamepad_ok and self._gamepad:
            if code in self.DIR_CODES:
                self._gamepad.send_direction(self.DIR_CODES[code], val)
            elif code in self.gamepad_map:
                self._gamepad.send_button(self.gamepad_map[code], val)
            if self.bridge_mode == "hybrid" and vkbd_ok and self._vkbd:
                if code in self.HYBRID_SHORTCUTS:
                    self._vkbd.send_key(self.HYBRID_SHORTCUTS[code], val)
            return

        if vkbd_ok and self._vkbd and code in self.kbd_map:
            self._vkbd.send_key(self.kbd_map[code], val)

    def _loop(self):
        fds = []
        grabbed_fds = []
        gamepad_ok = False
        vkbd_ok = False
        try:
            if self._gamepad:
                gamepad_ok = self._gamepad.open()
                if not gamepad_ok:
                    self.last_error = "تعذر إنشاء عصا التحكم الافتراضية (/dev/uinput)"
            if self._vkbd:
                vkbd_ok = self._vkbd.open()
                if not vkbd_ok and not self.last_error:
                    self.last_error = "تعذر فتح لوحة المفاتيح الوهمية (/dev/uinput)"

            for ev in sorted(glob.glob("/dev/input/event[0-9]*")):
                if not self._is_physical_remote(ev):
                    continue
                try:
                    fd = os.open(ev, os.O_RDONLY | os.O_NONBLOCK)
                    fds.append(fd)
                    if self.grab_remote:
                        try:
                            fcntl.ioctl(fd, EVIOCGRAB, 1)
                            grabbed_fds.append(fd)
                        except Exception:
                            pass
                except Exception:
                    pass

            if not fds:
                self.last_error = "لا توجد أجهزة إدخال فيزيائية قابلة للقراءة"
                return

            start_t = time.time()
            for fd in fds:
                try:
                    while os.read(fd, self.EV_SIZE * 16):
                        pass
                except Exception:
                    pass

            watch_fds = list(fds)
            if self._wake_r is not None:
                watch_fds.append(self._wake_r)

            while self.running:
                try:
                    readable, _, _ = select.select(watch_fds, [], [], 0.25)
                except Exception:
                    break
                if self._wake_r is not None and self._wake_r in readable:
                    break
                for fd in readable:
                    if fd == self._wake_r:
                        continue
                    while self.running:
                        try:
                            data = os.read(fd, self.EV_SIZE)
                            if not data or len(data) < self.EV_SIZE:
                                break
                            _, _, ev_t, code, val = struct.unpack(self.EV_FMT, data)
                            if time.time() - start_t < 1.0:
                                continue
                            if ev_t == EV_KEY and val in (0, 1, 2):
                                if self.allow_exit_kill and val == 1 and code in self.EXIT_CODES:
                                    self._terminate_retroarch("key_code=%s" % code)
                                    return
                                self._dispatch_event(code, val, gamepad_ok, vkbd_ok)
                        except OSError as e:
                            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                                break
                            break
                        except Exception:
                            break
        finally:
            for fd in grabbed_fds:
                try:
                    fcntl.ioctl(fd, EVIOCGRAB, 0)
                except Exception:
                    pass
            if self._gamepad:
                self._gamepad.close()
            if self._vkbd:
                self._vkbd.close()
            for fd in fds:
                try:
                    os.close(fd)
                except Exception:
                    pass


# مؤشر عالمي لجسر الريموت كعصا تحكم على مستوى النظام (خارج الألعاب)
_GLOBAL_REMOTE_WATCHER = None


def is_global_gamepad_active():
    return bool(_GLOBAL_REMOTE_WATCHER and _GLOBAL_REMOTE_WATCHER.running)


def start_global_gamepad(settings):
    global _GLOBAL_REMOTE_WATCHER
    stop_global_gamepad()
    if not check_uinput_ready():
        return False
    _GLOBAL_REMOTE_WATCHER = RemoteBridgeWatcher(
        get_pid_fn=None,
        enable_pad=True,
        layout=settings.get("remote_layout", "colors"),
        bridge_mode=settings.get("bridge_mode", "hybrid"),
        stick_mode=settings.get("stick_mode", "both"),
        allow_exit_kill=False,
        grab_remote=False,
    )
    _GLOBAL_REMOTE_WATCHER.start()
    return True


def stop_global_gamepad():
    global _GLOBAL_REMOTE_WATCHER
    if _GLOBAL_REMOTE_WATCHER:
        try:
            _GLOBAL_REMOTE_WATCHER.stop()
        except Exception:
            pass
        _GLOBAL_REMOTE_WATCHER = None


REMOTE_MAP_HELP_COLORS = (
    "خريطة أزرار الريموت كعصا تحكم (وضع الألوان):\n\n"
    "الأسهم        = عصا التحكم + D-Pad (ABS_X / ABS_Y / HAT0)\n"
    "الأحمر / 1    = زر A  (تأكيد / قفز)\n"
    "الأخضر / 2    = زر B  (رجوع / هجوم)\n"
    "الأصفر / 3    = زر X\n"
    "الأزرق / 4    = زر Y\n"
    "OK / 5        = Start (بدء اللعبة)\n"
    "0             = Select (إدخال عملة)\n"
    "CH+ / CH-     = L1 / R1   |   7 / 8 = L2 / R2\n"
    "REC / REW / FF= حفظ سريع / استرجاع / تسريع\n"
    "MENU          = قائمة RetroArch (RGUI)\n"
    "EXIT / BACK   = إغلاق اللعبة والعودة للبانل"
)

REMOTE_MAP_HELP_NUMBERS = (
    "خريطة أزرار الريموت كعصا تحكم (وضع الأرقام):\n\n"
    "الأسهم        = عصا التحكم + D-Pad (ABS_X / ABS_Y / HAT0)\n"
    "1 = A   |   2 = B   |   3 = X   |   4 = Y\n"
    "5 أو OK = Start   |   0 = Select\n"
    "7 أو CH+ = L1   |   8 أو CH- = R1\n"
    "الأحمر = L2   |   الأخضر = R2\n"
    "9 أو MENU = قائمة RetroArch (RGUI)\n"
    "EXIT / BACK = إغلاق اللعبة والعودة للبانل"
)

# ============================================================================
#  الثيمات
# ============================================================================
THEMES = [
    {
        "id": "midnight_sky", "name": "أزرق سماوي ليلي",
        "bg": "#060b18", "header_bg": "#091124",
        "header_top": (16, 28, 52), "header_bot": (11, 19, 38),
        "header_border": (36, 56, 92), "header_shine": (56, 86, 136),
        "sidebar_top": (12, 21, 40), "sidebar_bot": (8, 15, 30), "sidebar_border": (30, 48, 80),
        "card_top": (22, 35, 62), "card_bot": (14, 23, 42),
        "card_border": (38, 58, 94), "card_footer": (9, 15, 29),
        "focus_top": (28, 54, 96), "focus_bot": (17, 34, 64),
        "accent_rgb": (56, 189, 248), "accent_hex": "#38bdf8",
        "accent_light": "#7dd3fc", "accent_shine": (105, 210, 255),
    },
    {
        "id": "emerald_pro", "name": "زمردي احترافي",
        "bg": "#04120e", "header_bg": "#071c16",
        "header_top": (12, 42, 34), "header_bot": (8, 28, 23),
        "header_border": (24, 78, 64), "header_shine": (45, 130, 108),
        "sidebar_top": (10, 32, 26), "sidebar_bot": (6, 22, 18), "sidebar_border": (20, 64, 52),
        "card_top": (16, 48, 40), "card_bot": (10, 32, 27),
        "card_border": (28, 76, 63), "card_footer": (6, 20, 17),
        "focus_top": (20, 74, 60), "focus_bot": (13, 48, 39),
        "accent_rgb": (52, 211, 153), "accent_hex": "#34d399",
        "accent_light": "#6ee7b7", "accent_shine": (110, 231, 183),
    },
    {
        "id": "royal_amethyst", "name": "بنفسجي ملكي",
        "bg": "#0b0716", "header_bg": "#130d26",
        "header_top": (32, 22, 62), "header_bot": (21, 14, 42),
        "header_border": (58, 42, 108), "header_shine": (96, 72, 168),
        "sidebar_top": (25, 17, 49), "sidebar_bot": (16, 11, 33), "sidebar_border": (48, 34, 90),
        "card_top": (38, 26, 72), "card_bot": (24, 16, 48),
        "card_border": (64, 46, 116), "card_footer": (15, 10, 31),
        "focus_top": (58, 38, 108), "focus_bot": (36, 24, 70),
        "accent_rgb": (167, 139, 250), "accent_hex": "#a78bfa",
        "accent_light": "#c4b5fd", "accent_shine": (196, 181, 253),
    },
    {
        "id": "obsidian_gold", "name": "ذهبي فاخر",
        "bg": "#0c0a07", "header_bg": "#17130d",
        "header_top": (42, 34, 22), "header_bot": (28, 22, 14),
        "header_border": (78, 63, 40), "header_shine": (130, 104, 62),
        "sidebar_top": (32, 26, 17), "sidebar_bot": (22, 18, 11), "sidebar_border": (64, 52, 33),
        "card_top": (48, 39, 25), "card_bot": (32, 26, 16),
        "card_border": (82, 66, 42), "card_footer": (20, 16, 10),
        "focus_top": (78, 60, 32), "focus_bot": (50, 38, 20),
        "accent_rgb": (251, 191, 36), "accent_hex": "#fbbf24",
        "accent_light": "#fde68a", "accent_shine": (253, 224, 71),
    },
    {
        "id": "arctic_cyber", "name": "أزرق قطبي عصري",
        "bg": "#050d1a", "header_bg": "#08162b",
        "header_top": (14, 38, 68), "header_bot": (9, 24, 46),
        "header_border": (32, 82, 136), "header_shine": (56, 132, 204),
        "sidebar_top": (10, 27, 50), "sidebar_bot": (7, 18, 35), "sidebar_border": (26, 66, 110),
        "card_top": (16, 44, 78), "card_bot": (10, 28, 52),
        "card_border": (34, 84, 138), "card_footer": (7, 19, 36),
        "focus_top": (22, 68, 118), "focus_bot": (14, 42, 76),
        "accent_rgb": (125, 211, 252), "accent_hex": "#7dd3fc",
        "accent_light": "#bae6fd", "accent_shine": (186, 230, 253),
    },
    {
        "id": "crimson_carbon", "name": "كربوني قرمزي",
        "bg": "#11070a", "header_bg": "#1d0b11",
        "header_top": (54, 18, 28), "header_bot": (36, 12, 19),
        "header_border": (102, 34, 52), "header_shine": (168, 56, 86),
        "sidebar_top": (40, 14, 21), "sidebar_bot": (26, 9, 14), "sidebar_border": (82, 28, 42),
        "card_top": (62, 20, 32), "card_bot": (40, 13, 21),
        "card_border": (108, 36, 56), "card_footer": (25, 8, 13),
        "focus_top": (98, 28, 48), "focus_bot": (64, 18, 31),
        "accent_rgb": (251, 113, 133), "accent_hex": "#fb7185",
        "accent_light": "#fda4af", "accent_shine": (253, 164, 175),
    },
    {
        "id": "ocean_teal", "name": "محيطي فيروزي",
        "bg": "#041114", "header_bg": "#071c21",
        "header_top": (12, 44, 52), "header_bot": (8, 29, 35),
        "header_border": (24, 84, 98), "header_shine": (45, 142, 164),
        "sidebar_top": (9, 33, 39), "sidebar_bot": (6, 22, 26), "sidebar_border": (20, 68, 80),
        "card_top": (14, 50, 58), "card_bot": (9, 33, 39),
        "card_border": (28, 88, 102), "card_footer": (6, 21, 25),
        "focus_top": (20, 78, 92), "focus_bot": (13, 50, 60),
        "accent_rgb": (45, 212, 191), "accent_hex": "#2dd4bf",
        "accent_light": "#5eead4", "accent_shine": (94, 234, 212),
    },
    {
        "id": "nordic_slate", "name": "أردوازي نورديك",
        "bg": "#090d14", "header_bg": "#101724",
        "header_top": (28, 38, 56), "header_bot": (19, 26, 39),
        "header_border": (54, 72, 104), "header_shine": (88, 116, 164),
        "sidebar_top": (22, 30, 44), "sidebar_bot": (15, 20, 30), "sidebar_border": (44, 58, 84),
        "card_top": (32, 43, 64), "card_bot": (21, 29, 43),
        "card_border": (58, 76, 108), "card_footer": (14, 19, 29),
        "focus_top": (48, 66, 98), "focus_bot": (31, 43, 64),
        "accent_rgb": (96, 165, 250), "accent_hex": "#60a5fa",
        "accent_light": "#93c5fd", "accent_shine": (147, 197, 253),
    },
    {
        "id": "imperial_sapphire", "name": "ياقوتي ملكي فاخر",
        "bg": "#050917", "header_bg": "#091229",
        "header_top": (18, 36, 76), "header_bot": (11, 22, 48),
        "header_border": (42, 78, 152), "header_shine": (76, 128, 224),
        "sidebar_top": (13, 26, 56), "sidebar_bot": (8, 17, 37), "sidebar_border": (34, 62, 118),
        "card_top": (20, 42, 86), "card_bot": (13, 27, 56),
        "card_border": (46, 86, 164), "card_footer": (8, 18, 38),
        "focus_top": (32, 68, 134), "focus_bot": (20, 44, 88),
        "accent_rgb": (56, 189, 248), "accent_hex": "#38bdf8",
        "accent_light": "#bae6fd", "accent_shine": (125, 211, 252),
    },
    {
        "id": "velvet_aurora", "name": "شفق مخملي راقٍ",
        "bg": "#090714", "header_bg": "#120e24",
        "header_top": (36, 26, 68), "header_bot": (22, 16, 44),
        "header_border": (74, 52, 132), "header_shine": (124, 92, 204),
        "sidebar_top": (27, 19, 52), "sidebar_bot": (17, 12, 34), "sidebar_border": (58, 40, 104),
        "card_top": (42, 30, 78), "card_bot": (26, 19, 50),
        "card_border": (82, 58, 146), "card_footer": (16, 11, 32),
        "focus_top": (64, 46, 118), "focus_bot": (40, 28, 76),
        "accent_rgb": (192, 132, 252), "accent_hex": "#c084fc",
        "accent_light": "#e9d5ff", "accent_shine": (216, 180, 254),
    },
    {
        "id": "arabian_oasis_gold", "name": "واحة الصحراء الذهبية (عربي)",
        "bg": "#0d0904", "header_bg": "#1a1208",
        "header_top": (56, 38, 14), "header_bot": (34, 22, 8),
        "header_border": (118, 82, 28), "header_shine": (196, 138, 46),
        "sidebar_top": (38, 26, 10), "sidebar_bot": (24, 16, 6), "sidebar_border": (92, 64, 22),
        "card_top": (62, 42, 16), "card_bot": (38, 25, 10),
        "card_border": (124, 86, 30), "card_footer": (22, 14, 5),
        "focus_top": (98, 66, 22), "focus_bot": (62, 41, 14),
        "accent_rgb": (245, 158, 11), "accent_hex": "#f59e0b",
        "accent_light": "#fcd34d", "accent_shine": (253, 224, 71),
    },
    {
        "id": "andalus_emerald", "name": "ليالي الأندلس الزمردية (عربي)",
        "bg": "#031310", "header_bg": "#06211c",
        "header_top": (10, 54, 45), "header_bot": (6, 34, 28),
        "header_border": (22, 106, 88), "header_shine": (45, 178, 148),
        "sidebar_top": (8, 38, 32), "sidebar_bot": (5, 24, 20), "sidebar_border": (18, 84, 70),
        "card_top": (12, 58, 48), "card_bot": (8, 36, 30),
        "card_border": (26, 112, 94), "card_footer": (5, 22, 18),
        "focus_top": (18, 88, 72), "focus_bot": (11, 56, 46),
        "accent_rgb": (16, 185, 129), "accent_hex": "#10b981",
        "accent_light": "#6ee7b7", "accent_shine": (110, 231, 183),
    },
    {
        "id": "cyberpunk_neon", "name": "سايبربانك نيون (عالمي)",
        "bg": "#070614", "header_bg": "#110d29",
        "header_top": (42, 18, 78), "header_bot": (24, 11, 48),
        "header_border": (118, 36, 156), "header_shine": (236, 72, 153),
        "sidebar_top": (26, 14, 52), "sidebar_bot": (15, 8, 32), "sidebar_border": (86, 30, 122),
        "card_top": (48, 20, 86), "card_bot": (28, 12, 54),
        "card_border": (132, 42, 172), "card_footer": (16, 7, 34),
        "focus_top": (78, 28, 128), "focus_bot": (46, 16, 80),
        "accent_rgb": (236, 72, 153), "accent_hex": "#ec4899",
        "accent_light": "#f9a8d4", "accent_shine": (244, 114, 182),
    },
    {
        "id": "pure_oled_black", "name": "أوليد الأسود النقي (عالمي)",
        "bg": "#000000", "header_bg": "#0a0a0c",
        "header_top": (26, 28, 34), "header_bot": (14, 15, 18),
        "header_border": (56, 62, 74), "header_shine": (112, 122, 142),
        "sidebar_top": (18, 19, 24), "sidebar_bot": (10, 11, 14), "sidebar_border": (44, 48, 58),
        "card_top": (28, 30, 36), "card_bot": (15, 16, 20),
        "card_border": (60, 66, 78), "card_footer": (9, 10, 12),
        "focus_top": (44, 52, 66), "focus_bot": (26, 30, 38),
        "accent_rgb": (14, 165, 233), "accent_hex": "#0ea5e9",
        "accent_light": "#7dd3fc", "accent_shine": (125, 211, 252),
    },
    {
        "id": "deep_ocean_abyss", "name": "أعماق المحيط الهادئ (عالمي)",
        "bg": "#030c18", "header_bg": "#06182e",
        "header_top": (12, 48, 86), "header_bot": (7, 29, 54),
        "header_border": (26, 98, 168), "header_shine": (56, 156, 236),
        "sidebar_top": (9, 34, 62), "sidebar_bot": (5, 21, 38), "sidebar_border": (20, 76, 132),
        "card_top": (14, 54, 96), "card_bot": (8, 32, 58),
        "card_border": (30, 106, 178), "card_footer": (5, 20, 36),
        "focus_top": (22, 84, 142), "focus_bot": (13, 52, 88),
        "accent_rgb": (34, 211, 238), "accent_hex": "#22d3ee",
        "accent_light": "#67e8f9", "accent_shine": (103, 232, 249),
    },
]

# ============================================================================
#  أنظمة الجيل الذهبي
# ============================================================================
GOLDEN_SYSTEMS = [
    {
        "id": "neogeo",
        "name": "SNK Neo Geo",
        "exts": [".zip", ".neo", ".gno", ".7z"],
        "cores": ["fbneo_libretro.so", "fbalpha2012_neogeo_libretro.so",
                  "gngeo_libretro.so", "mame2003_plus_libretro.so"],
        "bios_required": True,
        "bios_file": "neogeo.zip",
    },
    {
        "id": "arcade",
        "name": "Arcade / MAME",
        "exts": [".zip", ".7z", ".chd"],
        "cores": ["fbneo_libretro.so", "mame2003_plus_libretro.so",
                  "mame2003_libretro.so", "mame2000_libretro.so"],
    },
]

BIOS_FILES = {"neogeo.zip", "pgm.zip", "qsound.zip", "skns.zip",
              "awbios.zip", "naomi.zip", "dc_boot.bin", "dc_flash.bin"}

# ============================================================================
#  سكربت السيرفرات المجانية (متوافق مع Python 3 و Python 2)
# ============================================================================
FREE_SERVER_SHELL_SCRIPT = r"""#!/bin/sh
# DEVELOPED BY TFK (c) 2026 - WGET BACKBONE ENGINE
mkdir -p /etc/tuxbox/config 2>/dev/null
OUTPUT_FILE="/etc/tuxbox/config/ncam.server"
[ ! -f "$OUTPUT_FILE" ] && OUTPUT_FILE="/etc/tuxbox/config/oscam.server"

URLS="
https://cccam-premium.pro/free-cccam/
https://cccamsate.com/free
https://cccamiptv.tv/cccamfree/
https://cccam.net/freecccam
https://cccamia.com/cccam-free/
https://cccamhub.com/cccamfree/
https://cccamgalaxy.com/
https://cccamfree48h.yolasite.com/server-2.php
https://raw.githubusercontent.com/levi-45/free-cccam/main/servers.txt
"

PY_BIN=$(command -v python3 || command -v python)
if [ -n "$PY_BIN" ]; then
    YESTERDAY=$($PY_BIN -c "from datetime import datetime, timedelta; print((datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'))" 2>/dev/null)
    TODAY=$($PY_BIN -c "from datetime import datetime; print(datetime.now().strftime('%Y-%m-%d'))" 2>/dev/null)
else
    TODAY=$(date +%Y-%m-%d 2>/dev/null)
    YESTERDAY=""
fi
[ -n "$YESTERDAY" ] && URLS="$URLS https://testious.com/old-free-cccam-servers/$YESTERDAY/"
[ -n "$TODAY" ] && URLS="$URLS https://testious.com/old-free-cccam-servers/$TODAY/"

TEMP_FILE="/tmp/servers_temp.txt"
FINAL_FILE="/tmp/servers_final.txt"
CONVERTED_FILE="/tmp/servers_converted.txt"
: > "$FINAL_FILE"
: > "$TEMP_FILE"
: > "$CONVERTED_FILE"

echo "=== Scraping Live Feeds (Wget Universal Engine) ==="

parse_servers() {
    clean_content=$(echo "$1" | sed 's/<[^>]*>//g' | tr -d '\r' | sed 's/&amp;/\&/g')
    echo "$clean_content" | grep -oE '[Cc]:[[:space:]]*[[:alnum:].-]+[[:space:]]+[0-9]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+' >> "$TEMP_FILE"
    echo "$clean_content" | grep -oE '[Nn]:[[:space:]]*[[:alnum:].-]+[[:space:]]+[0-9]+[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+[0-9a-fA-F]+' >> "$TEMP_FILE"
}

for URL in $URLS; do
    echo "Downloading & Processing: $URL"
    if wget -q --no-check-certificate --timeout=6 --user-agent="Mozilla/5.0" "$URL" -O "$TEMP_FILE.download"; then
        if [ -s "$TEMP_FILE.download" ]; then
            parse_servers "$(cat "$TEMP_FILE.download")"
        fi
        rm -f "$TEMP_FILE.download"
    else
        echo "--> Timeout or Host Down: Skipping $URL safely..."
    fi
done

convert_to_oscam() {
    line="$1"
    set -- $line
    [ $# -lt 5 ] && return
    ptype=$(echo "$1" | tr -d ':')
    host="$2"; port="$3"; user="$4"; pass="$5"; key="$6"
    if [ "$ptype" = "C" ] || [ "$ptype" = "c" ]; then
        echo "[reader]"
        echo "label = ${host}_${port}"
        echo "enable = 1"
        echo "protocol = cccam"
        echo "device = ${host},${port}"
        echo "user = ${user}"
        echo "password = ${pass}"
        echo "group = 1"
        echo "cccversion = 2.1.2"
        echo "inactivitytimeout = 1"
        echo "reconnecttimeout = 30"
        echo "disablelog = 1"
        echo ""
    elif [ "$ptype" = "N" ] || [ "$ptype" = "n" ]; then
        [ -z "$key" ] && return
        echo "[reader]"
        echo "label = ${host}_${port}"
        echo "enable = 1"
        echo "protocol = newcamd"
        echo "key = ${key}"
        echo "device = ${host},${port}"
        echo "user = ${user}"
        echo "password = ${pass}"
        echo "group = 1"
        echo "inactivitytimeout = 1"
        echo "reconnecttimeout = 30"
        echo "ccckeepalive = 1"
        echo ""
    fi
}

if [ -s "$TEMP_FILE" ]; then
    grep -E '^[CNcn]:' "$TEMP_FILE" | sed 's/#.*//' | sed 's/[[:space:]]*$//' | sort -u > "$FINAL_FILE"
    FINAL_COUNT=$(wc -l < "$FINAL_FILE")
    if [ "$FINAL_COUNT" -gt 0 ]; then
        START_MARKER="#--- TFK FREE START ---"
        END_MARKER="#--- TFK FREE END ---"
        while IFS= read -r line; do
            convert_to_oscam "$line" >> "$CONVERTED_FILE"
        done < "$FINAL_FILE"
        INSTALLED_TO=0
        if [ ! -f /etc/tuxbox/config/ncam.server ] && [ ! -f /etc/tuxbox/config/oscam.server ]; then
            touch "$OUTPUT_FILE"
        fi
        for config_path in /etc/tuxbox/config/ncam.server /etc/tuxbox/config/oscam.server; do
            if [ -f "$config_path" ]; then
                cp "$config_path" "${config_path}.bak"
                sed -i "/$START_MARKER/,/$END_MARKER/d" "$config_path"
                echo "$START_MARKER" >> "$config_path"
                cat "$CONVERTED_FILE" >> "$config_path"
                echo "$END_MARKER" >> "$config_path"
                INSTALLED_TO=$((INSTALLED_TO + 1))
            fi
        done
        echo "=== Sync Complete! Readers: $FINAL_COUNT | Configs Updated: $INSTALLED_TO ==="
    else
        echo "--> No valid C/N lines parsed."
    fi
else
    echo "--> No servers found from any active source."
fi

rm -f "$TEMP_FILE" "$FINAL_FILE" "$CONVERTED_FILE" "$TEMP_FILE.download" 2>/dev/null
"""

SOFTCAM_RESTART_CMD = (
    "killall -9 ncam oscam CCcam 2>/dev/null; sleep 1; "
    "([ -x /usr/bin/ncam ] && /usr/bin/ncam -b -c /etc/tuxbox/config) || "
    "([ -x /usr/bin/oscam ] && /usr/bin/oscam -b -c /etc/tuxbox/config) || "
    "echo 'No NCam/OSCam binary found in /usr/bin'; "
    "echo 'Softcam Restart Routine Completed!'"
)

CLEAN_RAM_CMD = (
    "sync && echo 3 > /proc/sys/vm/drop_caches && "
    "rm -rf /tmp/*.log /tmp/*.ipk 2>/dev/null && free -m"
)

UINPUT_FIX_CMD = (
    "modprobe uinput 2>/dev/null; "
    "chmod 666 /dev/uinput 2>/dev/null; "
    "lsmod | grep uinput; "
    "ls -l /dev/uinput 2>/dev/null; "
    "echo '--- Joystick Devices (/dev/input/js*) ---'; "
    "ls -l /dev/input/js* 2>/dev/null || echo 'None currently active'; "
    "echo '--- Input Devices ---'; "
    "cat /proc/bus/input/devices | grep -E 'Name|Handlers'"
)

# ============================================================================
#  الأقسام والعناصر
# ============================================================================
CATEGORIES = [
    {"id": "golden_age", "title": "الجيل الذهبي"},
    {"id": "panels", "title": "بانلات"},
    {"id": "plugins", "title": "إضافات"},
    {"id": "skins", "title": "سكنات"},
    {"id": "tools", "title": "أدوات"},
    {"id": "system", "title": "النظام"},
]


def get_ordered_categories(top_section_key=DEFAULT_TOP_SECTION_KEY):
    items = list(CATEGORIES)
    if top_section_key:
        items.sort(key=lambda c: 0 if c.get("id") == top_section_key else 1)
    return items


CAT_BADGE_COLORS = {
    "golden_age": ((180, 83, 9), (120, 53, 15), (251, 191, 36)),
    "panels": ((14, 116, 144), (17, 78, 99), (56, 189, 248)),
    "plugins": ((109, 40, 217), (76, 29, 149), (167, 139, 250)),
    "skins": ((190, 24, 93), (131, 24, 67), (244, 114, 182)),
    "picons": ((180, 83, 9), (120, 53, 15), (251, 191, 36)),
    "tools": ((4, 120, 87), (6, 78, 59), (52, 211, 153)),
    "system": ((29, 78, 216), (30, 58, 138), (96, 165, 250)),
}

DEFAULT_ITEMS = [
    {
        "id": "remote_gamepad_tester", "name": "الريموت كعصا تحكم (اختبار)", "short": "JOY",
        "version": "PRO", "category": "golden_age", "type": "gamepad_tester",
        "check_path": "/dev/uinput", "icon": "icons/neogeo.png",
        "desc": "تحويل ريموت الجهاز لعصا تحكم حقيقية (Gamepad) واختبار الأزرار والمحاور مباشرة",
    },
    {
        "id": "remote_global_toggle", "name": "تشغيل عصا التحكم بالخلفية", "short": "HID",
        "version": "PRO", "category": "golden_age", "type": "global_gamepad",
        "check_path": "/dev/uinput", "icon": "icons/arcade.png",
        "desc": "تفعيل/إيقاف الريموت كعصا تحكم دائمة لجميع الألعاب والتطبيقات على الجهاز",
    },
    {
        "id": "remote_pad_setup", "name": "تجهيز uinput لعصا التحكم", "short": "PAD",
        "version": "PRO", "category": "golden_age", "type": "remote_setup",
        "check_path": "/dev/uinput", "icon": "icons/neogeo.png",
        "desc": "فحص وتجهيز وحدة uinput وصلاحيات /dev/input لعمل الريموت كعصا تحكم",
    },
    {
        "id": "retroarch_perf_settings", "name": "إعدادات سرعة الصورة والأداء", "short": "FPS",
        "version": "NORMAL", "category": "golden_age", "type": "ra_perf_settings",
        "check_path": "", "icon": "icons/tools.png",
        "desc": "ضبط السرعة على NORMAL وتخفيف التقل عبر دقة الصورة والخيوط المتعددة وتخطي الإطارات",
    },
    {
        "id": "retroarch_neogeo", "name": "RetroArch Neo Geo", "short": "NEO",
        "version": "RA", "category": "golden_age", "sys_id": "neogeo",
        "type": "retro_launcher", "check_path": "/usr/bin/retroarch",
        "icon": "icons/neogeo.png",
        "desc": "محاكي RetroArch لألعاب SNK Neo Geo للجيل الذهبي",
    },
    {
        "id": "retroarch_arcade", "name": "RetroArch Arcade/MAME", "short": "ARC",
        "version": "RA", "category": "golden_age", "sys_id": "arcade",
        "type": "retro_launcher", "check_path": "/usr/bin/retroarch",
        "icon": "icons/arcade.png",
        "desc": "محاكي RetroArch لألعاب Arcade و MAME للجيل الذهبي",
    },
    {
        "id": "taoufik_free_server", "name": "TFK FREE SERVER", "short": "SRV",
        "version": "2026", "category": "tools", "type": "free_server",
        "check_path": "/etc/tuxbox/config/ncam.server", "icon": "icons/server.png",
        "desc": "جلب وتحديث السيرفرات المجانية تلقائياً إلى NCam / OSCam",
    },
    {
        "id": "softcam_restart", "name": "إعادة تشغيل الإيمو", "short": "CAM",
        "version": "PRO", "category": "tools", "type": "script",
        "cmd": SOFTCAM_RESTART_CMD, "check_path": "", "icon": "icons/cam.png",
        "desc": "إعادة تشغيل سريعة لإيمو NCam أو OSCam لتفعيل السيرفرات فوراً",
    },
    {
        "id": "clean_ram_cache", "name": "تنظيف الذاكرة والكاش", "short": "RAM",
        "version": "PRO", "category": "system", "type": "script",
        "cmd": CLEAN_RAM_CMD, "check_path": "", "icon": "icons/tools.png",
        "desc": "تحرير الذاكرة العشوائية RAM وحذف الملفات المؤقتة لتسريع الرسيفر",
    },
    {
        "id": "ajpanel", "name": "AJPanel Tools", "short": "AJ", "version": "10.0",
        "category": "panels", "type": "script",
        "cmd": "wget -qO- https://raw.githubusercontent.com/AMAJamry/AJPanel/main/installer.sh | sh",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/AJPanel",
        "icon": "icons/ajpanel.png",
        "desc": "بانل شامل لإدارة القنوات، الباقات، IPTV والملفات",
    },
    {
        "id": "dreamosat", "name": "DreamOSat Downloader", "short": "DOS", "version": "9.0",
        "category": "panels", "type": "script",
        "cmd": "wget -qO- https://raw.githubusercontent.com/tarekzoka/dreamosat/main/installer.sh | sh",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/DreamOSatDownloader",
        "icon": "icons/dreamosat.png",
        "desc": "تحميل الإضافات، السوفتكام والسكنات بضغطة زر",
    },
    {
        "id": "e2iplayer", "name": "E2iPlayer", "short": "E2i", "version": "2026",
        "category": "plugins", "type": "opkg",
        "package": "enigma2-plugin-extensions-e2iplayer",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/IPTVPlayer",
        "icon": "icons/e2iplayer.png", "desc": "مشغل مواقع البث والأفلام والمسلسلات",
    },
    {
        "id": "xstreamity", "name": "XStreamity", "short": "XS", "version": "4.5",
        "category": "plugins", "type": "opkg",
        "package": "enigma2-plugin-extensions-xstreamity",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/XStreamity",
        "icon": "icons/xstreamity.png", "desc": "مشغل Xtream Codes احترافي للقنوات والـ VOD",
    },
    {
        "id": "jedi", "name": "Jedi Maker Xtream", "short": "JMX", "version": "6.3",
        "category": "plugins", "type": "opkg",
        "package": "enigma2-plugin-extensions-jedimakerxtream",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/JediMakerXtream",
        "icon": "icons/jedi.png", "desc": "تحويل قوائم IPTV إلى باقات نظام داخل الرسيفر",
    },
    {
        "id": "subssupport", "name": "SubsSupport", "short": "SUB", "version": "1.7",
        "category": "plugins", "type": "opkg",
        "package": "enigma2-plugin-extensions-subssupport",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/SubsSupport",
        "icon": "icons/subs.png", "desc": "تحميل وعرض الترجمة العربية للأفلام والقنوات",
    },
    {
        "id": "aglare_fhd", "name": "Aglare FHD", "short": "SKN", "version": "3.0",
        "category": "skins", "type": "opkg",
        "package": "enigma2-plugin-skins-aglare-fhd",
        "check_path": "/usr/share/enigma2/Aglare-FHD",
        "icon": "icons/skin.png", "desc": "سكن FHD عصري وخفيف وسريع الاستجابة",
    },
    {
        "id": "metrix_fhd", "name": "MetrixHD Mod", "short": "MTX", "version": "2.4",
        "category": "skins", "type": "opkg",
        "package": "enigma2-plugin-skins-metrixhd",
        "check_path": "/usr/share/enigma2/MetrixHD",
        "icon": "icons/metrix.png", "desc": "السكن الكلاسيكي الشهير بدعم الأيقونات والطقس",
    },
    {
        "id": "cacheflush", "name": "CacheFlush", "short": "CFL", "version": "1.2",
        "category": "tools", "type": "opkg",
        "package": "enigma2-plugin-extensions-cacheflush",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/CacheFlush",
        "icon": "icons/tools.png", "desc": "تنظيف الذاكرة العشوائية تلقائياً وتحسين الأداء",
    },
    {
        "id": "epgimport", "name": "EPG Import", "short": "EPG", "version": "1.9",
        "category": "tools", "type": "opkg",
        "package": "enigma2-plugin-extensions-epgimport",
        "check_path": "/usr/lib/enigma2/python/Plugins/Extensions/EPGImport",
        "icon": "icons/epg.png", "desc": "جلب دليل البرامج الإلكتروني للقنوات تلقائياً",
    },
    {
        "id": "sysinfo", "name": "فحص موارد النظام", "short": "SYS", "version": "1.0",
        "category": "system", "type": "script",
        "cmd": "uname -a && df -h && free -m", "check_path": "",
        "icon": "icons/system.png",
        "desc": "عرض مساحة التخزين واستهلاك الذاكرة ومعلومات النظام",
    },
    {
        "id": "restart_gui", "name": "إعادة تشغيل الواجهة", "short": "GUI", "version": "E2",
        "category": "system", "type": "restart_gui", "check_path": "",
        "icon": "icons/system.png",
        "desc": "إعادة تشغيل واجهة Enigma2 لتفعيل الإضافات والسكنات الجديدة",
    },
    {
        "id": "reboot_box", "name": "إعادة تشغيل الرسيفر", "short": "RBT", "version": "SYS",
        "category": "system", "type": "reboot_box", "check_path": "",
        "icon": "icons/system.png",
        "desc": "إعادة تشغيل كاملة لجهاز الاستقبال (Reboot)",
    },
]

# ============================================================================
#  دوال مساعدة عامة
# ============================================================================
def load_custom_font():
    if os.path.exists(FONT_PATH):
        try:
            addFont(FONT_PATH, "PanelArFont", 100, 1)
            return "PanelArFont"
        except Exception:
            pass
    return "Regular"


PANEL_FONT = load_custom_font()


def shape_ar(text):
    if not text:
        return ""
    if ENABLE_ARABIC_SHAPING:
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text
    return text


def get_free_ram_text():
    try:
        info = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    val = parts[1].strip().split()[0]
                    info[parts[0]] = int(val)
        avail = info.get("MemAvailable")
        if avail is None:
            avail = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0)
        return "RAM %dMB" % (avail // 1024)
    except Exception:
        return "RAM --"


def get_cpu_temp_text():
    for path in ("/proc/stb/sensors/temp0/value",
                 "/sys/class/thermal/thermal_zone0/temp",
                 "/proc/stb/fp/temp_sensor"):
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    val = int(re.sub(r"\D", "", f.read().strip()))
                if val > 1000:
                    val //= 1000
                if 10 <= val <= 120:
                    return "%d°C" % val
            except Exception:
                pass
    return "OK"


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Offline"


def get_hdd_summary():
    target = "/media/hdd" if os.path.ismount("/media/hdd") else "/"
    try:
        st = os.statvfs(target)
        free_gb = (st.f_bavail * st.f_frsize) / (1024.0 ** 3)
        total_gb = (st.f_blocks * st.f_frsize) / (1024.0 ** 3)
        mount_lbl = "HDD" if target == "/media/hdd" else "Flash"
        return "%s: %.1f/%.1f GB" % (mount_lbl, free_gb, total_gb)
    except Exception:
        return "Disk: --"


def load_panel_settings():
    defaults = {
        "theme_idx": DEFAULT_THEME_IDX,
        "remote_pad": True,
        "remote_layout": "colors",
        "bridge_mode": "hybrid",       # "gamepad", "keyboard", "hybrid"
        "stick_mode": "both",          # "both", "analog", "dpad"
        "video_profile": "auto",       # "auto", "fbcon", "kmsdrm", "sdl2", "gl"
        "grab_remote": False,
        "ra_speed_mode": "normal",     # "normal", "turbo_125", "turbo_150", "turbo_200", "unthrottled"
        "ra_res_preset": "720p",       # "720p", "540p", "480p", "native"
        "ra_threaded_video": True,
        "ra_video_smooth": False,
        "ra_audio_sync": True,
        "ra_vsync": False,
        "ra_frameskip": True,
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_panel_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def build_free_server_command():
    with open(TEMP_SERVER_SCRIPT, "w", encoding="utf-8") as f:
        f.write(FREE_SERVER_SHELL_SCRIPT)
    os.chmod(TEMP_SERVER_SCRIPT, 0o755)
    return "sh %s" % shlex.quote(TEMP_SERVER_SCRIPT)


# ============================================================================
#  دوال محاكي RetroArch + التهيئة التلقائية لعصا التحكم
# ============================================================================
def find_retroarch():
    for path in ("/usr/bin/retroarch", "/usr/local/bin/retroarch",
                 "/opt/retroarch/bin/retroarch", "/media/hdd/retroarch/retroarch",
                 os.path.join(PLUGIN_DIR, "bin", "retroarch")):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("retroarch")


def find_core_file(name):
    for d in CORE_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def resolve_core(sys_cfg):
    if not sys_cfg or "cores" not in sys_cfg:
        return None
    for name in sys_cfg["cores"]:
        p = find_core_file(name)
        if p:
            return p
    return None


def get_golden_system(sys_id):
    return next((s for s in GOLDEN_SYSTEMS if s["id"] == sys_id), None)


def golden_rom_dirs(sys_id):
    dirs = [
        os.path.join(PLUGIN_DIR, "roms", sys_id),
        os.path.join("/media/hdd/roms", sys_id),
        os.path.join("/media/usb/roms", sys_id),
    ]
    out = []
    for p in dirs:
        if p not in out:
            out.append(p)
    return out


def ensure_golden_rom_folders():
    created = []
    roots = ["/media/hdd/roms"]
    if os.path.ismount("/media/usb"):
        roots.append("/media/usb/roms")
    roots.append(os.path.join(PLUGIN_DIR, "roms"))
    for root in roots:
        for sys_cfg in GOLDEN_SYSTEMS:
            target = os.path.join(root, sys_cfg["id"])
            try:
                os.makedirs(target, exist_ok=True)
                created.append(target)
            except Exception:
                pass
    return created


def fmt_size(n):
    if n >= 1024 ** 3:
        return "%.2f GB" % (n / 1024.0 ** 3)
    if n >= 1024 ** 2:
        return "%.1f MB" % (n / 1024.0 ** 2)
    return "%d KB" % max(1, n // 1024)


def scan_golden_roms(sys_id, exts):
    if not exts:
        return []
    out, seen = [], set()
    ext_tuple = tuple(e.lower() for e in exts)
    sys_cfg = get_golden_system(sys_id)
    sys_title = sys_cfg["name"] if sys_cfg else sys_id
    for folder in golden_rom_dirs(sys_id):
        if not os.path.isdir(folder):
            continue
        try:
            for root, _, files in os.walk(folder):
                for fname in files:
                    if not fname.lower().endswith(ext_tuple):
                        continue
                    if fname.lower() in BIOS_FILES:
                        continue
                    full = os.path.join(root, fname)
                    if full in seen:
                        continue
                    seen.add(full)
                    try:
                        size = os.stat(full).st_size
                    except Exception:
                        size = 0
                    base_no_ext = os.path.splitext(fname)[0]
                    title = re.sub(r"\s*[([].*?[)\]]", "", base_no_ext).strip() or fname
                    out.append({
                        "id": full,
                        "name": title,
                        "short": title[:3].upper(),
                        "version": "ROM",
                        "category": "golden_age",
                        "sys_id": sys_id,
                        "type": "retro_rom",
                        "path": full,
                        "check_path": full,
                        "icon": "",
                        "desc": "RetroArch • %s • %s" % (sys_title, fmt_size(size)),
                    })
        except Exception:
            pass
    out.sort(key=lambda x: x["name"].lower())
    return out


_RA_FEATURES_CACHE = {}


def probe_retroarch_features(binary):
    """فحص المشغّلات المدعومة فعلياً داخل ملف RetroArch على الجهاز بدون افتراضات خاطئة."""
    if not binary:
        return {}
    if binary in _RA_FEATURES_CACHE:
        return _RA_FEATURES_CACHE[binary]
    # الافتراضات الآمنة المطابقة لبيئة Enigma2 حتى لو تعذر تحليل مخرجات --features
    feats = {
        "sdl2": True,
        "fbdev": False,
        "gl": False,
        "kms": False,
        "udev": True,
        "linuxraw": True,
        "alsa": True,
        "oss": False,
    }
    try:
        out = os.popen("%s --features 2>/dev/null" % shlex.quote(binary)).read()
        if out:
            low = out.lower()

            def _check(patterns, default_val):
                for pat in patterns:
                    m = re.search(pat, low, re.MULTILINE)
                    if m:
                        return m.group(1) == "yes"
                return default_val

            feats["sdl2"] = _check(
                [r"sdl2[^\n]*?:\s*(yes|no)", r"^\s*sdl2\s*:\s*\n\s*[^\n]*?:\s*(yes|no)"],
                feats["sdl2"],
            )
            feats["fbdev"] = _check(
                [r"framebuffer[^\n]*?:\s*(yes|no)", r"fbdev[^\n]*?:\s*(yes|no)"],
                feats["fbdev"],
            )
            feats["gl"] = _check(
                [r"opengles?[^\n]*?:\s*(yes|no)"],
                feats["gl"],
            )
            feats["kms"] = _check(
                [r"kms[^\n]*?:\s*(yes|no)"],
                feats["kms"],
            )
            feats["udev"] = _check(
                [r"udev[^\n]*?:\s*(yes|no)"],
                feats["udev"],
            )
            feats["alsa"] = _check(
                [r"alsa[^\n]*?:\s*(yes|no)"],
                feats["alsa"],
            )
            feats["oss"] = _check(
                [r"\boss\b[^\n]*?:\s*(yes|no)"],
                feats["oss"],
            )
    except Exception:
        pass
    _RA_FEATURES_CACHE[binary] = feats
    return feats


def read_system_retroarch_defaults():
    """قراءة إعدادات RetroArch الأصلية لصورة الرسيفر (إن وُجدت) للاستفادة من مشغّلاتها الصحيحة."""
    defaults = {}
    keys_of_interest = {
        "video_driver", "video_context_driver", "audio_driver",
        "input_driver", "input_joypad_driver", "system_directory",
        "assets_directory", "libretro_info_path",
    }
    for cfg_p in (
        "/etc/retroarch.cfg",
        "/home/root/.config/retroarch/retroarch.cfg",
        "/root/.config/retroarch/retroarch.cfg",
    ):
        if not os.path.isfile(cfg_p):
            continue
        try:
            with open(cfg_p, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k in keys_of_interest and k not in defaults:
                        val = v.strip().strip('"').strip("'")
                        if val:
                            defaults[k] = val
        except Exception:
            pass
    return defaults


def resolve_bios_dir(sys_cfg=None, rom_path=None):
    """تحديد مجلد ملفات BIOS مثل neogeo.zip."""
    sys_ra = read_system_retroarch_defaults()
    candidates = []
    if rom_path:
        candidates.append(os.path.dirname(rom_path))
    if sys_cfg:
        candidates.extend(golden_rom_dirs(sys_cfg["id"]))
    if sys_ra.get("system_directory"):
        candidates.append(sys_ra["system_directory"])
    candidates.extend([
        "/media/hdd/retroarch/system",
        "/media/usb/retroarch/system",
        "/home/root/.config/retroarch/system",
        "/root/.config/retroarch/system",
        "/etc/retroarch/system",
        os.path.join(PLUGIN_DIR, "bios"),
        "/usr/share/retroarch/system",
        "/usr/lib/libretro",
    ])
    bios_name = (sys_cfg or {}).get("bios_file", "neogeo.zip")
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, bios_name)):
            return d
    for d in candidates:
        if d and os.path.isdir(d):
            return d
    return "/tmp"


def generate_gamepad_autoconfig(input_driver="sdl2"):
    """توليد ملف تعريف تلقائي لعصا تحكم الريموت داخل RetroArch."""
    try:
        os.makedirs(RA_AUTOCONFIG_DIR, exist_ok=True)
        cfg_path = os.path.join(RA_AUTOCONFIG_DIR, "TFK_SAT_Remote_Gamepad.cfg")
        content = "\n".join([
            'input_driver = "%s"' % input_driver,
            'input_device = "%s"' % V_GAMEPAD_NAME,
            'input_vendor_id = "1118"',
            'input_product_id = "654"',
            'input_b_btn = "1"',
            'input_y_btn = "3"',
            'input_select_btn = "8"',
            'input_start_btn = "9"',
            'input_up_btn = "h0up"',
            'input_down_btn = "h0down"',
            'input_left_btn = "h0left"',
            'input_right_btn = "h0right"',
            'input_a_btn = "0"',
            'input_x_btn = "2"',
            'input_l_btn = "4"',
            'input_r_btn = "5"',
            'input_l2_btn = "6"',
            'input_r2_btn = "7"',
            'input_l_x_plus_axis = "+0"',
            'input_l_x_minus_axis = "-0"',
            'input_l_y_plus_axis = "+1"',
            'input_l_y_minus_axis = "-1"',
            'input_menu_toggle_btn = "10"',
        ]) + "\n"
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass


def generate_ra_cfg(settings=None, sys_cfg=None, rom_path=None,
                    cfg_path=None, video_driver_override=None,
                    audio_driver_override=None, input_driver_override=None):
    """ينشئ retroarch.cfg متوافقاً مع مشغّلات الجهاز وعصا تحكم الريموت."""
    settings = settings or {}
    cfg_path = cfg_path or RA_CFG
    binary = find_retroarch() or "retroarch"
    feats = probe_retroarch_features(binary)
    sys_ra = read_system_retroarch_defaults()

    remote_pad = settings.get("remote_pad", True)
    bridge_mode = settings.get("bridge_mode", "hybrid")
    use_uinput = remote_pad and check_uinput_ready()

    if video_driver_override:
        vdrv = video_driver_override
    elif sys_ra.get("video_driver"):
        vdrv = sys_ra["video_driver"]
    elif feats.get("sdl2", True):
        vdrv = "sdl2"
    elif feats.get("gl"):
        vdrv = "gl"
    else:
        vdrv = "sdl2"

    vctx = sys_ra.get("video_context_driver", "") if vdrv == sys_ra.get("video_driver") else ""

    if input_driver_override:
        idrv = input_driver_override
    elif sys_ra.get("input_driver"):
        idrv = sys_ra["input_driver"]
    else:
        idrv = "udev" if feats.get("udev", True) else ("sdl2" if feats.get("sdl2", True) else "linuxraw")

    if sys_ra.get("input_joypad_driver") and sys_ra["input_joypad_driver"] != "linuxraw":
        jdrv = sys_ra["input_joypad_driver"]
    else:
        jdrv = "sdl2" if feats.get("sdl2", True) else ("udev" if feats.get("udev") else "hid")

    if audio_driver_override:
        adrv = audio_driver_override
    elif sys_ra.get("audio_driver"):
        adrv = sys_ra["audio_driver"]
    else:
        adrv = "alsa" if feats.get("alsa", True) else ("sdl2" if feats.get("sdl2") else ("oss" if feats.get("oss") else "null"))

    if use_uinput and bridge_mode in ("gamepad", "hybrid"):
        generate_gamepad_autoconfig(jdrv)

    sys_dir = resolve_bios_dir(sys_cfg, rom_path)
    save_dir = "/media/hdd/retroarch/saves" if os.path.ismount("/media/hdd") else "/tmp/ra_saves"
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception:
        save_dir = "/tmp/ra_saves"
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception:
            pass

    res_map = {
        "720p": ("1280", "720"),
        "540p": ("960", "540"),
        "480p": ("720", "480"),
        "native": ("0", "0"),
    }
    res_preset = settings.get("ra_res_preset", "720p")
    fs_w, fs_h = res_map.get(res_preset, ("1280", "720"))

    speed_mode = settings.get("ra_speed_mode", "normal")
    threaded_v = bool(settings.get("ra_threaded_video", True))
    smooth_v = bool(settings.get("ra_video_smooth", False))
    frameskip_v = bool(settings.get("ra_frameskip", True))
    req_audio_sync = bool(settings.get("ra_audio_sync", True))
    req_vsync = bool(settings.get("ra_vsync", False))

    if speed_mode == "unthrottled":
        eff_audio_sync = False
        eff_vsync = False
        ff_ratio = "0.0"
        refresh_hz = "60.000000"
    elif speed_mode in ("turbo_125", "turbo_150", "turbo_200"):
        ratio_map = {"turbo_125": "1.25", "turbo_150": "1.5", "turbo_200": "2.0"}
        hz_map = {"turbo_125": "75.000000", "turbo_150": "90.000000", "turbo_200": "120.000000"}
        eff_audio_sync = (req_audio_sync and adrv != "null")
        eff_vsync = req_vsync
        if not eff_audio_sync and not eff_vsync:
            eff_vsync = True
        ff_ratio = ratio_map[speed_mode]
        refresh_hz = hz_map[speed_mode]
    else:
        # الوضع الطبيعي NORMAL (1.0x)
        eff_audio_sync = (req_audio_sync and adrv != "null")
        eff_vsync = req_vsync
        # ضمان عدم انطلاق السرعة بشكل جنوني إذا تعطّل الصوت والتزامن معاً
        if not eff_audio_sync and not eff_vsync:
            eff_vsync = True
        ff_ratio = "2.0"
        refresh_hz = "60.000000"

    lines = [
        'video_driver = "%s"' % vdrv,
        'video_context_driver = "%s"' % vctx,
        'video_fullscreen = "true"',
        'video_windowed_fullscreen = "true"',
        'video_fullscreen_x = "%s"' % fs_w,
        'video_fullscreen_y = "%s"' % fs_h,
        'video_vsync = "%s"' % ("true" if eff_vsync else "false"),
        'video_hard_sync = "false"',
        'video_smooth = "%s"' % ("true" if smooth_v else "false"),
        'video_threaded = "%s"' % ("true" if threaded_v else "false"),
        'video_refresh_rate = "%s"' % refresh_hz,
        'fastforward_ratio = "%s"' % ff_ratio,
        'fastforward_frameskip = "%s"' % ("true" if frameskip_v else "false"),
        'rewind_enable = "false"',
        'run_ahead_enabled = "false"',
        'pause_nonactive = "false"',
        'aspect_ratio_index = "1"',
        'menu_driver = "rgui"',
        'audio_driver = "%s"' % adrv,
        'audio_enable = "%s"' % ("false" if adrv == "null" else "true"),
        'audio_resampler = "nearest"',
        'audio_rate_control = "true"',
        'audio_max_timing_skew = "0.050000"',
        'audio_latency = "128"',
        'audio_sync = "%s"' % ("true" if eff_audio_sync else "false"),
        'input_driver = "%s"' % idrv,
        'input_joypad_driver = "%s"' % jdrv,
        'input_autodetect_enable = "true"',
        'joypad_autoconfig_dir = "%s"' % RA_AUTOCONFIG_DIR,
        'system_directory = "%s"' % sys_dir,
        'savefile_directory = "%s"' % save_dir,
        'savestate_directory = "%s"' % save_dir,
        'input_max_users = "2"',
        'input_poll_type_behavior = "0"',
        'input_libretro_device_p1 = "1"',
        'input_player1_analog_dpad_mode = "1"',
        'quit_press_twice = "false"',
        'config_save_on_exit = "false"',
        'input_exit_emulator = "escape"',
        'input_menu_toggle = "f1"',
        'input_save_state = "f2"',
        'input_load_state = "f4"',
        'input_toggle_fast_forward = "space"',
        'menu_swap_ok_cancel_buttons = "false"',
    ]

    if sys_ra.get("assets_directory"):
        lines.append('assets_directory = "%s"' % sys_ra["assets_directory"])
    if sys_ra.get("libretro_info_path"):
        lines.append('libretro_info_path = "%s"' % sys_ra["libretro_info_path"])

    if use_uinput:
        lines += [
            'input_player1_up = "up"',
            'input_player1_down = "down"',
            'input_player1_left = "left"',
            'input_player1_right = "right"',
            'input_player1_a = "x"',
            'input_player1_b = "z"',
            'input_player1_x = "s"',
            'input_player1_y = "a"',
            'input_player1_l = "q"',
            'input_player1_r = "w"',
            'input_player1_start = "enter"',
            'input_player1_select = "rshift"',
            'input_player1_turbo = "nul"',
            'input_enable_hotkey = "nul"',
        ]
    else:
        lines += [
            'input_player1_up = "up"',
            'input_player1_down = "down"',
            'input_player1_left = "left"',
            'input_player1_right = "right"',
            'input_player1_a = "num1"',
            'input_player1_b = "num2"',
            'input_player1_x = "num3"',
            'input_player1_y = "num4"',
            'input_player1_start = "num5"',
            'input_player1_select = "num0"',
            'input_player1_l = "num7"',
            'input_player1_r = "num8"',
        ]

    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return cfg_path


def build_ra_launch_cmd(sys_cfg, rom_path, settings=None):
    """يبني سكربت تشغيل مرن لـ RetroArch يجرب المشغّلات المتوافقة مع الجهاز تلقائياً عند الفشل."""
    settings = settings or {}
    binary = find_retroarch() or "retroarch"
    sys_ra = read_system_retroarch_defaults()

    cfg_sdl = generate_ra_cfg(
        settings, sys_cfg=sys_cfg, rom_path=rom_path,
        cfg_path=RA_CFG, video_driver_override="sdl2"
    )
    cfg_gl = "/tmp/retroarch_pro_gl.cfg"
    generate_ra_cfg(
        settings, sys_cfg=sys_cfg, rom_path=rom_path,
        cfg_path=cfg_gl, video_driver_override="gl"
    )
    cfg_safe = "/tmp/retroarch_pro_safe.cfg"
    safe_vdrv = sys_ra.get("video_driver") or ("gl" if probe_retroarch_features(binary).get("gl") else "sdl2")
    generate_ra_cfg(
        settings, sys_cfg=sys_cfg, rom_path=rom_path,
        cfg_path=cfg_safe, video_driver_override=safe_vdrv,
        audio_driver_override="null", input_driver_override="linuxraw"
    )

    core = resolve_core(sys_cfg)
    vprof = settings.get("video_profile", "auto")
    launcher_sh = "/tmp/tfk_ra_launch.sh"

    core_flag = ("-L %s" % shlex.quote(core)) if core else ""
    q_bin = shlex.quote(binary)
    q_cfg = shlex.quote(cfg_sdl)
    q_glcfg = shlex.quote(cfg_gl)
    q_safecfg = shlex.quote(cfg_safe)
    q_log = shlex.quote(RA_LOG)
    q_rom = shlex.quote(rom_path)

    if vprof == "fbcon":
        body = (
            "export SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 SDL_DYNAMIC_VIDEODRIVER=0 "
            "SDL_RENDER_DRIVER=software RETROARCH_DISABLE_GL=1\n"
            "exec %s -v -f -c %s %s %s >>%s 2>&1\n"
            % (q_bin, q_cfg, core_flag, q_rom, q_log)
        )
    elif vprof == "kmsdrm":
        body = (
            "unset RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
            "export SDL_VIDEODRIVER=kmsdrm\n"
            "exec %s -v -f -c %s %s %s >>%s 2>&1\n"
            % (q_bin, q_cfg, core_flag, q_rom, q_log)
        )
    elif vprof == "sdl2":
        body = (
            "unset SDL_VIDEODRIVER SDL_FBDEV SDL_DYNAMIC_VIDEODRIVER RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
            "exec %s -v -f -c %s %s %s >>%s 2>&1\n"
            % (q_bin, q_cfg, core_flag, q_rom, q_log)
        )
    elif vprof == "gl":
        body = (
            "unset SDL_VIDEODRIVER SDL_FBDEV SDL_DYNAMIC_VIDEODRIVER RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
            "exec %s -v -f -c %s %s %s >>%s 2>&1\n"
            % (q_bin, q_glcfg, core_flag, q_rom, q_log)
        )
    else:
        prefer_gl = (sys_ra.get("video_driver") in ("gl", "glcore"))
        first_gl_block = ""
        if prefer_gl:
            first_gl_block = (
                "echo '--- Attempt 0: System GL ---' >>%s\n"
                "unset SDL_VIDEODRIVER SDL_FBDEV SDL_DYNAMIC_VIDEODRIVER RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
                "run_ra %s\n"
                "RC=$?\n"
                % (q_log, q_glcfg)
            )
            fbcon_cond = "if [ \"$RC\" -ne 0 ] && [ \"$ELAPSED\" -le 3 ]; then\n"
        else:
            fbcon_cond = ""

        fbcon_attempt = (
            "echo '--- Attempt: SDL2 fbcon ---' >>%s\n"
            "SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 SDL_DYNAMIC_VIDEODRIVER=0 "
            "SDL_RENDER_DRIVER=software RETROARCH_DISABLE_GL=1 run_ra %s\n"
            "RC=$?\n"
            % (q_log, q_cfg)
        )
        if fbcon_cond:
            fbcon_block = fbcon_cond + fbcon_attempt + "fi\n"
        else:
            fbcon_block = fbcon_attempt

        body = (
            "trap 'killall -TERM retroarch 2>/dev/null; exit 0' TERM INT\n"
            "run_ra() {\n"
            "  T0=$(date +%%s 2>/dev/null || echo 0)\n"
            "  %s -v -f -c \"$1\" %s %s >>%s 2>&1\n"
            "  RC=$?\n"
            "  T1=$(date +%%s 2>/dev/null || echo 0)\n"
            "  case \"$T0$T1\" in\n"
            "    *[!0-9]*|'') ELAPSED=0 ;;\n"
            "    *) ELAPSED=$((T1 - T0)) ;;\n"
            "  esac\n"
            "  return $RC\n"
            "}\n"
            "%s"
            "%s"
            "# إذا فشل الإقلاع خلال 3 ثوانٍ نجرب المشغّلات البديلة تلقائياً\n"
            "if [ \"$RC\" -ne 0 ] && [ \"$ELAPSED\" -le 3 ]; then\n"
            "  echo '--- Fallback 1: Default SDL2 ---' >>%s\n"
            "  unset SDL_VIDEODRIVER SDL_FBDEV SDL_DYNAMIC_VIDEODRIVER RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
            "  run_ra %s\n"
            "  RC=$?\n"
            "fi\n"
            "if [ \"$RC\" -ne 0 ] && [ \"$ELAPSED\" -le 3 ]; then\n"
            "  echo '--- Fallback 2: KMSDRM ---' >>%s\n"
            "  unset RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
            "  SDL_VIDEODRIVER=kmsdrm run_ra %s\n"
            "  RC=$?\n"
            "fi\n"
            "if [ \"$RC\" -ne 0 ] && [ \"$ELAPSED\" -le 3 ]; then\n"
            "  echo '--- Fallback 3: Native OpenGL/GLES ---' >>%s\n"
            "  unset SDL_VIDEODRIVER SDL_FBDEV SDL_DYNAMIC_VIDEODRIVER RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
            "  run_ra %s\n"
            "  RC=$?\n"
            "fi\n"
            "if [ \"$RC\" -ne 0 ] && [ \"$ELAPSED\" -le 3 ]; then\n"
            "  echo '--- Fallback 4: Safe Audio-Null ---' >>%s\n"
            "  unset SDL_VIDEODRIVER SDL_FBDEV SDL_DYNAMIC_VIDEODRIVER RETROARCH_DISABLE_GL SDL_RENDER_DRIVER\n"
            "  run_ra %s\n"
            "  RC=$?\n"
            "fi\n"
            "exit $RC\n"
            % (q_bin, core_flag, q_rom, q_log,
               first_gl_block, fbcon_block,
               q_log, q_cfg, q_log, q_cfg, q_log, q_glcfg, q_log, q_safecfg)
        )

    scale_q = "1" if settings.get("ra_video_smooth", False) else "0"
    script = (
        "#!/bin/sh\n"
        "killall -9 retroarch 2>/dev/null\n"
        "mkdir -p /tmp/ra_home 2>/dev/null\n"
        ": > %s\n"
        "export SDL_AUDIODRIVER=alsa SDL_NOMOUSE=1 SDL_JOYSTICK_HIDAPI=0 "
        "SDL_RENDER_SCALE_QUALITY=%s HOME=/tmp/ra_home\n"
        "%s"
        % (q_log, scale_q, body)
    )
    try:
        with open(launcher_sh, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(launcher_sh, 0o755)
        return "sh %s" % shlex.quote(launcher_sh)
    except Exception:
        return "%s -v -f -c %s %s %s" % (q_bin, q_cfg, core_flag, q_rom)


# ============================================================================
#  مولّد الرسوميات السريع بالزوايا الدائرية
# ============================================================================
def _png_chunk(tag, data):
    return (struct.pack("!I", len(data)) + tag + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _write_rounded_png(path, w, h, r, bw, top_rgb, bot_rgb, border_rgb,
                       footer_rgb=None, footer_h=0, div_rgb=None, top_shine_rgb=None):
    if os.path.exists(path):
        return path
    w = max(4, int(w))
    h = max(4, int(h))
    r = max(0, min(int(r), w // 2, h // 2))
    bw = max(0, min(int(bw), r if r > 0 else min(w, h) // 2))
    footer_start = h - int(footer_h) if (footer_rgb and footer_h > 0) else h
    br_px = bytes([border_rgb[0], border_rgb[1], border_rgb[2], 255])
    rows = []
    for y in range(h):
        if footer_rgb and y == footer_start and div_rgb:
            cr, cg, cb = div_rgb
        elif footer_rgb and y >= footer_start:
            cr, cg, cb = footer_rgb
        elif top_shine_rgb and y == bw:
            cr, cg, cb = top_shine_rgb
        else:
            denom = max(1, footer_start - 1)
            t = min(1.0, y / float(denom))
            cr = int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * t)
            cg = int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * t)
            cb = int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * t)
        body_px = bytes([cr, cg, cb, 255])
        y_edge = y if y < r else (h - 1 - y if y >= h - r else -1)
        if y_edge == -1:
            if bw > 0:
                row = br_px * bw + body_px * (w - 2 * bw) + br_px * bw
            else:
                row = body_px * w
        else:
            left_list = []
            for x in range(r):
                d = math.hypot((r - 0.5) - x, (r - 0.5) - y_edge)
                outer_cov = max(0.0, min(1.0, r + 0.5 - d))
                if outer_cov <= 0.0:
                    left_list.append(b"\x00\x00\x00\x00")
                else:
                    if bw > 0:
                        bmix = max(0.0, min(1.0, d - ((r - bw) - 0.5)))
                        pr = int(cr * (1.0 - bmix) + border_rgb[0] * bmix)
                        pg = int(cg * (1.0 - bmix) + border_rgb[1] * bmix)
                        pb = int(cb * (1.0 - bmix) + border_rgb[2] * bmix)
                    else:
                        pr, pg, pb = cr, cg, cb
                    left_list.append(bytes([pr, pg, pb, int(round(255 * outer_cov))]))
            mid_w = w - 2 * r
            mid_px = (br_px * mid_w) if (bw > 0 and y_edge < bw) else (body_px * mid_w)
            row = b"".join(left_list) + mid_px + b"".join(reversed(left_list))
        rows.append(b"\x00" + row)

    ihdr = struct.pack("!IIBBBBB", w, h, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"".join(rows), 1)
    try:
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n"
                    + _png_chunk(b"IHDR", ihdr)
                    + _png_chunk(b"IDAT", idat)
                    + _png_chunk(b"IEND", b""))
    except Exception:
        pass
    return path


def ensure_ui_assets(w, h, theme):
    sx = w / 1920.0
    sy = h / 1080.0

    def X(v):
        return max(2, int(round(v * sx)))

    def Y(v):
        return max(2, int(round(v * sy)))

    def R(v):
        return max(2, int(round(v * min(sx, sy))))

    tid = theme["id"]
    cache_dir = "/tmp/tfk_panel_v10_%s_%dx%d" % (tid, w, h)
    os.makedirs(cache_dir, exist_ok=True)
    acc = theme["accent_rgb"]
    acc_shine = theme["accent_shine"]
    assets = {}

    assets["header"] = _write_rounded_png(
        os.path.join(cache_dir, "header.png"),
        X(1848), Y(94), R(18), R(2),
        theme["header_top"], theme["header_bot"], theme["header_border"],
        top_shine_rgb=theme["header_shine"])

    assets["pill_info"] = _write_rounded_png(
        os.path.join(cache_dir, "pill_info.png"),
        X(150), Y(60), R(14), R(1), theme["card_top"], theme["card_bot"], acc)

    assets["pill_ram"] = _write_rounded_png(
        os.path.join(cache_dir, "pill_ram.png"),
        X(176), Y(60), R(14), R(1),
        theme["sidebar_top"], theme["sidebar_bot"], theme["card_border"])

    assets["pill_temp"] = _write_rounded_png(
        os.path.join(cache_dir, "pill_temp.png"),
        X(116), Y(60), R(14), R(1),
        theme["sidebar_top"], theme["sidebar_bot"], theme["card_border"])

    assets["sidebar_box"] = _write_rounded_png(
        os.path.join(cache_dir, "sidebar_box.png"),
        X(346), Y(804), R(18), R(2),
        theme["sidebar_top"], theme["sidebar_bot"], theme["sidebar_border"])

    assets["side_norm"] = _write_rounded_png(
        os.path.join(cache_dir, "side_norm.png"),
        X(322), Y(76), R(14), R(1),
        theme["card_top"], theme["card_bot"], theme["card_border"])

    assets["side_active"] = _write_rounded_png(
        os.path.join(cache_dir, "side_active.png"),
        X(322), Y(76), R(14), R(1), theme["focus_bot"], theme["card_bot"], acc)

    assets["side_focus"] = _write_rounded_png(
        os.path.join(cache_dir, "side_focus.png"),
        X(322), Y(76), R(14), R(2), theme["focus_top"], theme["focus_bot"], acc,
        top_shine_rgb=acc_shine)

    assets["side_bar"] = _write_rounded_png(
        os.path.join(cache_dir, "side_bar.png"),
        X(8), Y(46), R(4), 0, acc, acc, acc)

    assets["card_norm"] = _write_rounded_png(
        os.path.join(cache_dir, "card_norm.png"),
        X(354), Y(256), R(18), R(2),
        theme["card_top"], theme["card_bot"], theme["card_border"],
        footer_rgb=theme["card_footer"], footer_h=Y(68), div_rgb=theme["card_border"])

    assets["card_focus"] = _write_rounded_png(
        os.path.join(cache_dir, "card_focus.png"),
        X(354), Y(256), R(18), R(3), theme["focus_top"], theme["focus_bot"], acc,
        footer_rgb=theme["card_footer"], footer_h=Y(68), div_rgb=acc,
        top_shine_rgb=acc_shine)

    assets["pill_inst"] = _write_rounded_png(
        os.path.join(cache_dir, "pill_inst.png"),
        X(116), Y(34), R(10), R(1), (6, 95, 70), (4, 72, 54), (52, 211, 153))

    assets["pill_ver"] = _write_rounded_png(
        os.path.join(cache_dir, "pill_ver.png"),
        X(116), Y(34), R(10), R(1),
        theme["card_top"], theme["card_bot"], theme["card_border"])

    assets["status_bar"] = _write_rounded_png(
        os.path.join(cache_dir, "status_bar.png"),
        X(1848), Y(46), R(12), R(1),
        theme["sidebar_top"], theme["sidebar_bot"], theme["sidebar_border"])

    btn_accents = {
        "red": (239, 68, 68),
        "green": (34, 197, 94),
        "yellow": (234, 179, 8),
        "blue": (59, 130, 246),
    }
    for key, rgb in btn_accents.items():
        assets["btn_%s" % key] = _write_rounded_png(
            os.path.join(cache_dir, "btn_%s.png" % key),
            X(447), Y(58), R(14), R(2), theme["card_top"], theme["card_bot"], rgb)
        assets["dot_%s" % key] = _write_rounded_png(
            os.path.join(cache_dir, "dot_%s.png" % key),
            X(18), Y(18), R(9), 0, rgb, rgb, rgb)

    for cat, (c1, c2, border_c) in CAT_BADGE_COLORS.items():
        assets["badge_%s" % cat] = _write_rounded_png(
            os.path.join(cache_dir, "badge_%s.png" % cat),
            X(136), Y(102), R(20), R(2), c1, c2, border_c, top_shine_rgb=border_c)

    assets["plugin_logo"] = ensure_plugin_icon()
    return assets


_PIXEL_FONT_5X7 = {
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


def _generate_taoufik_icon_png(path):
    """ينشئ أيقونة 260x130 مكتوب عليها TAOUFIK STORE عند عدم توفر plugin.png."""
    w, h, r, bw = 260, 130, 16, 3
    buf = bytearray(w * h * 4)

    def put_px(px, py, rgba):
        if 0 <= px < w and 0 <= py < h:
            idx = (py * w + px) * 4
            buf[idx:idx + 4] = bytes(rgba)

    for y in range(h):
        t = y / float(h - 1)
        cr = int(10 + 8 * t)
        cg = int(18 + 12 * t)
        cb = int(34 + 22 * t)
        for x in range(w):
            in_rx = (r - 0.5 - x) if x < r else ((x - (w - r - 0.5)) if x >= w - r else 0.0)
            in_ry = (r - 0.5 - y) if y < r else ((y - (h - r - 0.5)) if y >= h - r else 0.0)
            if in_rx > 0.0 and in_ry > 0.0:
                d = math.hypot(in_rx, in_ry)
                cov = max(0.0, min(1.0, r + 0.5 - d))
                if cov <= 0.0:
                    continue
                is_border = d >= (r - bw)
            else:
                cov = 1.0
                is_border = (x < bw or x >= w - bw or y < bw or y >= h - bw)
            if is_border:
                # تدرج سماوي-ذهبي أنيق للإطار
                bt = x / float(w - 1)
                br = int(56 + (251 - 56) * bt)
                bg = int(189 + (191 - 189) * bt)
                bb = int(248 + (36 - 248) * bt)
                put_px(x, y, (br, bg, bb, int(round(255 * cov))))
            else:
                put_px(x, y, (cr, cg, cb, int(round(255 * cov))))

    def draw_text(text, start_x, start_y, scale, rgb):
        cx = start_x
        for ch in text:
            glyph = _PIXEL_FONT_5X7.get(ch, _PIXEL_FONT_5X7[" "])
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == "1":
                        for sy in range(scale):
                            for sx in range(scale):
                                put_px(cx + gx * scale + sx, start_y + gy * scale + sy,
                                       (rgb[0], rgb[1], rgb[2], 255))
            cx += (5 * scale) + max(2, scale)

    # شعار عصا تحكم مصغّر يسار الأيقونة + اسم المتجر TAOUFIK STORE بالمنتصف/اليمين
    for yy in range(36, 94):
        for xx in range(20, 62):
            if math.hypot(xx - 41, yy - 65) <= 20:
                put_px(xx, yy, (14, 165, 233, 255))
            if math.hypot(xx - 41, yy - 65) <= 13:
                put_px(xx, yy, (15, 23, 42, 255))
            if math.hypot(xx - 41, yy - 65) <= 6:
                put_px(xx, yy, (251, 191, 36, 255))

    draw_text("TAOUFIK", 74, 24, 4, (248, 250, 252))
    draw_text("STORE", 86, 60, 4, (56, 189, 248))
    draw_text("ENIGMA2 PANEL", 88, 97, 2, (251, 191, 36))

    rows = [b"\x00" + bytes(buf[y * w * 4:(y + 1) * w * 4]) for y in range(h)]
    ihdr = struct.pack("!IIBBBBB", w, h, 8, 6, 0, 0, 0)
    idat = zlib.compress(b"".join(rows), 4)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + _png_chunk(b"IHDR", ihdr)
                + _png_chunk(b"IDAT", idat)
                + _png_chunk(b"IEND", b""))
    return path


def ensure_plugin_icon():
    """يرجع مسار أيقونة البانل plugin.png أو ينشئها تلقائياً باسم TAOUFIK STORE."""
    plugin_icon = os.path.join(PLUGIN_DIR, "plugin.png")
    try:
        if os.path.isfile(plugin_icon) and os.path.getsize(plugin_icon) > 500:
            return plugin_icon
    except Exception:
        pass
    try:
        return _generate_taoufik_icon_png(plugin_icon)
    except Exception:
        tmp_icon = "/tmp/tfk_taoufik_store_plugin.png"
        try:
            if os.path.isfile(tmp_icon) and os.path.getsize(tmp_icon) > 500:
                return tmp_icon
            return _generate_taoufik_icon_png(tmp_icon)
        except Exception:
            return ""


def ensure_welcome_assets(w, h, theme):
    sx = w / 1920.0
    sy = h / 1080.0

    def X(v):
        return max(2, int(round(v * sx)))

    def Y(v):
        return max(2, int(round(v * sy)))

    def R(v):
        return max(2, int(round(v * min(sx, sy))))

    cache_dir = "/tmp/tfk_panel_welcome_v7_%s_%dx%d" % (theme["id"], w, h)
    os.makedirs(cache_dir, exist_ok=True)
    acc = theme["accent_rgb"]
    acc_shine = theme["accent_shine"]
    return {
        "single_card": _write_rounded_png(
            os.path.join(cache_dir, "single_card.png"),
            X(1280), Y(590), R(28), R(3), theme["focus_top"], theme["card_bot"], acc,
            footer_rgb=theme["card_footer"], footer_h=Y(116), div_rgb=acc,
            top_shine_rgb=acc_shine),
        "tag_pill": _write_rounded_png(
            os.path.join(cache_dir, "tag_pill.png"),
            X(380), Y(68), R(18), R(2),
            theme["sidebar_top"], theme["sidebar_bot"], acc, top_shine_rgb=acc_shine),
        "timer_pill": _write_rounded_png(
            os.path.join(cache_dir, "timer_pill.png"),
            X(380), Y(74), R(18), R(2),
            theme["sidebar_top"], theme["sidebar_bot"], acc, top_shine_rgb=acc_shine),
    }


def build_responsive_skin(theme, num_categories):
    desktop = getDesktop(0).size()
    w, h = desktop.width(), desktop.height()
    sx = w / 1920.0
    sy = h / 1080.0

    def X(v):
        return int(round(v * sx))

    def Y(v):
        return int(round(v * sy))

    def F(v):
        return max(16, int(round(v * sy)))

    assets = ensure_ui_assets(w, h, theme)
    widgets = []

    logo_pixmap = assets.get("plugin_logo") or ""
    logo_widget = (
        '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" scale="1" zPosition="2" />'
        % (X(1704), Y(31), X(152), Y(76), logo_pixmap)
    ) if logo_pixmap and os.path.exists(logo_pixmap) else ""
    title_w = 552 if logo_widget else 716

    widgets.append(
        '<eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="-2" />'
        '<eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="-1" />'
        '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="0" />'
        '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="1" />'
        '<widget name="lbl_clock" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#e0f2fe" transparent="1" zPosition="2" />'
        '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="1" />'
        '<widget name="lbl_ram" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#94a3b8" transparent="1" zPosition="2" />'
        '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="1" />'
        '<widget name="lbl_temp" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#fbbf24" transparent="1" zPosition="2" />'
        '<widget name="lbl_counter" position="%d,%d" size="%d,%d" font="%s;%d" halign="left" valign="center" foregroundColor="%s" transparent="1" zPosition="2" />'
        '<widget name="lbl_title" position="%d,%d" size="%d,%d" font="%s;%d" halign="right" valign="center" foregroundColor="#f8fafc" transparent="1" zPosition="2" />'
        '%s'
        % (
            w, h, theme["bg"], w, Y(134), theme["header_bg"],
            X(36), Y(22), X(1848), Y(94), assets["header"],
            X(54), Y(39), X(150), Y(60), assets["pill_info"],
            X(54), Y(39), X(150), Y(60), PANEL_FONT, F(29),
            X(214), Y(39), X(176), Y(60), assets["pill_ram"],
            X(214), Y(39), X(176), Y(60), PANEL_FONT, F(23),
            X(400), Y(39), X(116), Y(60), assets["pill_temp"],
            X(400), Y(39), X(116), Y(60), PANEL_FONT, F(23),
            X(532), Y(35), X(600), Y(68), PANEL_FONT, F(26), theme["accent_hex"],
            X(1140), Y(31), X(title_w), Y(76), PANEL_FONT, F(36),
            logo_widget,
        )
    )

    widgets.append(
        '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="0" />'
        % (X(36), Y(132), X(346), Y(804), assets["sidebar_box"])
    )

    step_y = min(86, max(54, 774 // max(1, num_categories)))
    item_h = min(76, step_y - 8)
    for i in range(num_categories):
        sy_pos = 144 + i * step_y
        widgets.append(
            '<widget name="side_bg_%d" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="1" />'
            '<widget name="side_active_%d" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="2" />'
            '<widget name="side_count_%d" position="%d,%d" size="%d,%d" font="%s;%d" halign="left" valign="center" foregroundColor="#64748b" transparent="1" zPosition="3" />'
            '<widget name="side_lbl_%d" position="%d,%d" size="%d,%d" font="%s;%d" halign="right" valign="center" foregroundColor="#e2e8f0" transparent="1" zPosition="3" />'
            % (
                i, X(48), Y(sy_pos), X(322), Y(item_h),
                i, X(358), Y(sy_pos + 15), X(8), Y(max(24, item_h - 30)),
                i, X(62), Y(sy_pos), X(62), Y(item_h), PANEL_FONT, F(23),
                i, X(124), Y(sy_pos), X(224), Y(item_h), PANEL_FONT, F(29),
            )
        )

    for row in range(3):
        for col in range(4):
            idx = row * 4 + col
            cx = 402 + col * 376
            cy = 132 + row * 274
            widgets.append(
                '<widget name="card_bg_%d" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="1" />'
                '<widget name="card_fallback_bg_%d" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="2" />'
                '<widget name="card_fallback_%d" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#ffffff" transparent="1" zPosition="3" />'
                '<widget name="card_icon_%d" position="%d,%d" size="%d,%d" alphatest="blend" scale="1" zPosition="4" />'
                '<widget name="card_title_%d" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#f8fafc" transparent="1" zPosition="5" />'
                '<widget name="card_star_%d" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#fbbf24" transparent="1" zPosition="5" />'
                '<widget name="card_badge_bg_%d" position="%d,%d" size="%d,%d" alphatest="blend" zPosition="4" />'
                '<widget name="card_badge_%d" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#f8fafc" transparent="1" zPosition="5" />'
                % (
                    idx, X(cx), Y(cy), X(354), Y(256),
                    idx, X(cx + 109), Y(cy + 56), X(136), Y(102),
                    idx, X(cx + 109), Y(cy + 56), X(136), Y(102), PANEL_FONT, F(44),
                    idx, X(cx + 117), Y(cy + 46), X(120), Y(120),
                    idx, X(cx + 12), Y(cy + 188), X(330), Y(64), PANEL_FONT, F(26),
                    idx, X(cx + 296), Y(cy + 10), X(46), Y(44), PANEL_FONT, F(34),
                    idx, X(cx + 14), Y(cy + 14), X(116), Y(34),
                    idx, X(cx + 14), Y(cy + 14), X(116), Y(34), PANEL_FONT, F(20),
                )
            )

    widgets.append(
        '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="1" />'
        '<widget name="lbl_status" position="%d,%d" size="%d,%d" font="%s;%d" halign="right" valign="center" foregroundColor="#fbbf24" transparent="1" zPosition="2" />'
        % (X(36), Y(946), X(1848), Y(46), assets["status_bar"],
           X(56), Y(946), X(1808), Y(46), PANEL_FONT, F(25))
    )

    for name, bx in (("red", 36), ("green", 503), ("yellow", 970), ("blue", 1437)):
        widgets.append(
            '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="1" />'
            '<ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="2" />'
            '<widget name="key_%s" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#f8fafc" transparent="1" zPosition="3" />'
            % (X(bx), Y(1000), X(447), Y(58), assets["btn_" + name],
               X(bx + 398), Y(1020), X(18), Y(18), assets["dot_" + name],
               name, X(bx + 20), Y(1000), X(368), Y(58), PANEL_FONT, F(28))
        )

    skin_xml = (
        '<screen name="TFKPanelScreen" position="0,0" size="%d,%d" '
        'title="توفيق ستور TAOUFIK STORE" flags="wfNoBorder" backgroundColor="%s">\n'
        % (w, h, theme["bg"])
        + "\n".join(widgets) + "\n</screen>"
    )
    return skin_xml, assets


# ============================================================================
#  شاشة اختبار ومعايرة الريموت كعصا تحكم داخل Enigma2
# ============================================================================
class RemoteGamepadTesterScreen(Screen):
    """شاشة تفاعلية لاختبار الريموت كعصا تحكم حقيقية (Gamepad / uinput)."""
    def __init__(self, session, settings):
        self.settings = settings
        theme_idx = int(settings.get("theme_idx", DEFAULT_THEME_IDX)) % len(THEMES)
        theme = THEMES[theme_idx]
        acc_hex = theme["accent_hex"]

        desktop = getDesktop(0).size()
        w, h = desktop.width(), desktop.height()
        sx, sy = w / 1920.0, h / 1080.0

        def X(v):
            return int(round(v * sx))

        def Y(v):
            return int(round(v * sy))

        def F(v):
            return max(18, int(round(v * sy)))

        assets = ensure_welcome_assets(w, h, theme)
        self.skin = """
<screen name="RemoteGamepadTesterScreen" position="0,0" size="%d,%d" title="اختبار الريموت كعصا تحكم" flags="wfNoBorder" backgroundColor="%s">
    <eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="-2" />
    <ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="0" />
    <widget name="lbl_head" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="%s" transparent="1" zPosition="2" />
    <widget name="lbl_diag" position="%d,%d" size="%d,%d" font="%s;%d" halign="right" valign="top" foregroundColor="#e2e8f0" transparent="1" zPosition="2" />
    <widget name="lbl_live" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#34d399" transparent="1" zPosition="2" />
    <widget name="lbl_hint" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#fbbf24" transparent="1" zPosition="2" />
</screen>
""" % (
            w, h, theme["bg"], w, h, theme["bg"],
            X(320), Y(220), X(1280), Y(640), assets["single_card"],
            X(360), Y(250), X(1200), Y(74), PANEL_FONT, F(42), acc_hex,
            X(380), Y(340), X(1160), Y(240), PANEL_FONT, F(27),
            X(380), Y(600), X(1160), Y(100), PANEL_FONT, F(34),
            X(360), Y(735), X(1200), Y(90), PANEL_FONT, F(26),
        )
        Screen.__init__(self, session)
        self._watcher = None
        self._last_msg = "اضغط أي زر على الريموت لاختبار الاستجابة..."

        self["lbl_head"] = Label(shape_ar("الريموت كنترول كعصا تحكم — فحص واختبار فوري"))
        self["lbl_diag"] = Label("")
        self["lbl_live"] = Label(shape_ar(self._last_msg))
        self["lbl_hint"] = Label(shape_ar(
            "أحمر/خروج: رجوع  |  أصفر: تبديل وضع الأزرار  |  أزرق: تبديل وضع العصا"))

        self._refresh_timer = eTimer()
        if hasattr(self._refresh_timer, "callback"):
            self._refresh_timer.callback.append(self._refresh_status)
        else:
            self._refresh_timer.timeout.connect(self._refresh_status)

        self["actions"] = ActionMap(
            ["WizardActions", "DirectionActions", "ColorActions", "NumberActions", "MenuActions"],
            {
                "back": self.close_tester,
                "red": self.close_tester,
                "yellow": self._cycle_layout,
                "blue": self._cycle_stick_mode,
                "up": lambda: self._sim_press("UP -> عصا تحكم للأعلى (ABS_Y=-32767 / HAT0Y=-1)"),
                "down": lambda: self._sim_press("DOWN -> عصا تحكم للأسفل (ABS_Y=+32767 / HAT0Y=+1)"),
                "left": lambda: self._sim_press("LEFT -> عصا تحكم لليسار (ABS_X=-32767 / HAT0X=-1)"),
                "right": lambda: self._sim_press("RIGHT -> عصا تحكم لليمين (ABS_X=+32767 / HAT0X=+1)"),
                "ok": lambda: self._sim_press("OK -> زر START (BTN_START)"),
                "green": lambda: self._sim_press("GREEN -> زر B (BTN_EAST)"),
                "0": lambda: self._sim_press("0 -> زر SELECT / COIN (BTN_SELECT)"),
                "1": lambda: self._sim_press("1 -> زر A (BTN_SOUTH)"),
                "2": lambda: self._sim_press("2 -> زر B (BTN_EAST)"),
                "3": lambda: self._sim_press("3 -> زر X (BTN_NORTH)"),
                "4": lambda: self._sim_press("4 -> زر Y (BTN_WEST)"),
                "5": lambda: self._sim_press("5 -> زر START (BTN_START)"),
                "7": lambda: self._sim_press("7 -> زر L2 (BTN_TL2)"),
                "8": lambda: self._sim_press("8 -> زر R2 (BTN_TR2)"),
                "9": lambda: self._sim_press("9 -> قائمة المحاكي (BTN_MODE)"),
                "menu": lambda: self._sim_press("MENU -> قائمة المحاكي (BTN_MODE / F1)"),
            }, -1)

        self.onShown.append(self._on_shown)
        self.onClose.append(self._on_close)

    def _on_shown(self):
        self._start_preview_bridge()
        self._refresh_status()
        self._refresh_timer.start(700, False)

    def _on_close(self):
        try:
            self._refresh_timer.stop()
        except Exception:
            pass
        self._stop_preview_bridge()

    def _start_preview_bridge(self):
        self._stop_preview_bridge()
        if not is_global_gamepad_active() and check_uinput_ready():
            self._watcher = RemoteBridgeWatcher(
                get_pid_fn=None,
                enable_pad=True,
                layout=self.settings.get("remote_layout", "colors"),
                bridge_mode=self.settings.get("bridge_mode", "hybrid"),
                stick_mode=self.settings.get("stick_mode", "both"),
                allow_exit_kill=False,
                grab_remote=False,
            )
            self._watcher.start()

    def _stop_preview_bridge(self):
        if self._watcher:
            try:
                self._watcher.stop()
            except Exception:
                pass
            self._watcher = None

    def _sim_press(self, label):
        self._last_msg = label
        self["lbl_live"].setText(shape_ar(label))

    def _cycle_layout(self):
        cur = self.settings.get("remote_layout", "colors")
        self.settings["remote_layout"] = "numbers" if cur == "colors" else "colors"
        save_panel_settings(self.settings)
        self._start_preview_bridge()
        self._refresh_status()

    def _cycle_stick_mode(self):
        order = ("both", "analog", "dpad")
        cur = self.settings.get("stick_mode", "both")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "both"
        self.settings["stick_mode"] = nxt
        save_panel_settings(self.settings)
        self._start_preview_bridge()
        self._refresh_status()

    def _refresh_status(self):
        uinput_ok = "متوفر وجاهز ✓" if os.path.exists("/dev/uinput") else "غير متوفر ✗"
        js_nodes = get_joystick_nodes()
        js_txt = ", ".join("%s (%s)" % (os.path.basename(p), n) for p, n in js_nodes) or "جاري التهيئة..."
        lay = "الألوان" if self.settings.get("remote_layout", "colors") == "colors" else "الأرقام"
        bmode = {"gamepad": "عصا تحكم فقط", "keyboard": "لوحة مفاتيح", "hybrid": "هجين (عصا + لوحة)"}.get(
            self.settings.get("bridge_mode", "hybrid"), "هجين")
        smode = {"both": "أنالوج + D-Pad", "analog": "عصا أنالوج فقط", "dpad": "أسهم D-Pad فقط"}.get(
            self.settings.get("stick_mode", "both"), "أنالوج + D-Pad")
        diag = (
            "حالة نواة /dev/uinput: %s\n"
            "وضع الجسر: %s   •   نمط العصا: %s\n"
            "توزيع أزرار الريموت: %s\n"
            "أجهزة عصا التحكم النشطة: %s"
            % (uinput_ok, bmode, smode, lay, js_txt)
        )
        self["lbl_diag"].setText(shape_ar(diag))

    def close_tester(self):
        self.close()


# ============================================================================
#  واجهة الترحيب
# ============================================================================
class FirstLaunchWelcomeScreen(Screen):
    def __init__(self, session, seconds=WELCOME_SECONDS):
        settings = load_panel_settings()
        theme_idx = int(settings.get("theme_idx", DEFAULT_THEME_IDX)) % len(THEMES)
        theme = THEMES[theme_idx]
        acc_hex = theme["accent_hex"]
        acc_light = theme["accent_light"]

        desktop = getDesktop(0).size()
        w, h = desktop.width(), desktop.height()
        sx, sy = w / 1920.0, h / 1080.0

        def X(v):
            return int(round(v * sx))

        def Y(v):
            return int(round(v * sy))

        def F(v):
            return max(20, int(round(v * sy)))

        assets = ensure_welcome_assets(w, h, theme)
        logo_path = ensure_plugin_icon()
        welcome_logo_xml = (
            '\n    <ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" scale="1" zPosition="2" />'
            % (X(360), Y(274), X(176), Y(88), logo_path)
        ) if logo_path and os.path.exists(logo_path) else ""
        self.skin = """
<screen name="FirstLaunchWelcomeScreen" position="0,0" size="%d,%d" title="توفيق ستور TAOUFIK STORE" flags="wfNoBorder" backgroundColor="%s">
    <eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="-2" />
    <eLabel position="0,0" size="%d,%d" backgroundColor="%s" zPosition="4" />
    <ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="0" />%s
    <ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="1" />
    <widget name="card_badge" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="%s" transparent="1" zPosition="2" />
    <widget name="brand_title" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="%s" transparent="1" zPosition="2" />
    <widget name="brand_ar_title" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#f8fafc" transparent="1" zPosition="2" />
    <widget name="brand_sub" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="#cbd5e1" transparent="1" zPosition="2" />
    <widget name="status_lbl" position="%d,%d" size="%d,%d" font="%s;%d" halign="right" valign="center" foregroundColor="#e2e8f0" transparent="1" zPosition="2" />
    <ePixmap position="%d,%d" size="%d,%d" pixmap="%s" alphatest="blend" zPosition="1" />
    <widget name="countdown_lbl" position="%d,%d" size="%d,%d" font="%s;%d" halign="center" valign="center" foregroundColor="%s" transparent="1" zPosition="2" />
    <eLabel position="0,%d" size="%d,%d" backgroundColor="%s" zPosition="4" />
</screen>
""" % (
            w, h, theme["bg"], w, h, theme["bg"], w, Y(6), acc_hex,
            X(320), Y(245), X(1280), Y(590), assets["single_card"],
            welcome_logo_xml,
            X(770), Y(282), X(380), Y(68), assets["tag_pill"],
            X(770), Y(282), X(380), Y(68), PANEL_FONT, F(26), acc_light,
            X(360), Y(366), X(1200), Y(92), PANEL_FONT, F(64), acc_hex,
            X(380), Y(456), X(1160), Y(66), PANEL_FONT, F(40),
            X(390), Y(526), X(1140), Y(66), PANEL_FONT, F(29),
            X(360), Y(734), X(780), Y(78), PANEL_FONT, F(28),
            X(1175), Y(736), X(380), Y(74), assets["timer_pill"],
            X(1175), Y(736), X(380), Y(74), PANEL_FONT, F(31), acc_hex,
            Y(1074), w, Y(6), acc_hex,
        )
        Screen.__init__(self, session)
        self.remaining = max(1, int(seconds))
        self._closing_started = False
        self["card_badge"] = Label(shape_ar("مرحباً بك في المتجر"))
        self["brand_title"] = Label("TAOUFIK STORE")
        self["brand_ar_title"] = Label(shape_ar("توفيق ستور"))
        self["brand_sub"] = Label(shape_ar("إضافات وأدوات إنيغما 2 مع محاكي الجيل الذهبي والريموت كعصا تحكم"))
        self["status_lbl"] = Label(shape_ar("اضغط OK للدخول فوراً أو انتظر الفتح التلقائي"))
        self["countdown_lbl"] = Label(shape_ar("يفتح تلقائياً خلال %d ث" % self.remaining))

        self["actions"] = ActionMap(
            ["WizardActions", "ColorActions"],
            {
                "ok": self._begin_safe_close,
                "back": self._cancel_launch,
                "red": self._cancel_launch,
            }, -1)

        self._countdown_timer = eTimer()
        if hasattr(self._countdown_timer, "callback"):
            self._countdown_timer.callback.append(self._on_countdown_tick)
        else:
            self._countdown_timer.timeout.connect(self._on_countdown_tick)

        self._close_timer = eTimer()
        if hasattr(self._close_timer, "callback"):
            self._close_timer.callback.append(self._finish_close)
        else:
            self._close_timer.timeout.connect(self._finish_close)

        self.onShown.append(self._on_screen_shown)
        self.onClose.append(self._cleanup_timers)

    def _on_screen_shown(self):
        if self._closing_started:
            return
        self["countdown_lbl"].setText(shape_ar("يفتح تلقائياً خلال %d ث" % self.remaining))
        self._countdown_timer.start(1000, True)

    def _on_countdown_tick(self):
        if self._closing_started:
            return
        self.remaining -= 1
        if self.remaining > 0:
            self["countdown_lbl"].setText(shape_ar("يفتح تلقائياً خلال %d ث" % self.remaining))
            self._countdown_timer.start(1000, True)
        else:
            self["countdown_lbl"].setText(shape_ar("جاري فتح المتجر..."))
            self._begin_safe_close()

    def _cleanup_timers(self):
        for t in (self._countdown_timer, self._close_timer):
            try:
                t.stop()
            except Exception:
                pass

    def _cancel_launch(self):
        if self._closing_started:
            return
        self._closing_started = True
        self._cleanup_timers()
        self.close("cancel")

    def _begin_safe_close(self):
        if self._closing_started:
            return
        self._closing_started = True
        try:
            self._countdown_timer.stop()
        except Exception:
            pass
        self._close_timer.start(60, True)

    def _finish_close(self):
        try:
            self._close_timer.stop()
        except Exception:
            pass
        self.close("open_panel")


# ============================================================================
#  البانل الرئيسي
# ============================================================================
class TFKPanelScreen(Screen):
    def __init__(self, session):
        self.settings = load_panel_settings()
        self.theme_idx = int(self.settings.get("theme_idx", DEFAULT_THEME_IDX)) % len(THEMES)
        self.theme = THEMES[self.theme_idx]
        top_section = self.settings.get("top_section_key", DEFAULT_TOP_SECTION_KEY)
        self.categories = get_ordered_categories(top_section)
        self.skin, self.ui_assets = build_responsive_skin(self.theme, len(self.categories))
        Screen.__init__(self, session)

        self._layout_ready = False
        self._pix = {}
        self._icon_cache = {}
        self._color_cache = {}
        self.all_items = self._load_items()
        self.favorites = self._load_favorites()
        self.search_query = ""
        saved_cat_id = self.settings.get("last_cat_id", "")
        initial_cat_idx = next((idx for idx, c in enumerate(self.categories)
                                if c["id"] == saved_cat_id), 0)
        self.cat_index = initial_cat_idx
        self.sidebar_cursor = initial_cat_idx
        self.focus_area = "grid"
        self.page = 0
        self.grid_cursor = 0
        self.filtered_items = []

        self._remote_watcher = None
        self._user_exited_game = False
        self._ra_launch_ts = 0.0
        self._ra_output_buf = []
        self._pending_ra_cmd = None
        self._current_rom_info = {}
        self._prev_service = None
        self._rc_locked = False
        self._game_running = False
        self._launch_timer = eTimer()
        if hasattr(self._launch_timer, "callback"):
            self._launch_timer.callback.append(self._execute_pending_ra)
        else:
            self._launch_timer.timeout.connect(self._execute_pending_ra)

        self.ra_container = eConsoleAppContainer()
        try:
            if hasattr(self.ra_container.appClosed, "append"):
                self.ra_container.appClosed.append(self._on_ra_closed)
            elif hasattr(self.ra_container.appClosed, "get"):
                self.ra_container.appClosed.get().append(self._on_ra_closed)
            else:
                self.ra_container.appClosed.connect(self._on_ra_closed)
        except Exception:
            pass
        try:
            if hasattr(self.ra_container, "dataAvail"):
                if hasattr(self.ra_container.dataAvail, "append"):
                    self.ra_container.dataAvail.append(self._on_ra_data)
                elif hasattr(self.ra_container.dataAvail, "get"):
                    self.ra_container.dataAvail.get().append(self._on_ra_data)
                else:
                    self.ra_container.dataAvail.connect(self._on_ra_data)
        except Exception:
            pass

        self["lbl_title"] = Label(shape_ar("توفيق ستور  •  TAOUFIK STORE"))
        self["lbl_clock"] = Label(time.strftime("%H:%M"))
        self["lbl_ram"] = Label(get_free_ram_text())
        self["lbl_temp"] = Label(get_cpu_temp_text())
        self["lbl_counter"] = Label("")
        self["lbl_status"] = Label(shape_ar(
            "جاهز • OK للتثبيت أو التشغيل  |  MENU للخيارات  |  INFO للتفاصيل"))
        self["key_red"] = Label(shape_ar("خروج"))
        self["key_green"] = Label(shape_ar("تثبيت / تشغيل"))
        self["key_yellow"] = Label(shape_ar("بحث"))
        self["key_blue"] = Label(shape_ar("خيارات سريعة"))

        for i in range(len(self.categories)):
            self["side_bg_%d" % i] = Pixmap()
            self["side_active_%d" % i] = Pixmap()
            self["side_count_%d" % i] = Label("")
            self["side_lbl_%d" % i] = Label("")

        for i in range(12):
            self["card_bg_%d" % i] = Pixmap()
            self["card_fallback_bg_%d" % i] = Pixmap()
            self["card_fallback_%d" % i] = Label("")
            self["card_icon_%d" % i] = Pixmap()
            self["card_title_%d" % i] = Label("")
            self["card_star_%d" % i] = Label("")
            self["card_badge_bg_%d" % i] = Pixmap()
            self["card_badge_%d" % i] = Label("")

        self.clock_timer = eTimer()
        if hasattr(self.clock_timer, "callback"):
            self.clock_timer.callback.append(self._update_sys_bar)
        else:
            self.clock_timer.timeout.connect(self._update_sys_bar)
        self.clock_timer.start(15000, False)

        self["actions"] = ActionMap(
            ["WizardActions", "DirectionActions", "ColorActions",
             "ChannelSelectBaseActions", "NumberActions", "EPGSelectActions", "MenuActions"],
            {
                "ok": self.key_ok,
                "back": self.key_exit,
                "red": self.key_exit,
                "green": self.key_ok,
                "yellow": self.key_search,
                "blue": self.open_quick_menu,
                "menu": self.open_quick_menu,
                "up": self.key_up,
                "down": self.key_down,
                "left": self.key_left,
                "right": self.key_right,
                "upRepeated": self.key_up,
                "downRepeated": self.key_down,
                "leftRepeated": self.key_left,
                "rightRepeated": self.key_right,
                "nextBouquet": self.next_page,
                "prevBouquet": self.prev_page,
                "1": lambda: self._jump_category(0),
                "2": lambda: self._jump_category(1),
                "3": lambda: self._jump_category(2),
                "4": lambda: self._jump_category(3),
                "5": lambda: self._jump_category(4),
                "6": lambda: self._jump_category(5),
                "7": lambda: self._jump_category(6),
                "8": lambda: self._jump_category(7),
                "9": lambda: self._jump_category(8),
                "info": self.show_item_details,
            }, -1)

        self.onLayoutFinish.append(self._on_layout_finish)
        self.onClose.append(self._on_close)

    def _color(self, hex_str):
        c = self._color_cache.get(hex_str)
        if c is None:
            c = parseColor(hex_str)
            self._color_cache[hex_str] = c
        return c

    def _get_icon_pix(self, path):
        if path in self._icon_cache:
            return self._icon_cache[path]
        pix = LoadPixmap(path) if (path and os.path.exists(path)) else None
        self._icon_cache[path] = pix
        return pix

    def _persist_active_category(self):
        cur_cat = self.categories[self.cat_index]["id"]
        if self.settings.get("last_cat_id") != cur_cat:
            self.settings["last_cat_id"] = cur_cat
            save_panel_settings(self.settings)

    def _on_close(self):
        self._persist_active_category()
        try:
            self._launch_timer.stop()
        except Exception:
            pass
        self._pending_ra_cmd = None
        self._stop_remote_watcher()
        if self._game_running:
            try:
                self.ra_container.kill()
            except Exception:
                pass
            os.system("killall -TERM retroarch 2>/dev/null")
        self._restore_after_game()
        try:
            self.clock_timer.stop()
        except Exception:
            pass

    def _update_sys_bar(self):
        self["lbl_clock"].setText(time.strftime("%H:%M"))
        self["lbl_ram"].setText(get_free_ram_text())
        self["lbl_temp"].setText(get_cpu_temp_text())

    def _on_layout_finish(self):
        self._layout_ready = True
        for key, path in self.ui_assets.items():
            self._pix[key] = LoadPixmap(path)
        side_bar_pix = self._pix.get("side_bar")
        for i in range(len(self.categories)):
            if side_bar_pix and self["side_active_%d" % i].instance:
                self["side_active_%d" % i].instance.setPixmap(side_bar_pix)
        for i in range(12):
            if self["card_icon_%d" % i].instance:
                self["card_icon_%d" % i].instance.setScale(1)
        self._apply_filter()
        self._render_all()

    def _load_items(self):
        base = None
        for path in (EXTERNAL_DATA_FILE, LOCAL_DATA_FILE):
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list) and data:
                        base = list(data)
                        break
                except Exception:
                    pass
        if base is None:
            base = list(DEFAULT_ITEMS)
        for sys_cfg in GOLDEN_SYSTEMS:
            base.extend(scan_golden_roms(sys_cfg["id"], sys_cfg["exts"]))
        return base

    def _load_favorites(self):
        if os.path.exists(FAVS_FILE):
            try:
                with open(FAVS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return set(data)
            except Exception:
                pass
        return set()

    def _save_favorites(self):
        try:
            os.makedirs(os.path.dirname(FAVS_FILE), exist_ok=True)
            with open(FAVS_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self.favorites)), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _is_installed(self, item):
        itype = item.get("type", "")
        if itype == "retro_launcher":
            sys_cfg = get_golden_system(item.get("sys_id", ""))
            return bool(find_retroarch() and resolve_core(sys_cfg))
        if itype == "retro_rom":
            return bool(find_retroarch() and os.path.isfile(item.get("path", "")))
        if itype == "global_gamepad":
            return is_global_gamepad_active()
        if itype in ("remote_setup", "gamepad_tester"):
            return os.path.exists("/dev/uinput")
        check_path = item.get("check_path", "")
        return bool(check_path and os.path.exists(check_path))

    def _count_for_category(self, cat_id):
        return sum(1 for x in self.all_items if x.get("category") == cat_id)

    def _apply_filter(self):
        cat_id = self.categories[self.cat_index]["id"]
        q = self.search_query.strip().lower()
        result = []
        for item in self.all_items:
            if q:
                haystack = "%s %s %s" % (item.get("name", ""), item.get("desc", ""),
                                         item.get("short", ""))
                if q not in haystack.lower():
                    continue
            if item.get("category") == cat_id:
                result.append(item)
        self.filtered_items = result
        total_pages = max(1, (len(self.filtered_items) + 11) // 12)
        if self.page >= total_pages:
            self.page = 0
        self._clamp_grid_cursor()

    def _page_items(self):
        start = self.page * 12
        return self.filtered_items[start:start + 12]

    def _clamp_grid_cursor(self):
        count = len(self._page_items())
        if count == 0:
            self.grid_cursor = 0
        elif self.grid_cursor >= count:
            self.grid_cursor = count - 1

    def _render_all(self):
        if not self._layout_ready:
            return
        self._render_header()
        self._render_sidebar()
        self._render_grid()

    def _render_header(self):
        cat_title = self.categories[self.cat_index]["title"]
        total_items = len(self.filtered_items)
        total_pages = max(1, (total_items + 11) // 12)
        bmode = self.settings.get("bridge_mode", "hybrid").upper()
        pad_flag = ("JOY:%s" % bmode[:3]) if self.settings.get("remote_pad", True) else "JOY:OFF"
        if is_global_gamepad_active():
            pad_flag += "+BG"
        if self.search_query:
            info = "بحث: %s  •  %d نتيجة  |  %d/%d" % (
                self.search_query, total_items, self.page + 1, total_pages)
            self["key_yellow"].setText(shape_ar("إلغاء البحث"))
        else:
            info = "[%s] %s  •  %d عنصر  |  صفحة %d/%d" % (
                pad_flag, cat_title, total_items, self.page + 1, total_pages)
            self["key_yellow"].setText(shape_ar("بحث"))
        self["lbl_counter"].setText(shape_ar(info))

    def _render_sidebar(self):
        acc_hex = self.theme["accent_hex"]
        acc_light = self.theme["accent_light"]
        for i, cat in enumerate(self.categories):
            lbl = self["side_lbl_%d" % i]
            cnt = self["side_count_%d" % i]
            bg = self["side_bg_%d" % i]
            lbl.setText(shape_ar(cat["title"]))
            cnt.setText(str(self._count_for_category(cat["id"])))
            is_active = (i == self.cat_index)
            is_focused = (self.focus_area == "sidebar" and i == self.sidebar_cursor)
            if is_focused:
                pix = self._pix.get("side_focus")
            elif is_active:
                pix = self._pix.get("side_active")
            else:
                pix = self._pix.get("side_norm")
            if pix and bg.instance:
                bg.instance.setPixmap(pix)
            if is_active:
                self["side_active_%d" % i].show()
            else:
                self["side_active_%d" % i].hide()
            if lbl.instance:
                lbl.instance.setForegroundColor(
                    self._color(acc_hex if (is_active or is_focused) else "#e2e8f0"))
            if cnt.instance:
                cnt.instance.setForegroundColor(
                    self._color(acc_light if (is_active or is_focused) else "#64748b"))

    def _update_card_selection(self, idx, selected):
        items = self._page_items()
        if idx < 0 or idx >= len(items):
            return
        bg_w = self["card_bg_%d" % idx]
        pix = self._pix.get("card_focus" if selected else "card_norm")
        if pix and bg_w.instance:
            bg_w.instance.setPixmap(pix)
        title_w = self["card_title_%d" % idx]
        if title_w.instance:
            title_w.instance.setForegroundColor(
                self._color(self.theme["accent_hex"] if selected else "#f8fafc"))

    def _update_status_bar(self):
        items = self._page_items()
        if self.focus_area == "grid" and items:
            cur = items[self.grid_cursor]
            ver = cur.get("version", "")
            status_txt = "%s %s  —  %s   |   MENU خيارات • INFO تفاصيل" % (
                cur.get("name", ""), ("v" + ver) if ver else "", cur.get("desc", ""))
            self["lbl_status"].setText(shape_ar(status_txt))
        elif self.focus_area == "sidebar":
            self["lbl_status"].setText(shape_ar(
                "القسم: %s  •  اضغط OK أو يمين للدخول للشبكة (1-9 للانتقال السريع)"
                % self.categories[self.sidebar_cursor]["title"]))
        else:
            self["lbl_status"].setText(shape_ar("لا توجد عناصر مطابقة في هذا القسم"))

    def _render_grid(self):
        items = self._page_items()
        for i in range(12):
            if i >= len(items):
                for prefix in ("card_bg_", "card_fallback_bg_", "card_fallback_",
                               "card_icon_", "card_title_", "card_star_",
                               "card_badge_bg_", "card_badge_"):
                    self["%s%d" % (prefix, i)].hide()
                continue
            item = items[i]
            is_selected = (self.focus_area == "grid" and i == self.grid_cursor)
            self["card_bg_%d" % i].show()
            self["card_title_%d" % i].show()
            self["card_star_%d" % i].hide()
            self["card_title_%d" % i].setText(shape_ar(item.get("name", "")))
            self._update_card_selection(i, is_selected)

            installed = self._is_installed(item)
            ver = item.get("version", "")
            badge_bg = self["card_badge_bg_%d" % i]
            badge_lbl = self["card_badge_%d" % i]
            if installed:
                pix_pill = self._pix.get("pill_inst")
                if pix_pill and badge_bg.instance:
                    badge_bg.instance.setPixmap(pix_pill)
                lbl_txt = "نشط ✓" if item.get("type") == "global_gamepad" else "مثبت ✓"
                badge_lbl.setText(shape_ar(lbl_txt))
                if badge_lbl.instance:
                    badge_lbl.instance.setForegroundColor(self._color("#ecfdf5"))
                badge_bg.show()
                badge_lbl.show()
            elif ver:
                pix_pill = self._pix.get("pill_ver")
                if pix_pill and badge_bg.instance:
                    badge_bg.instance.setPixmap(pix_pill)
                badge_lbl.setText("v%s" % ver)
                if badge_lbl.instance:
                    badge_lbl.instance.setForegroundColor(self._color("#cbd5e1"))
                badge_bg.show()
                badge_lbl.show()
            else:
                badge_bg.hide()
                badge_lbl.hide()

            icon_rel = item.get("icon", "")
            icon_path = os.path.join(PLUGIN_DIR, icon_rel) if icon_rel else ""
            pix = self._get_icon_pix(icon_path)
            if pix and self["card_icon_%d" % i].instance:
                self["card_icon_%d" % i].instance.setPixmap(pix)
                self["card_icon_%d" % i].show()
                self["card_fallback_bg_%d" % i].hide()
                self["card_fallback_%d" % i].hide()
            else:
                self["card_icon_%d" % i].hide()
                cat_key = item.get("category", "system")
                pix_badge = self._pix.get("badge_%s" % cat_key) or self._pix.get("badge_system")
                if pix_badge and self["card_fallback_bg_%d" % i].instance:
                    self["card_fallback_bg_%d" % i].instance.setPixmap(pix_badge)
                self["card_fallback_bg_%d" % i].show()
                short = (item.get("short") or item.get("name", "E2")[:3]).upper()
                self["card_fallback_%d" % i].setText(short)
                self["card_fallback_%d" % i].show()
        self._update_status_bar()

    def _jump_category_by_id(self, cat_id):
        idx = next((i for i, c in enumerate(self.categories) if c.get("id") == cat_id), None)
        if idx is not None:
            self._jump_category(idx)

    def _jump_category(self, idx):
        if 0 <= idx < len(self.categories):
            self.cat_index = idx
            self.sidebar_cursor = idx
            self.page = 0
            self.grid_cursor = 0
            self._persist_active_category()
            self._apply_filter()
            self._render_all()

    def _move_grid_cursor(self, new_idx):
        old_idx = self.grid_cursor
        if old_idx == new_idx:
            return
        self.grid_cursor = new_idx
        self._update_card_selection(old_idx, False)
        self._update_card_selection(new_idx, True)
        self._update_status_bar()

    def key_up(self):
        if self.focus_area == "sidebar":
            self.sidebar_cursor = (self.sidebar_cursor - 1) % len(self.categories)
            self.cat_index = self.sidebar_cursor
            self.page = 0
            self._persist_active_category()
            self._apply_filter()
            self._render_all()
        else:
            if self.grid_cursor // 4 > 0:
                self._move_grid_cursor(self.grid_cursor - 4)
            elif self.page > 0:
                self.page -= 1
                self.grid_cursor = min(len(self._page_items()) - 1, 8 + (self.grid_cursor % 4))
                self._render_all()

    def key_down(self):
        if self.focus_area == "sidebar":
            self.sidebar_cursor = (self.sidebar_cursor + 1) % len(self.categories)
            self.cat_index = self.sidebar_cursor
            self.page = 0
            self._persist_active_category()
            self._apply_filter()
            self._render_all()
        else:
            items = self._page_items()
            if not items:
                return
            if self.grid_cursor + 4 < len(items):
                self._move_grid_cursor(self.grid_cursor + 4)
            else:
                total_pages = max(1, (len(self.filtered_items) + 11) // 12)
                if self.page + 1 < total_pages:
                    self.page += 1
                    col = self.grid_cursor % 4
                    self.grid_cursor = min(len(self._page_items()) - 1, col)
                    self._render_all()

    def key_left(self):
        if self.focus_area == "grid":
            if self.grid_cursor % 4 > 0:
                self._move_grid_cursor(self.grid_cursor - 1)
            else:
                self.focus_area = "sidebar"
                self.sidebar_cursor = self.cat_index
                self._update_card_selection(self.grid_cursor, False)
                self._render_sidebar()
                self._update_status_bar()

    def key_right(self):
        if self.focus_area == "sidebar":
            if self._page_items():
                self.focus_area = "grid"
                self.grid_cursor = 0
                self._render_sidebar()
                self._update_card_selection(0, True)
                self._update_status_bar()
        else:
            items = self._page_items()
            if (self.grid_cursor % 4) < 3 and self.grid_cursor + 1 < len(items):
                self._move_grid_cursor(self.grid_cursor + 1)

    def next_page(self):
        total_pages = max(1, (len(self.filtered_items) + 11) // 12)
        if self.page + 1 < total_pages:
            self.page += 1
            self.grid_cursor = 0
            self._render_all()

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.grid_cursor = 0
            self._render_all()

    def toggle_favorite(self):
        if self.focus_area != "grid":
            return
        items = self._page_items()
        if not items:
            return
        item_id = items[self.grid_cursor].get("id")
        if not item_id:
            return
        if item_id in self.favorites:
            self.favorites.remove(item_id)
        else:
            self.favorites.add(item_id)
        self._save_favorites()
        self._apply_filter()
        self._render_all()

    def show_item_details(self):
        if self.focus_area != "grid":
            return
        items = self._page_items()
        if not items:
            return
        item = items[self.grid_cursor]
        itype = item.get("type", "")
        if itype in ("retro_launcher", "retro_rom"):
            sys_cfg = get_golden_system(item.get("sys_id", ""))
            core = resolve_core(sys_cfg) if sys_cfg else None
            pad_on = self.settings.get("remote_pad", True)
            lay = "الألوان" if self.settings.get("remote_layout", "colors") == "colors" else "الأرقام"
            bmode = self.settings.get("bridge_mode", "hybrid")
            details = (
                "الاسم: %s\nالمحاكي: RetroArch\nالمنصة: %s\nالنواة: %s\n"
                "الريموت كعصا تحكم: %s (%s / %s)\nuinput: %s\nالمسار: %s\n\nالوصف:\n%s"
                % (item.get("name", ""),
                   sys_cfg["name"] if sys_cfg else item.get("sys_id", ""),
                   os.path.basename(core) if core else "غير متوفرة",
                   "مفعّل" if pad_on else "معطّل", bmode, lay,
                   "متوفر ✓" if os.path.exists("/dev/uinput") else "غير متوفر ✗",
                   item.get("path") or item.get("check_path") or "-",
                   item.get("desc", ""))
            )
            self.session.open(MessageBox, shape_ar(details), MessageBox.TYPE_INFO)
            return
        status = "مثبت على الجهاز ✓" if self._is_installed(item) else "غير مثبت"
        cat_name = next((c["title"] for c in self.categories
                         if c["id"] == item.get("category")), item.get("category", ""))
        details = (
            "الاسم: %s\nالإصدار: %s\nالتصنيف: %s\nالحالة: %s\nالمسار: %s\n\nالوصف:\n%s"
            % (item.get("name", ""), item.get("version", "-"), cat_name, status,
               item.get("check_path") or "-", item.get("desc", ""))
        )
        self.session.open(MessageBox, shape_ar(details), MessageBox.TYPE_INFO)

    def key_search(self):
        if self.search_query:
            self.search_query = ""
            self.page = 0
            self.grid_cursor = 0
            self._apply_filter()
            self._render_all()
            return
        self.session.openWithCallback(
            self._on_search_cb, VirtualKeyBoard,
            title=shape_ar("ابحث عن إضافة أو سكن أو لعبة:"), text="")

    def _on_search_cb(self, result):
        if result is None:
            return
        self.search_query = result.strip()
        self.page = 0
        self.grid_cursor = 0
        self._apply_filter()
        self._render_all()

    def open_quick_menu(self):
        pad_state = "مفعّل ✓" if self.settings.get("remote_pad", True) else "معطّل ✗"
        bg_state = "نشط ✓" if is_global_gamepad_active() else "متوقف"
        lay_state = "الألوان" if self.settings.get("remote_layout", "colors") == "colors" else "الأرقام"
        bmode_lbl = {
            "gamepad": "عصا تحكم فقط (Gamepad)",
            "keyboard": "لوحة مفاتيح (Keyboard)",
            "hybrid": "هجين (عصا تحكم + اختصارات)",
        }.get(self.settings.get("bridge_mode", "hybrid"), "هجين")
        smode_lbl = {
            "both": "أنالوج + D-Pad",
            "analog": "عصا أنالوج فقط",
            "dpad": "أسهم D-Pad فقط",
        }.get(self.settings.get("stick_mode", "both"), "أنالوج + D-Pad")
        vprof = self.settings.get("video_profile", "auto")

        menu = [
            (shape_ar("إعدادات سرعة الصورة والأداء (NORMAL / Fast)"), "ra_perf_menu"),
            (shape_ar("تشغيل/إيقاف عصا التحكم الدائمة للنظام: %s" % bg_state), "toggle_global_pad"),
            (shape_ar("فتح شاشة اختبار ومعايرة عصا التحكم"), "open_tester"),
            (shape_ar("الريموت كعصا تحكم بالألعاب: %s" % pad_state), "toggle_pad"),
            (shape_ar("وضع الجسر: %s (اضغط للتبديل)" % bmode_lbl), "cycle_bridge_mode"),
            (shape_ar("نمط العصا: %s (اضغط للتبديل)" % smode_lbl), "cycle_stick_mode"),
            (shape_ar("توزيع أزرار الريموت: %s (اضغط للتبديل)" % lay_state), "toggle_layout"),
            (shape_ar("ملف الفيديو لـ RetroArch: %s" % vprof), "cycle_video_profile"),
            (shape_ar("عرض خريطة أزرار الريموت كعصا تحكم"), "show_map"),
            (shape_ar("فحص وتجهيز uinput للريموت"), "fix_uinput"),
            (shape_ar("تغيير ثيم الواجهة (الحالي: %s)" % self.theme["name"]), "theme"),
            (shape_ar("تحديث بيانات وعناصر المتجر والـ ROMs"), "refresh"),
            (shape_ar("تثبيت القسم الحالي في أعلى القائمة"), "pin_top"),
            (shape_ar("استعادة الترتيب الافتراضي للأقسام"), "reset_top"),
            (shape_ar("تحديث السيرفرات المجانية فوراً (NCam/OSCam)"), "free_srv"),
            (shape_ar("إعادة تشغيل إيمو NCam / OSCam"), "softcam"),
            (shape_ar("إنشاء مجلدات ألعاب الجيل الذهبي (ROMs)"), "mk_roms"),
            (shape_ar("عرض سجل محاكي RetroArch الأخير"), "ra_log"),
            (shape_ar("حفظ نسخة احتياطية للإعدادات"), "backup"),
            (shape_ar("استعادة النسخة الاحتياطية المحفوظة"), "restore"),
            (shape_ar("تنظيف الذاكرة العشوائية RAM والكاش"), "clean_ram"),
            (shape_ar("تشخيص شامل للنظام والشبكة والقرص والمحاكي"), "box_info"),
            (shape_ar("إعادة تشغيل واجهة Enigma2 (GUI)"), "restart_gui"),
            (shape_ar("إعادة تشغيل الرسيفر بالكامل"), "reboot_box"),
        ]
        self.session.openWithCallback(
            self._on_quick_menu_cb, ChoiceBox,
            title=shape_ar("قائمة التحكم السريعة — توفيق ستور TAOUFIK STORE"), list=menu)

    def _toggle_global_gamepad_action(self):
        if is_global_gamepad_active():
            stop_global_gamepad()
            self._render_all()
            self.session.open(
                MessageBox, shape_ar("تم إيقاف عصا التحكم الدائمة للنظام."),
                MessageBox.TYPE_INFO, timeout=3)
        else:
            ok = start_global_gamepad(self.settings)
            self._render_all()
            if ok:
                js_nodes = get_joystick_nodes()
                js_info = ", ".join(p for p, _ in js_nodes) if js_nodes else "uinput جاهز"
                self.session.open(
                    MessageBox,
                    shape_ar("تم تفعيل الريموت كعصا تحكم دائمة للنظام ✓\n(%s)" % js_info),
                    MessageBox.TYPE_INFO, timeout=4)
            else:
                self.session.open(
                    MessageBox,
                    shape_ar("تعذر تفعيل /dev/uinput.\nاستخدم خيار: فحص وتجهيز uinput"),
                    MessageBox.TYPE_ERROR, timeout=5)

    def _on_quick_menu_cb(self, choice):
        if not choice:
            return
        act = choice[1]
        if act == "ra_perf_menu":
            self.open_ra_perf_menu()
        elif act == "toggle_global_pad":
            self._toggle_global_gamepad_action()
        elif act == "open_tester":
            self.session.openWithCallback(
                lambda *a: self._render_all(),
                RemoteGamepadTesterScreen, self.settings)
        elif act == "toggle_pad":
            self.settings["remote_pad"] = not self.settings.get("remote_pad", True)
            save_panel_settings(self.settings)
            if self.settings["remote_pad"]:
                check_uinput_ready()
            self._render_all()
            self.session.open(
                MessageBox,
                shape_ar("الريموت كعصا تحكم: %s" % ("مفعّل ✓" if self.settings["remote_pad"] else "معطّل ✗")),
                MessageBox.TYPE_INFO, timeout=3)
        elif act == "cycle_bridge_mode":
            order = ("hybrid", "gamepad", "keyboard")
            cur = self.settings.get("bridge_mode", "hybrid")
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "hybrid"
            self.settings["bridge_mode"] = nxt
            save_panel_settings(self.settings)
            if is_global_gamepad_active():
                start_global_gamepad(self.settings)
            self._render_all()
            self.session.open(
                MessageBox, shape_ar("وضع جسر الريموت: %s" % nxt),
                MessageBox.TYPE_INFO, timeout=3)
        elif act == "cycle_stick_mode":
            order = ("both", "analog", "dpad")
            cur = self.settings.get("stick_mode", "both")
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "both"
            self.settings["stick_mode"] = nxt
            save_panel_settings(self.settings)
            if is_global_gamepad_active():
                start_global_gamepad(self.settings)
            self.session.open(
                MessageBox, shape_ar("نمط عصا التحكم: %s" % nxt),
                MessageBox.TYPE_INFO, timeout=3)
        elif act == "cycle_video_profile":
            order = ("auto", "fbcon", "kmsdrm", "sdl2", "gl")
            cur = self.settings.get("video_profile", "auto")
            nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "auto"
            self.settings["video_profile"] = nxt
            save_panel_settings(self.settings)
            self.session.open(
                MessageBox, shape_ar("ملف فيديو RetroArch: %s" % nxt),
                MessageBox.TYPE_INFO, timeout=3)
        elif act == "toggle_layout":
            cur = self.settings.get("remote_layout", "colors")
            self.settings["remote_layout"] = "numbers" if cur == "colors" else "colors"
            save_panel_settings(self.settings)
            if is_global_gamepad_active():
                start_global_gamepad(self.settings)
            self._show_remote_map()
        elif act == "show_map":
            self._show_remote_map()
        elif act == "fix_uinput":
            self.session.openWithCallback(
                self._on_console_done, Console,
                title=shape_ar("فحص وتجهيز uinput"), cmdlist=[UINPUT_FIX_CMD])
        elif act == "theme":
            self._choose_theme()
        elif act == "refresh":
            self.key_update_panel()
        elif act == "pin_top":
            top_id = self.categories[self.cat_index]["id"]
            self.settings["top_section_key"] = top_id
            self.settings["last_cat_id"] = top_id
            save_panel_settings(self.settings)
            self.close("reopen")
        elif act == "reset_top":
            self.settings["top_section_key"] = DEFAULT_TOP_SECTION_KEY
            self.settings["last_cat_id"] = DEFAULT_TOP_SECTION_KEY
            save_panel_settings(self.settings)
            self.close("reopen")
        elif act == "free_srv":
            self.session.openWithCallback(
                self._on_console_done, Console,
                title=shape_ar("TFK Free Server Live Engine"),
                cmdlist=[build_free_server_command()])
        elif act == "softcam":
            self.session.openWithCallback(
                self._on_console_done, Console,
                title=shape_ar("إعادة تشغيل الإيمو"), cmdlist=[SOFTCAM_RESTART_CMD])
        elif act == "mk_roms":
            folders = ensure_golden_rom_folders()
            self.all_items = self._load_items()
            self._apply_filter()
            self._render_all()
            msg = ("تم تجهيز مجلدات الـ ROMs:\n" + "\n".join(folders)) if folders else "تعذر إنشاء المجلدات."
            self.session.open(MessageBox, shape_ar(msg), MessageBox.TYPE_INFO)
        elif act == "ra_log":
            self._show_ra_log()
        elif act == "backup":
            self._backup_panel_data()
        elif act == "restore":
            self._restore_panel_data()
        elif act == "clean_ram":
            self.session.openWithCallback(
                self._on_console_done, Console,
                title=shape_ar("تنظيف الذاكرة العشوائية RAM"), cmdlist=[CLEAN_RAM_CMD])
        elif act == "box_info":
            self._show_box_info()
        elif act == "restart_gui":
            self._confirm_power_action(3, "هل تريد إعادة تشغيل واجهة Enigma2 الآن؟")
        elif act == "reboot_box":
            self._confirm_power_action(2, "هل تريد إعادة تشغيل الرسيفر بالكامل الآن؟")

    def open_ra_perf_menu(self):
        speed_labels = {
            "normal": "NORMAL (طبيعي 1.0x)",
            "turbo_125": "سريع خفيف (1.25x)",
            "turbo_150": "سريع متوسط (1.5x)",
            "turbo_200": "سريع مضاعف (2.0x)",
            "unthrottled": "أقصى سرعة (بدون قيد التزامن)",
        }
        res_labels = {
            "720p": "720p (متوازن وسريع — موصى به)",
            "540p": "540p (خفيف — يقلل التقل)",
            "480p": "480p (أقصى خفة وسرعة)",
            "native": "أصلي (دقة التلفاز الكاملة)",
        }
        sp = self.settings.get("ra_speed_mode", "normal")
        rp = self.settings.get("ra_res_preset", "720p")
        th = "مفعّل ✓" if self.settings.get("ra_threaded_video", True) else "معطّل ✗"
        fs = "مفعّل ✓" if self.settings.get("ra_frameskip", True) else "معطّل ✗"
        asyn = "مفعّل (NORMAL)" if self.settings.get("ra_audio_sync", True) else "معطّل (تخفيف التقل)"
        vs = "مفعّل ✓" if self.settings.get("ra_vsync", False) else "معطّل (أسرع)"
        sm = "ناعم" if self.settings.get("ra_video_smooth", False) else "حاد وسريع (إيقاف التنعيم)"
        vp = self.settings.get("video_profile", "auto")

        choices = [
            (shape_ar("سرعة اللعبة: %s" % speed_labels.get(sp, "NORMAL")), "speed"),
            (shape_ar("دقة الصورة (لتخفيف التقل): %s" % res_labels.get(rp, rp)), "res"),
            (shape_ar("المعالجة المتوازية (Threaded Video): %s" % th), "threaded"),
            (shape_ar("تخطي الإطارات التلقائي (Frameskip): %s" % fs), "frameskip"),
            (shape_ar("تزامن الصوت والسرعة (Audio Sync): %s" % asyn), "audiosync"),
            (shape_ar("مزامنة الشاشة (VSync): %s" % vs), "vsync"),
            (shape_ar("فلتر تنعيم الصورة (Smooth): %s" % sm), "smooth"),
            (shape_ar("مشغّل الفيديو (Video Driver): %s" % vp), "vprof"),
            (shape_ar("استعادة الوضع الطبيعي المثالي (NORMAL)"), "reset_normal"),
            (shape_ar("حفظ وإغلاق"), "done"),
        ]
        self.session.openWithCallback(
            self._on_ra_perf_cb, ChoiceBox,
            title=shape_ar("إعدادات سرعة الصورة والأداء — توفيق ستور"),
            list=choices,
        )

    def _on_ra_perf_cb(self, choice):
        if not choice or choice[1] == "done":
            return
        act = choice[1]
        if act == "speed":
            order = ("normal", "turbo_125", "turbo_150", "turbo_200", "unthrottled")
            cur = self.settings.get("ra_speed_mode", "normal")
            self.settings["ra_speed_mode"] = order[(order.index(cur) + 1) % len(order)] if cur in order else "normal"
        elif act == "res":
            order = ("720p", "540p", "480p", "native")
            cur = self.settings.get("ra_res_preset", "720p")
            self.settings["ra_res_preset"] = order[(order.index(cur) + 1) % len(order)] if cur in order else "720p"
        elif act == "threaded":
            self.settings["ra_threaded_video"] = not self.settings.get("ra_threaded_video", True)
        elif act == "frameskip":
            self.settings["ra_frameskip"] = not self.settings.get("ra_frameskip", True)
        elif act == "audiosync":
            self.settings["ra_audio_sync"] = not self.settings.get("ra_audio_sync", True)
        elif act == "vsync":
            self.settings["ra_vsync"] = not self.settings.get("ra_vsync", False)
        elif act == "smooth":
            self.settings["ra_video_smooth"] = not self.settings.get("ra_video_smooth", False)
        elif act == "vprof":
            order = ("auto", "fbcon", "kmsdrm", "sdl2", "gl")
            cur = self.settings.get("video_profile", "auto")
            self.settings["video_profile"] = order[(order.index(cur) + 1) % len(order)] if cur in order else "auto"
        elif act == "reset_normal":
            self.settings["ra_speed_mode"] = "normal"
            self.settings["ra_res_preset"] = "720p"
            self.settings["ra_threaded_video"] = True
            self.settings["ra_frameskip"] = True
            self.settings["ra_audio_sync"] = True
            self.settings["ra_vsync"] = False
            self.settings["ra_video_smooth"] = False
            save_panel_settings(self.settings)
            self.session.openWithCallback(
                lambda *a: self.open_ra_perf_menu(),
                MessageBox,
                shape_ar("تمت استعادة الإعدادات على الوضع الطبيعي السلس (NORMAL 720p) ✓"),
                MessageBox.TYPE_INFO, timeout=2,
            )
            return

        save_panel_settings(self.settings)
        self.open_ra_perf_menu()

    def _show_remote_map(self):
        txt = (REMOTE_MAP_HELP_COLORS
               if self.settings.get("remote_layout", "colors") == "colors"
               else REMOTE_MAP_HELP_NUMBERS)
        self.session.open(MessageBox, shape_ar(txt), MessageBox.TYPE_INFO)

    def _show_ra_log(self):
        if not os.path.isfile(RA_LOG):
            self.session.open(MessageBox,
                              shape_ar("لا يوجد سجل تشغيل لمحاكي RetroArch حتى الآن."),
                              MessageBox.TYPE_INFO, timeout=4)
            return
        try:
            with open(RA_LOG, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().strip().splitlines()[-14:]
            content = "\n".join(lines) if lines else "السجل فارغ."
        except Exception as e:
            content = "تعذر قراءة السجل:\n%s" % e
        self.session.open(MessageBox, shape_ar("آخر أسطر سجل RetroArch:\n\n%s" % content),
                          MessageBox.TYPE_INFO)

    def _backup_panel_data(self):
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            copied = []
            for src in (SETTINGS_FILE, FAVS_FILE, EXTERNAL_DATA_FILE):
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(BACKUP_DIR, os.path.basename(src)))
                    copied.append(os.path.basename(src))
            msg = ("تم حفظ النسخة الاحتياطية في:\n%s\n\nالملفات: %s"
                   % (BACKUP_DIR, ", ".join(copied))) if copied else \
                  "لا توجد ملفات إعدادات أو مفضلة لحفظها حالياً."
            self.session.open(MessageBox, shape_ar(msg), MessageBox.TYPE_INFO, timeout=5)
        except Exception as e:
            self.session.open(MessageBox, shape_ar("فشل حفظ النسخة الاحتياطية:\n%s" % e),
                              MessageBox.TYPE_ERROR)

    def _restore_panel_data(self):
        if not os.path.isdir(BACKUP_DIR):
            self.session.open(MessageBox,
                              shape_ar("لا توجد نسخة احتياطية محفوظة في /tmp/pro_panel_backup."),
                              MessageBox.TYPE_INFO, timeout=4)
            return
        try:
            restored = []
            mapping = {
                "pro_panel_settings.json": SETTINGS_FILE,
                "pro_panel_favs.json": FAVS_FILE,
                "pro_panel_items.json": EXTERNAL_DATA_FILE,
            }
            for fname, dst in mapping.items():
                src = os.path.join(BACKUP_DIR, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    restored.append(fname)
            if not restored:
                self.session.open(MessageBox, shape_ar("مجلد النسخة الاحتياطية فارغ."),
                                  MessageBox.TYPE_INFO, timeout=4)
                return
            self.settings = load_panel_settings()
            self.favorites = self._load_favorites()
            self.all_items = self._load_items()
            self.session.open(
                MessageBox,
                shape_ar("تمت استعادة الملفات: %s\nسيتم إعادة فتح البانل لتطبيق الإعدادات."
                         % ", ".join(restored)),
                MessageBox.TYPE_INFO, timeout=3)
            self.close("reopen")
        except Exception as e:
            self.session.open(MessageBox, shape_ar("فشل استعادة النسخة الاحتياطية:\n%s" % e),
                              MessageBox.TYPE_ERROR)

    def _choose_theme(self):
        choices = [(shape_ar("%s%s" % ("✓ " if i == self.theme_idx else "", t["name"])), i)
                   for i, t in enumerate(THEMES)]
        self.session.openWithCallback(self._on_theme_picked, ChoiceBox,
                                      title=shape_ar("اختر ثيم الواجهة المفضل:"), list=choices)

    def _on_theme_picked(self, choice):
        if not choice:
            return
        new_idx = int(choice[1])
        if new_idx == self.theme_idx:
            return
        self.settings["theme_idx"] = new_idx
        save_panel_settings(self.settings)
        self.close("reopen")

    def _show_box_info(self):
        found_cores = []
        for sys_cfg in GOLDEN_SYSTEMS:
            c = resolve_core(sys_cfg)
            if c:
                found_cores.append("%s: %s" % (sys_cfg["name"], os.path.basename(c)))
        cores_txt = " | ".join(found_cores) if found_cores else "لا توجد أنوية مكتشفة"
        cam_cfg = ("NCam" if os.path.exists("/etc/tuxbox/config/ncam.server")
                   else ("OSCam" if os.path.exists("/etc/tuxbox/config/oscam.server") else "غير محدد"))
        ra_bin = find_retroarch()
        pad_on = self.settings.get("remote_pad", True)
        lay = "الألوان" if self.settings.get("remote_layout", "colors") == "colors" else "الأرقام"
        js_nodes = get_joystick_nodes()
        js_txt = ", ".join(os.path.basename(p) for p, _ in js_nodes) if js_nodes else "غير نشط"
        info = (
            "عنوان الشبكة (IP): %s\nالذاكرة المتاحة: %s  •  الحرارة: %s\nالتخزين: %s\n"
            "ملف الإيمو المكتشف: %s\nمحاكي RetroArch: %s\nالأنوية: %s\n"
            "uinput: %s  •  أجهزة Joystick: %s\n"
            "الريموت كعصا تحكم: %s (%s / %s)"
            % (get_local_ip(), get_free_ram_text(), get_cpu_temp_text(), get_hdd_summary(),
               cam_cfg, ("مثبت (%s)" % ra_bin) if ra_bin else "غير مثبت", cores_txt,
               "متوفر ✓" if os.path.exists("/dev/uinput") else "غير متوفر ✗", js_txt,
               "مفعّل" if pad_on else "معطّل", self.settings.get("bridge_mode", "hybrid"),
               lay)
        )
        self.session.open(MessageBox, shape_ar(info), MessageBox.TYPE_INFO)

    def _confirm_power_action(self, mode, question):
        def _do_power(ans):
            if not ans:
                return
            if TryQuitMainloop is not None:
                self.session.open(TryQuitMainloop, mode)
            else:
                os.system("killall -9 enigma2" if mode == 3 else "reboot")
        self.session.openWithCallback(_do_power, MessageBox, shape_ar(question),
                                      MessageBox.TYPE_YESNO)

    def key_update_panel(self):
        self._icon_cache.clear()
        self.all_items = self._load_items()
        self._update_sys_bar()
        self._apply_filter()
        self._render_all()
        self.session.open(
            MessageBox,
            shape_ar("تم تحديث بيانات وعناصر توفيق ستور TAOUFIK STORE بنجاح."),
            MessageBox.TYPE_INFO, timeout=3)

    def _open_golden_system_roms(self, sys_id):
        sys_cfg = get_golden_system(sys_id)
        if not sys_cfg:
            return
        if not find_retroarch():
            self.session.openWithCallback(
                lambda ans: self.session.open(
                    Console, title=shape_ar("تثبيت RetroArch"),
                    cmdlist=["opkg update && opkg install retroarch"]) if ans else None,
                MessageBox,
                shape_ar("محاكي RetroArch غير مثبت.\nهل تريد تثبيته الآن؟"),
                MessageBox.TYPE_YESNO)
            return
        if not resolve_core(sys_cfg):
            self.session.open(
                MessageBox,
                shape_ar("النواة المطلوبة لنظام %s غير موجودة:\n%s"
                         % (sys_cfg["name"], "\n".join(sys_cfg["cores"]))),
                MessageBox.TYPE_ERROR)
            return
        roms = scan_golden_roms(sys_cfg["id"], sys_cfg["exts"])
        if not roms:
            self.session.open(
                MessageBox,
                shape_ar("لم يتم العثور على ألعاب %s في:\n%s"
                         % (sys_cfg["name"], "\n".join(golden_rom_dirs(sys_cfg["id"])))),
                MessageBox.TYPE_INFO)
            return
        choices = [(shape_ar(r["name"]), r) for r in roms]
        self.session.openWithCallback(
            lambda picked: self._launch_golden_rom(picked[1], sys_cfg)
            if (picked and isinstance(picked[1], dict)) else None,
            ChoiceBox, title=shape_ar("ألعاب %s (RetroArch):" % sys_cfg["name"]), list=choices)

    def _stop_remote_watcher(self):
        w = self._remote_watcher
        self._remote_watcher = None
        if w:
            try:
                w.stop()
            except Exception:
                pass

    def _restore_after_game(self):
        if self._rc_locked:
            try:
                eRCInput.getInstance().unlock()
            except Exception:
                pass
            self._rc_locked = False
        if self._game_running:
            self._game_running = False
            try:
                self.show()
            except Exception:
                pass
            if self._prev_service is not None:
                try:
                    self.session.nav.playService(self._prev_service)
                except Exception:
                    pass
                self._prev_service = None

    def _on_ra_data(self, data):
        try:
            txt = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
            for line in txt.splitlines():
                line = line.strip()
                if line:
                    self._ra_output_buf.append(line)
                    if len(self._ra_output_buf) > 30:
                        self._ra_output_buf = self._ra_output_buf[-30:]
        except Exception:
            pass

    def _has_bios_file(self, sys_cfg, rom_path):
        bios_file = (sys_cfg or {}).get("bios_file")
        if not bios_file:
            return True
        bdir = resolve_bios_dir(sys_cfg, rom_path)
        return os.path.isfile(os.path.join(bdir, bios_file))

    def _launch_golden_rom(self, rom_item, sys_cfg, skip_bios_warn=False):
        rom_path = rom_item.get("path", "")
        if not rom_path or not os.path.isfile(rom_path):
            self.session.open(MessageBox, shape_ar("ملف اللعبة غير موجود."),
                              MessageBox.TYPE_ERROR)
            return
        if self._game_running:
            return

        if not skip_bios_warn and sys_cfg.get("bios_required") and not self._has_bios_file(sys_cfg, rom_path):
            bios_file = sys_cfg.get("bios_file", "neogeo.zip")
            self.session.openWithCallback(
                lambda ans: self._launch_golden_rom(rom_item, sys_cfg, skip_bios_warn=True) if ans else None,
                MessageBox,
                shape_ar("تنبيه: ملف البيوس (%s) غير موجود في مجلد الألعاب:\n%s\n\n"
                         "بدون هذا الملف قد يخرج المحاكي فوراً.\nهل تريد المتابعة على أي حال؟"
                         % (bios_file, os.path.dirname(rom_path))),
                MessageBox.TYPE_YESNO)
            return

        # إيقاف الجسر العالمي مؤقتاً لمنع تضارب أجهزة uinput أثناء اللعبة
        was_global = is_global_gamepad_active()
        if was_global:
            stop_global_gamepad()
        self._restore_global_after_game = was_global

        pad_on = self.settings.get("remote_pad", True) and check_uinput_ready()
        cmd = build_ra_launch_cmd(sys_cfg, rom_path, self.settings)
        core_used = resolve_core(sys_cfg) or "Auto"
        self._current_rom_info = {
            "name": rom_item.get("name", os.path.basename(rom_path)),
            "rom": rom_path,
            "core": core_used,
            "bios": "متوفر ✓" if self._has_bios_file(sys_cfg, rom_path) else "غير موجود ✗",
        }

        try:
            self._prev_service = self.session.nav.getCurrentlyPlayingServiceReference()
            self.session.nav.stopService()
        except Exception:
            self._prev_service = None
        try:
            eRCInput.getInstance().lock()
            self._rc_locked = True
        except Exception:
            self._rc_locked = False

        self._user_exited_game = False
        self._ra_output_buf = []
        self._ra_launch_ts = time.time()
        self._game_running = True
        try:
            self.hide()
        except Exception:
            pass

        def _mark_user_exit():
            self._user_exited_game = True

        # تشغيل عصا التحكم الافتراضية قبل إقلاع RetroArch حتى يتعرف عليها فوراً
        self._remote_watcher = RemoteBridgeWatcher(
            get_pid_fn=lambda: self.ra_container.getPID() if self.ra_container else 0,
            enable_pad=pad_on,
            layout=self.settings.get("remote_layout", "colors"),
            bridge_mode=self.settings.get("bridge_mode", "hybrid"),
            stick_mode=self.settings.get("stick_mode", "both"),
            allow_exit_kill=True,
            grab_remote=bool(self.settings.get("grab_remote", False)),
            on_exit_cb=_mark_user_exit,
        )
        self._remote_watcher.start()

        # منح Enigma2 180ms لإخفاء الواجهة وتحرير موارد الصوت/الفيديو وتسجيل uinput قبل بدء RetroArch
        self._pending_ra_cmd = cmd
        try:
            self._launch_timer.start(180 if pad_on else 100, True)
        except Exception:
            self._execute_pending_ra()

    def _execute_pending_ra(self):
        cmd = self._pending_ra_cmd
        self._pending_ra_cmd = None
        if not cmd or not self._game_running:
            return
        self._ra_launch_ts = time.time()
        try:
            rc = self.ra_container.execute(cmd)
            if isinstance(rc, int) and rc < 0:
                raise RuntimeError("execute failed (%s)" % rc)
        except Exception as e:
            self._stop_remote_watcher()
            self._restore_after_game()
            self.session.open(MessageBox, shape_ar("تعذر تشغيل المحاكي:\n%s" % e),
                              MessageBox.TYPE_ERROR)

    def _on_ra_closed(self, retval):
        try:
            self._launch_timer.stop()
        except Exception:
            pass
        self._pending_ra_cmd = None
        elapsed = time.time() - (self._ra_launch_ts or time.time())
        user_exited = self._user_exited_game or (
            self._remote_watcher and self._remote_watcher.user_exited
        )
        self._stop_remote_watcher()
        self._restore_after_game()
        if getattr(self, "_restore_global_after_game", False):
            self._restore_global_after_game = False
            start_global_gamepad(self.settings)
        try:
            self._update_sys_bar()
            self._render_all()
        except Exception:
            pass
        if not user_exited and (retval not in (0, None) or elapsed < 2.5):
            raw_lines = []
            if os.path.isfile(RA_LOG):
                try:
                    with open(RA_LOG, "r", encoding="utf-8", errors="ignore") as f:
                        raw_lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
                except Exception:
                    pass
            if not raw_lines and self._ra_output_buf:
                raw_lines = list(self._ra_output_buf)

            err_keywords = ("error", "fail", "cannot", "fatal", "unsupported",
                            "not found", "missing", "no such", "segmentation", "abort")
            key_lines = [ln for ln in raw_lines if any(k in ln.lower() for k in err_keywords)]
            tail_lines = (key_lines[-6:] + raw_lines[-6:]) if key_lines else raw_lines[-10:]
            seen = set()
            clean_lines = []
            for ln in tail_lines:
                if ln not in seen:
                    seen.add(ln)
                    clean_lines.append(ln)

            rinfo = self._current_rom_info or {}
            header = "اللعبة: %s\nالنواة: %s  •  BIOS: %s" % (
                rinfo.get("name", "-"),
                os.path.basename(rinfo.get("core", "-")),
                rinfo.get("bios", "-"),
            )
            tail = "\n".join(clean_lines) if clean_lines else (
                "خرج المحاكي سريعاً بدون سجل مفصل.\n"
                "جرّب تغيير ملف الفيديو من القائمة السريعة (MENU ← ملف الفيديو: gl/fbcon/kmsdrm/sdl2)."
            )
            self.session.open(
                MessageBox,
                shape_ar("أغلق RetroArch (رمز %s):\n%s\n\n%s" % (retval, header, tail)),
                MessageBox.TYPE_ERROR)

    def key_ok(self):
        if self.focus_area == "sidebar":
            self.cat_index = self.sidebar_cursor
            self.page = 0
            self._persist_active_category()
            self._apply_filter()
            if self._page_items():
                self.focus_area = "grid"
                self.grid_cursor = 0
            self._render_all()
            return

        items = self._page_items()
        if not items:
            return
        item = items[self.grid_cursor]
        itype = item.get("type", "opkg")

        if itype == "restart_gui":
            self._confirm_power_action(3, "هل تريد إعادة تشغيل واجهة Enigma2 الآن؟")
            return
        if itype == "reboot_box":
            self._confirm_power_action(2, "هل تريد إعادة تشغيل الرسيفر بالكامل الآن؟")
            return
        if itype == "gamepad_tester":
            self.session.openWithCallback(
                lambda *a: self._render_all(),
                RemoteGamepadTesterScreen, self.settings)
            return
        if itype == "ra_perf_settings":
            self.open_ra_perf_menu()
            return
        if itype == "global_gamepad":
            self._toggle_global_gamepad_action()
            return
        if itype == "remote_setup":
            self.session.openWithCallback(
                self._on_console_done, Console,
                title=shape_ar("فحص وتجهيز uinput للريموت"), cmdlist=[UINPUT_FIX_CMD])
            return
        if itype == "retro_launcher":
            self._open_golden_system_roms(item.get("sys_id", ""))
            return
        if itype == "retro_rom":
            sys_cfg = get_golden_system(item.get("sys_id", ""))
            if not sys_cfg:
                return
            if not find_retroarch():
                self.session.open(MessageBox, shape_ar("محاكي RetroArch غير مثبت."),
                                  MessageBox.TYPE_ERROR)
                return
            if not resolve_core(sys_cfg):
                self.session.open(
                    MessageBox,
                    shape_ar("النواة المطلوبة لنظام %s غير موجودة." % sys_cfg["name"]),
                    MessageBox.TYPE_ERROR)
                return
            self.session.openWithCallback(
                lambda ans: self._launch_golden_rom(item, sys_cfg) if ans else None,
                MessageBox,
                shape_ar("تشغيل لعبة %s عبر RetroArch؟\n(الريموت كعصا تحكم: %s)"
                         % (item.get("name", ""),
                            "مفعّل" if self.settings.get("remote_pad", True) else "معطّل")),
                MessageBox.TYPE_YESNO)
            return
        if itype == "free_server":
            try:
                self.session.openWithCallback(
                    self._on_console_done, Console,
                    title=shape_ar("TFK Free Server Live Engine"),
                    cmdlist=[build_free_server_command()])
            except Exception as e:
                self.session.open(
                    MessageBox, shape_ar("خطأ في إنشاء ملف التشغيل المؤقت:\n%s" % e),
                    MessageBox.TYPE_ERROR)
            return

        if self._is_installed(item) and itype == "opkg" and item.get("package"):
            choices = [
                (shape_ar("إعادة التثبيت / التحديث"), "install"),
                (shape_ar("إلغاء التثبيت (حذف الإضافة)"), "remove"),
                (shape_ar("إلغاء"), "cancel"),
            ]
            self.session.openWithCallback(
                lambda choice: self._on_installed_action(choice, item), ChoiceBox,
                title=shape_ar("%s مثبتة بالفعل:" % item.get("name", "")), list=choices)
        else:
            self.session.openWithCallback(
                lambda answer: self._confirm_install(answer, item), MessageBox,
                shape_ar("هل تريد تنفيذ تثبيت/تشغيل:\n%s ؟" % item.get("name", "")),
                MessageBox.TYPE_YESNO)

    def _on_installed_action(self, choice, item):
        if not choice:
            return
        action = choice[1]
        if action == "install":
            self._confirm_install(True, item)
        elif action == "remove":
            pkg = item.get("package", "")
            if pkg:
                self.session.openWithCallback(
                    self._on_console_done, Console,
                    title=shape_ar("جاري حذف: %s" % item.get("name", "")),
                    cmdlist=["opkg remove %s" % shlex.quote(pkg)])

    def _confirm_install(self, answer, item):
        if not answer:
            return
        itype = item.get("type", "opkg")
        if itype == "opkg":
            pkg = item.get("package", "")
            cmd = ("opkg update && opkg install %s" % shlex.quote(pkg)) if pkg else ""
        elif itype == "ipk":
            url = item.get("url", "")
            cmd = ("wget -q --no-check-certificate -O /tmp/panel_pkg.ipk %s && "
                   "opkg install --force-overwrite /tmp/panel_pkg.ipk && "
                   "rm -f /tmp/panel_pkg.ipk" % shlex.quote(url)) if url else ""
        elif itype == "script":
            cmd = item.get("cmd", "")
        else:
            cmd = ""
        if not cmd:
            self.session.open(MessageBox,
                              shape_ar("لا يوجد أمر تثبيت معرف لهذا العنصر."),
                              MessageBox.TYPE_INFO, timeout=4)
            return
        self.session.openWithCallback(
            self._on_console_done, Console,
            title=shape_ar("جاري تنفيذ: %s" % item.get("name", "")), cmdlist=[cmd])

    def _on_console_done(self, *args):
        self._update_sys_bar()
        self._apply_filter()
        self._render_all()

    def key_exit(self):
        if self.search_query:
            self.search_query = ""
            self.page = 0
            self.grid_cursor = 0
            self._apply_filter()
            self._render_all()
            return
        self.close()


# ============================================================================
#  نقاط الدخول
# ============================================================================
def _open_panel_loop(session):
    def _cb(result=None):
        if result == "reopen":
            _open_panel_loop(session)
    session.openWithCallback(_cb, TFKPanelScreen)


def _after_welcome_cb(session, result=None):
    if result == "open_panel":
        _open_panel_loop(session)


def main(session, **kwargs):
    check_uinput_ready()
    session.openWithCallback(
        lambda res=None: _after_welcome_cb(session, res),
        FirstLaunchWelcomeScreen, seconds=WELCOME_SECONDS)


def Plugins(**kwargs):
    ensure_plugin_icon()
    icon_file = os.path.join(PLUGIN_DIR, "plugin.png")
    return [
        PluginDescriptor(
            name="توفيق ستور TAOUFIK STORE",
            description="توفيق ستور TAOUFIK STORE - إضافات وأدوات إنيغما 2 مع محاكي RetroArch والريموت كعصا تحكم",
            where=[PluginDescriptor.WHERE_PLUGINMENU,
                   PluginDescriptor.WHERE_EXTENSIONSMENU],
            icon="plugin.png" if os.path.exists(icon_file) else None,
            fnc=main,
        )
    ]
