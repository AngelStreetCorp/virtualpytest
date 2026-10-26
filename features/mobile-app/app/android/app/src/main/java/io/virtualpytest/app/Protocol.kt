package io.virtualpytest.app

/**
 * mobile-app feature — wire protocol constants, mirroring
 * features/mobile-app/lib/protocol.py exactly. Change both or neither.
 * docs/tasks/TASK-17-mobile-app-phone-agent.md §1.3 is the human-readable spec.
 */
object Protocol {
    const val PROTOCOL_VERSION = 1

    // Socket.IO namespace on the HOST (app.socketio).
    const val NAMESPACE = "/phone"
    // Socket.IO path when going through nginx: <host_url path>/phone/socket.io
    const val PROXIED_SOCKETIO_SUFFIX = "/phone/socket.io"

    const val DEVICE_MODEL = "phone_agent"
    const val REMOTE_IMPLEMENTATION = "phone_agent"

    // --- phone -> host events ---
    const val EV_HELLO = "hello"
    const val EV_FRAME = "frame"
    const val EV_STATUS = "status"

    // --- host -> phone events ---
    const val EV_CAPTURE = "capture"
    const val EV_CMD = "cmd"
    const val EV_UNPAIR = "unpair"

    // --- commands (cmd.name) ---
    const val CMD_TAP = "tap"
    const val CMD_SWIPE = "swipe"
    const val CMD_KEY = "key"
    const val CMD_TEXT = "text"
    const val CMD_LAUNCH_APP = "launch_app"
    const val CMD_CLOSE_APP = "close_app"
    const val CMD_LIST_APPS = "list_apps"
    const val CMD_DUMP_UI = "dump_ui"
    const val CMD_SCREENSHOT = "screenshot"
    const val CMD_DEVICE_INFO = "device_info"

    val ALL_COMMANDS = setOf(
        CMD_TAP, CMD_SWIPE, CMD_KEY, CMD_TEXT, CMD_LAUNCH_APP, CMD_CLOSE_APP,
        CMD_LIST_APPS, CMD_DUMP_UI, CMD_SCREENSHOT, CMD_DEVICE_INFO,
    )

    // Keys the agent understands (AccessibilityService global actions / volume via AudioManager)
    const val KEY_BACK = "BACK"
    const val KEY_HOME = "HOME"
    const val KEY_RECENTS = "RECENTS"
    const val KEY_VOLUME_UP = "VOLUME_UP"
    const val KEY_VOLUME_DOWN = "VOLUME_DOWN"
    const val KEY_POWER = "POWER"
    const val KEY_NOTIFICATIONS = "NOTIFICATIONS"
    const val KEY_QUICK_SETTINGS = "QUICK_SETTINGS"

    // --- drone bridge (TASK-160) ------------------------------------------------
    // The phone holds the drone's Wi-Fi conversation and relays it to the host over this
    // same channel. The host sidecar presents the drone as a local UDP peer, so the host
    // keeps speaking plain UDP to the drone and nothing else in the stack changes.
    //
    // `drone` is the label the owner gave the drone in the app; the host maps it to its
    // own device slot.
    const val EV_DRONE_CMD = "drone_cmd"        // host -> phone: {drone, target, cmd}, ack {ok, reply}
    const val EV_DRONE_STATE = "drone_state"    // phone -> host: {drone, text}
    const val EV_DRONE_VIDEO = "drone_video"    // phone -> host: ({drone}, rtp bytes)
    const val EV_DRONE_STATUS = "drone_status"  // phone -> host: {drones: [{label, ip}], hotspot}

    // The drone's own ports, on the phone's hotspot interface.
    const val DRONE_CMD_PORT = 8889
    const val DRONE_STATE_PORT = 8890
    const val DRONE_VIDEO_PORT = 11111
    // How long the host waits for the phone to acknowledge a drone command: phone ->
    // drone -> phone -> host carries the drone's latency twice plus the cellular hop.
    const val DRONE_CMD_TIMEOUT_S = 15
    // Commands the drone never answers. `rc` holds the stick values until the next
    // one, so it is sent without waiting - the joystick streams at 10 Hz and a wait
    // per stick value would cap it at one command per round trip.
    val DRONE_NO_REPLY_COMMANDS = setOf("rc")

    val AGENT_KEYS = setOf(
        KEY_BACK, KEY_HOME, KEY_RECENTS, KEY_VOLUME_UP, KEY_VOLUME_DOWN, KEY_POWER,
        KEY_NOTIFICATIONS, KEY_QUICK_SETTINGS,
    )

    // --- timing ---
    const val TOKEN_TTL_S = 600
    const val CMD_TIMEOUT_S = 10L
    const val CMD_TIMEOUT_SLOW_S = 20L
    const val OFFLINE_PLACEHOLDER_DELAY_S = 5

    // --- capture defaults (host `capture` event overrides these) ---
    const val DEFAULT_FPS = 3
    const val DEFAULT_MAX_SIDE = 1280
    const val DEFAULT_QUALITY = 70

    // --- QR payload ---
    const val QR_KIND_PAIR = "pair"
    const val QR_KIND_CONFIG = "config"
    val QR_REQUIRED_PAIR_FIELDS = listOf(
        "v", "kind", "server_url", "host_name", "device_id", "host_api_url", "host_url", "token", "expires_at",
    )

    fun isSlowCommand(name: String): Boolean =
        name == CMD_SCREENSHOT || name == CMD_DUMP_UI || name == CMD_LIST_APPS
}
