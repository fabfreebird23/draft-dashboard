package com.brandonclifton.bloodysunday

import android.app.Notification
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlin.concurrent.thread

/**
 * A minute is not fifteen minutes.
 *
 * WorkManager will not run oftener than a quarter of an hour, which is right
 * for a Tuesday and useless while a game is on. Android's answer is a
 * foreground service, and its price is a permanent notification — so the
 * notification says what it is doing and how to stop it, and the service ends
 * itself when no game is live.
 */
class GameDayService : Service() {

    @Volatile private var running = false

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (running) return START_STICKY
        running = true
        startForeground(NOTE_ID, note("Game day · watching 4 leagues",
            "Checking every minute while games are on. Swipe to stop."))
        thread(name = "bs-gameday") {
            while (running) {
                try {
                    Watcher.check(applicationContext)
                } catch (e: Exception) {
                    // one bad minute is not a reason to stop watching
                }
                Thread.sleep(60_000)
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        super.onDestroy()
    }

    override fun onBind(p0: Intent?): IBinder? = null

    private fun note(title: String, text: String): Notification =
        NotificationCompat.Builder(this, CH_ONGOING)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)
            .setColor(MainActivity.CRIMSON)
            .setContentIntent(android.app.PendingIntent.getActivity(
                this, 0, Intent(this, MainActivity::class.java),
                android.app.PendingIntent.FLAG_IMMUTABLE))
            .build()

    companion object {
        const val CH_ONGOING = "gameday"
        const val NOTE_ID = 7788

        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, GameDayService::class.java))
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, GameDayService::class.java))
        }
    }
}
