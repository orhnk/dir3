package dev.dir3.phone

import android.content.Context

/** Small settings store; no AndroidX, no database. */
object Prefs {
    private const val NAME = "dir3"

    private fun sp(context: Context) =
        context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun base(context: Context): String = sp(context).getString("base", "") ?: ""

    fun token(context: Context): String = sp(context).getString("token", "") ?: ""

    fun setServer(context: Context, base: String, token: String) {
        sp(context).edit().putString("base", base.trim().trimEnd('/')).putString("token", token.trim()).apply()
    }

    fun horizon(context: Context): Int = sp(context).getInt("horizon", 14)

    fun setHorizon(context: Context, days: Int) {
        sp(context).edit().putInt("horizon", days.coerceIn(1, 366)).apply()
    }

    fun lastSync(context: Context): Long = sp(context).getLong("lastSync", 0L)

    fun setLastSync(context: Context, millis: Long) {
        sp(context).edit().putLong("lastSync", millis).apply()
    }

    fun alarmSound(context: Context): String = sp(context).getString("alarmSound", "") ?: ""

    fun setAlarmSound(context: Context, uri: String) {
        sp(context).edit().putString("alarmSound", uri).apply()
    }

    fun ttsLanguage(context: Context): String = sp(context).getString("ttsLanguage", "") ?: ""

    fun setTtsLanguage(context: Context, tag: String) {
        sp(context).edit().putString("ttsLanguage", tag).apply()
    }

    fun scheduledIds(context: Context): Set<String> =
        (sp(context).getStringSet("scheduledIds", emptySet()) ?: emptySet()).toSet()

    fun setScheduledIds(context: Context, ids: Set<String>) {
        sp(context).edit().putStringSet("scheduledIds", ids).apply()
    }

    fun snoozeCount(context: Context, alarmId: String): Int =
        sp(context).getInt("snooze:$alarmId", 0)

    fun setSnoozeCount(context: Context, alarmId: String, count: Int) {
        sp(context).edit().putInt("snooze:$alarmId", count).apply()
    }
}
