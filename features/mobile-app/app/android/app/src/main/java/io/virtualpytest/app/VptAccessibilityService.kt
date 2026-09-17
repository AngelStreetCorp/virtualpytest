package io.virtualpytest.app

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Path
import android.graphics.Rect
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * Input + UI-dump side of the phone agent (§1.3 tap/swipe/key/text/dump_ui/launch_app/
 * close_app/list_apps). The instance is only alive while the user has enabled the service in
 * Settings > Accessibility (PhoneAgentPlugin#openAccessibilitySettings); PhoneAgentService reads
 * [instance] and reports [Protocol] command errors when it is null.
 */
class VptAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "VptAccessibility"
        private const val GESTURE_TIMEOUT_MS = 5_000L

        @Volatile
        var instance: VptAccessibilityService? = null
            private set
    }

    /**
     * Draws what the host is doing on the phone's own screen. It lives here because
     * TYPE_ACCESSIBILITY_OVERLAY is granted by this service — drawing from anywhere else would
     * need SYSTEM_ALERT_WINDOW, another permission and another settings trip.
     */
    val overlay: ActionOverlay by lazy { ActionOverlay(this) }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        PhoneAgentState.update(applicationContext) { it.copy(accessibilityEnabled = true) }
    }

    override fun onDestroy() {
        instance = null
        overlay.destroy()
        PhoneAgentState.update(applicationContext) { it.copy(accessibilityEnabled = false) }
        super.onDestroy()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        instance = null
        overlay.destroy()
        PhoneAgentState.update(applicationContext) { it.copy(accessibilityEnabled = false) }
        return super.onUnbind(intent)
    }

    // Required override; the agent drives input rather than reacting to accessibility events.
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    override fun onInterrupt() {}

    // ---- gestures (CMD_TAP / CMD_SWIPE) -------------------------------------------------

    fun tap(x: Int, y: Int, onDone: (Boolean) -> Unit) {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 50)
        dispatch(GestureDescription.Builder().addStroke(stroke).build(), onDone)
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long, onDone: (Boolean) -> Unit) {
        val duration = durationMs.coerceIn(1, GESTURE_TIMEOUT_MS)
        val path = Path().apply {
            moveTo(x1.toFloat(), y1.toFloat())
            lineTo(x2.toFloat(), y2.toFloat())
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, duration)
        dispatch(GestureDescription.Builder().addStroke(stroke).build(), onDone)
    }

    private fun dispatch(gesture: GestureDescription, onDone: (Boolean) -> Unit) {
        val ok = dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) = onDone(true)
                override fun onCancelled(gestureDescription: GestureDescription?) = onDone(false)
            },
            null,
        )
        if (!ok) onDone(false)
    }

    // ---- keys (CMD_KEY) ------------------------------------------------------------------

    /** Returns null on success, or an error string for the cmd ack. */
    fun pressKey(key: String): String? {
        val handled = when (key) {
            Protocol.KEY_BACK -> performGlobalAction(GLOBAL_ACTION_BACK)
            Protocol.KEY_HOME -> performGlobalAction(GLOBAL_ACTION_HOME)
            Protocol.KEY_RECENTS -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            Protocol.KEY_NOTIFICATIONS -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            Protocol.KEY_QUICK_SETTINGS -> performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS)
            Protocol.KEY_POWER -> pressPower()
            Protocol.KEY_VOLUME_UP -> adjustVolume(AudioManager.ADJUST_RAISE)
            Protocol.KEY_VOLUME_DOWN -> adjustVolume(AudioManager.ADJUST_LOWER)
            else -> return "unknown_key: $key"
        }
        return if (handled) null else "key_failed: $key"
    }

    private fun pressPower(): Boolean =
        // No unrooted way to send an actual power-button event; GLOBAL_ACTION_LOCK_SCREEN (28+)
        // is the closest equivalent (locks the screen, same end state a real STB POWER press
        // would leave the phone in). Below API 28 this key is unsupported.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN)
        } else {
            false
        }

    private fun adjustVolume(direction: Int): Boolean {
        val audioManager = getSystemService(Context.AUDIO_SERVICE) as? AudioManager ?: return false
        audioManager.adjustStreamVolume(AudioManager.STREAM_MUSIC, direction, 0)
        return true
    }

    // ---- text (CMD_TEXT) -------------------------------------------------------------------

    /** Returns null on success, or an error string for the cmd ack. */
    fun setText(text: String): String? {
        val root = rootInActiveWindow ?: return "no_active_window"
        val focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: return "no_focused_editable_field"
        try {
            val args = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
            }
            if (focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) return null

            // Fallback: clipboard + paste, for fields that don't support ACTION_SET_TEXT.
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                ?: return "set_text_failed"
            clipboard.setPrimaryClip(ClipData.newPlainText("vpt", text))
            return if (focused.performAction(AccessibilityNodeInfo.ACTION_PASTE)) null else "set_text_failed"
        } finally {
            focused.recycle()
        }
    }

    // ---- UI dump (CMD_DUMP_UI) --------------------------------------------------------------

    fun dumpUi(): JSONArray {
        val elements = JSONArray()
        rootInActiveWindow?.let { root ->
            try {
                collectElements(root, elements)
            } finally {
                root.recycle()
            }
        }
        return elements
    }

    private fun collectElements(node: AccessibilityNodeInfo, out: JSONArray) {
        val bounds = Rect()
        node.getBoundsInScreen(bounds)
        out.put(
            JSONObject().apply {
                put("id", node.viewIdResourceName ?: JSONObject.NULL)
                put("text", node.text?.toString() ?: "")
                put("content_desc", node.contentDescription?.toString() ?: "")
                put("class", node.className?.toString() ?: "")
                put("package", node.packageName?.toString() ?: "")
                put("bounds", JSONArray(listOf(bounds.left, bounds.top, bounds.right, bounds.bottom)))
                put("clickable", node.isClickable)
                put("enabled", node.isEnabled)
                put("focused", node.isFocused)
            },
        )
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            try {
                collectElements(child, out)
            } finally {
                child.recycle()
            }
        }
    }

    // ---- apps (CMD_LAUNCH_APP / CMD_CLOSE_APP / CMD_LIST_APPS) -------------------------------

    /**
     * Bring an app to the front, optionally at its entry point rather than where it was left.
     *
     * `reset` is what a tree wants when it says "start from the app's home screen". Without it
     * a launch RESUMES the existing task: `closeApp()` below can only press HOME (unrooted
     * Android has no force-stop API), so close-then-launch means "go to the launcher, then put
     * the app back exactly as it was". On YouTube that is the watch page, not the feed, and a
     * tree whose first step verifies the feed's bottom nav then fails on a screen that never
     * had one.
     *
     * FLAG_ACTIVITY_CLEAR_TASK clears the target's task before starting, which gets the same
     * end state as a force-stop for this purpose and needs no permission. It must be paired
     * with NEW_TASK — Android throws otherwise.
     *
     * Off by default: a tree that relies on resuming where it left off keeps working, and an
     * older agent that does not know the flag simply ignores it and launches as before.
     */
    fun launchApp(packageName: String, reset: Boolean = false): String? {
        val intent = packageManager.getLaunchIntentForPackage(packageName)
            ?: return "not_launchable: $packageName"
        // CLEAR_TASK and CLEAR_TOP are not combinable — asking for both cleared YouTube's task
        // and then started nothing, leaving the launcher on screen. Verified on a Galaxy S21.
        intent.addFlags(
            if (reset) {
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            } else {
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            },
        )
        return try {
            startActivity(intent)
            null
        } catch (e: Exception) {
            Log.w(TAG, "launch_app failed for $packageName", e)
            "launch_failed: ${e.message}"
        }
    }

    /**
     * Best effort only: unrooted Android has no force-stop API. HOME backgrounds the app, which
     * is the closest we can get (documented in app/README.md's "known limits").
     */
    fun closeApp(): String? =
        if (performGlobalAction(GLOBAL_ACTION_HOME)) null else "close_app_failed"

    fun listApps(): JSONArray {
        val apps = JSONArray()
        val launcherIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val resolved = packageManager.queryIntentActivities(launcherIntent, PackageManager.MATCH_ALL)
        for (info in resolved) {
            val appInfo = info.activityInfo?.applicationInfo ?: continue
            apps.put(
                JSONObject().apply {
                    put("package", appInfo.packageName)
                    put("label", info.loadLabel(packageManager)?.toString() ?: appInfo.packageName)
                },
            )
        }
        return apps
    }
}
