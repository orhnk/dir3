package dev.dir3.phone

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.sqrt

/**
 * The screen that wakes you up.  All appearance and dismiss behaviour comes
 * from the dir3 alarm spec, so the plan - not the app - decides how an alarm
 * looks and how it is stopped.
 */
class AlarmActivity : Activity() {
    private lateinit var spec: AlarmSpec
    private val handler = Handler(Looper.getMainLooper())
    private var sensorManager: SensorManager? = null
    private var sensorListener: SensorEventListener? = null
    private var flipSince = 0L
    private var shakeCount = 0
    private var firstShake = 0L
    private var lastShake = 0L

    private val tick = object : Runnable {
        override fun run() {
            val text = SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date())
            findViewById<TextView>(R.id.alarmTime).text = text
            handler.postDelayed(this, 1_000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        spec = AlarmSpec.fromString(intent.getStringExtra(AlarmScheduler.EXTRA_ALARM)) ?: run {
            finish()
            return
        }
        wakeScreen()
        setContentView(R.layout.activity_alarm)
        applyBackground()
        bindContent()
        handler.post(tick)
        if (savedInstanceState == null) {
            // Recovered from a notification while the process was gone: make
            // sure the sound actually plays.
            try {
                startService(Intent(this, AlarmService::class.java).apply {
                    action = AlarmService.ACTION_START
                    putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
                })
            } catch (_: Exception) {
                // The service is already running in the normal case.
            }
        }
    }

    private fun wakeScreen() {
        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD or
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
        )
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        }
    }

    private fun applyBackground() {
        val root = findViewById<View>(R.id.alarmRoot)
        val value = spec.background ?: return
        try {
            root.setBackgroundColor(
                if (value == "black" || value == "dark") Color.BLACK else Color.parseColor(value)
            )
        } catch (_: IllegalArgumentException) {
            // keep the default black
        }
    }

    private fun bindContent() {
        findViewById<TextView>(R.id.alarmLabel).text = spec.label
        findViewById<TextView>(R.id.alarmEvent).text = spec.eventName

        val snooze = findViewById<Button>(R.id.btnSnooze)
        val count = Prefs.snoozeCount(this, spec.id)
        val exhausted = spec.snoozeLimit > 0 && count >= spec.snoozeLimit
        if (spec.snoozeMinutes <= 0) {
            snooze.visibility = View.GONE
        } else if (exhausted) {
            snooze.isEnabled = false
            snooze.text = "Erteleme hakkı bitti"
        } else {
            snooze.text = "${spec.snoozeMinutes} dakika ertele"
            snooze.setOnClickListener { snoozeAlarm() }
        }
        findViewById<Button>(R.id.btnDismiss).setOnClickListener { requestDismiss() }
        setupChallenge()
    }

    private fun setupChallenge() {
        val challenge = spec.dismiss.firstOrNull() ?: "button"
        val hint = findViewById<TextView>(R.id.alarmHint)
        when (challenge) {
            "math" -> {
                hint.visibility = View.VISIBLE
                hint.text = "Kapatmak için hesabı çöz"
            }
            "flip" -> {
                hint.visibility = View.VISIBLE
                hint.text = "Kapatmak için telefonu ters çevir"
                startFlipSensor()
            }
            "shake" -> {
                hint.visibility = View.VISIBLE
                hint.text = "Kapatmak için telefonu salla"
                startShakeSensor()
            }
            "swipe" -> {
                hint.visibility = View.VISIBLE
                hint.text = "Kapatmak için aşağıdaki çubuğu sonuna kadar kaydır"
                showSwipeBar()
            }
            else -> Unit
        }
    }

    /** Called by the dismiss button and hardware keys. */
    private fun requestDismiss() {
        when (spec.dismiss.firstOrNull() ?: "button") {
            "math" -> mathChallenge()
            else -> dismissAlarm()
        }
    }

    private fun showSwipeBar() {
        val box = findViewById<LinearLayout>(R.id.challengeBox)
        val bar = SeekBar(this).apply {
            max = 100
            progress = 0
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                    if (progress >= 100) dismissAlarm()
                }

                override fun onStartTrackingTouch(seekBar: SeekBar?) = Unit

                override fun onStopTrackingTouch(seekBar: SeekBar?) {
                    if ((seekBar?.progress ?: 0) < 100) seekBar?.progress = 0
                }
            })
        }
        box.addView(bar, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT,
        ))
    }

    private fun mathChallenge() {
        val a = (7..19).random()
        val b = (3..9).random()
        val input = EditText(this).apply {
            hint = "Cevap"
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or
                android.text.InputType.TYPE_NUMBER_FLAG_SIGNED
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle("$a × $b = ?")
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("Kapat", null)
            .setNegativeButton("Vazgeç", null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                if (input.text.toString().trim().toIntOrNull() == a * b) {
                    dialog.dismiss()
                    dismissAlarm()
                } else {
                    input.error = "Yanlış"
                    Toast.makeText(this, "Tekrar dene", Toast.LENGTH_SHORT).show()
                }
            }
        }
        dialog.show()
    }

    private fun startFlipSensor() {
        val manager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val sensor = manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) ?: return
        sensorManager = manager
        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                val z = event.values[2]
                if (z < -8.0f) {
                    if (flipSince == 0L) flipSince = System.currentTimeMillis()
                    if (System.currentTimeMillis() - flipSince > 500) dismissAlarm()
                } else {
                    flipSince = 0L
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }
        sensorListener = listener
        manager.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_UI)
    }

    private fun startShakeSensor() {
        val manager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val sensor = manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) ?: return
        sensorManager = manager
        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                val magnitude = sqrt(
                    event.values[0] * event.values[0] +
                        event.values[1] * event.values[1] +
                        event.values[2] * event.values[2]
                )
                if (magnitude > 22f) {
                    val now = System.currentTimeMillis()
                    if (now - lastShake > 180) {
                        if (shakeCount == 0 || now - firstShake > 2_500) {
                            firstShake = now
                            shakeCount = 1
                        } else {
                            shakeCount += 1
                        }
                        lastShake = now
                        if (shakeCount >= 3) dismissAlarm()
                    }
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }
        sensorListener = listener
        manager.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_UI)
    }

    private fun snoozeAlarm() {
        try {
            startService(Intent(this, AlarmService::class.java).apply {
                action = AlarmService.ACTION_SNOOZE
                putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
            })
        } catch (_: Exception) {
            AlarmScheduler.snooze(this, spec)
        }
        finish()
    }

    private fun dismissAlarm() {
        Prefs.setSnoozeCount(this, spec.id, 0)
        try {
            startService(Intent(this, AlarmService::class.java).apply {
                action = AlarmService.ACTION_STOP
                putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
            })
        } catch (_: Exception) {
            // nothing else to stop
        }
        finish()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        // Volume keys are an escape hatch only when the plan did not ask for
        // a real challenge - otherwise a math alarm could be skipped blindly.
        val hardwareKeys = spec.dismiss.any { it == "button" || it == "volume" || it == "power" }
        if (hardwareKeys &&
            (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)
        ) {
            dismissAlarm()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    @Deprecated("Alarm must be dismissed explicitly")
    override fun onBackPressed() {
        // Swallow back: an alarm should not disappear by accident.
        Toast.makeText(this, "Alarmı kapatmak için ekrandaki yolu kullan", Toast.LENGTH_SHORT).show()
    }

    override fun onDestroy() {
        handler.removeCallbacks(tick)
        sensorManager?.let { manager ->
            sensorListener?.let { manager.unregisterListener(it) }
        }
        sensorListener = null
        super.onDestroy()
    }
}
