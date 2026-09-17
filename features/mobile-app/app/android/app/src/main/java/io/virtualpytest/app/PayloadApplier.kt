package io.virtualpytest.app

import android.content.Context
import android.net.Uri
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Applies a QR payload (TASK-17 §1.2: kind `config` or `pair`) to the stored prefs and, for a
 * pairing, starts the agent service. Shared by the Capacitor plugin (scanned QR) and the
 * debug-only ADB entry point in MainActivity (emulator tests, no camera). Throws
 * IllegalArgumentException with a user-readable message on a bad payload.
 */
object PayloadApplier {

    fun apply(context: Context, payloadStr: String) {
        require(payloadStr.isNotBlank()) { "payload is required" }
        val trimmed = payloadStr.trim()
        // The "Get the app" QR is a plain URL, not JSON: it has to work when a normal camera
        // app scans it before this app exists (Open link -> downloads the APK directly). The
        // in-app scanner can hit that same code again post-install; treat its origin as the
        // config payload (equivalent to the old kind=config JSON, minus the fields this app
        // fetches from <origin>/runtime-config.json anyway).
        if (trimmed.startsWith("http://", ignoreCase = true) || trimmed.startsWith("https://", ignoreCase = true)) {
            applyConfig(context, JSONObject().apply {
                put("v", Protocol.PROTOCOL_VERSION)
                put("server_url", originOf(trimmed))
                put("frontend_url", originOf(trimmed))
            })
            return
        }
        val json = try {
            JSONObject(trimmed)
        } catch (e: Exception) {
            throw IllegalArgumentException("payload is not valid JSON: ${e.message}")
        }
        require(json.optInt("v", -1) == Protocol.PROTOCOL_VERSION) {
            "unsupported QR version (expected v=${Protocol.PROTOCOL_VERSION})"
        }
        when (val kind = json.optString("kind")) {
            Protocol.QR_KIND_CONFIG -> applyConfig(context, json)
            Protocol.QR_KIND_PAIR -> applyPair(context, json)
            else -> throw IllegalArgumentException("unknown QR kind: $kind")
        }
    }

    private fun originOf(url: String): String {
        val uri = Uri.parse(url)
        return "${uri.scheme}://${uri.authority}"
    }

    private fun applyConfig(context: Context, json: JSONObject) {
        val serverUrl = json.optString("server_url")
        require(serverUrl.isNotBlank()) { "server_url is required" }
        PhoneAgentPrefs.putAll(context, mapOf(PhoneAgentPrefs.KEY_SERVER_URL to serverUrl) + runtimeConfig(json))
        PhoneAgentState.update(context)
    }

    /**
     * Public frontend settings (Supabase URL + anon key, project name). A QR that carried them
     * was too dense for phone cameras, so the web build now publishes them as
     * `<frontend_url>/runtime-config.json` and the QR only names the origin. Older payloads
     * that still embed the fields are honoured as-is. Network I/O: callers run off the main thread.
     */
    private fun runtimeConfig(json: JSONObject): Map<String, String?> {
        val embedded = mapOf(
            PhoneAgentPrefs.KEY_SUPABASE_URL to json.optStringOrNull("supabase_url"),
            PhoneAgentPrefs.KEY_SUPABASE_ANON_KEY to json.optStringOrNull("supabase_anon_key"),
            PhoneAgentPrefs.KEY_PROJECT_NAME to json.optStringOrNull("project_name"),
        )
        if (embedded.values.any { it != null }) return embedded
        val origin = json.optStringOrNull("frontend_url") ?: json.optStringOrNull("server_url") ?: return embedded
        return try {
            val conn = URL(origin.trimEnd('/') + "/runtime-config.json").openConnection() as HttpURLConnection
            conn.connectTimeout = 8_000
            conn.readTimeout = 8_000
            conn.setRequestProperty("User-Agent", "VirtualPyTest-app")
            val remote = JSONObject(conn.inputStream.bufferedReader().readText())
            mapOf(
                PhoneAgentPrefs.KEY_SUPABASE_URL to remote.optStringOrNull("supabase_url"),
                PhoneAgentPrefs.KEY_SUPABASE_ANON_KEY to remote.optStringOrNull("supabase_anon_key"),
                PhoneAgentPrefs.KEY_PROJECT_NAME to remote.optStringOrNull("project_name"),
            )
        } catch (e: Exception) {
            Log.w("PayloadApplier", "runtime-config.json not fetched from $origin: ${e.message}")
            embedded
        }
    }

    private fun applyPair(context: Context, json: JSONObject) {
        val missing = Protocol.QR_REQUIRED_PAIR_FIELDS.filter { field -> !json.hasNonBlank(field) }
        require(missing.isEmpty()) { "QR payload missing field(s): ${missing.joinToString(", ")}" }
        PhoneAgentPrefs.putAll(
            context,
            runtimeConfig(json) + mapOf(
                PhoneAgentPrefs.KEY_SERVER_URL to json.getString("server_url"),
                PhoneAgentPrefs.KEY_HOST_NAME to json.getString("host_name"),
                PhoneAgentPrefs.KEY_DEVICE_ID to json.getString("device_id"),
                PhoneAgentPrefs.KEY_HOST_API_URL to json.getString("host_api_url"),
                PhoneAgentPrefs.KEY_HOST_URL to json.getString("host_url"),
                PhoneAgentPrefs.KEY_TOKEN to json.getString("token"),
                PhoneAgentPrefs.KEY_DEVICE_SECRET to null, // fresh pairing invalidates any prior secret
            ),
        )
        PhoneAgentState.update(context)
        PhoneAgentService.start(context)
    }

    private fun JSONObject.optStringOrNull(field: String): String? =
        if (has(field) && !isNull(field)) optString(field).takeIf { it.isNotBlank() } else null

    private fun JSONObject.hasNonBlank(field: String): Boolean =
        has(field) && !isNull(field) && get(field).toString().isNotBlank()
}
