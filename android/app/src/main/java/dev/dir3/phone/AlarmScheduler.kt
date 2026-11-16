package dev.dir3.phone

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import org.json.JSONObject
import java.time.Instant

/**
 * Turns the plan's resolved alarms into Android alarms.
 *
 * `setAlarmClock` is used whenever possible: it is exact, survives Doze and
 * shows the system alarm icon, which is what users expect from a wake-up
 * alarm.  Without the exact-alarm permission it degrades to
 * `setAndAllowWhileIdle` instead of silently dropping the alarm.
 */
object AlarmScheduler {
    const val ACTION_RING = "dev.dir3.phone.action.RING"
    const val ACTION_PRE = "dev.dir3.phone.action.PRE"
    const val EXTRA_ALARM = "alarm_json"
    private const val PRE_OFFSET = 7_919
    private const val SNOOZE_OFFSET = 4_111
    private const val SHOW_OFFSET = 991

    private fun pending(
        context: Context,
        requestCode: Int,
        action: String,
        alarmJson: String,
    ): PendingIntent {
        val intent = Intent(context, AlarmReceiver::class.java).apply {
            this.action = action
            putExtra(EXTRA_ALARM, alarmJson)
            setPackage(context.packageName)
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (Build.VERSION.SDK_INT >= 23) flags = flags or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getBroadcast(context, requestCode, intent, flags)
    }

    private fun showIntent(context: Context, requestCode: Int): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (Build.VERSION.SDK_INT >= 23) flags = flags or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getActivity(context, requestCode + SHOW_OFFSET, intent, flags)
    }

    fun canScheduleExact(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < 31) return true
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        return manager.canScheduleExactAlarms()
    }

    private fun set(
        context: Context,
        triggerMillis: Long,
        pendingIntent: PendingIntent,
        show: PendingIntent,
    ) {
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        try {
            if (canScheduleExact(context)) {
                manager.setAlarmClock(AlarmManager.AlarmClockInfo(triggerMillis, show), pendingIntent)
            } else {
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerMillis, pendingIntent)
            }
        } catch (_: SecurityException) {
            manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerMillis, pendingIntent)
        }
    }

    /** Cancel every alarm this app scheduled from the previous plan. */
    fun cancelAll(context: Context) {
        val ids = Prefs.scheduledIds(context)
        for (id in ids) {
            val requestCode = when {
                id.startsWith("pre:") -> id.removePrefix("pre:").hashCode() + PRE_OFFSET
                id.startsWith("snooze:") -> id.removePrefix("snooze:").hashCode() + SNOOZE_OFFSET
                else -> id.hashCode()
            }
            val action = when {
                id.startsWith("pre:") -> ACTION_PRE
                else -> ACTION_RING
            }
            val pi = pending(context, requestCode, action, "")
            (context.getSystemService(Context.ALARM_SERVICE) as AlarmManager).cancel(pi)
        }
        Prefs.setScheduledIds(context, emptySet())
    }

    /** Rebuild all alarms from the cached plan. Call on boot, sync and edits. */
    fun reschedule(context: Context) {
        cancelAll(context)
        val json = PlanRepository.load(context) ?: return
        val alarms = try {
            JSONObject(json).optJSONArray("alarms")
        } catch (_: Exception) {
            null
        } ?: return
        val now = System.currentTimeMillis()
        val scheduled = mutableSetOf<String>()
        for (index in 0 until alarms.length()) {
            val spec = try {
                AlarmSpec.fromJson(alarms.getJSONObject(index))
            } catch (_: Exception) {
                null
            } ?: continue
            if (!spec.enabled || spec.skipNext) continue
            // Ignore stale alarms; the next plan refresh will bring new ones.
            if (spec.triggerMillis <= now + 1_000) continue
            scheduleOne(context, spec, spec.triggerMillis, scheduled)
            val pre = spec.preTriggerMillis
            if (pre != null && pre > now + 1_000) {
                val prePending = pending(context, spec.id.hashCode() + PRE_OFFSET, ACTION_PRE, spec.toJson())
                set(context, pre, prePending, showIntent(context, spec.id.hashCode()))
                scheduled.add("pre:${spec.id}")
            }
        }
        Prefs.setScheduledIds(context, scheduled)
    }

    private fun scheduleOne(
        context: Context,
        spec: AlarmSpec,
        triggerMillis: Long,
        scheduled: MutableSet<String>,
    ) {
        val pi = pending(context, spec.id.hashCode(), ACTION_RING, spec.toJson())
        set(context, triggerMillis, pi, showIntent(context, spec.id.hashCode()))
        scheduled.add(spec.id)
    }

    /** One-shot snooze, reusing the same alarm payload. */
    fun snooze(context: Context, spec: AlarmSpec) {
        if (spec.snoozeMinutes <= 0) return
        val trigger = System.currentTimeMillis() + spec.snoozeMinutes * 60_000L
        val pi = pending(context, spec.id.hashCode() + SNOOZE_OFFSET, ACTION_RING, spec.toJson())
        set(context, trigger, pi, showIntent(context, spec.id.hashCode()))
        val ids = Prefs.scheduledIds(context).toMutableSet()
        ids.add("snooze:${spec.id}")
        Prefs.setScheduledIds(context, ids)
    }

    fun nextAlarmMillis(context: Context): Long? {
        val json = PlanRepository.load(context) ?: return null
        return try {
            val alarms = JSONObject(json).optJSONArray("alarms") ?: return null
            var best: Long? = null
            val now = System.currentTimeMillis()
            for (index in 0 until alarms.length()) {
                val spec = AlarmSpec.fromJson(alarms.getJSONObject(index)) ?: continue
                if (!spec.enabled || spec.skipNext) continue
                if (spec.triggerMillis <= now) continue
                val current = best
                if (current == null || spec.triggerMillis < current) best = spec.triggerMillis
            }
            best
        } catch (_: Exception) {
            null
        }
    }

    fun nextAlarmText(context: Context): String {
        val millis = nextAlarmMillis(context) ?: return "Alarm yok"
        val formatter = java.time.format.DateTimeFormatter.ofPattern("dd.MM HH:mm")
            .withZone(java.time.ZoneId.systemDefault())
        return formatter.format(Instant.ofEpochMilli(millis))
    }
}
