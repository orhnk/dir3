package dev.dir3.phone

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.RemoteViews
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Home-screen widget: today's plan, Google-Calendar style.
 *
 * It renders the last cached plan (the same JSON `dir3 serve` returns), so it
 * keeps working while the PC is off.  A row with a bell rings on the phone;
 * tapping a row opens the calendar on that day, tapping ↻ pulls a fresh plan.
 */
class CalendarWidget : AppWidgetProvider() {

    override fun onUpdate(
        context: Context,
        manager: AppWidgetManager,
        appWidgetIds: IntArray,
    ) {
        for (id in appWidgetIds) {
            render(context, manager, id)
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_REFRESH) {
            super.onReceive(context, intent)
            return
        }
        val pending = goAsync()
        Thread {
            try {
                PlanRepository.refreshAndSchedule(context)
            } finally {
                updateAll(context)
                pending.finish()
            }
        }.start()
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        manager: AppWidgetManager,
        appWidgetId: Int,
        newOptions: Bundle,
    ) {
        render(context, manager, appWidgetId)
    }

    private fun render(context: Context, manager: AppWidgetManager, id: Int) {
        val views = RemoteViews(context.packageName, R.layout.widget_calendar)
        val today = java.time.LocalDate.now(ZoneId.systemDefault())
        val dateFormat = DateTimeFormatter.ofPattern("EEEE, d MMMM", Locale.forLanguageTag("tr"))
        views.setTextViewText(R.id.widgetDate, today.format(dateFormat).replaceFirstChar { it.uppercase() })
        views.setOnClickPendingIntent(R.id.widgetHead, openApp(context, 0, today))
        views.setOnClickPendingIntent(R.id.widgetRefresh, refresh(context))
        views.setOnClickPendingIntent(R.id.widgetRoot, openApp(context, 0, today))

        val plan = parsePlan(context)
        if (plan == null) {
            views.setViewVisibility(R.id.widgetEmpty, View.VISIBLE)
            views.setTextViewText(R.id.widgetEmpty, context.getString(R.string.widget_no_plan))
            views.setTextViewText(R.id.widgetFooter, context.getString(R.string.widget_footer_hint))
            manager.updateAppWidget(id, views)
            return
        }

        val rows = maxRows(manager, id)
        val todays = plan.events.filter { it.date == today }
        val shown = todays.take(rows)
        views.removeAllViews(R.id.widgetRows)
        val now = Instant.now()
        for (event in shown) {
            val row = RemoteViews(context.packageName, R.layout.widget_row)
            row.setTextViewText(R.id.rowTime, event.time.format(TIME))
            row.setTextViewText(R.id.rowName, event.name)
            row.setViewVisibility(R.id.rowBell, if (event.hasAlarm) View.VISIBLE else View.GONE)
            row.setInt(R.id.rowColor, "setBackgroundColor", parseColor(event.color))
            // Events that already ended stay readable but recede, like the PC calendar.
            val muted = event.end != null && event.end.isBefore(now)
            row.setTextColor(
                R.id.rowName,
                if (muted) MUTED else Color.WHITE,
            )
            row.setOnClickPendingIntent(R.id.rowRoot, openApp(context, event.id.hashCode(), event.date))
            views.addView(R.id.widgetRows, row)
        }
        if (todays.isEmpty()) {
            views.setViewVisibility(R.id.widgetEmpty, View.VISIBLE)
            views.setTextViewText(R.id.widgetEmpty, context.getString(R.string.widget_empty))
        } else {
            views.setViewVisibility(R.id.widgetEmpty, View.GONE)
        }
        if (todays.size > shown.size) {
            val more = RemoteViews(context.packageName, R.layout.widget_row)
            more.setTextViewText(R.id.rowTime, "+${todays.size - shown.size}")
            more.setTextViewText(R.id.rowName, context.getString(R.string.widget_more))
            more.setViewVisibility(R.id.rowBell, View.GONE)
            more.setInt(R.id.rowColor, "setBackgroundColor", Color.TRANSPARENT)
            more.setTextColor(R.id.rowName, MUTED)
            more.setTextColor(R.id.rowTime, MUTED)
            more.setOnClickPendingIntent(R.id.rowRoot, openApp(context, 1, today))
            views.addView(R.id.widgetRows, more)
        }

        views.setTextViewText(R.id.widgetFooter, footer(context, plan, today))
        manager.updateAppWidget(id, views)
    }

    /** "⏰ 06:49 Fajr" when an alarm is still ahead, otherwise the last sync. */
    private fun footer(context: Context, plan: Plan, today: java.time.LocalDate): String {
        val now = Instant.now()
        val next = plan.alarms
            .filter { it.trigger.isAfter(now) }
            .minByOrNull { it.trigger }
        if (next != null) {
            val zone = ZoneId.systemDefault()
            val moment = next.trigger.atZone(zone)
            val whenText = if (moment.toLocalDate() == today) {
                moment.format(TIME)
            } else {
                context.getString(R.string.widget_tomorrow, moment.format(DAY), moment.format(TIME))
            }
            return context.getString(R.string.widget_next_alarm, whenText, next.label)
        }
        val synced = Prefs.lastSync(context)
        if (synced > 0) {
            val text = Instant.ofEpochMilli(synced).atZone(ZoneId.systemDefault()).format(TIME)
            return context.getString(R.string.widget_last_sync, text)
        }
        return context.getString(R.string.widget_footer_hint)
    }

    private fun maxRows(manager: AppWidgetManager, id: Int): Int {
        val options = manager.getAppWidgetOptions(id)
        val height = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 110)
        return ((height - 82) / 26).coerceIn(1, 10)
    }

    private fun openApp(context: Context, requestCode: Int, day: java.time.LocalDate): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra(MainActivity.EXTRA_DATE, day.toString())
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (android.os.Build.VERSION.SDK_INT >= 23) flags = flags or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getActivity(context, requestCode, intent, flags)
    }

    private fun refresh(context: Context): PendingIntent {
        val intent = Intent(context, CalendarWidget::class.java).apply {
            action = ACTION_REFRESH
            setPackage(context.packageName)
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT
        if (android.os.Build.VERSION.SDK_INT >= 23) flags = flags or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getBroadcast(context, REFRESH_REQUEST, intent, flags)
    }

    private fun parseColor(value: String?): Int {
        if (value.isNullOrBlank()) return Color.parseColor("#a4bdfc")
        return try {
            Color.parseColor(value)
        } catch (_: IllegalArgumentException) {
            Color.parseColor("#a4bdfc")
        }
    }

    private fun parsePlan(context: Context): Plan? {
        val raw = PlanRepository.load(context) ?: return null
        return try {
            val root = JSONObject(raw)
            val events = mutableListOf<WidgetEvent>()
            val array = root.optJSONArray("events")
            for (index in 0 until (array?.length() ?: 0)) {
                val item = array!!.optJSONObject(index) ?: continue
                val start = parseMoment(item.optString("start")) ?: continue
                val end = parseMoment(item.optString("end"))
                val local = start.atZone(ZoneId.systemDefault())
                val alarms = item.optJSONArray("alarm_ids")?.length() ?: 0
                events.add(
                    WidgetEvent(
                        id = item.optString("id"),
                        name = item.optString("name").ifBlank { item.optString("title") },
                        date = local.toLocalDate(),
                        time = local.toLocalTime(),
                        end = end,
                        color = item.optString("color"),
                        hasAlarm = alarms > 0,
                    )
                )
            }
            events.sortBy { it.time }
            Plan(events, parseAlarms(root.optJSONArray("alarms")))
        } catch (_: Exception) {
            null
        }
    }

    private fun parseAlarms(array: JSONArray?): List<WidgetAlarm> {
        if (array == null) return emptyList()
        val alarms = mutableListOf<WidgetAlarm>()
        for (index in 0 until array.length()) {
            val item = array.optJSONObject(index) ?: continue
            if (!item.optBoolean("enabled", true) || item.optBoolean("skip_next", false)) continue
            val trigger = parseMoment(item.optString("trigger")) ?: continue
            alarms.add(
                WidgetAlarm(
                    trigger = trigger,
                    label = item.optString("label").ifBlank { item.optString("event_name") },
                )
            )
        }
        return alarms
    }

    private fun parseMoment(value: String?): Instant? {
        if (value.isNullOrBlank()) return null
        return try {
            OffsetDateTime.parse(value).toInstant()
        } catch (_: Exception) {
            try {
                Instant.parse(value)
            } catch (_: Exception) {
                null
            }
        }
    }

    private data class WidgetEvent(
        val id: String,
        val name: String,
        val date: java.time.LocalDate,
        val time: java.time.LocalTime,
        val end: Instant?,
        val color: String?,
        val hasAlarm: Boolean,
    )

    private data class WidgetAlarm(val trigger: Instant, val label: String)

    private data class Plan(val events: List<WidgetEvent>, val alarms: List<WidgetAlarm>)

    companion object {
        const val ACTION_REFRESH = "dev.dir3.phone.action.WIDGET_REFRESH"
        private const val REFRESH_REQUEST = 42
        private const val MUTED = 0xFF9aa4af.toInt()
        private val TIME: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")
        private val DAY: DateTimeFormatter =
            DateTimeFormatter.ofPattern("d MMM", Locale.forLanguageTag("tr"))

        /** Repaint every widget instance; called after a sync or an edit. */
        fun updateAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val component = ComponentName(context, CalendarWidget::class.java)
            val ids = manager.getAppWidgetIds(component)
            if (ids.isEmpty()) return
            val intent = Intent(context, CalendarWidget::class.java).apply {
                action = AppWidgetManager.ACTION_APPWIDGET_UPDATE
                putExtra(AppWidgetManager.EXTRA_APPWIDGET_IDS, ids)
            }
            context.sendBroadcast(intent)
        }
    }
}
