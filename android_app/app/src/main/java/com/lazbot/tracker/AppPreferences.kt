package com.lazbot.tracker

import android.content.Context
import android.content.SharedPreferences

class AppPreferences(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("lazbot_prefs", Context.MODE_PRIVATE)

    var botToken: String
        get() = prefs.getString("bot_token", "") ?: ""
        set(value) = prefs.edit().putString("bot_token", value.trim()).apply()

    var chatId: String
        get() = prefs.getString("chat_id", "") ?: ""
        set(value) = prefs.edit().putString("chat_id", value.trim()).apply()

    var cookie: String
        get() = prefs.getString("cookie", "") ?: ""
        set(value) = prefs.edit().putString("cookie", value.trim()).apply()

    var intervalMinutes: Int
        get() = prefs.getInt("interval_minutes", 1).coerceAtLeast(1)
        set(value) = prefs.edit().putInt("interval_minutes", value.coerceAtLeast(1)).apply()

    var isServiceRunning: Boolean
        get() = prefs.getBoolean("is_service_running", false)
        set(value) = prefs.edit().putBoolean("is_service_running", value).apply()

    var lastPrice: String
        get() = prefs.getString("last_price", "Chưa quét") ?: "Chưa quét"
        set(value) = prefs.edit().putString("last_price", value).apply()

    var lastSkuCount: Int
        get() = prefs.getInt("last_sku_count", 0)
        set(value) = prefs.edit().putInt("last_sku_count", value).apply()

    var lastScanTime: String
        get() = prefs.getString("last_scan_time", "--:--:--") ?: "--:--:--"
        set(value) = prefs.edit().putString("last_scan_time", value).apply()
}
