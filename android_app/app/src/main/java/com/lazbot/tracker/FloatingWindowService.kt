package com.lazbot.tracker

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs

class FloatingWindowService : Service() {

    private lateinit var windowManager: WindowManager
    private lateinit var prefs: AppPreferences
    private lateinit var trackerEngine: LazadaTrackerEngine

    private var bubbleView: View? = null
    private var expandedView: View? = null

    private lateinit var bubbleParams: WindowManager.LayoutParams
    private lateinit var expandedParams: WindowManager.LayoutParams

    private val serviceJob = Job()
    private val serviceScope = CoroutineScope(Dispatchers.Main + serviceJob)
    private var scanJob: Job? = null

    companion object {
        private const val CHANNEL_ID = "lazbot_service_channel"
        private const val NOTIFICATION_ID = 1001
        const val ACTION_STOP_SERVICE = "com.lazbot.tracker.STOP_SERVICE"
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        prefs = AppPreferences(this)
        trackerEngine = LazadaTrackerEngine(this)
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager

        prefs.isServiceRunning = true

        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("LazBot đang theo dõi giỏ hàng Lazada"))

        initFloatingViews()
        startPeriodicCartTracking()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP_SERVICE) {
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    @SuppressLint("InflateParams", "ClickableViewAccessibility")
    private fun initFloatingViews() {
        val inflater = LayoutInflater.from(this)

        val overlayType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        // 1. Cấu hình Bong bóng nổi thu gọn (Bubble)
        bubbleView = inflater.inflate(R.layout.layout_floating_bubble, null)
        bubbleParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            overlayType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 30
            y = 250
        }

        // 2. Cấu hình Cửa sổ nổi mở rộng (Expanded Card)
        expandedView = inflater.inflate(R.layout.layout_floating_window, null)
        expandedParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            overlayType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.CENTER
        }

        // Kéo thả & Click cho Bong bóng
        var initialX = 0
        var initialY = 0
        var touchStartX = 0f
        var touchStartY = 0f
        var touchStartTime = 0L

        bubbleView?.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = bubbleParams.x
                    initialY = bubbleParams.y
                    touchStartX = event.rawX
                    touchStartY = event.rawY
                    touchStartTime = System.currentTimeMillis()
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    bubbleParams.x = initialX + (event.rawX - touchStartX).toInt()
                    bubbleParams.y = initialY + (event.rawY - touchStartY).toInt()
                    try {
                        windowManager.updateViewLayout(bubbleView, bubbleParams)
                    } catch (e: Exception) {
                        // ignore
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    val deltaX = abs(event.rawX - touchStartX)
                    val deltaY = abs(event.rawY - touchStartY)
                    val duration = System.currentTimeMillis() - touchStartTime

                    // Click nếu di chuyển ít và thời gian ngắn
                    if (deltaX < 15 && deltaY < 15 && duration < 300) {
                        showExpandedWindow()
                    }
                    true
                }
                else -> false
            }
        }

        // Sự kiện các nút trên cửa sổ mở rộng
        expandedView?.findViewById<View>(R.id.btnMinimize)?.setOnClickListener {
            hideExpandedWindow()
        }

        expandedView?.findViewById<Button>(R.id.btnFloatingCheckNow)?.setOnClickListener {
            triggerSingleScan()
        }

        expandedView?.findViewById<Button>(R.id.btnFloatingStop)?.setOnClickListener {
            stopSelf()
        }

        // Cập nhật giá trị hiển thị ban đầu
        updateCardUi(prefs.lastPrice, prefs.lastSkuCount, prefs.lastScanTime)

        // Thêm Bubble vào màn hình
        try {
            windowManager.addView(bubbleView, bubbleParams)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun showExpandedWindow() {
        try {
            bubbleView?.visibility = View.GONE
            if (expandedView?.parent == null) {
                windowManager.addView(expandedView, expandedParams)
            }
            expandedView?.visibility = View.VISIBLE
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun hideExpandedWindow() {
        try {
            expandedView?.visibility = View.GONE
            bubbleView?.visibility = View.VISIBLE
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun updateCardUi(totalPrice: String, skuCount: Int, timeStr: String) {
        expandedView?.findViewById<TextView>(R.id.tvFloatingTotal)?.text = totalPrice
        expandedView?.findViewById<TextView>(R.id.tvFloatingSkuCount)?.text = "📦 Số lượng: $skuCount SKU"
        expandedView?.findViewById<TextView>(R.id.tvFloatingLastCheck)?.text = "⏱️ Lần quét: $timeStr"
    }

    private fun startPeriodicCartTracking() {
        scanJob?.cancel()
        scanJob = serviceScope.launch {
            while (isActive) {
                performScan()
                val waitMs = (prefs.intervalMinutes.coerceAtLeast(1) * 60 * 1000L)
                delay(waitMs)
            }
        }
    }

    private fun triggerSingleScan() {
        serviceScope.launch {
            expandedView?.findViewById<TextView>(R.id.tvFloatingLastCheck)?.text = "⏱️ Đang quét..."
            performScan()
        }
    }

    private suspend fun performScan() {
        val nowStr = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        val result = trackerEngine.scanCart(prefs.cookie)

        val prevPrice = prefs.lastPrice
        val newPrice = result.totalPrice

        if (result.status == "ok") {
            prefs.lastPrice = newPrice
            prefs.lastSkuCount = result.skuCount
            prefs.lastScanTime = nowStr

            updateCardUi(newPrice, result.skuCount, nowStr)

            // Cập nhật thông báo hệ thống
            val noti = buildNotification("Tổng: $newPrice (${result.skuCount} SKU) - $nowStr")
            val notiManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notiManager.notify(NOTIFICATION_ID, noti)

            // Kiểm tra biến động giá để gửi Telegram
            if (prevPrice != "Chưa quét" && prevPrice != newPrice) {
                val alertMsg = """
                    🔥 <b>CẢNH BÁO BIẾN ĐỘNG GIÁ LAZADA!</b>
                    
                    💰 <b>Giá mới:</b> <code>$newPrice</code>
                    📉 <b>Giá trước đó:</b> <code>$prevPrice</code>
                    📦 <b>Số lượng:</b> ${result.skuCount} SKU
                    ⏱️ <b>Thời gian:</b> $nowStr
                    
                    ${result.itemsSummary}
                """.trimIndent()

                TelegramSender.sendMessage(prefs.botToken, prefs.chatId, alertMsg)
            }
        } else if (result.status == "need_login") {
            updateCardUi("Cookie hết hạn!", 0, nowStr)
            TelegramSender.sendMessage(
                prefs.botToken,
                prefs.chatId,
                "⚠️ <b>LazBot:</b> Cookie Lazada đã hết hạn! Vui lòng nạp lại cookie trên ứng dụng."
            )
        } else {
            expandedView?.findViewById<TextView>(R.id.tvFloatingLastCheck)?.text = "⏱️ ${result.message} ($nowStr)"
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "LazBot Tracking Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Thông báo trạng thái theo dõi giỏ hàng Lazada ngầm"
            }
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(contentText: String): Notification {
        val openAppIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingOpen = PendingIntent.getActivity(
            this,
            0,
            openAppIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val stopIntent = Intent(this, FloatingWindowService::class.java).apply {
            action = ACTION_STOP_SERVICE
        }
        val pendingStop = PendingIntent.getService(
            this,
            1,
            stopIntent,
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_cart)
            .setContentTitle("LazBot Monitor")
            .setContentText(contentText)
            .setContentIntent(pendingOpen)
            .addAction(R.drawable.ic_cart, "Dừng Bot", pendingStop)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    override fun onDestroy() {
        super.onDestroy()
        prefs.isServiceRunning = false
        serviceJob.cancel()

        try {
            if (bubbleView?.parent != null) windowManager.removeView(bubbleView)
            if (expandedView?.parent != null) windowManager.removeView(expandedView)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}
