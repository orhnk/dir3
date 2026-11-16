package dev.dir3.phone

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime

/**
 * One alarm exactly as `dir3 export` resolved it.  Every field has a safe
 * default so an older export still rings instead of crashing the app.
 */
data class AlarmSpec(
    val id: String,
    val triggerMillis: Long,
    val preTriggerMillis: Long?,
    val eventName: String,
    val label: String,
    val sound: String?,
    val sounds: List<String>,
    val speak: Boolean,
    val speakText: String?,
    val volume: Int?,
    val crescendo: Boolean,
    val crescendoSeconds: Int,
    val vibrate: Boolean,
    val vibration: String,
    val snoozeMinutes: Int,
    val snoozeLimit: Int,
    val dismiss: List<String>,
    val dismissMath: String,
    val fullScreen: Boolean,
    val background: String?,
    val flashlight: Boolean,
    val silentOverride: Boolean,
    val enabled: Boolean,
    val skipNext: Boolean,
) {
    fun toJson(): String = toJsonObject().toString()

    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("id", id)
        put("trigger", Instant.ofEpochMilli(triggerMillis).toString())
        if (preTriggerMillis != null) put("pre_trigger", Instant.ofEpochMilli(preTriggerMillis).toString())
        put("event_name", eventName)
        put("label", label)
        if (sound != null) put("sound", sound)
        put("sounds", JSONArray(sounds))
        put("speak", speak)
        if (speakText != null) put("speak_text", speakText)
        if (volume != null) put("volume", volume)
        put("crescendo", crescendo)
        put("crescendo_seconds", crescendoSeconds)
        put("vibrate", vibrate)
        put("vibration", vibration)
        put("snooze_minutes", snoozeMinutes)
        put("snooze_limit", snoozeLimit)
        put("dismiss", JSONArray(dismiss))
        put("dismiss_math", dismissMath)
        put("full_screen", fullScreen)
        if (background != null) put("background", background)
        put("flashlight", flashlight)
        put("silent_override", silentOverride)
        put("enabled", enabled)
        put("skip_next", skipNext)
    }

    companion object {
        fun fromString(raw: String?): AlarmSpec? {
            if (raw.isNullOrBlank()) return null
            return try {
                fromJson(JSONObject(raw))
            } catch (_: Exception) {
                null
            }
        }

        fun fromJson(json: JSONObject): AlarmSpec? {
            val id = json.optString("id").ifBlank { return null }
            val trigger = parseTime(json.optString("trigger")) ?: return null
            val sounds = mutableListOf<String>()
            val soundArray = json.optJSONArray("sounds")
            if (soundArray != null) {
                for (index in 0 until soundArray.length()) {
                    sounds.add(soundArray.optString(index))
                }
            }
            val dismiss = mutableListOf<String>()
            val dismissArray = json.optJSONArray("dismiss")
            if (dismissArray != null) {
                for (index in 0 until dismissArray.length()) {
                    dismiss.add(dismissArray.optString(index))
                }
            }
            return AlarmSpec(
                id = id,
                triggerMillis = trigger,
                preTriggerMillis = parseTime(json.optString("pre_trigger")),
                eventName = json.optString("event_name").ifBlank { json.optString("event") },
                label = json.optString("label").ifBlank { json.optString("event_name") },
                sound = if (json.isNull("sound")) null else json.optString("sound").ifBlank { null },
                sounds = sounds,
                speak = json.optBoolean("speak", false),
                speakText = if (json.isNull("speak_text")) null else json.optString("speak_text").ifBlank { null },
                volume = if (json.isNull("volume")) null else json.optInt("volume", -1).takeIf { it in 0..100 },
                crescendo = json.optBoolean("crescendo", true),
                crescendoSeconds = json.optInt("crescendo_seconds", 30).coerceAtLeast(0),
                vibrate = json.optBoolean("vibrate", true),
                vibration = json.optString("vibration", "default"),
                snoozeMinutes = json.optInt("snooze_minutes", 5).coerceAtLeast(0),
                snoozeLimit = json.optInt("snooze_limit", 3).coerceAtLeast(0),
                dismiss = dismiss.ifEmpty { listOf("button") },
                dismissMath = json.optString("dismiss_math", "medium"),
                fullScreen = json.optBoolean("full_screen", true),
                background = if (json.isNull("background")) null else json.optString("background").ifBlank { null },
                flashlight = json.optBoolean("flashlight", false),
                silentOverride = json.optBoolean("silent_override", true),
                enabled = json.optBoolean("enabled", true),
                skipNext = json.optBoolean("skip_next", false),
            )
        }

        /** A clearly-labelled one-shot alarm for the "test alarm" button. */
        fun demo(label: String): AlarmSpec = AlarmSpec(
            id = "test-${System.currentTimeMillis()}",
            triggerMillis = System.currentTimeMillis(),
            preTriggerMillis = null,
            eventName = label,
            label = label,
            sound = "system",
            sounds = emptyList(),
            speak = true,
            speakText = label,
            volume = null,
            crescendo = true,
            crescendoSeconds = 8,
            vibrate = true,
            vibration = "default",
            snoozeMinutes = 5,
            snoozeLimit = 3,
            dismiss = listOf("button"),
            dismissMath = "medium",
            fullScreen = true,
            background = "black",
            flashlight = false,
            silentOverride = true,
            enabled = true,
            skipNext = false,
        )

        fun parseTime(value: String?): Long? {
            if (value.isNullOrBlank()) return null
            return try {
                OffsetDateTime.parse(value).toInstant().toEpochMilli()
            } catch (_: Exception) {
                try {
                    Instant.parse(value).toEpochMilli()
                } catch (_: Exception) {
                    null
                }
            }
        }
    }
}
