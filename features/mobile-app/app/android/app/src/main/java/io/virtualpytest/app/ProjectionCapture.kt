package io.virtualpytest.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import java.io.ByteArrayOutputStream
import kotlin.math.max

/**
 * MediaProjection -> ImageReader(RGBA_8888) -> scaled JPEG, at the fps/max_side/quality the
 * host's `capture` event (§1.3) requests. One instance per granted [MediaProjection]; call
 * [start]/[updateSettings]/[stop] from PhoneAgentService. Every captured frame is cached
 * ([lastFrame]) so the `screenshot` cmd can reuse it instead of starting a second capture.
 */
class ProjectionCapture(
    private val context: Context,
    private val mediaProjection: MediaProjection,
    private val onFrame: (jpeg: ByteArray, width: Int, height: Int) -> Unit,
) {
    companion object {
        private const val TAG = "ProjectionCapture"
        private const val VIRTUAL_DISPLAY_NAME = "vpt-phone-agent"
    }

    data class Frame(val jpeg: ByteArray, val width: Int, val height: Int)

    private var handlerThread: HandlerThread? = null
    private var handler: Handler? = null
    private var imageReader: ImageReader? = null
    private var virtualDisplay: VirtualDisplay? = null

    @Volatile private var fps: Int = Protocol.DEFAULT_FPS
    @Volatile private var maxSide: Int = Protocol.DEFAULT_MAX_SIDE
    @Volatile private var quality: Int = Protocol.DEFAULT_QUALITY
    @Volatile private var lastEmitMs: Long = 0

    @Volatile
    var lastFrame: Frame? = null
        private set

    /** Emission is paused rather than torn down — see [stop]. */
    @Volatile private var paused: Boolean = false

    val isRunning: Boolean get() = virtualDisplay != null && !paused

    /**
     * Starts (or re-tunes, e.g. after a rotation) capture at the given settings. fps<=0 stops.
     *
     * Android 14 allows exactly ONE VirtualDisplay per MediaProjection, for the life of that
     * projection — a second `createVirtualDisplay` is refused even after the first is
     * released: "Don't take multiple captures by invoking MediaProjection#createVirtualDisplay
     * multiple times on the same instance". This used to tear the display down and rebuild it
     * on every settings change, so the first `capture` event after a successful pairing threw
     * SecurityException on the Socket.IO event thread and took the whole process with it —
     * the phone paired, crashed, was restarted by Android, paired again, crashed again. The
     * display is therefore created once and afterwards adapted in place with
     * resize()/setSurface(), which is the supported way to follow a rotation or a new size.
     */
    @Synchronized
    fun start(fps: Int, maxSide: Int, quality: Int) {
        if (fps <= 0) {
            stop()
            return
        }
        this.fps = fps
        this.maxSide = maxSide
        this.quality = quality.coerceIn(1, 100)
        paused = false

        val metrics = context.resources.displayMetrics
        val width = metrics.widthPixels
        val height = metrics.heightPixels
        val density = metrics.densityDpi

        if (handlerThread == null) {
            handlerThread = HandlerThread("vpt-projection-capture").also { it.start() }
            handler = Handler(handlerThread!!.looper)
        }

        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        reader.setOnImageAvailableListener({ ir ->
            val image = try {
                ir.acquireLatestImage()
            } catch (e: Exception) {
                null
            } ?: return@setOnImageAvailableListener
            try {
                if (paused) return@setOnImageAvailableListener
                val now = System.currentTimeMillis()
                val minIntervalMs = 1000L / this.fps.coerceAtLeast(1)
                if (now - lastEmitMs < minIntervalMs) return@setOnImageAvailableListener
                lastEmitMs = now
                encodeAndEmit(image, width, height)
            } catch (e: Exception) {
                Log.w(TAG, "frame encode failed", e)
            } finally {
                image.close()
            }
        }, handler)

        val existing = virtualDisplay
        try {
            if (existing == null) {
                virtualDisplay = mediaProjection.createVirtualDisplay(
                    VIRTUAL_DISPLAY_NAME,
                    width,
                    height,
                    density,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    reader.surface,
                    null,
                    handler,
                )
            } else {
                // Same display, new geometry/target — no second createVirtualDisplay.
                existing.resize(width, height, density)
                existing.surface = reader.surface
            }
        } catch (e: Exception) {
            // Never let this reach the caller: start() runs on the Socket.IO event thread, so
            // an exception here is an uncaught crash rather than a failed frame.
            Log.w(TAG, "could not (re)configure the capture display", e)
            reader.close()
            return
        }
        val previous = imageReader
        imageReader = reader
        previous?.close()
    }

    fun updateSettings(fps: Int, maxSide: Int, quality: Int) = start(fps, maxSide, quality)

    /** Call from the service's onConfigurationChanged while running, to pick up the new rotation. */
    fun restartForRotation() {
        if (isRunning) start(fps, maxSide, quality)
    }

    /**
     * Stops emitting frames but KEEPS the VirtualDisplay. The one display this MediaProjection
     * is ever allowed (Android 14+) must survive a pause, or the next start would need a
     * second one and be refused — which is why the screenshot path, which briefly starts and
     * stops capture, used to poison every later capture. Use [release] to actually tear down.
     */
    @Synchronized
    fun stop() {
        paused = true
    }

    /** Full teardown, for when the projection itself is going away. */
    @Synchronized
    fun release() {
        paused = true
        teardownDisplay()
        handlerThread?.quitSafely()
        handlerThread = null
        handler = null
    }

    private fun teardownDisplay() {
        virtualDisplay?.release()
        virtualDisplay = null
        imageReader?.close()
        imageReader = null
    }

    private fun encodeAndEmit(image: Image, srcWidth: Int, srcHeight: Int) {
        val plane = image.planes[0]
        val buffer = plane.buffer
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val rowPadding = rowStride - pixelStride * srcWidth

        var bitmap = Bitmap.createBitmap(
            srcWidth + rowPadding / pixelStride,
            srcHeight,
            Bitmap.Config.ARGB_8888,
        )
        bitmap.copyPixelsFromBuffer(buffer)
        if (rowPadding != 0) {
            val cropped = Bitmap.createBitmap(bitmap, 0, 0, srcWidth, srcHeight)
            bitmap.recycle()
            bitmap = cropped
        }

        val longSide = max(bitmap.width, bitmap.height)
        if (longSide > maxSide) {
            val scale = maxSide.toDouble() / longSide
            val scaledW = max(1, (bitmap.width * scale).toInt())
            val scaledH = max(1, (bitmap.height * scale).toInt())
            val scaled = Bitmap.createScaledBitmap(bitmap, scaledW, scaledH, true)
            if (scaled !== bitmap) bitmap.recycle()
            bitmap = scaled
        }

        val out = ByteArrayOutputStream(64 * 1024)
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
        val w = bitmap.width
        val h = bitmap.height
        bitmap.recycle()

        val jpeg = out.toByteArray()
        lastFrame = Frame(jpeg, w, h)
        onFrame(jpeg, w, h)
    }
}
