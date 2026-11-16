package dev.dir3.phone

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Downloads the compiled plan from `dir3 serve` and keeps the last good copy. */
object PlanRepository {
    private const val CACHE = "plan.json"

    data class FetchResult(val json: String, val events: Int, val alarms: Int, val title: String)

    private fun cacheFile(context: Context) = File(context.filesDir, CACHE)

    fun load(context: Context): String? {
        val file = cacheFile(context)
        if (!file.isFile) return null
        return try {
            file.readText(Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    fun save(context: Context, json: String) {
        try {
            val file = cacheFile(context)
            val temp = File(context.filesDir, "$CACHE.tmp")
            temp.writeText(json, Charsets.UTF_8)
            if (!temp.renameTo(file)) {
                file.writeText(json, Charsets.UTF_8)
                temp.delete()
            }
            CalendarWidget.updateAll(context)
        } catch (_: Exception) {
            // A full disk must not take the alarm engine down.
        }
    }

    fun fetch(context: Context): FetchResult {
        val base = Prefs.base(context).trimEnd('/')
        if (base.isBlank()) throw IOException("Sunucu adresi ayarlanmamış")
        val token = URLEncoder.encode(Prefs.token(context), "UTF-8")
        val url = URL("$base/api/plan?until=${Prefs.horizon(context)}&refresh=1&token=$token")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            connectTimeout = 12_000
            readTimeout = 45_000
            requestMethod = "GET"
            setRequestProperty("X-Dir3-Token", Prefs.token(context))
            setRequestProperty("Accept", "application/json")
        }
        try {
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code !in 200..299) {
                val message = try {
                    JSONObject(text).optString("error")
                } catch (_: Exception) {
                    ""
                }
                throw IOException(if (message.isBlank()) "HTTP $code" else message)
            }
            val root = JSONObject(text)
            val events = root.optJSONArray("events")?.length() ?: 0
            val alarms = root.optJSONArray("alarms")?.length() ?: 0
            val title = root.optString("title", "dir3")
            save(context, text)
            Prefs.setLastSync(context, System.currentTimeMillis())
            return FetchResult(text, events, alarms, title)
        } finally {
            connection.disconnect()
        }
    }

    fun refreshAndSchedule(context: Context): FetchResult? {
        return try {
            val result = fetch(context)
            AlarmScheduler.reschedule(context)
            result
        } catch (_: Exception) {
            null
        }
    }
}
