package io.virtualpytest.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.concurrent.CopyOnWriteArrayList

/** Mirrors the web-side `PhoneAgentStatus` shape (frontend/native/phoneAgent.ts). */
data class PhoneAgentStatus(
    val configured: Boolean = false,
    val serverUrl: String? = null,
    val paired: Boolean = false,
    val hostName: String? = null,
    val deviceId: String? = null,
    val connected: Boolean = false,
    /** A connect attempt is in flight, or one is scheduled: the link is trying, not dead. */
    val connecting: Boolean = false,
    val captureActive: Boolean = false,
    /**
     * A host is driving this phone right now — a script is running against it.
     *
     * Inferred from commands arriving rather than told to us: the protocol carries no run
     * boundaries, so the service raises this on every command and drops it after a quiet
     * spell (see PhoneAgentService.DRIVING_IDLE_MS).
     */
    val driving: Boolean = false,
    /** Which script is driving, when the host said so. Null for remote-panel use. */
    val runLabel: String? = null,
    val fps: Double = 0.0,
    val accessibilityEnabled: Boolean = false,
    val projectionGranted: Boolean = false,
    val batteryUnrestricted: Boolean = false,
    val lastError: String? = null,
)

/**
 * In-process pub/sub for the current [PhoneAgentStatus]. PhoneAgentService (and
 * VptAccessibilityService, for the accessibility flag) publish; PhoneAgentPlugin subscribes and
 * forwards every change to the web layer as the "statusChanged" plugin event. Plugin and service
 * run in the same process, so a plain in-memory singleton is enough — no IPC needed.
 */
object PhoneAgentState {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val listeners = CopyOnWriteArrayList<(PhoneAgentStatus) -> Unit>()

    @Volatile
    var current: PhoneAgentStatus = PhoneAgentStatus()
        private set

    fun addListener(listener: (PhoneAgentStatus) -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: (PhoneAgentStatus) -> Unit) {
        listeners.remove(listener)
    }

    /** Recomputes `configured`/`paired`/`serverUrl` from prefs and merges in the given fields. */
    fun update(context: Context, mutate: (PhoneAgentStatus) -> PhoneAgentStatus = { it }) {
        val base = current.copy(
            configured = PhoneAgentPrefs.isConfigured(context),
            serverUrl = PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SERVER_URL),
            paired = PhoneAgentPrefs.isPaired(context),
            hostName = PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_HOST_NAME),
            deviceId = PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_DEVICE_ID),
        )
        set(mutate(base))
    }

    fun set(status: PhoneAgentStatus) {
        current = status
        mainHandler.post {
            for (listener in listeners) listener(status)
        }
    }
}
