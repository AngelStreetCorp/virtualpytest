"""
mobile-app feature — wire protocol constants shared by the host bridge, the server
pairing routes, the phone simulator and the tests. The Android app mirrors these
values in app/android/.../Protocol.kt; docs/tasks/TASK-17-mobile-app-phone-agent.md §1.3
is the human-readable spec. Change both or neither.
"""

PROTOCOL_VERSION = 1

# Socket.IO namespace on the HOST (app.socketio). The phone connects here directly
# (host_api_url, LAN) or through the nginx location /host/<name>/phone/socket.io/.
NAMESPACE = '/phone'
# Socket.IO path when going through nginx: <host_url path>/phone/socket.io
PROXIED_SOCKETIO_SUFFIX = '/phone/socket.io'

# Device model / remote implementation name (shared/src/lib/config/device_capabilities.py)
DEVICE_MODEL = 'phone_agent'
REMOTE_IMPLEMENTATION = 'phone_agent'

# --- phone -> host events ---------------------------------------------------------
EV_HELLO = 'hello'        # {v, token? | device_secret?, device:{...}}  ack {ok, device_id, device_secret, capture}
EV_FRAME = 'frame'        # (meta {ts, w, h, rotation}, jpeg bytes)
EV_STATUS = 'status'      # {battery, charging, thermal, foreground_app, capture_active, accessibility_enabled, projection_granted}

# --- host -> phone events ---------------------------------------------------------
EV_CAPTURE = 'capture'    # {fps, max_side, quality}; fps 0 stops
EV_CMD = 'cmd'            # {id, name, params} with ack {ok, result?, error?}
EV_UNPAIR = 'unpair'      # {}

# --- commands (cmd.name) ----------------------------------------------------------
CMD_TAP = 'tap'                  # {x, y}
CMD_SWIPE = 'swipe'              # {x1, y1, x2, y2, duration_ms}
CMD_KEY = 'key'                  # {key}
CMD_TEXT = 'text'                # {text}
CMD_LAUNCH_APP = 'launch_app'    # {package, reset?} - reset=true clears the app's task so it
                                 # starts at its entry point instead of resuming where it
                                 # was left (agent >= 1.0.38; older agents ignore it)
CMD_CLOSE_APP = 'close_app'      # {package}
CMD_LIST_APPS = 'list_apps'      # {} -> {apps:[{package,label}]}
CMD_DUMP_UI = 'dump_ui'          # {} -> {elements:[...]}
CMD_SCREENSHOT = 'screenshot'    # {} -> {jpeg_b64, w, h}
CMD_DEVICE_INFO = 'device_info'  # {} -> {manufacturer, model, android, screen:{w,h,density}, battery}

ALL_COMMANDS = (
    CMD_TAP, CMD_SWIPE, CMD_KEY, CMD_TEXT, CMD_LAUNCH_APP, CMD_CLOSE_APP,
    CMD_LIST_APPS, CMD_DUMP_UI, CMD_SCREENSHOT, CMD_DEVICE_INFO,
)

# Keys the agent understands (AccessibilityService global actions / volume via AudioManager)
AGENT_KEYS = (
    'BACK', 'HOME', 'RECENTS', 'VOLUME_UP', 'VOLUME_DOWN', 'POWER',
    'NOTIFICATIONS', 'QUICK_SETTINGS',
)

# ADB keycode names (what scripts / the AndroidMobile panel send) -> agent key
ADB_KEY_MAP = {
    'BACK': 'BACK', 'KEYCODE_BACK': 'BACK',
    'HOME': 'HOME', 'KEYCODE_HOME': 'HOME',
    'MENU': 'RECENTS', 'KEYCODE_MENU': 'RECENTS',
    'APP_SWITCH': 'RECENTS', 'KEYCODE_APP_SWITCH': 'RECENTS', 'RECENTS': 'RECENTS',
    'VOLUME_UP': 'VOLUME_UP', 'KEYCODE_VOLUME_UP': 'VOLUME_UP',
    'VOLUME_DOWN': 'VOLUME_DOWN', 'KEYCODE_VOLUME_DOWN': 'VOLUME_DOWN',
    'POWER': 'POWER', 'KEYCODE_POWER': 'POWER',
    'NOTIFICATIONS': 'NOTIFICATIONS', 'QUICK_SETTINGS': 'QUICK_SETTINGS',
}

# --- timing -----------------------------------------------------------------------
TOKEN_TTL_S = 600               # one-time pairing token lifetime
CMD_TIMEOUT_S = 10              # host waits this long for a cmd ack
CMD_TIMEOUT_SLOW_S = 20         # screenshot / dump_ui / list_apps
OFFLINE_PLACEHOLDER_DELAY_S = 5 # after disconnect, before the "phone offline" frame is written

# --- hello rate limiting (TASK-19 P0 #2) -------------------------------------------
# A stolen/guessed token or device_secret is practically infeasible to brute-force (32
# random bytes each), but nothing stopped unlimited attempts either. This bounds it:
# past HELLO_MAX_FAILURES rejected `hello`s from one source IP within the window, that
# IP is locked out for HELLO_LOCKOUT_S regardless of whether the next attempt would have
# been valid.
HELLO_MAX_FAILURES = 8
HELLO_FAILURE_WINDOW_S = 60
HELLO_LOCKOUT_S = 120

# --- capture defaults (host env PHONE_AGENT_FPS / PHONE_AGENT_MAX_SIDE override) -----
DEFAULT_FPS = 3
DEFAULT_MAX_SIDE = 1280
DEFAULT_QUALITY = 70            # JPEG quality the phone encodes with

# --- QR payload (built by the web frontend = server response + its own VITE env) --------
QR_KIND_PAIR = 'pair'       # configures the app AND pairs it to a slot
QR_KIND_CONFIG = 'config'   # configures the app only
QR_REQUIRED_PAIR_FIELDS = (
    'v', 'kind', 'server_url', 'host_name', 'device_id', 'host_api_url', 'host_url', 'token', 'expires_at',
)


def is_slow_command(name: str) -> bool:
    return name in (CMD_SCREENSHOT, CMD_DUMP_UI, CMD_LIST_APPS)


def adb_key_to_agent_key(key: str):
    """Map an ADB-style key name to an agent key, or None when the phone cannot press it."""
    if not key:
        return None
    return ADB_KEY_MAP.get(str(key).strip().upper())
