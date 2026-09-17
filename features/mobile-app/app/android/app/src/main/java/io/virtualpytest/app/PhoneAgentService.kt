package io.virtualpytest.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.Base64
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import io.socket.client.Ack
import io.socket.client.IO
import io.socket.client.Socket
import org.json.JSONObject
import java.net.URI

/**
 * Foreground service that owns the phone side of the wire protocol (§1.3): connects the
 * Socket.IO client to the host, streams frames from [ProjectionCapture], dispatches `cmd`s to
 * [VptAccessibilityService], and reports `status`. Started by PhoneAgentPlugin once a `pair` QR
 * is applied; stopped on unpair.
 */
class PhoneAgentService : Service() {

    companion object {
        private const val TAG = "PhoneAgentService"
        private const val CHANNEL_ID = "vpt_phone_agent_link"
        private const val NOTIFICATION_ID = 4201
        private const val CONNECT_ATTEMPT_TIMEOUT_MS = 8_000L
        /**
         * How often a paired-but-disconnected phone starts a completely fresh attempt.
         *
         * Socket.IO retries on its own, but only the URL it last used and only while it still
         * considers itself connecting — a manual disconnect (a transient hello rejection does
         * one) stops it for good, and a phone that fell back to the proxied URL never tries
         * the faster LAN one again even after coming home. This watchdog covers both: every
         * tick, if we are paired and not connected, start over from the primary URL.
         */
        private const val RECONNECT_WATCHDOG_MS = 30_000L
        private const val STATUS_INTERVAL_MS = 15_000L
        private const val SCREENSHOT_POLL_MS = 150L

        // Shown in the notification shade; the status-bar silhouette carries up/down by shape.
        private const val COLOR_CONNECTED = 0xFF2E7D32.toInt()
        private const val COLOR_DISCONNECTED = 0xFFC62828.toInt()
        // Blue while a script is driving, so "busy" never reads as plain "connected". Deeper
        // than the overlay's accent because a notification colour is tinted against the shade's
        // own background, where a light blue washes out.
        private const val COLOR_DRIVING = 0xFF0288D1.toInt()

        /**
         * How long after the last command the phone still counts as under test.
         *
         * The protocol has no run-start/run-end event, so this is inferred from traffic. The
         * number is a compromise: a navigation step can sit quiet for a while (a 60s video
         * verification runs entirely on the host and sends the phone nothing), so too short and
         * the badge flickers mid-run; too long and it lingers after a run is over. 45s covers the
         * gaps between the commands of one step without outstaying a finished script by much.
         */
        private const val DRIVING_IDLE_MS = 45_000L

        const val ACTION_START = "io.virtualpytest.app.action.START"
        const val ACTION_GRANT_PROJECTION = "io.virtualpytest.app.action.GRANT_PROJECTION"
        const val ACTION_STOP = "io.virtualpytest.app.action.STOP"
        const val EXTRA_RESULT_CODE = "resultCode"
        const val EXTRA_RESULT_DATA = "data"

        fun start(context: Context) {
            val intent = Intent(context, PhoneAgentService::class.java).setAction(ACTION_START)
            context.startForegroundService(intent)
        }

        /** Called by PhoneAgentPlugin's requestProjection ActivityCallback with the consent result. */
        fun grantProjection(context: Context, resultCode: Int, data: Intent) {
            val intent = Intent(context, PhoneAgentService::class.java).setAction(ACTION_GRANT_PROJECTION)
            intent.putExtra(EXTRA_RESULT_CODE, resultCode)
            intent.putExtra(EXTRA_RESULT_DATA, data)
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, PhoneAgentService::class.java).setAction(ACTION_STOP))
        }
    }

    private lateinit var mediaProjectionManager: MediaProjectionManager
    private var mediaProjection: MediaProjection? = null
    private var projectionCapture: ProjectionCapture? = null
    private var pendingCaptureSettings: JSONObject? = null

    private var socket: Socket? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    /** Fires once the phone has gone DRIVING_IDLE_MS without a command. */
    private val drivingIdleRunnable = Runnable { setDriving(false) }
    /**
     * Set once onDestroy starts, so nothing re-posts the notification on the way out. A
     * foreground notification is removed when the service stops, but a notify() racing that
     * teardown comes back as an ordinary one and stays on screen with no service behind it.
     */
    @Volatile
    private var stopping = false
    private var connectTimeoutRunnable: Runnable? = null
    private var reconnectRunnable: Runnable? = null
    private var statusRunnable: Runnable? = null
    private val stateListener: (PhoneAgentStatus) -> Unit = {
        sendStatusNow()
        refreshNotification()
    }

    override fun onCreate() {
        super.onCreate()
        mediaProjectionManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        createNotificationChannel()
        // Go foreground at the earliest possible point: API 34+ raises
        // ForegroundServiceDidNotStartInTimeException (seen on the emulator) when
        // startForeground lags the startForegroundService() call. mediaProjection type is
        // only allowed once capture is granted, so start as dataSync (the socket link).
        goForeground(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        PhoneAgentState.addListener(stateListener)
    }

    private fun goForeground(type: Int) {
        try {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(), type)
        } catch (e: Exception) {
            // e.g. ForegroundServiceStartNotAllowedException (API 31+) when started from the background
            Log.w(TAG, "startForeground(type=$type) failed: ${e.message}")
            PhoneAgentState.update(applicationContext) { it.copy(lastError = "foreground_service: ${e.message}") }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_GRANT_PROJECTION -> handleGrantProjection(intent)
            ACTION_STOP -> {
                stopEverything()
                return START_NOT_STICKY
            }
            else -> connectIfPaired()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        projectionCapture?.restartForRotation()
    }

    override fun onDestroy() {
        stopping = true
        PhoneAgentState.removeListener(stateListener)
        // Nothing is driving a phone whose agent is gone; the idle timer dies with the handler
        // below, so drop the badge here rather than leaving it up until the overlay is torn down.
        setDriving(false)
        teardownSocket()
        projectionCapture?.release()
        mediaProjection?.stop()
        mainHandler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun stopEverything() {
        reconnectRunnable?.let { mainHandler.removeCallbacks(it) }
        reconnectRunnable = null
        teardownSocket()
        projectionCapture?.release()
        mediaProjection?.stop()
        mediaProjection = null
        projectionCapture = null
        PhoneAgentState.update(applicationContext) {
            it.copy(connected = false, connecting = false, captureActive = false, projectionGranted = false)
        }
        stopForeground(true)
        stopSelf()
    }

    // ---- connection -----------------------------------------------------------------------

    private fun connectIfPaired() {
        if (!PhoneAgentPrefs.isPaired(applicationContext)) return
        connectSocket(primary = true)
        startReconnectWatchdog()
    }

    /** Restarts the connection from the primary URL whenever we are paired but not connected. */
    private fun startReconnectWatchdog() {
        reconnectRunnable?.let { mainHandler.removeCallbacks(it) }
        val runnable = object : Runnable {
            override fun run() {
                if (!PhoneAgentPrefs.isPaired(applicationContext)) {
                    reconnectRunnable = null
                    return
                }
                if (socket?.connected() != true) {
                    Log.i(TAG, "still not connected - starting a fresh attempt")
                    connectSocket(primary = true)
                }
                mainHandler.postDelayed(this, RECONNECT_WATCHDOG_MS)
            }
        }
        reconnectRunnable = runnable
        mainHandler.postDelayed(runnable, RECONNECT_WATCHDOG_MS)
    }

    private fun connectSocket(primary: Boolean) {
        teardownSocket()
        // Say the link is trying. Without this the page showed a flat "disconnected" for the
        // whole of a retry cycle, which reads as "nothing is happening" rather than "working
        // on it".
        PhoneAgentState.update(applicationContext) { it.copy(connecting = true) }
        val opts = IO.Options().apply {
            reconnection = true
            reconnectionDelay = 1_000
            reconnectionDelayMax = 30_000
            randomizationFactor = 0.5
            timeout = CONNECT_ATTEMPT_TIMEOUT_MS
        }

        // Primary: connect straight to the LAN host, default Socket.IO path (/socket.io/).
        // Fallback: connect to the host_url origin, through the nginx-proxied path (§1.4).
        val url: String = if (primary) {
            val hostApiUrl = PhoneAgentPrefs.getString(applicationContext, PhoneAgentPrefs.KEY_HOST_API_URL)
                ?: return
            hostApiUrl.trimEnd('/') + Protocol.NAMESPACE
        } else {
            val hostUrl = PhoneAgentPrefs.getString(applicationContext, PhoneAgentPrefs.KEY_HOST_URL) ?: return
            val uri = URI(hostUrl)
            val origin = "${uri.scheme}://${uri.authority}"
            val prefixPath = uri.path?.trimEnd('/') ?: ""
            opts.path = "$prefixPath${Protocol.PROXIED_SOCKETIO_SUFFIX}"
            origin + Protocol.NAMESPACE
        }

        val s = try {
            IO.socket(url, opts)
        } catch (e: Exception) {
            Log.w(TAG, "invalid socket url", e)
            if (primary) connectSocket(primary = false)
            return
        }
        socket = s
        wireSocketListeners(s)
        s.connect()

        if (primary) {
            val runnable = Runnable {
                if (socket === s && s.connected().not()) {
                    Log.i(TAG, "host_api_url unreachable, falling back to host_url")
                    connectSocket(primary = false)
                }
            }
            connectTimeoutRunnable = runnable
            mainHandler.postDelayed(runnable, CONNECT_ATTEMPT_TIMEOUT_MS)
        }
    }

    private fun teardownSocket() {
        if (PhoneAgentState.current.driving) setDriving(false)
        connectTimeoutRunnable?.let { mainHandler.removeCallbacks(it) }
        connectTimeoutRunnable = null
        statusRunnable?.let { mainHandler.removeCallbacks(it) }
        statusRunnable = null
        socket?.off()
        socket?.disconnect()
        socket = null
    }

    private fun wireSocketListeners(s: Socket) {
        s.on(Socket.EVENT_CONNECT) {
            connectTimeoutRunnable?.let { mainHandler.removeCallbacks(it) }
            sendHello(s)
        }
        s.on(Socket.EVENT_DISCONNECT) {
            // Socket.IO reconnects by itself after a drop, and the watchdog covers it if not.
            PhoneAgentState.update(applicationContext) { it.copy(connected = false, connecting = true) }
        }
        s.on(Socket.EVENT_CONNECT_ERROR) { args ->
            Log.w(TAG, "connect_error: ${args.firstOrNull()}")
        }
        s.on(Protocol.EV_CAPTURE) { args -> (args.firstOrNull() as? JSONObject)?.let { applyCaptureSettings(it) } }
        s.on(Protocol.EV_CMD) { args -> handleCmdEvent(args) }
        s.on(Protocol.EV_UNPAIR) { handleUnpair() }
    }

    private fun sendHello(s: Socket) {
        val screen = resources.displayMetrics
        val device = JSONObject()
            .put("manufacturer", Build.MANUFACTURER)
            .put("model", Build.MODEL)
            .put("android", Build.VERSION.RELEASE)
            .put("app_version", appVersionName())
            .put(
                "screen",
                JSONObject()
                    .put("w", screen.widthPixels)
                    .put("h", screen.heightPixels)
                    .put("density", screen.densityDpi),
            )
        val payload = JSONObject().put("v", Protocol.PROTOCOL_VERSION).put("device", device)
        val secret = PhoneAgentPrefs.getString(applicationContext, PhoneAgentPrefs.KEY_DEVICE_SECRET)
        val token = PhoneAgentPrefs.getString(applicationContext, PhoneAgentPrefs.KEY_TOKEN)
        if (!secret.isNullOrBlank()) {
            payload.put("device_secret", secret)
        } else if (!token.isNullOrBlank()) {
            payload.put("token", token)
        }
        s.emit(Protocol.EV_HELLO, payload, Ack { args -> onHelloAck(args) })
    }

    private fun onHelloAck(args: Array<out Any>) {
        val ack = args.firstOrNull() as? JSONObject
        if (ack == null || !ack.optBoolean("ok", false)) {
            val error = ack?.optString("error").takeUnless { it.isNullOrBlank() } ?: "hello_rejected"
            Log.w(TAG, "hello rejected: $error")
            if (isDeadCredential(error)) {
                // The saved pairing can never work again: the host has no slot holding this
                // secret — its state file was lost or wiped across a restart, or the slot was
                // re-paired to another phone — and every reconnect will be refused the same
                // way. Keeping the pairing left the page insisting "paired" while the link sat
                // at disconnected / 0 fps forever, with Unpair the only way out and nothing
                // saying why. Drop the dead credential so the page falls back to "Scan QR
                // code", and keep the reason on screen.
                Log.i(TAG, "dropping the stored pairing; it can no longer authenticate")
                PhoneAgentPrefs.clearPairing(applicationContext)
                stopEverything()
                PhoneAgentState.update(applicationContext) { it.copy(lastError = error) }
                return
            }
            // Still trying: this refusal may be transient (the host restarting mid-hello), and
            // the watchdog starts a fresh attempt shortly.
            PhoneAgentState.update(applicationContext) { it.copy(connected = false, connecting = true, lastError = error) }
            socket?.disconnect()
            return
        }
        // The one-time token is now consumed server-side; reconnects must use the device secret.
        val newSecret = ack.optString("device_secret", "")
        if (newSecret.isNotBlank()) {
            PhoneAgentPrefs.putAll(
                applicationContext,
                mapOf(PhoneAgentPrefs.KEY_DEVICE_SECRET to newSecret, PhoneAgentPrefs.KEY_TOKEN to null),
            )
        }
        PhoneAgentState.update(applicationContext) { it.copy(connected = true, connecting = false, lastError = null) }
        startStatusLoop()
        ack.optJSONObject("capture")?.let { applyCaptureSettings(it) }
    }

    /**
     * True when the host rejected us because the credential itself is worthless, rather than
     * for something transient. These are the three refusals `handle_hello` can return
     * (features/mobile-app/backend_host/bridge.py); a retry with the same stored secret or
     * token gets the same answer every time, so the only way forward is a fresh pairing.
     */
    private fun isDeadCredential(error: String): Boolean {
        val e = error.lowercase()
        return e.contains("device_secret") || e.contains("token")
    }

    private fun handleUnpair() {
        Log.i(TAG, "unpaired by host")
        PhoneAgentPrefs.clearPairing(applicationContext)
        stopEverything()
    }

    // ---- capture ----------------------------------------------------------------------------

    private fun applyCaptureSettings(settings: JSONObject) {
        val fps = settings.optInt("fps", Protocol.DEFAULT_FPS)
        val maxSide = settings.optInt("max_side", Protocol.DEFAULT_MAX_SIDE)
        val quality = settings.optInt("quality", Protocol.DEFAULT_QUALITY)
        val projection = mediaProjection
        if (projection == null) {
            // Remembered and applied once the user grants MediaProjection (requestProjection()).
            pendingCaptureSettings = settings
            return
        }
        val capture = projectionCapture ?: ProjectionCapture(applicationContext, projection) { jpeg, w, h ->
            sendFrame(jpeg, w, h)
        }.also { projectionCapture = it }
        if (fps <= 0) {
            capture.stop()
        } else {
            capture.start(fps, maxSide, quality)
        }
        PhoneAgentState.update(applicationContext) { it.copy(captureActive = fps > 0, fps = fps.toDouble()) }
    }

    private fun sendFrame(jpeg: ByteArray, width: Int, height: Int) {
        val s = socket ?: return
        if (!s.connected()) return
        val meta = JSONObject()
            .put("ts", System.currentTimeMillis() / 1000.0)
            .put("w", width)
            .put("h", height)
            .put("rotation", currentRotationDegrees())
        s.emit(Protocol.EV_FRAME, meta, jpeg)
    }

    private fun currentRotationDegrees(): Int = try {
        when (windowManager()?.defaultDisplay?.rotation) {
            android.view.Surface.ROTATION_90 -> 90
            android.view.Surface.ROTATION_180 -> 180
            android.view.Surface.ROTATION_270 -> 270
            else -> 0
        }
    } catch (e: Exception) {
        0
    }

    private fun windowManager() = getSystemService(WINDOW_SERVICE) as? android.view.WindowManager

    // ---- MediaProjection grant ----------------------------------------------------------------

    private fun handleGrantProjection(intent: Intent) {
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, android.app.Activity.RESULT_CANCELED)
        val data = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
        if (resultCode != android.app.Activity.RESULT_OK || data == null) {
            PhoneAgentState.update(applicationContext) { it.copy(projectionGranted = false, lastError = "projection_denied") }
            return
        }
        mediaProjection?.stop()
        // API 34+: the service must already be foreground WITH the mediaProjection type
        // before getMediaProjection() is called, else it throws SecurityException.
        goForeground(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        val projection = mediaProjectionManager.getMediaProjection(resultCode, data)
        mediaProjection = projection
        projection.registerCallback(
            object : MediaProjection.Callback() {
                override fun onStop() {
                    // The projection we just replaced also reports onStop, and it is delivered
                    // on mainHandler — i.e. AFTER this method has finished installing its
                    // replacement. Without this guard that late callback tore down the NEW
                    // capture it knows nothing about: virtual display created and destroyed in
                    // the same breath, projectionGranted back to false with no error logged,
                    // and the checklist showing "Fix" seconds after the user had allowed it.
                    // Only the projection that is still the current one may tear anything down.
                    if (mediaProjection !== projection) return
                    projectionCapture?.release()
                    projectionCapture = null
                    mediaProjection = null
                    PhoneAgentState.update(applicationContext) { it.copy(projectionGranted = false, captureActive = false) }
                }
            },
            mainHandler,
        )
        projectionCapture = ProjectionCapture(applicationContext, projection) { jpeg, w, h -> sendFrame(jpeg, w, h) }
        PhoneAgentState.update(applicationContext) { it.copy(projectionGranted = true) }
        pendingCaptureSettings?.let {
            applyCaptureSettings(it)
            pendingCaptureSettings = null
        }
    }

    // ---- cmd dispatch (§1.3) -------------------------------------------------------------------

    private fun handleCmdEvent(args: Array<out Any>) {
        val payload = args.firstOrNull() as? JSONObject
        val ack = args.lastOrNull() as? Ack
        if (payload == null) {
            ack?.call(JSONObject().put("ok", false).put("error", "bad_payload"))
            return
        }
        val name = payload.optString("name")
        val params = payload.optJSONObject("params") ?: JSONObject()
        handleCommand(name, params) { result, error ->
            val response = JSONObject().put("ok", error == null)
            if (error != null) response.put("error", error) else if (result != null) response.put("result", result)
            ack?.call(response)
        }
    }

    /**
     * Shows the command on the phone's own screen, so someone holding it can see that a script
     * is driving rather than the device misbehaving - and can tell a command that never arrived
     * from one that arrived and did nothing.
     *
     * CMD_SCREENSHOT is deliberately absent: its caption would be *in* the frame it captures.
     * That one is announced after the grab. CMD_TEXT is announced without its value, because a
     * tree can carry a credential there and this draws onto a screen that is being recorded.
     */
    private fun announce(name: String, params: JSONObject) {
        val overlay = VptAccessibilityService.instance?.overlay ?: return
        when (name) {
            Protocol.CMD_TAP -> overlay.tap(params.optInt("x"), params.optInt("y"))
            Protocol.CMD_SWIPE -> overlay.swipe(
                params.optInt("x1"), params.optInt("y1"), params.optInt("x2"), params.optInt("y2"),
            )
            Protocol.CMD_KEY -> overlay.action("key " + params.optString("key"))
            Protocol.CMD_TEXT -> overlay.action("type text")
            Protocol.CMD_LAUNCH_APP -> overlay.action(
                (if (params.optBoolean("reset")) "restart " else "launch ") + params.optString("package"),
            )
            Protocol.CMD_CLOSE_APP -> overlay.action("close app")
            Protocol.CMD_LIST_APPS -> overlay.action("list apps")
            Protocol.CMD_DUMP_UI -> overlay.action("dump UI")
            Protocol.CMD_DEVICE_INFO -> overlay.action("device info")
        }
    }

    /**
     * Note that a host is driving, and start the clock that will say it stopped.
     *
     * Every command refreshes it, so the state lasts as long as the traffic does.
     */
    private fun markDriving(runLabel: String?) {
        mainHandler.removeCallbacks(drivingIdleRunnable)
        mainHandler.postDelayed(drivingIdleRunnable, DRIVING_IDLE_MS)
        val label = runLabel?.takeIf { it.isNotBlank() }
        // A later command in the same run repeats the label; a different run replaces it.
        if (!PhoneAgentState.current.driving || label != PhoneAgentState.current.runLabel) {
            setDriving(true, label)
        }
    }

    private fun setDriving(driving: Boolean, runLabel: String? = null) {
        PhoneAgentState.update(applicationContext) {
            it.copy(driving = driving, runLabel = if (driving) runLabel else null)
        }
        VptAccessibilityService.instance?.overlay?.setDriving(driving, runLabel)
        // Only the colour and the wording change, so a repost is all this needs.
        refreshNotification()
    }

    private fun handleCommand(name: String, params: JSONObject, callback: (JSONObject?, String?) -> Unit) {
        // `_run` is the host telling us which script is driving; see
        // PhoneAgentRemoteController._with_run_label. Absent when a person is driving the
        // remote panel, which is exactly when a script name would be a lie.
        markDriving(params.optString("_run").takeIf { it.isNotBlank() })
        announce(name, params)
        when (name) {
            Protocol.CMD_TAP -> withAccessibility(callback) { access, cb ->
                access.tap(params.optInt("x"), params.optInt("y")) { ok -> cb(null, if (ok) null else "gesture_failed") }
            }
            Protocol.CMD_SWIPE -> withAccessibility(callback) { access, cb ->
                access.swipe(
                    params.optInt("x1"), params.optInt("y1"), params.optInt("x2"), params.optInt("y2"),
                    params.optLong("duration_ms", 300L),
                ) { ok -> cb(null, if (ok) null else "gesture_failed") }
            }
            Protocol.CMD_KEY -> withAccessibility(callback) { access, cb -> cb(null, access.pressKey(params.optString("key"))) }
            Protocol.CMD_TEXT -> withAccessibility(callback) { access, cb -> cb(null, access.setText(params.optString("text"))) }
            Protocol.CMD_LAUNCH_APP -> withAccessibility(callback) { access, cb ->
                cb(null, access.launchApp(params.optString("package"), params.optBoolean("reset")))
            }
            Protocol.CMD_CLOSE_APP -> withAccessibility(callback) { access, cb -> cb(null, access.closeApp()) }
            Protocol.CMD_LIST_APPS -> withAccessibility(callback) { access, cb ->
                cb(JSONObject().put("apps", access.listApps()), null)
            }
            Protocol.CMD_DUMP_UI -> withAccessibility(callback) { access, cb ->
                cb(JSONObject().put("elements", access.dumpUi()), null)
            }
            Protocol.CMD_SCREENSHOT -> handleScreenshot { result, error ->
                // Announced only now: the frame is already taken, so the caption cannot land
                // inside the screenshot the host is about to verify against.
                VptAccessibilityService.instance?.overlay?.action("screenshot")
                callback(result, error)
            }
            Protocol.CMD_DEVICE_INFO -> callback(deviceInfoJson(), null)
            else -> callback(null, "unknown_command: $name")
        }
    }

    private fun withAccessibility(
        callback: (JSONObject?, String?) -> Unit,
        block: (VptAccessibilityService, (JSONObject?, String?) -> Unit) -> Unit,
    ) {
        val access = VptAccessibilityService.instance
        if (access == null) {
            callback(null, "accessibility_disabled")
            return
        }
        mainHandler.post { block(access, callback) }
    }

    private fun handleScreenshot(callback: (JSONObject?, String?) -> Unit) {
        val capture = projectionCapture
        if (capture == null) {
            callback(null, "projection_not_granted")
            return
        }
        capture.lastFrame?.let {
            callback(screenshotResult(it), null)
            return
        }
        val wasRunning = capture.isRunning
        if (!wasRunning) capture.start(2, Protocol.DEFAULT_MAX_SIDE, Protocol.DEFAULT_QUALITY)
        val deadline = System.currentTimeMillis() + Protocol.CMD_TIMEOUT_SLOW_S * 1000
        mainHandler.post(
            object : Runnable {
                override fun run() {
                    val frame = capture.lastFrame
                    when {
                        frame != null -> {
                            if (!wasRunning) capture.stop()
                            callback(screenshotResult(frame), null)
                        }
                        System.currentTimeMillis() >= deadline -> {
                            if (!wasRunning) capture.stop()
                            callback(null, "screenshot_timeout")
                        }
                        else -> mainHandler.postDelayed(this, SCREENSHOT_POLL_MS)
                    }
                }
            },
        )
    }

    private fun screenshotResult(frame: ProjectionCapture.Frame) = JSONObject()
        .put("jpeg_b64", Base64.encodeToString(frame.jpeg, Base64.NO_WRAP))
        .put("w", frame.width)
        .put("h", frame.height)

    private fun deviceInfoJson(): JSONObject {
        val screen = resources.displayMetrics
        return JSONObject()
            .put("manufacturer", Build.MANUFACTURER)
            .put("model", Build.MODEL)
            .put("android", Build.VERSION.RELEASE)
            .put(
                "screen",
                JSONObject().put("w", screen.widthPixels).put("h", screen.heightPixels).put("density", screen.densityDpi),
            )
            .put("battery", batteryPercent())
    }

    // ---- status loop (every 15s + on connect) ---------------------------------------------

    private fun startStatusLoop() {
        statusRunnable?.let { mainHandler.removeCallbacks(it) }
        val runnable = object : Runnable {
            override fun run() {
                sendStatusNow()
                mainHandler.postDelayed(this, STATUS_INTERVAL_MS)
            }
        }
        statusRunnable = runnable
        mainHandler.post(runnable)
    }

    private fun sendStatusNow() {
        val s = socket ?: return
        if (!s.connected()) return
        val status = JSONObject()
            .put("battery", batteryPercent())
            .put("charging", isCharging())
            .put("thermal", thermalStatus())
            .put("foreground_app", "") // requires Usage Access, not part of the granted permission set
            .put("capture_active", projectionCapture?.isRunning ?: false)
            .put("accessibility_enabled", VptAccessibilityService.instance != null)
            .put("projection_granted", mediaProjection != null)
        s.emit(Protocol.EV_STATUS, status)
    }

    private fun batteryPercent(): Int = try {
        val intent = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        if (level >= 0 && scale > 0) (level * 100 / scale) else -1
    } catch (e: Exception) {
        -1
    }

    private fun isCharging(): Boolean = try {
        val intent = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val status = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
    } catch (e: Exception) {
        false
    }

    private fun thermalStatus(): String = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            pm.currentThermalStatus.toString()
        } else {
            "unknown"
        }
    } catch (e: Exception) {
        "unknown"
    }

    private fun appVersionName(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "unknown"
    } catch (e: Exception) {
        "unknown"
    }

    // ---- notification -----------------------------------------------------------------------

    private fun createNotificationChannel() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(CHANNEL_ID, "VirtualPyTest link", NotificationManager.IMPORTANCE_LOW)
        channel.description = "Whether this phone is connected to its VirtualPyTest host"
        manager.createNotificationChannel(channel)
    }

    /**
     * The one place on the phone that can say whether the link is up.
     *
     * Android's own screen-capture indicator looks identical either way — it only means
     * "something can see this screen" — so without this there is no way to tell a working
     * agent from a dead one without opening the app. The status bar renders a small icon as a
     * flat silhouette (colour there is not ours to set), so up/down has to be carried by the
     * SHAPE: a filled dot when connected, a hollow one when not. The colour and the wording
     * then make it unambiguous once the shade is pulled down.
     */
    private fun buildNotification(): Notification {
        val s = PhoneAgentState.current
        val connected = s.connected
        // Driving is the state worth seeing at a glance, so it wins the colour and the title.
        val driving = connected && s.driving
        val detail = when {
            !s.paired -> "Not paired — scan a pairing QR"
            driving && s.runLabel != null -> "Running ${s.runLabel} on this phone"
            driving -> "${s.hostName ?: "A host"} is running a test on this phone"
            connected && s.captureActive -> "Connected to ${s.hostName ?: "host"} · streaming ${fpsLabel(s.fps)}"
            connected -> "Connected to ${s.hostName ?: "host"} · not streaming"
            s.lastError != null -> "Disconnected — ${s.lastError}"
            else -> "Disconnected — reconnecting"
        }
        val title = when {
            driving -> "VirtualPyTest — under test"
            connected -> "VirtualPyTest — connected"
            else -> "VirtualPyTest — disconnected"
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(detail)
            .setStyle(NotificationCompat.BigTextStyle().bigText(detail))
            .setSmallIcon(
                if (connected) android.R.drawable.presence_online else android.R.drawable.presence_offline,
            )
            .setColor(if (driving) COLOR_DRIVING else if (connected) COLOR_CONNECTED else COLOR_DISCONNECTED)
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setShowWhen(false)
            .build()
    }

    private fun fpsLabel(fps: Double): String =
        if (fps % 1.0 == 0.0) "${fps.toInt()} fps" else "$fps fps"

    private fun openAppIntent(): PendingIntent? = try {
        val intent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE)
    } catch (e: Exception) {
        null
    }

    /**
     * Re-post the ongoing notification so it matches the current state. Silently does nothing
     * when the user has not granted POST_NOTIFICATIONS (Android 13+) — the service keeps
     * running either way, there is simply nothing on screen to update.
     */
    private fun refreshNotification() {
        if (stopping) return
        try {
            NotificationManagerCompat.from(this).notify(NOTIFICATION_ID, buildNotification())
        } catch (e: SecurityException) {
            // POST_NOTIFICATIONS not granted; PhoneAgentPlugin.enableNotifications() asks for it.
        }
    }
}
