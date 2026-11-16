package dev.dir3.phone

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.speech.tts.TextToSpeech
import java.util.Locale

class AlarmService : Service() {
    companion object {
        const val ACTION_START = "dev.dir3.phone.service.START"
        const val ACTION_STOP = "dev.dir3.phone.service.STOP"
        const val ACTION_SNOOZE = "dev.dir3.phone.service.SNOOZE"
        private const val CHANNEL = "dir3-alarm"
        private const val NOTIFICATION_ID = 4201
    }

    private var player: MediaPlayer? = null
    private var vibrator: Vibrator? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var audioFocus: AudioFocusRequest? = null
    private var torchId: String? = null
    private val handler = Handler(Looper.getMainLooper())
    private var current: AlarmSpec? = null
    private var speaking = false
    private var soundTarget = 1f

    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var pendingSpeech: String? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        vibrator = getSystemService(Vibrator::class.java)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val raw = intent?.getStringExtra(AlarmScheduler.EXTRA_ALARM)
        when (intent?.action) {
            ACTION_STOP -> stopEverything()
            ACTION_SNOOZE -> {
                val spec = AlarmSpec.fromString(raw) ?: current
                if (spec != null) {
                    Prefs.setSnoozeCount(this, spec.id, Prefs.snoozeCount(this, spec.id) + 1)
                    AlarmScheduler.snooze(this, spec)
                }
                stopEverything()
            }
            else -> {
                val spec = AlarmSpec.fromString(raw)
                if (spec != null) startAlarm(spec) else stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL,
            "dir3 alarm",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Plan-Events, die klingeln"
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            enableVibration(false)
            setSound(null, null) // the service plays the plan's sound
            setShowBadge(true)
            try {
                setBypassDnd(true)
            } catch (_: SecurityException) {
                // Needs notification-policy access; the alarm still rings.
            }
        }
        manager.createNotificationChannel(channel)
    }

    private fun startAlarm(spec: AlarmSpec) {
        if (current?.id == spec.id && player?.isPlaying == true) return
        stopSoundOnly()
        current = spec

        acquireWakeLock()
        val notification = buildNotification(spec)
        startForeground(NOTIFICATION_ID, notification)

        playSound(spec)
        startVibration(spec)
        if (spec.speak) speakLater(spec.speakText ?: spec.eventName, repeat = spec.sound == "tts")
        if (spec.flashlight) torch(true)

        if (spec.fullScreen) {
            val intent = Intent(this, AlarmActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP
                )
                putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
            }
            try {
                startActivity(intent)
            } catch (_: Exception) {
                // Full-screen notifications still present the activity.
            }
        }
    }

    private fun buildNotification(spec: AlarmSpec): Notification {
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (Build.VERSION.SDK_INT >= 23) flags = flags or PendingIntent.FLAG_IMMUTABLE
        val alarmIntent = Intent(this, AlarmActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
        }
        val fullScreen = PendingIntent.getActivity(this, spec.id.hashCode() + 3, alarmIntent, flags)

        val snoozeIntent = Intent(this, AlarmService::class.java).apply {
            action = ACTION_SNOOZE
            putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
        }
        val stopIntent = Intent(this, AlarmService::class.java).apply {
            action = ACTION_STOP
            putExtra(AlarmScheduler.EXTRA_ALARM, spec.toJson())
        }
        val snooze = PendingIntent.getService(this, spec.id.hashCode() + 4, snoozeIntent, flags)
        val stop = PendingIntent.getService(this, spec.id.hashCode() + 5, stopIntent, flags)
        // A dismiss challenge must also hold on the notification: tapping
        // "Kapat" opens the alarm screen instead of stopping silently.
        val challenge = spec.dismiss.any { it in listOf("math", "flip", "shake", "swipe") }
        val dismissAction = if (challenge) fullScreen else stop

        val builder = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(this, CHANNEL)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        builder
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("⏰ ${spec.label}")
            .setContentText(spec.eventName)
            .setCategory(Notification.CATEGORY_ALARM)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setOngoing(true)
            .setAutoCancel(false)
            .setContentIntent(fullScreen)
            .setFullScreenIntent(fullScreen, true)
            .setDeleteIntent(dismissAction)
        if (spec.snoozeMinutes > 0) {
            @Suppress("DEPRECATION")
            builder.addAction(Notification.Action.Builder(R.drawable.ic_notification, "Ertele", snooze).build())
        }
        @Suppress("DEPRECATION")
        builder.addAction(
            Notification.Action.Builder(R.drawable.ic_notification, "Kapat", dismissAction).build()
        )
        return builder.build()
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "dir3:alarm").apply {
            setReferenceCounted(false)
            acquire(15 * 60 * 1000L)
        }
    }

    private fun playSound(spec: AlarmSpec) {
        if (spec.sound == "tts" || spec.sound == "voice") return
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        val manager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (Build.VERSION.SDK_INT >= 26) {
            val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(attributes)
                .setOnAudioFocusChangeListener { }
                .build()
            audioFocus = request
            manager.requestAudioFocus(request)
        }
        val created = openPlayer(spec) ?: return
        player = created
        created.setAudioAttributes(attributes)
        created.isLooping = true
        val target = (spec.volume ?: 100).coerceIn(1, 100) / 100f
        soundTarget = target
        if (spec.crescendo && spec.crescendoSeconds > 0) {
            created.setVolume(target * 0.08f, target * 0.08f)
            val steps = (spec.crescendoSeconds * 2).coerceAtLeast(1)
            var step = 0
            val ramp = object : Runnable {
                override fun run() {
                    step += 1
                    val fraction = 0.08f + (0.92f * step / steps)
                    try {
                        created.setVolume(target * fraction, target * fraction)
                    } catch (_: IllegalStateException) {
                        return
                    }
                    if (step < steps) handler.postDelayed(this, 500)
                }
            }
            handler.postDelayed(ramp, 500)
        } else {
            created.setVolume(target, target)
        }
        try {
            created.start()
        } catch (_: IllegalStateException) {
            // Ignore: the notification and vibration still work.
        }
    }

    private fun openPlayer(spec: AlarmSpec): MediaPlayer? {
        val chosen = when {
            spec.sound == "random" && spec.sounds.isNotEmpty() -> spec.sounds.random()
            spec.sound == "app" -> Prefs.alarmSound(this).ifBlank { "system" }
            spec.sound.isNullOrBlank() || spec.sound == "system" || spec.sound == "random" -> "system"
            else -> spec.sound
        }
        return try {
            when {
                chosen == "system" -> {
                    val uri = android.media.RingtoneManager.getDefaultUri(
                        android.media.RingtoneManager.TYPE_ALARM
                    ) ?: android.media.RingtoneManager.getDefaultUri(
                        android.media.RingtoneManager.TYPE_NOTIFICATION
                    )
                    MediaPlayer.create(this, uri)
                }
                chosen.startsWith("content://") || chosen.startsWith("file://") -> {
                    MediaPlayer.create(this, Uri.parse(chosen))
                }
                else -> {
                    val name = chosen.removePrefix("asset:").removePrefix("sounds/")
                    val descriptor = assets.openFd("sounds/$name")
                    MediaPlayer().apply {
                        descriptor.use {
                            setDataSource(it.fileDescriptor, it.startOffset, it.length)
                        }
                        prepare()
                    }
                }
            }
        } catch (_: Exception) {
            try {
                val uri = android.media.RingtoneManager.getDefaultUri(
                    android.media.RingtoneManager.TYPE_ALARM
                )
                MediaPlayer.create(this, uri)
            } catch (_: Exception) {
                null
            }
        }
    }

    private fun startVibration(spec: AlarmSpec) {
        if (!spec.vibrate || spec.vibration == "off") return
        val vibrator = vibrator ?: return
        if (!vibrator.hasVibrator()) return
        val pattern = vibrationPattern(spec.vibration)
        try {
            vibrator.vibrate(VibrationEffect.createWaveform(pattern, 0))
        } catch (_: Exception) {
            // Some devices refuse very long waveforms; a short one is fine.
            vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 600, 400), 0))
        }
    }

    private fun vibrationPattern(name: String): LongArray {
        if (name.startsWith("custom:")) {
            val values = name.removePrefix("custom:").split(",")
                .mapNotNull { it.trim().toLongOrNull() }
                .toLongArray()
            if (values.isNotEmpty()) return longArrayOf(0) + values
        }
        return when (name) {
            "short" -> longArrayOf(0, 250, 250)
            "long" -> longArrayOf(0, 1200, 500)
            "heartbeat" -> longArrayOf(0, 180, 120, 180, 700)
            else -> longArrayOf(0, 700, 450)
        }
    }

    private fun speakLater(text: String, repeat: Boolean) {
        pendingSpeech = text
        ensureTts()
        handler.postDelayed({
            speakNow(text)
            if (repeat) {
                handler.postDelayed(object : Runnable {
                    override fun run() {
                        if (current != null) {
                            speakNow(text)
                            handler.postDelayed(this, 15_000)
                        }
                    }
                }, 15_000)
            }
        }, if (repeat) 300 else 1_400)
    }

    private fun ensureTts() {
        if (tts != null) return
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                ttsReady = true
                val tag = Prefs.ttsLanguage(this)
                val locale = if (tag.isBlank()) Locale.getDefault() else Locale.forLanguageTag(tag)
                val result = tts?.setLanguage(locale)
                if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                    tts?.setLanguage(Locale.ENGLISH)
                }
                val pending = pendingSpeech
                if (pending != null) handler.postDelayed({ speakNow(pending) }, 250)
            }
        }
    }

    private fun speakNow(text: String) {
        if (!ttsReady) {
            pendingSpeech = text
            return
        }
        if (speaking) return
        speaking = true
        // Duck the ringtone so the spoken event name is audible.
        player?.let { active ->
            try {
                active.setVolume(soundTarget * 0.12f, soundTarget * 0.12f)
                handler.postDelayed({
                    try {
                        active.setVolume(soundTarget, soundTarget)
                    } catch (_: IllegalStateException) {
                        // already stopped
                    }
                }, 4_500)
            } catch (_: IllegalStateException) {
                // ignore
            }
        }
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "dir3-alarm")
        handler.postDelayed({ speaking = false }, 4_000)
    }

    private fun torch(on: Boolean) {
        try {
            if (checkSelfPermission(android.Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                return
            }
            val manager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val id = torchId ?: manager.cameraIdList.firstOrNull { candidate ->
                val chars = manager.getCameraCharacteristics(candidate)
                val flash = chars.get(android.hardware.camera2.CameraCharacteristics.FLASH_INFO_AVAILABLE)
                flash == true
            } ?: return
            torchId = id
            manager.setTorchMode(id, on)
        } catch (_: Exception) {
            // Torch is a bonus; never let it break the alarm.
        }
    }

    private fun stopSoundOnly() {
        handler.removeCallbacksAndMessages(null)
        try {
            player?.stop()
        } catch (_: Exception) {
            // already stopped
        }
        player?.release()
        player = null
        try {
            vibrator?.cancel()
        } catch (_: Exception) {
            // ignore
        }
        if (torchId != null) torch(false)
        audioFocus?.let {
            val manager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            manager.abandonAudioFocusRequest(it)
        }
        audioFocus = null
        speaking = false
    }

    private fun stopEverything() {
        stopSoundOnly()
        current = null
        tts?.stop()
        tts?.shutdown()
        tts = null
        ttsReady = false
        wakeLock?.let {
            if (it.isHeld) it.release()
        }
        wakeLock = null
        try {
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).cancel(NOTIFICATION_ID)
        } catch (_: Exception) {
            // ignore
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stopSoundOnly()
        tts?.shutdown()
        tts = null
        wakeLock?.let {
            if (it.isHeld) it.release()
        }
        super.onDestroy()
    }
}
