package dev.dir3.phone

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast

/**
 * Thin native shell.  The calendar UI, editor and CLI panel are the shared
 * web assets; everything that must survive a sleeping phone (alarms) is
 * native and lives in [AlarmScheduler] / [AlarmService].
 */
class MainActivity : Activity() {
    private lateinit var webView: WebView

    @Suppress("DEPRECATION")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        webView = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            setBackgroundColor(Color.parseColor("#0f1317"))
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                allowFileAccess = true
                allowContentAccess = true
                mediaPlaybackRequiresUserGesture = false
                cacheMode = WebSettings.LOAD_DEFAULT
                allowUniversalAccessFromFileURLs = true
                allowFileAccessFromFileURLs = true
                mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                setSupportZoom(false)
                textZoom = 100
            }
            webViewClient = WebViewClient()
            webChromeClient = WebChromeClient()
            addJavascriptInterface(WebBridge(this@MainActivity, this), "Dir3Bridge")
            loadUrl("file:///android_asset/index.html")
        }
        setContentView(webView)

        requestNeededPermissions()
        SyncJob.schedule(this)
        AlarmScheduler.reschedule(this)
    }

    fun requestNeededPermissions() {
        val wanted = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            wanted.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            wanted.add(Manifest.permission.CAMERA)
        }
        if (wanted.isNotEmpty()) {
            requestPermissions(wanted.toTypedArray(), PERMISSION_REQUEST)
        }
    }

    fun openExactAlarmSettings() {
        if (Build.VERSION.SDK_INT >= 31) {
            try {
                startActivity(
                    Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM).apply {
                        data = Uri.parse("package:$packageName")
                    }
                )
                return
            } catch (_: Exception) {
                // fall through to the app-detail page
            }
        }
        openAppDetails()
    }

    @Suppress("DEPRECATION")
    fun pickRingtone() {
        val intent = Intent(RingtoneManager.ACTION_RINGTONE_PICKER).apply {
            putExtra(RingtoneManager.EXTRA_RINGTONE_TYPE, RingtoneManager.TYPE_ALARM)
            putExtra(RingtoneManager.EXTRA_RINGTONE_SHOW_DEFAULT, true)
            putExtra(RingtoneManager.EXTRA_RINGTONE_SHOW_SILENT, false)
            putExtra(RingtoneManager.EXTRA_RINGTONE_TITLE, "dir3 alarm sesi")
        }
        try {
            startActivityForResult(intent, RINGTONE_REQUEST)
        } catch (_: Exception) {
            Toast.makeText(this, "Ses seçici açılamadı", Toast.LENGTH_SHORT).show()
        }
    }

    fun openBatterySettings() {
        try {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:$packageName")
                }
            )
        } catch (_: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (_: Exception) {
                openAppDetails()
            }
        }
    }

    private fun openAppDetails() {
        try {
            startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.parse("package:$packageName")
                }
            )
        } catch (_: Exception) {
            // nothing sensible left to open
        }
    }

    @Deprecated("WebView back handling")
    override fun onBackPressed() {
        webView.evaluateJavascript(
            "(window.dir3HandleBack && window.dir3HandleBack()) ? '1' : '0'"
        ) { result ->
            if (result != "\"1\"" && result != "1") {
                finish()
            }
        }
    }

    @Deprecated("Ringtone picker result")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != RINGTONE_REQUEST || resultCode != RESULT_OK) return
        val uri = if (Build.VERSION.SDK_INT >= 33) {
            data?.getParcelableExtra(RingtoneManager.EXTRA_RINGTONE_PICKED_URI, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            data?.getParcelableExtra(RingtoneManager.EXTRA_RINGTONE_PICKED_URI)
        }
        Prefs.setAlarmSound(this, uri?.toString() ?: "")
        Toast.makeText(
            this,
            if (uri == null) "Sistem alarm sesi kullanılacak" else "Alarm sesi kaydedildi",
            Toast.LENGTH_SHORT,
        ).show()
    }

    override fun onResume() {
        super.onResume()
        if (::webView.isInitialized) {
            webView.evaluateJavascript("window.dir3OnResume && window.dir3OnResume()", null)
        }
    }

    override fun onDestroy() {
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface("Dir3Bridge")
            webView.destroy()
        }
        super.onDestroy()
    }

    companion object {
        private const val PERMISSION_REQUEST = 1001
        private const val RINGTONE_REQUEST = 1002
    }
}
