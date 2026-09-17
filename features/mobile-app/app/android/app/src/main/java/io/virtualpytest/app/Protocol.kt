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
