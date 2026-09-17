package io.virtualpytest.app

import android.Manifest
import android.app.Activity
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import androidx.activity.result.ActivityResult
import androidx.core.app.NotificationManagerCompat
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import com.google.zxing.integration.android.IntentIntegrator

/**
 * Native side of `window.Capacitor.Plugins.PhoneAgent` (frontend/native/phoneAgent.ts, owned by
 * another worker). Config/pairing state lives in [PhoneAgentPrefs]; connection/capture/permission
 * state is owned by [PhoneAgentService] and published through [PhoneAgentState] — this plugin is
 * a thin bridge that also forwards every state change as the "statusChanged" event.
 */
@CapacitorPlugin(
    name = "PhoneAgent",
    permissions = [Permission(alias = PhoneAgentPlugin.NOTIFICATIONS, strings = [Manifest.permission.POST_NOTIFICATIONS])],
)
class PhoneAgentPlugin : Plugin() {

    private val stateListener: (PhoneAgentStatus) -> Unit = { notifyListeners("statusChanged", statusObject()) }

    override fun load() {
        super.load()
        PhoneAgentState.addListener(stateListener)
    }

    override fun handleOnDestroy() {
        PhoneAgentState.removeListener(stateListener)
        super.handleOnDestroy()
    }

    // ---- pairing / config ------------------------------------------------------------------

    @PluginMethod
    fun scanQr(call: PluginCall) {
        // Restricted to QR: the pairing payload is a dense ~65-module symbol, and letting
        // zxing also hunt for every 1D format costs decode attempts per frame on exactly the
        // code that needs them most.
        val intent = IntentIntegrator(activity)
            .setOrientationLocked(false)
            .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
            .setBeepEnabled(false)
            .setPrompt("Point the camera at the pairing QR")
            .createScanIntent()
        startActivityForResult(call, intent, "scanQrResult")
    }

    @ActivityCallback
    private fun scanQrResult(call: PluginCall?, result: ActivityResult) {
        if (call == null) return
        val scanned = IntentIntegrator.parseActivityResult(result.resultCode, result.data)
        if (scanned?.contents == null) {
            call.reject("cancelled")
            return
        }
        call.resolve(JSObject().put("value", scanned.contents))
    }

    @PluginMethod
    fun applyConfig(call: PluginCall) {
        val payload = call.getString("payload") ?: ""
        // PayloadApplier may fetch runtime-config.json: never on the main thread.
        Thread {
            try {
                PayloadApplier.apply(context, payload)
                activity.runOnUiThread { call.resolve(statusObject()) }
            } catch (e: IllegalArgumentException) {
                activity.runOnUiThread { call.reject(e.message ?: "invalid payload") }
            }
        }.start()
    }

    @PluginMethod
    fun setServer(call: PluginCall) {
        val serverUrl = call.getString("serverUrl")
        if (serverUrl.isNullOrBlank()) {
            call.reject("serverUrl is required")
            return
        }
        val values = mutableMapOf<String, String?>(PhoneAgentPrefs.KEY_SERVER_URL to serverUrl)
        call.getString("supabaseUrl")?.let { values[PhoneAgentPrefs.KEY_SUPABASE_URL] = it }
        call.getString("supabaseAnonKey")?.let { values[PhoneAgentPrefs.KEY_SUPABASE_ANON_KEY] = it }
        call.getString("projectName")?.let { values[PhoneAgentPrefs.KEY_PROJECT_NAME] = it }
        PhoneAgentPrefs.putAll(context, values)
        PhoneAgentState.update(context)
        call.resolve(statusObject())
    }

    @PluginMethod
    fun getStatus(call: PluginCall) {
        PhoneAgentState.update(context)
        call.resolve(statusObject())
    }

    @PluginMethod
    fun unpair(call: PluginCall) {
        PhoneAgentPrefs.clearPairing(context)
        PhoneAgentService.stop(context)
        PhoneAgentState.update(context) {
            it.copy(connected = false, captureActive = false, projectionGranted = false)
        }
        call.resolve(statusObject())
    }

    // ---- permissions --------------------------------------------------------------------------

    @PluginMethod
    fun openAccessibilitySettings(call: PluginCall) {
        openAccessibilityService()
        call.resolve()
    }

    /**
     * Land the user on OUR service's own page — the one with the on/off switch — rather than
     * the Accessibility list, where "Installed apps" / "Downloaded apps" is several taps deep
     * and nothing says which entry to touch.
     *
     * ACTION_ACCESSIBILITY_DETAILS_SETTINGS (API 29+) is exactly that page. Some OEM Settings
     * apps do not implement it, so fall back to the full list with our row highlighted via the
     * `:settings:fragment_args_key` extras, and finally to the plain list as before.
     */
    private fun openAccessibilityService() {
        val flat = ComponentName(context, VptAccessibilityService::class.java).flattenToString()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val details = Intent(ACTION_ACCESSIBILITY_DETAILS_SETTINGS)
                .putExtra(Intent.EXTRA_COMPONENT_NAME, flat)
            if (startSettings(details)) return
        }

        val highlighted = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            .putExtra(EXTRA_FRAGMENT_ARG_KEY, flat)
            .putExtra(EXTRA_SHOW_FRAGMENT_ARGS, Bundle().apply { putString(EXTRA_FRAGMENT_ARG_KEY, flat) })
        if (startSettings(highlighted)) return

        startSettings(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }

    private fun startSettings(intent: Intent): Boolean =
        try {
            activity.startActivity(intent)
            true
        } catch (e: Exception) {
            Log.w(TAG, "settings intent not available: " + intent.action + " (" + e.message + ")")
            false
        }

    @PluginMethod
    fun openBatterySettings(call: PluginCall) {
        try {
            activity.startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}")),
            )
        } catch (e: Exception) {
            activity.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
        call.resolve()
    }

    @PluginMethod
    fun requestProjection(call: PluginCall) {
        val manager = activity.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(call, manager.createScreenCaptureIntent(), "requestProjectionResult")
    }

    @ActivityCallback
    private fun requestProjectionResult(call: PluginCall?, result: ActivityResult) {
        val data = result.data
        val granted = result.resultCode == Activity.RESULT_OK && data != null
        // Act on the consent BEFORE worrying about the call. Capacitor hands this back with a
        // null call whenever it could not restore the saved one — which it logs as "Couldn't
        // save last PhoneAgent's Plugin requestProjection call" — and the old `if (call ==
        // null) return` threw away a grant the user had just given. The screen-capture row
        // then stayed on "Fix" after they had allowed it, with no way to tell why.
        if (granted) {
            PhoneAgentService.grantProjection(context, result.resultCode, data!!)
        }
        call?.resolve(JSObject().put("granted", granted))
    }

    /**
     * Capacitor only preserves an in-flight plugin call across an Activity recreation when the
     * plugin returns a Bundle here; the default is null, so every requestProjection logged that
     * it could not be saved. The consent dialog backgrounds MainActivity, and when Android
     * chooses to recreate it the call is gone — hence the null above. Nothing of ours needs to
     * ride along, an empty Bundle is enough to let Capacitor keep the call.
     */
    override fun saveInstanceState(): Bundle = Bundle()

    /**
     * Whether the phone draws what the host is doing on its own screen. On by default; worth
     * turning off when a capture must be pristine, since the overlay is part of the screen and
     * MediaProjection records it like anything else.
     */
    @PluginMethod
    fun setActionOverlay(call: PluginCall) {
        val enabled = call.getBoolean("enabled") ?: true
        PhoneAgentPrefs.setActionOverlayEnabled(context, enabled)
        PhoneAgentState.update(context)
        call.resolve(statusObject())
    }

    @PluginMethod
    fun reloadApp(call: PluginCall) {
        activity.runOnUiThread { bridge.webView.reload() }
        call.resolve()
    }

    // ---- status -----------------------------------------------------------------------------

    private fun statusObject(): JSObject {
        val s = PhoneAgentState.current
        return JSObject().apply {
            put("configured", s.configured)
            put("serverUrl", s.serverUrl)
            put("paired", s.paired)
            put("hostName", s.hostName)
            put("deviceId", s.deviceId)
            put("connected", s.connected)
            put("connecting", s.connecting)
            put("captureActive", s.captureActive)
            put("fps", s.fps)
            put("accessibilityEnabled", isAccessibilityServiceEnabled())
            put("projectionGranted", s.projectionGranted)
        put("batteryUnrestricted", isBatteryUnrestricted())
            put("notificationsEnabled", areNotificationsEnabled())
            put("actionOverlay", PhoneAgentPrefs.isActionOverlayEnabled(context))
            put("appVersion", installedAppVersion())
            put("lastError", s.lastError)
        }
    }

    /**
     * POST_NOTIFICATIONS is declared in the manifest but, on Android 13+, denied until it is
     * asked for at runtime — and it never was, so the ongoing notification was silently
     * dropped and the phone had nothing on screen saying whether the link was up or down
     * (Android's screen-capture indicator looks the same either way). Unlike the accessibility
     * service, this one really is a single system dialog, so just ask.
     */
    @PluginMethod
    fun enableNotifications(call: PluginCall) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU || getPermissionState(NOTIFICATIONS) == PermissionState.GRANTED) {
            PhoneAgentState.update(context)
            call.resolve(statusObject())
            return
        }
        requestPermissionForAlias(NOTIFICATIONS, call, "notificationsPermissionResult")
    }

    @PermissionCallback
    private fun notificationsPermissionResult(call: PluginCall) {
        // Android stops showing the runtime dialog once it has been refused twice, so from
        // then on "Fix" would appear to do nothing at all — and pairing now waits for this row
        // to go green, so that would be a dead end with no way out of the app. Send them to
        // the one screen that can still grant it.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            getPermissionState(NOTIFICATIONS) != PermissionState.GRANTED
        ) {
            openAppNotificationSettings()
        }
        // Re-publishing the state makes the service rebuild the notification, so granting it
        // puts the indicator on screen straight away rather than at the next status change.
        PhoneAgentState.update(context)
        call.resolve(statusObject())
    }

    private fun openAppNotificationSettings() {
        try {
            activity.startActivity(
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
            )
        } catch (e: Exception) {
            Log.w(TAG, "could not open notification settings", e)
            try {
                activity.startActivity(
                    Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${'$'}{context.packageName}")),
                )
            } catch (e2: Exception) {
                Log.w(TAG, "could not open app details either", e2)
            }
        }
    }

    /**
     * The APK actually running, so "This phone" can be checked against the version the
     * download page advertises without digging through Android's app settings.
     */
    private fun installedAppVersion(): String? = try {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        val code = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else info.versionCode.toLong()
        "${info.versionName} (${code})"
    } catch (e: Exception) {
        null
    }

    private fun areNotificationsEnabled(): Boolean = try {
        NotificationManagerCompat.from(context).areNotificationsEnabled()
    } catch (e: Exception) {
        false
    }

    private fun isAccessibilityServiceEnabled(): Boolean {
        if (VptAccessibilityService.instance != null) return true
        return try {
            val enabled = Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
            enabled?.contains("${context.packageName}/${VptAccessibilityService::class.java.name}") == true
        } catch (e: Exception) {
            false
        }
    }

    private fun isBatteryUnrestricted(): Boolean = try {
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        powerManager.isIgnoringBatteryOptimizations(context.packageName)
    } catch (e: Exception) {
        false
    }

    internal companion object {
        const val NOTIFICATIONS = "notifications"
        const val TAG = "VptPhoneAgentPlugin"
        // Settings.EXTRA_FRAGMENT_ARG_KEY is API 28+; the bundle wrapper has no public
        // constant at all, so both are spelled out here.
        // Settings.ACTION_ACCESSIBILITY_DETAILS_SETTINGS is not exposed by this compileSdk,
        // so the documented action name is spelled out.
        const val ACTION_ACCESSIBILITY_DETAILS_SETTINGS = "android.settings.ACCESSIBILITY_DETAILS_SETTINGS"
        const val EXTRA_FRAGMENT_ARG_KEY = ":settings:fragment_args_key"
        const val EXTRA_SHOW_FRAGMENT_ARGS = ":settings:show_fragment_args"
    }
}
