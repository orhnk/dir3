package dev.dir3.phone

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context

/** Refreshes the plan in the background; alarms stay correct while the PC sleeps. */
class SyncJob : JobService() {
    override fun onStartJob(params: JobParameters?): Boolean {
        if (Prefs.base(this).isBlank()) {
            jobFinished(params, false)
            return false
        }
        Thread {
            val ok = PlanRepository.refreshAndSchedule(this) != null
            jobFinished(params, !ok)
        }.start()
        return true
    }

    override fun onStopJob(params: JobParameters?): Boolean = true

    companion object {
        private const val JOB_ID = 7331

        fun schedule(context: Context) {
            val scheduler = context.getSystemService(Context.JOB_SCHEDULER_SERVICE) as JobScheduler
            val component = ComponentName(context, SyncJob::class.java)
            val info = JobInfo.Builder(JOB_ID, component)
                .setPeriodic(15 * 60 * 1000L)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .build()
            try {
                scheduler.schedule(info)
            } catch (_: Exception) {
                // Some OEMs cap jobs; the app still syncs on open.
            }
        }
    }
}
