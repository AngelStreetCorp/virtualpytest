package io.virtualpytest.app

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.PointF
import android.graphics.RectF
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager

/**
 * Shows what the host is doing, on the phone itself: a ripple where a tap landed, a trail for a
 * swipe, and a caption naming the command ("tap 540,1200", "swipe left", "screenshot", "dump UI").
 *
 * Without it a phone under test looks possessed — things happen with no indication that a script
 * rather than a person is driving, and when nothing happens there is no way to tell a command
 * that was never delivered from one that was delivered and ignored.
 *
 * **Drawn from the AccessibilityService**, using TYPE_ACCESSIBILITY_OVERLAY. That window type is
 * granted by the accessibility service the agent already requires, so this costs no extra
 * permission — SYSTEM_ALERT_WINDOW ("draw over other apps") would have been another settings trip
 * and another row that could block pairing.
 *
 * **The per-action visuals are transient by design.** The overlay is part of the screen, so
 * MediaProjection captures it, and a caption still on screen when a verification grabs its frame
 * is a caption inside the evidence. Each visual clears itself well before the shortest `wait_time`
 * a tree uses (2s), and the window is removed entirely once nothing is showing, so an idle phone
 * streams exactly what it would without this.
 *
 * **The "under test" badge is the deliberate exception.** It stays up for as long as the host
 * keeps driving, because its whole job is to be visible when you glance at the phone — which
 * means it IS in every captured frame while a script runs. It is kept small and pinned to the
 * top-right strip above app content for that reason, and the whole overlay (badge included) is
 * behind the Execution overlay setting, so a run whose image references were captured without it
 * can turn it off.
 */
class ActionOverlay(private val service: VptAccessibilityService) {

    companion object {
        private const val TAG = "VptActionOverlay"
        /** A tap ripple lives this long. Short enough to be gone before any verification frame. */
        private const val RIPPLE_MS = 450L
        /** A swipe trail follows the gesture, then fades. */
        private const val SWIPE_MS = 600L
        /** How long the caption stays up. */
        private const val LABEL_MS = 900L
        private const val RIPPLE_MAX_RADIUS_DP = 44f
        private const val ACCENT = 0xFF29B6F6.toInt()   // the same blue a running script uses in the UI
        /** One breath of the badge's pulse. Slow enough to read as "alive", not as a strobe. */
        private const val BADGE_PULSE_MS = 1400L
        /** Longest script name the badge shows before cutting it. */
        private const val BADGE_LABEL_MAX = 22
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private val windowManager = service.getSystemService(Context.WINDOW_SERVICE) as? WindowManager
    private var view: OverlayView? = null
    private val hideRunnable = Runnable { detachIfIdle() }

    // ---- public API, called from the command dispatch ---------------------------------------

    fun tap(x: Int, y: Int) = post {
        it.ripple(x.toFloat(), y.toFloat(), RIPPLE_MS)
        it.caption("tap $x,$y", LABEL_MS)
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int) = post {
        it.trail(PointF(x1.toFloat(), y1.toFloat()), PointF(x2.toFloat(), y2.toFloat()), SWIPE_MS)
        it.caption("swipe ${direction(x1, y1, x2, y2)}", LABEL_MS)
    }

    /** Anything without a position — a key, text entry, a screenshot, a UI dump. */
    fun action(label: String) = post { it.caption(label, LABEL_MS) }

    /**
     * Raise or drop the persistent "under test" badge.
     *
     * Unlike the per-action visuals this one has no timer of its own: PhoneAgentService decides
     * when driving starts and stops, and the badge follows exactly. Turning it off also lets the
     * window go, so a phone nobody is driving is back to streaming its own screen and nothing
     * else.
     */
    fun setDriving(driving: Boolean, runLabel: String? = null) {
        mainHandler.post {
            if (driving) {
                if (!PhoneAgentPrefs.isActionOverlayEnabled(service.applicationContext)) return@post
                attach()?.setDriving(true, runLabel)
                // The badge outlives every per-action visual, so cancel the teardown those
                // schedule — otherwise the first quiet moment takes the window down with it.
                mainHandler.removeCallbacks(hideRunnable)
            } else {
                view?.setDriving(false)
                mainHandler.removeCallbacks(hideRunnable)
                mainHandler.post(hideRunnable)
            }
        }
    }

    /** Human-readable direction, which is how someone watching the phone thinks about a swipe. */
    private fun direction(x1: Int, y1: Int, x2: Int, y2: Int): String {
        val dx = x2 - x1
        val dy = y2 - y1
        return if (kotlin.math.abs(dx) >= kotlin.math.abs(dy)) {
            if (dx < 0) "left" else "right"
        } else {
            if (dy < 0) "up" else "down"
        }
    }

    // ---- window lifecycle -------------------------------------------------------------------

    private fun post(block: (OverlayView) -> Unit) {
        mainHandler.post {
            if (!PhoneAgentPrefs.isActionOverlayEnabled(service.applicationContext)) return@post
            val v = attach() ?: return@post
            block(v)
            mainHandler.removeCallbacks(hideRunnable)
            // Longest single visual + slack, so the window goes away rather than lingering
            // transparent over whatever the phone is doing.
            mainHandler.postDelayed(hideRunnable, LABEL_MS + 400L)
        }
    }

    private fun attach(): OverlayView? {
        view?.let { return it }
        val wm = windowManager ?: return null
        val v = OverlayView(service)
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            // Not focusable and not touchable: the overlay must never intercept the very
            // gestures it is drawing, nor take focus from the app under test.
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.TOP or Gravity.START }

        return try {
            wm.addView(v, params)
            view = v
            v
        } catch (e: Exception) {
            // A window can be refused (service tearing down, odd OEM policy). The agent must
            // keep working without its decorations.
            Log.w(TAG, "could not add the action overlay", e)
            null
        }
    }

    private fun detachIfIdle() {
        val v = view ?: return
        // The badge has no timer: it comes down when the host stops driving, and setDriving(false)
        // schedules this again. Re-checking on a 200ms tick meanwhile would just spin.
        if (v.isDriving()) return
        if (v.isShowingSomething()) {
            mainHandler.postDelayed(hideRunnable, 200L)
            return
        }
        try {
            windowManager?.removeView(v)
        } catch (e: Exception) {
            Log.w(TAG, "could not remove the action overlay", e)
        }
        view = null
    }

    /** Called when the service goes away, so no window outlives it. */
    fun destroy() {
        mainHandler.removeCallbacks(hideRunnable)
        mainHandler.post {
            val v = view ?: return@post
            try {
                windowManager?.removeView(v)
            } catch (_: Exception) {
            }
            view = null
        }
    }

    // ---- drawing ----------------------------------------------------------------------------

    private class OverlayView(context: Context) : View(context) {

        private val density = context.resources.displayMetrics.density
        private val ripplePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 3f * density
            color = ACCENT
        }
        private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = ACCENT
        }
        private val trailPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 5f * density
            strokeCap = Paint.Cap.ROUND
            color = ACCENT
        }
        private val pillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = 0xCC000000.toInt()
        }
        private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 13f * density
            textAlign = Paint.Align.CENTER
        }
        private val badgePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = ACCENT
        }
        private val badgeTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = 12f * density
            textAlign = Paint.Align.LEFT
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        }

        private var rippleCenter: PointF? = null
        private var rippleProgress = 0f
        private var swipeFrom: PointF? = null
        private var swipeTo: PointF? = null
        private var swipeProgress = 0f
        private var captionText: String? = null
        private var captionAlpha = 0f
        private var driving = false
        private var badgePulse = 1f
        private var badgeLabel: String? = null

        private var rippleAnim: ValueAnimator? = null
        private var swipeAnim: ValueAnimator? = null
        private var captionAnim: ValueAnimator? = null
        private var badgeAnim: ValueAnimator? = null

        fun isShowingSomething(): Boolean =
            rippleCenter != null || swipeFrom != null || captionText != null || driving

        fun isDriving(): Boolean = driving

        fun setDriving(on: Boolean, runLabel: String? = null) {
            // The label can change while driving stays true (a second script on the same
            // phone), so a plain equality guard on `on` alone would pin the first name.
            val label = runLabel?.takeIf { it.isNotBlank() }
            if (driving == on && label == badgeLabel) return
            badgeLabel = label
            driving = on
            badgeAnim?.cancel()
            badgeAnim = null
            if (on) {
                badgeAnim = ValueAnimator.ofFloat(1f, 0.45f).apply {
                    duration = BADGE_PULSE_MS
                    repeatMode = ValueAnimator.REVERSE
                    repeatCount = ValueAnimator.INFINITE
                    addUpdateListener { badgePulse = it.animatedValue as Float; invalidate() }
                    start()
                }
            } else {
                badgePulse = 1f
            }
            invalidate()
        }

        override fun onDetachedFromWindow() {
            super.onDetachedFromWindow()
            // An INFINITE animator keeps posting frames forever if the view goes without it.
            badgeAnim?.cancel()
            badgeAnim = null
        }

        fun ripple(x: Float, y: Float, durationMs: Long) {
            rippleAnim?.cancel()
            rippleCenter = PointF(x, y)
            rippleAnim = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = durationMs
                addUpdateListener { rippleProgress = it.animatedValue as Float; invalidate() }
                addListener(onEnd = { rippleCenter = null; invalidate() })
                start()
            }
        }

        fun trail(from: PointF, to: PointF, durationMs: Long) {
            swipeAnim?.cancel()
            swipeFrom = from
            swipeTo = to
            swipeAnim = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = durationMs
                addUpdateListener { swipeProgress = it.animatedValue as Float; invalidate() }
                addListener(onEnd = { swipeFrom = null; swipeTo = null; invalidate() })
                start()
            }
        }

        fun caption(text: String, durationMs: Long) {
            captionAnim?.cancel()
            captionText = text
            captionAnim = ValueAnimator.ofFloat(1f, 1f, 0f).apply {
                duration = durationMs
                addUpdateListener { captionAlpha = it.animatedValue as Float; invalidate() }
                addListener(onEnd = { captionText = null; invalidate() })
                start()
            }
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)

            if (driving) drawBadge(canvas)

            rippleCenter?.let { c ->
                val max = RIPPLE_MAX_RADIUS_DP * density
                val alpha = ((1f - rippleProgress) * 255).toInt().coerceIn(0, 255)
                ripplePaint.alpha = alpha
                canvas.drawCircle(c.x, c.y, max * rippleProgress, ripplePaint)
                fillPaint.alpha = (alpha * 0.35f).toInt().coerceIn(0, 255)
                canvas.drawCircle(c.x, c.y, max * 0.22f * (1f - rippleProgress), fillPaint)
            }

            val from = swipeFrom
            val to = swipeTo
            if (from != null && to != null) {
                trailPaint.alpha = ((1f - swipeProgress) * 220).toInt().coerceIn(0, 255)
                // The head travels with the gesture rather than drawing the whole path at once,
                // so the direction is readable at a glance.
                val hx = from.x + (to.x - from.x) * swipeProgress
                val hy = from.y + (to.y - from.y) * swipeProgress
                canvas.drawLine(from.x, from.y, hx, hy, trailPaint)
                fillPaint.alpha = trailPaint.alpha
                canvas.drawCircle(hx, hy, 7f * density, fillPaint)
            }

            captionText?.let { text ->
                val alpha = (captionAlpha * 255).toInt().coerceIn(0, 255)
                val padH = 12f * density
                val padV = 7f * density
                val textWidth = textPaint.measureText(text)
                val cx = width / 2f
                // Below the status bar, clear of the notch, and out of the way of most content.
                val top = 64f * density
                val rect = RectF(
                    cx - textWidth / 2f - padH,
                    top,
                    cx + textWidth / 2f + padH,
                    top + textPaint.textSize + padV * 2f,
                )
                pillPaint.alpha = (alpha * 0.8f).toInt().coerceIn(0, 255)
                canvas.drawRoundRect(rect, rect.height() / 2f, rect.height() / 2f, pillPaint)
                textPaint.alpha = alpha
                canvas.drawText(text, cx, rect.bottom - padV - textPaint.descent(), textPaint)
            }
        }

        /**
         * "● UNDER TEST", top-right, pulsing.
         *
         * Top-right and just below the status bar: out of the way of app content, and where a
         * phone's own recording and casting indicators already live, so it reads as a system
         * state rather than as part of whatever app is on screen.
         */
        private fun drawBadge(canvas: Canvas) {
            // The script's name beats "UNDER TEST": on a phone that runs several trees a day,
            // which one is driving is the thing you actually want off a glance. Upper-cased to
            // read as a status rather than as content, and cut so a long ref cannot push the
            // badge off screen.
            val label = badgeLabel?.uppercase()?.take(BADGE_LABEL_MAX) ?: "UNDER TEST"
            val dotR = 4f * density
            val gap = 7f * density
            val padH = 11f * density
            val padV = 6f * density
            val textWidth = badgeTextPaint.measureText(label)
            val w = padH * 2f + dotR * 2f + gap + textWidth
            val h = padV * 2f + badgeTextPaint.textSize
            val right = width - 12f * density
            val top = 36f * density
            val rect = RectF(right - w, top, right, top + h)

            badgePaint.alpha = 255
            canvas.drawRoundRect(rect, h / 2f, h / 2f, badgePaint)
            // Only the dot pulses. A whole badge fading in and out is harder to read at a
            // glance than a steady label with a blinking light on it.
            fillPaint.color = Color.WHITE
            fillPaint.alpha = (badgePulse * 255).toInt().coerceIn(0, 255)
            val cy = rect.centerY()
            canvas.drawCircle(rect.left + padH + dotR, cy, dotR, fillPaint)
            fillPaint.color = ACCENT
            badgeTextPaint.alpha = 255
            canvas.drawText(
                label,
                rect.left + padH + dotR * 2f + gap,
                cy - (badgeTextPaint.descent() + badgeTextPaint.ascent()) / 2f,
                badgeTextPaint,
            )
        }
    }
}

/** Tiny helper so the animators above read as one line each. */
private fun ValueAnimator.addListener(onEnd: () -> Unit) {
    addListener(object : android.animation.AnimatorListenerAdapter() {
        override fun onAnimationEnd(animation: android.animation.Animator) = onEnd()
    })
}
