package io.virtualpytest.app

import android.content.Context
import android.content.SharedPreferences

/**
 * Persisted configuration for the phone agent: runtime frontend config (server/Supabase URLs)
 * plus pairing state (host, slot, token/secret). Read by MainActivity (to build
 * window.__VPT_RUNTIME__), PhoneAgentPlugin and PhoneAgentService.
 *
 * Never log KEY_TOKEN or KEY_DEVICE_SECRET (task rule) — they are only ever read/written here.
 */
object PhoneAgentPrefs {
    private const val PREFS_NAME = "phone_agent_prefs"

    const val KEY_SERVER_URL = "server_url"
    const val KEY_SUPABASE_URL = "supabase_url"
    const val KEY_SUPABASE_ANON_KEY = "supabase_anon_key"
    const val KEY_PROJECT_NAME = "project_name"

    const val KEY_HOST_NAME = "host_name"
    const val KEY_DEVICE_ID = "device_id"
    const val KEY_HOST_API_URL = "host_api_url"
    const val KEY_HOST_URL = "host_url"
    const val KEY_TOKEN = "token"            // one-time pairing token, consumed on first hello
    const val KEY_DEVICE_SECRET = "device_secret"  // persisted secret for reconnects
    const val KEY_ACTION_OVERLAY = "action_overlay"  // show what the host is doing, on screen

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getString(context: Context, key: String): String? = prefs(context).getString(key, null)

    fun putAll(context: Context, values: Map<String, String?>) {
        val editor = prefs(context).edit()
        for ((key, value) in values) {
            if (value == null) editor.remove(key) else editor.putString(key, value)
        }
        editor.apply()
    }

    fun put(context: Context, key: String, value: String?) = putAll(context, mapOf(key to value))

    /** True once a server URL is stored (kind=config or kind=pair QR was applied). */
    /** Default on: a phone being driven should say so unless someone turns it off. */
    fun isActionOverlayEnabled(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ACTION_OVERLAY, true)

    fun setActionOverlayEnabled(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean(KEY_ACTION_OVERLAY, enabled).apply()
    }

    fun isConfigured(context: Context): Boolean = !getString(context, KEY_SERVER_URL).isNullOrBlank()

    /** True once bound to a host slot (kind=pair QR was applied, not yet unpaired). */
    fun isPaired(context: Context): Boolean =
        !getString(context, KEY_HOST_NAME).isNullOrBlank() && !getString(context, KEY_DEVICE_ID).isNullOrBlank()

    /** Clears pairing (host/device/token/secret) but keeps the server/Supabase config. */
    fun clearPairing(context: Context) {
        putAll(
            context,
            mapOf(
                KEY_HOST_NAME to null,
                KEY_DEVICE_ID to null,
                KEY_HOST_API_URL to null,
                KEY_HOST_URL to null,
                KEY_TOKEN to null,
                KEY_DEVICE_SECRET to null,
            ),
        )
    }
}
