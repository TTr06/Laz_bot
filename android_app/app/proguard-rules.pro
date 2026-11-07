# Proguard rules for LazBot
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.lazbot.tracker.** { *; }
