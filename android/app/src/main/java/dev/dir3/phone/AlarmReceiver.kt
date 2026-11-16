package dev.dir3.phone

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val raw = intent.getStringExtra(AlarmScheduler.EXTRA_ALARM) ?: return
        when (intent.action) {
            AlarmScheduler.ACTION_PRE -> postUpcoming(context, raw)
            AlarmScheduler.ACTION_RING -> {
                val service = Intent(context, AlarmService::class.java).apply {
                    action = AlarmService.ACTION_START
                    putExtra(AlarmScheduler.EXTRA_ALARM, raw)
                }
                try {
                    if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(service)
                    else context.startService(service)
                } catch (_: Exception) {
                    // Last resort: at least the notification appears.
                    postUpcoming(context, raw)
                }
            }
        }
    }

    private fun postUpcoming(context: Context, raw: String) {
        val spec = AlarmSpec.fromString(raw) ?: return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "dir3-upcoming"
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(channelId, "dir3 hatırlatma", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (Build.VERSION.SDK_INT >= 23) flags = flags or PendingIntent.FLAG_IMMUTABLE
        val open = PendingIntent.getActivity(
            context,
            spec.id.hashCode() + 17,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            flags,
        )
        val builder = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(context, channelId)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(context)
        }
        val notification = builder
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("⏰ ${spec.label}")
            .setContentText("${spec.snoozeMinutes} dk sonra alarm")
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_REMINDER)
            .build()
        try {
            manager.notify(spec.id.hashCode(), notification)
        } catch (_: SecurityException) {
            // Notification permission missing; the exact alarm still rings.
        }
    }
}
