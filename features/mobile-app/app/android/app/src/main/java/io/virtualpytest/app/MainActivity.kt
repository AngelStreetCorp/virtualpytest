package io.virtualpytest.app

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import com.getcapacitor.Bridge
import com.getcapacitor.BridgeActivity
import com.getcapacitor.BridgeWebViewClient
import org.json.JSONObject
import java.io.ByteArrayInputStream

/**
 * One APK ships for every deployment; the deployment-specific server/Supabase config is stored
 * natively (PhoneAgentPrefs, set by PhoneAgentPlugin#applyConfig/setServer from the QR) and
 * injected into the WebView as `window.__VPT_CONFIG__` *before* the bundled React app boots.
 * This is the SAME mechanism `getEnv()` (frontend/src/config/constants.ts) already reads for
 * the Docker self-service install (a container entrypoint writes `dist/config.js` from its own
 * environment) — one runtime-config global, not an app-specific one. `index.html` already
 * requests `/config.js` as its first classic script on every build, so nothing needs to patch
 * it; this WebViewClient just intercepts that one request and serves the phone's own prefs
 * instead of the static empty default (`frontend/public/config.js`).
 */
class MainActivity : BridgeActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        // Must run before super.onCreate(): Capacitor's PluginManager only picks up plugins
        // registered on bridgeBuilder before the Bridge is built at the end of onCreate().
        registerPlugin(PhoneAgentPlugin::class.java)
        super.onCreate(savedInstanceState)
        bridge.setWebViewClient(RuntimeConfigWebViewClient(bridge, applicationContext))
        installBackNavigation()
        installLinkCopy()
        handleDebugIntent(intent)

        // PhoneAgentService is otherwise only started from PayloadApplier at the moment of a
        // fresh pairing (QR scan) — an already-paired phone whose service isn't running (Android
        // killed it in the background, the device rebooted, or this is a fresh reinstall with
        // prefs restored some other way) never reconnects on its own until the user re-scans.
        // connectIfPaired() no-ops when unpaired, so this is safe to call unconditionally.
        if (PhoneAgentPrefs.isPaired(applicationContext)) {
            PhoneAgentService.start(applicationContext)
        }
    }

    /**
     * Long-press a link to copy its address.
     *
     * A bare Android WebView has no link context menu. Chrome builds its own from
     * `getHitTestResult()`; Capacitor ships nothing, so a long press on a report or logs link
     * did precisely nothing and there was no way to get a URL out of the app at all — the
     * signed report links are the thing you most want to paste somewhere else.
     *
     * Long-press elsewhere is left alone, so normal text selection still works.
     */
    private fun installLinkCopy() {
        val webView = bridge.webView ?: return
        webView.setOnLongClickListener { view ->
            val result = (view as? WebView)?.hitTestResult ?: return@setOnLongClickListener false
            val url = when (result.type) {
                WebView.HitTestResult.SRC_ANCHOR_TYPE,
                WebView.HitTestResult.SRC_IMAGE_ANCHOR_TYPE -> result.extra
                else -> null
            }
            if (url.isNullOrBlank()) {
                // Not a link: let the WebView do what it would have done (text selection).
                return@setOnLongClickListener false
            }
            copyToClipboard(url)
            true
        }
    }

    private fun copyToClipboard(url: String) {
        try {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("VirtualPyTest link", url))
            // Android 13+ shows its own copy confirmation, so a toast there would be a second
            // one saying the same thing.
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                Toast.makeText(this, "Link copied", Toast.LENGTH_SHORT).show()
            }
        } catch (e: Exception) {
            Log.w("VptMainActivity", "could not copy the link", e)
            Toast.makeText(this, "Could not copy the link", Toast.LENGTH_SHORT).show()
        }
    }

    /**
     * Make the system Back button walk the app's own history instead of leaving.
     *
     * Capacitor ships no back handling at all — there is no onBackPressed or canGoBack
     * anywhere in its Android source — so the activity simply finished on every press. From
     * inside the app that meant Back always dropped you on the launcher, whatever you were
     * looking at: three taps into Device, or with a stream modal open, it quit rather than
     * going back one step. The web build has never had this problem because a browser gives
     * it a Back button for free.
     *
     * Overlays that are not routes (the stream modal and friends) push their own history entry
     * while open — see useBackToClose in the frontend — so they are popped by the same
     * mechanism and close instead of navigating. When there is genuinely nothing left to go
     * back to, the callback steps aside and Android does what it did before: leave the app.
     */
    private fun installBackNavigation() {
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    val webView = bridge.webView
                    if (webView != null && webView.canGoBack()) {
                        webView.goBack()
                        return
                    }
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            },
        )
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleDebugIntent(intent)
    }

    /**
     * Debug builds only: lets an emulator (no camera, no human) be configured/paired and asked
     * for screen-capture consent over ADB, e.g.
     *   adb shell am start -n io.virtualpytest.app/.MainActivity --es vpt_payload_b64 <base64 QR JSON>
     *   adb shell am start -n io.virtualpytest.app/.MainActivity --ez vpt_request_projection true
     * The consent dialog still has to be accepted (adb shell input / uiautomator).
     */
    private fun handleDebugIntent(intent: Intent?) {
        if (!BuildConfig.DEBUG || intent == null) return
        // Consume the extras: the same Intent object is re-delivered on activity recreation
        // (onCreate + onNewIntent), and re-applying a pairing wipes the device secret the
        // first hello just obtained.
        val payloadB64 = intent.getStringExtra(EXTRA_PAYLOAD_B64)
        val wantsProjection = intent.getBooleanExtra(EXTRA_REQUEST_PROJECTION, false)
        intent.removeExtra(EXTRA_PAYLOAD_B64)
        intent.removeExtra(EXTRA_REQUEST_PROJECTION)
        payloadB64?.let { b64 ->
            Thread {
                try {
                    PayloadApplier.apply(applicationContext, String(Base64.decode(b64, Base64.DEFAULT), Charsets.UTF_8))
                    Log.i(TAG, "debug intent: payload applied")
                } catch (e: Exception) {
                    Log.w(TAG, "debug intent: payload rejected: ${e.message}")
                }
            }.start()
        }
        if (wantsProjection) {
            val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            @Suppress("DEPRECATION")
            startActivityForResult(manager.createScreenCaptureIntent(), REQ_DEBUG_PROJECTION)
        }
    }

    @Deprecated("Capacitor plugins use the ActivityResult API; this path is debug-only")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQ_DEBUG_PROJECTION) {
            if (resultCode == Activity.RESULT_OK && data != null) {
                PhoneAgentService.grantProjection(applicationContext, resultCode, data)
            } else {
                Log.w(TAG, "debug intent: projection consent denied")
            }
            return
        }
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
    }

    private companion object {
        const val TAG = "VptMainActivity"
        const val EXTRA_PAYLOAD_B64 = "vpt_payload_b64"
        const val EXTRA_REQUEST_PROJECTION = "vpt_request_projection"
        const val REQ_DEBUG_PROJECTION = 0x5A5A
    }
}

private class RuntimeConfigWebViewClient(
    private val vptBridge: Bridge,
    private val context: Context,
) : BridgeWebViewClient(vptBridge) {

    /**
     * Only the app's OWN origin gets the native config. The deployment's website serves a
     * `/config.js` of its own at the same path, and matching on the path alone injected the
     * phone's prefs — including `VITE_IS_NATIVE_APP` — into that remote page too. The bundle
     * then believed it was the native app on an origin where Capacitor injects no bridge, so
     * it offered a "This phone" tab that could never reach the plugin behind it. It also put
     * the deployment's Supabase URL and anon key into a page we do not serve.
     */
    override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
        val url = request?.url
        if (url != null && url.path?.endsWith("/config.js") == true && isAppOrigin(url)) {
            val body = "window.__VPT_CONFIG__ = ${buildRuntimeConfig(context)};"
            return WebResourceResponse(
                "application/javascript",
                "UTF-8",
                ByteArrayInputStream(body.toByteArray(Charsets.UTF_8)),
            )
        }
        return super.shouldInterceptRequest(view, request)
    }

    /** True when `url` is served by our own local server (`https://localhost`), not a remote host. */
    private fun isAppOrigin(url: Uri): Boolean {
        val local = appOrigin() ?: return false
        return url.scheme == local.scheme && url.host == local.host
    }

    private fun appOrigin(): Uri? =
        vptBridge.localUrl?.takeIf { it.isNotBlank() }?.let(Uri::parse)

    /**
     * Rewrite `url` onto the app's own origin, carrying path, query and fragment across —
     * that is where GoTrue puts the auth code / access token, so the session lands with it.
     * Null when there is nowhere to go or we are already home.
     */
    private fun toAppOrigin(url: Uri): String? {
        val local = appOrigin() ?: return null
        if (url.scheme == local.scheme && url.host == local.host) return null
        return local.buildUpon()
            .encodedPath(url.encodedPath ?: "/")
            .encodedQuery(url.encodedQuery)
            .encodedFragment(url.encodedFragment)
            .build()
            .toString()
    }

    /**
     * Capacitor's own shouldOverrideUrlLoading (Bridge#launchIntent) hands ANY navigation
     * outside the app's own https://localhost origin to the system browser via an external
     * Intent — that includes an OAuth provider (e.g. "Sign in with GitHub" does
     * `window.location.href = <provider>`). The provider then redirects back to
     * VITE_SUPABASE_URL's own /auth/v1/callback, which finally redirects to our
     * https://localhost/auth/callback — but by then control is in Chrome, a *different*
     * browsing context with no access to this WebView's storage, so the app never learns a
     * session was created and is left showing the login page forever, even though sign-in
     * genuinely succeeded in the browser.
     *
     * Fix: let the WHOLE redirect chain load inside this same WebView instead — provider,
     * Supabase's callback host and our own app origin are all same-session that way, so the
     * bundle's already-listening `onAuthStateChange` picks the session up normally once
     * navigation lands back on /auth/callback. Scoped to just the hosts this flow can touch
     * (the OAuth provider + the deployment's own server/Supabase hosts, read from the same
     * runtime prefs config.js is built from) so an unrelated external link (e.g. the footer's
     * "View on GitHub" repo link) still opens in the system browser as before.
     *
     * Does not help Google sign-in: Google's own OAuth pages detect and refuse an embedded
     * WebView regardless ("This browser or app may not be secure") — that needs a Custom
     * Tabs + deep-link flow instead, not implemented here.
     *
     * The chain is allowed to RUN here, but it must not END here. `redirectTo` is
     * `https://localhost/auth/callback` (window.location.origin, see AuthContext.tsx), and
     * GoTrue silently falls back to the project's Site URL whenever that is not in its
     * allow-list — which for this deployment sends the last hop to the public website
     * instead. The WebView then sits on that remote origin, where Capacitor injects no
     * bridge: no `window.Capacitor`, no PhoneAgent plugin, so the app quietly becomes a
     * browser showing the web build, with the native pages unreachable until it is killed
     * and relaunched. So: provider pages and the Supabase auth endpoints load as-is, but a
     * landing on the deployment's own website is carried back to our origin, query and
     * fragment intact, where the bundle finishes the sign-in in the right browsing context.
     * Keeping this in the app rather than allow-listing `https://localhost` in every
     * deployment's GoTrue is deliberate — one APK is meant to serve any deployment.
     */
    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
        val url = request?.url
        val host = url?.host
        if (url != null && host != null && isOAuthFlowHost(context, host)) {
            // Provider + Supabase's own endpoints are mid-chain: let them load untouched.
            if (isOAuthProviderHost(host) || isSupabaseEndpoint(context, url)) return false
            // ONLY the main frame. WebView#loadUrl replaces the whole page, so "carrying a
            // subframe home" throws the entire WebView at that subframe's URL. A host_vnc
            // device previews as an iframe on /host/<name>/vnc_lite.html, so every VNC
            // preview hijacked the app to https://localhost/host/... — a path the local
            // server does not serve — and left it on "Webpage not available".
            if (request.isForMainFrame && isAuthLanding(url)) {
                val home = toAppOrigin(url)
                if (home != null) {
                    Log.i(TAG_WV, "landing on $host carried back to the app origin")
                    view?.loadUrl(home)
                    return true
                }
            }
            return false
        }
        return super.shouldOverrideUrlLoading(view, request)
    }
}

private const val TAG_WV = "VptWebViewClient"

/** Query/fragment parameters that mark the end of a GoTrue redirect chain. */
private val AUTH_LANDING_PARAMS = listOf("code", "access_token", "refresh_token", "error", "error_code")

/**
 * True when a URL on the deployment's own host is the END OF THE SIGN-IN CHAIN rather than
 * ordinary content to display.
 *
 * Only these are carried back to the app origin. Everything else the deployment serves —
 * an HTML test report, a presigned storage object, a host's noVNC page — must load where it
 * lives: rewriting those onto `https://localhost` pointed the WebView at paths the local
 * server does not have, so every "View report" landed on an error page.
 *
 * GoTrue either redirects to the configured callback path or, when `redirectTo` is not
 * allow-listed, to the Site URL carrying the code/token (or an error) in the query or the
 * fragment — so both shapes are recognised.
 */
private fun isAuthLanding(url: Uri): Boolean {
    if (url.path.orEmpty().startsWith("/auth/")) return true
    return AUTH_LANDING_PARAMS.any { hasParam(url.encodedQuery, it) || hasParam(url.encodedFragment, it) }
}

/** Whole-name match, so a presigned URL's own parameters cannot look like an auth code. */
private fun hasParam(raw: String?, name: String): Boolean {
    if (raw.isNullOrEmpty()) return false
    val prefix = "$name="
    return raw.startsWith(prefix) || raw.contains("&$prefix")
}

private fun isOAuthProviderHost(host: String): Boolean =
    host == "github.com" || host.endsWith(".github.com")

private fun isOAuthFlowHost(context: Context, host: String): Boolean {
    if (isOAuthProviderHost(host)) return true
    return oauthDeploymentHosts(context).contains(host)
}

/**
 * True when `url` is one of Supabase's own endpoints. Here VITE_SUPABASE_URL shares the
 * website's host and is told apart only by its path prefix (`/supabase`), so the prefix is
 * what decides — rewriting `/supabase/auth/v1/callback` onto our origin would break the very
 * redirect we are trying to follow. An empty prefix means Supabase owns that whole host.
 */
private fun isSupabaseEndpoint(context: Context, url: Uri): Boolean {
    val base = PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SUPABASE_URL)
        ?.takeIf { it.isNotBlank() }?.let(Uri::parse) ?: return false
    if (url.host != base.host) return false
    val prefix = base.path?.trimEnd('/').orEmpty()
    if (prefix.isEmpty()) return true
    val path = url.path.orEmpty()
    return path == prefix || path.startsWith("$prefix/")
}

private fun oauthDeploymentHosts(context: Context): Set<String> {
    val urls = listOf(
        PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SERVER_URL),
        PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SUPABASE_URL),
    )
    return urls.mapNotNull { it?.let(Uri::parse)?.host }.toSet()
}

/**
 * JSONObject#toString() already produces a valid JS object literal (JSON is a JS subset).
 * Keys match what getEnv() reads on the web build — see frontend/src/config/constants.ts.
 *
 * VITE_IS_NATIVE_APP is the one key that is not a deployment setting: it tells the bundle it
 * is running inside the APK. The bundle can also ask `window.Capacitor`, but that global only
 * exists once Capacitor's injected bridge script has run, and components read the answer
 * synchronously while rendering — lose that race and the app renders its web layout (no
 * "This phone" tab) for the whole session. index.html requests this file as a classic script
 * ahead of the module bundle, so a flag set here is always there in time.
 * See isNativeApp() in frontend/src/config/runtimeConfig.ts.
 */
private fun buildRuntimeConfig(context: Context): String = JSONObject()
    .put("VITE_IS_NATIVE_APP", "true")
    .put("VITE_SERVER_URL", PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SERVER_URL) ?: "")
    .put("VITE_SUPABASE_URL", PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SUPABASE_URL) ?: "")
    .put("VITE_SUPABASE_ANON_KEY", PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SUPABASE_ANON_KEY) ?: "")
    .put("VITE_PROJECT_NAME", PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_PROJECT_NAME) ?: "")
    .toString()
