package com.lazbot.tracker

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: AppPreferences

    private lateinit var tvServiceStatus: TextView
    private lateinit var layoutOverlayWarning: LinearLayout
    private lateinit var btnGrantOverlay: Button
    private lateinit var etBotToken: EditText
    private lateinit var etChatId: EditText
    private lateinit var btnTestTelegram: Button
    private lateinit var etCookie: EditText
    private lateinit var etInterval: EditText
    private lateinit var btnToggleService: Button

    private val requestNotificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ -> }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = AppPreferences(this)
        bindViews()
        loadSavedData()
        setupListeners()
        checkPermissions()
    }

    override fun onResume() {
        super.onResume()
        updateStatusUi()
        checkPermissions()
    }

    private fun bindViews() {
        tvServiceStatus = findViewById(R.id.tvServiceStatus)
        layoutOverlayWarning = findViewById(R.id.layoutOverlayWarning)
        btnGrantOverlay = findViewById(R.id.btnGrantOverlay)
        etBotToken = findViewById(R.id.etBotToken)
        etChatId = findViewById(R.id.etChatId)
        btnTestTelegram = findViewById(R.id.btnTestTelegram)
        etCookie = findViewById(R.id.etCookie)
        etInterval = findViewById(R.id.etInterval)
        btnToggleService = findViewById(R.id.btnToggleService)
    }

    private fun loadSavedData() {
        etBotToken.setText(prefs.botToken)
        etChatId.setText(prefs.chatId)
        etCookie.setText(prefs.cookie)
        etInterval.setText(prefs.intervalMinutes.toString())
    }

    private fun saveData() {
        prefs.botToken = etBotToken.text.toString().trim()
        prefs.chatId = etChatId.text.toString().trim()
        prefs.cookie = etCookie.text.toString().trim()
        val interval = etInterval.text.toString().toIntOrNull() ?: 1
        prefs.intervalMinutes = interval.coerceAtLeast(1)
    }

    private fun setupListeners() {
        btnGrantOverlay.setOnClickListener {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )
            startActivity(intent)
        }

        btnTestTelegram.setOnClickListener {
            val token = etBotToken.text.toString().trim()
            val chatId = etChatId.text.toString().trim()
            if (token.isEmpty() || chatId.isEmpty()) {
                Toast.makeText(this, "Vui lòng nhập Bot Token và Chat ID!", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            btnTestTelegram.isEnabled = false
            btnTestTelegram.text = "Đang gửi..."
            lifecycleScope.launch {
                val res = TelegramSender.sendMessage(
                    token,
                    chatId,
                    "🔔 <b>LazBot:</b> Kiểm tra kết nối Telegram thành công!\nThiết bị Android đã sẵn sàng theo dõi giỏ hàng."
                )
                btnTestTelegram.isEnabled = true
                btnTestTelegram.text = "Kiểm tra gửi tin Telegram"

                if (res.isSuccess) {
                    Toast.makeText(this@MainActivity, "✅ Gửi tin nhắn thành công!", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(this@MainActivity, "❌ Thất bại: ${res.exceptionOrNull()?.message}", Toast.LENGTH_LONG).show()
                }
            }
        }

        btnToggleService.setOnClickListener {
            saveData()

            if (!Settings.canDrawOverlays(this)) {
                Toast.makeText(this, "Vui lòng cấp quyền Cửa sổ nổi trước!", Toast.LENGTH_LONG).show()
                val intent = Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName")
                )
                startActivity(intent)
                return@setOnClickListener
            }

            if (prefs.isServiceRunning) {
                // Dừng service
                val intent = Intent(this, FloatingWindowService::class.java)
                stopService(intent)
                prefs.isServiceRunning = false
                Toast.makeText(this, "Đã tắt bot và đóng cửa sổ nổi", Toast.LENGTH_SHORT).show()
            } else {
                if (prefs.cookie.isEmpty()) {
                    Toast.makeText(this, "Vui lòng dán Cookie Lazada trước khi bật!", Toast.LENGTH_LONG).show()
                    return@setOnClickListener
                }

                val intent = Intent(this, FloatingWindowService::class.java)
                ContextCompat.startForegroundService(this, intent)
                prefs.isServiceRunning = true
                Toast.makeText(this, "🚀 Đã bật bot! Cửa sổ nổi đang hoạt động ngoài màn hình.", Toast.LENGTH_LONG).show()
            }
            updateStatusUi()
        }
    }

    private fun checkPermissions() {
        // Kiểm tra quyền Cửa sổ nổi (Overlay)
        if (!Settings.canDrawOverlays(this)) {
            layoutOverlayWarning.visibility = View.VISIBLE
        } else {
            layoutOverlayWarning.visibility = View.GONE
        }

        // Quyền thông báo Android 13+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestNotificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun updateStatusUi() {
        if (prefs.isServiceRunning) {
            tvServiceStatus.text = "ĐANG CHẠY"
            tvServiceStatus.setBackgroundResource(R.drawable.bg_button)
            tvServiceStatus.backgroundTintList = ContextCompat.getColorStateList(this, R.color.success)
            btnToggleService.text = "🛑 DỪNG BOT & ĐÓNG CỬA SỔ NỔI"
            btnToggleService.backgroundTintList = ContextCompat.getColorStateList(this, R.color.error)
        } else {
            tvServiceStatus.text = "ĐANG TẮT"
            tvServiceStatus.setBackgroundResource(R.drawable.bg_button)
            tvServiceStatus.backgroundTintList = ContextCompat.getColorStateList(this, R.color.surface_card)
            btnToggleService.text = "🚀 BẬT BOT & HIỆN CỬA SỔ NỔI"
            btnToggleService.backgroundTintList = ContextCompat.getColorStateList(this, R.color.primary)
        }
    }
}
