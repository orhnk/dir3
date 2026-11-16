package dev.dir3.phone

import android.content.Intent
import android.os.Build
import android.speech.tts.TextToSpeech
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.Toast
import org.json.JSONObject
import java.util.Locale

/** Everything the web UI may ask the native side to do. */
class WebBridge(
    private val activity: MainActivity,
    @Suppress("unused") private val webView: WebView,
) {
    private var tts: TextToSpeech? = null

    @JavascriptInterface
    fun getConfig(): String {
        return JSONObject().apply {
            put("base", Prefs.base(activity))
            put("token", Prefs.token(activity))
            put("horizon", Prefs.horizon(activity))
            put("alarmSound", Prefs.alarmSound(activity))
            put("nextAlarm", AlarmScheduler.nextAlarmText(activity))
            put("exactAlarm", AlarmScheduler.canScheduleExact(activity))
        }.toString()
    }

    @JavascriptInterface
    fun saveConfig(base: String?, token: String?) {
        Prefs.setServer(activity, base ?: "", token ?: "")
        SyncJob.schedule(activity)
        syncNow()
    }

    @JavascriptInterface
    fun setHorizon(days: Int) {
        Prefs.setHorizon(activity, days)
    }

    @JavascriptInterface
    fun getCachedPlan(): String = PlanRepository.load(activity) ?: "{}"

    @JavascriptInterface
    fun applyPlan(json: String?) {
        if (json.isNullOrBlank()) return
        PlanRepository.save(activity, json)
        AlarmScheduler.reschedule(activity)
    }

    @JavascriptInterface
    fun syncNow() {
        Thread {
            val result = PlanRepository.refreshAndSchedule(activity)
            activity.runOnUiThread {
                if (result == null) {
                    toast("Senkronizasyon başarısız - önbellek kullanılıyor")
                } else {
                    toast("${result.events} event, ${result.alarms} alarm güncellendi")
                }
            }
        }.start()
    }

    @JavascriptInterface
    fun speak(text: String?) {
        val message = text?.takeIf { it.isNotBlank() } ?: return
        tts?.shutdown()
        tts = TextToSpeech(activity) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val tag = Prefs.ttsLanguage(activity)
                val locale = if (tag.isBlank()) Locale.getDefault() else Locale.forLanguageTag(tag)
                val result = tts?.setLanguage(locale)
                if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                    tts?.setLanguage(Locale.ENGLISH)
                }
                tts?.speak(message, TextToSpeech.QUEUE_FLUSH, null, "dir3-test")
            }
        }
    }

    @JavascriptInterface
    fun testAlarm(text: String?) {
        val spec = AlarmSpec.demo(text?.takeIf { it.isNotBlank() } ?: "Fajr")
        val intent = Intent(activity, AlarmService::class.java).apply {
            action = AlarmService.ACTION_START
            putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
        }
        try {
            if (Build.VERSION.SDK_INT >= 26) activity.startForegroundService(intent)
            else activity.startService(intent)
        } catch (_: Exception) {
            toast("Alarm başlatılamadı")
        }
    }

    @JavascriptInterface
    fun requestPermissions() {
        activity.runOnUiThread { activity.requestNeededPermissions() }
    }

    @JavascriptInterface
    fun openExactAlarmSettings() {
        activity.runOnUiThread { activity.openExactAlarmSettings() }
    }

    @JavascriptInterface
    fun openBatterySettings() {
        activity.runOnUiThread { activity.openBatterySettings() }
    }

    @JavascriptInterface
    fun pickSound() {
        activity.runOnUiThread { activity.pickRingtone() }
    }

    @JavascriptInterface
    fun getVersion(): String {
        return try {
            activity.packageManager.getPackageInfo(activity.packageName, 0).versionName ?: "0.1.0"
        } catch (_: Exception) {
            "0.1.0"
        }
    }

    @JavascriptInterface
    fun toast(message: String?) {
        val text = message ?: return
        activity.runOnUiThread { Toast.makeText(activity, text, Toast.LENGTH_SHORT).show() }
    }
}
