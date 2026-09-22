package com.brandonclifton.bloodysunday

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

/**
 * The phone watching his four leagues, with nothing in between.
 *
 * No push service and no account: Sleeper's own API is public and answers in a
 * few hundred milliseconds, so the phone asks it directly. Two things are worth
 * a buzz and they are the two he picked:
 *
 *   LOCK — a starter is questionable or out and a man on his bench plays the
 *          same week at the same slot for more points. Raised once per player
 *          per week, and only while the news can still be acted on.
 *   FLIP — a matchup changes hands. Not a fresh probability every tick, which
 *          would be noise: only when the projected winner is not who it was
 *          the last time this ran.
 *
 * WorkManager's floor is fifteen minutes and that is right for a Tuesday. A
 * Sunday wants a minute, and Android only allows that from a foreground
 * service, which is what GameDayService is for.
 */
class Watcher(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        return try {
            check(applicationContext)
            Result.success()
        } catch (e: Exception) {
            Log.w(TAG, "check failed: ${e.message}")
            Result.success()   // a failed poll is not a reason to unschedule
        }
    }

    companion object {
        const val TAG = "bs-watcher"
        const val CH_ALERT = "alerts"
        private const val WORK = "bs-watch"

        fun schedule(ctx: Context) {
            channels(ctx)
            val req = PeriodicWorkRequestBuilder<Watcher>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx)
                .enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, req)
        }

        private fun channels(ctx: Context) {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(
                CH_ALERT, "Lineup and matchup alerts", NotificationManager.IMPORTANCE_HIGH))
            nm.createNotificationChannel(NotificationChannel(
                GameDayService.CH_ONGOING, "Game day", NotificationManager.IMPORTANCE_LOW))
        }

        // ---------------------------------------------------------------- the check
        fun check(ctx: Context) {
            val state = State(ctx)
            val week = nflWeek() ?: return
            for (lg in Config.LEAGUES) {
                val id = state.leagueId(lg.slug) ?: continue
                try {
                    flip(ctx, state, lg, id, week)
                    lock(ctx, state, lg, id, week)
                } catch (e: Exception) {
                    Log.w(TAG, "${lg.label}: ${e.message}")
                }
            }
        }

        /** Who is winning, and has that changed since the last look? */
        private fun flip(ctx: Context, state: State, lg: Config.League, id: String, week: Int) {
            val me = state.rosterId(id) ?: return
            val matchups = json("https://api.sleeper.app/v1/league/$id/matchups/$week")
                as? JSONArray ?: return
            var mine: JSONObject? = null
            for (i in 0 until matchups.length()) {
                val m = matchups.getJSONObject(i)
                if (m.optInt("roster_id") == me) { mine = m; break }
            }
            val m = mine ?: return
            val group = m.optInt("matchup_id", -1)
            if (group < 0) return
            var opp: JSONObject? = null
            for (i in 0 until matchups.length()) {
                val o = matchups.getJSONObject(i)
                if (o.optInt("matchup_id", -2) == group && o.optInt("roster_id") != me) {
                    opp = o; break
                }
            }
            val o = opp ?: return
            val mePts = m.optDouble("points", 0.0)
            val opPts = o.optDouble("points", 0.0)
            if (mePts == 0.0 && opPts == 0.0) return    // nothing has happened yet
            val ahead = mePts >= opPts
            val key = "flip_${lg.slug}_$week"
            val was = state.getBool(key)
            state.putBool(key, ahead)
            if (was == null || was == ahead) return
            notify(ctx, lg.slug.hashCode(),
                if (ahead) "${lg.label} just flipped your way" else "${lg.label} just flipped",
                "%.1f – %.1f".format(mePts, opPts) +
                    if (ahead) " — you are ahead now." else " — you are behind now.")
        }

        /**
         * A starter he should look at, and the bench man who would do better.
         *
         * Sleeper carries the injury status on the player record and the week's
         * projections on its own endpoint, so the whole judgement is available
         * here: same position, actually plays this week, and worth more.
         */
        private fun lock(ctx: Context, state: State, lg: Config.League, id: String, week: Int) {
            val me = state.rosterId(id) ?: return
            val rosters = json("https://api.sleeper.app/v1/league/$id/rosters") as? JSONArray
                ?: return
            var mine: JSONObject? = null
            for (i in 0 until rosters.length()) {
                val r = rosters.getJSONObject(i)
                if (r.optInt("roster_id") == me) { mine = r; break }
            }
            val r = mine ?: return
            val starters = r.optJSONArray("starters") ?: return
            val all = r.optJSONArray("players") ?: return
            val players = state.players() ?: return
            val proj = state.projections(week) ?: return

            val bench = ArrayList<String>()
            for (i in 0 until all.length()) {
                val pid = all.optString(i)
                var isStarter = false
                for (j in 0 until starters.length()) {
                    if (starters.optString(j) == pid) { isStarter = true; break }
                }
                if (!isStarter) bench.add(pid)
            }

            for (i in 0 until starters.length()) {
                val pid = starters.optString(i)
                if (pid.isEmpty() || pid == "0") continue
                val p = players.optJSONObject(pid) ?: continue
                val status = p.optString("injury_status", "")
                if (status !in setOf("Questionable", "Doubtful", "Out", "IR")) continue
                val pos = p.optString("position", "")
                val mine_pts = proj.optDouble(pid, 0.0)
                var best: Pair<String, Double>? = null
                for (b in bench) {
                    val bp = players.optJSONObject(b) ?: continue
                    if (bp.optString("position", "") != pos) continue
                    if (bp.optString("injury_status", "") in setOf("Out", "IR")) continue
                    val bpts = proj.optDouble(b, 0.0)
                    if (bpts <= mine_pts) continue
                    if (best == null || bpts > best!!.second) best = b to bpts
                }
                val swap = best ?: continue
                val key = "lock_${lg.slug}_${week}_$pid"
                if (state.getBool(key) != null) continue     // said once is enough
                state.putBool(key, true)
                val bname = players.optJSONObject(swap.first)?.let {
                    it.optString("first_name", "") + " " + it.optString("last_name", "")
                }?.trim() ?: "a bench man"
                val name = (p.optString("first_name", "") + " " + p.optString("last_name", "")).trim()
                notify(ctx, key.hashCode(), "${lg.label}: $name is ${status.lowercase()}",
                    "Start $bname instead — %.1f against %.1f this week."
                        .format(swap.second, mine_pts))
            }
        }

        // ---------------------------------------------------------------- plumbing
        fun notify(ctx: Context, id: Int, title: String, text: String) {
            val open = android.app.PendingIntent.getActivity(
                ctx, id, android.content.Intent(ctx, MainActivity::class.java),
                android.app.PendingIntent.FLAG_IMMUTABLE or
                    android.app.PendingIntent.FLAG_UPDATE_CURRENT)
            val n = NotificationCompat.Builder(ctx, CH_ALERT)
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setColor(MainActivity.CRIMSON)
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
            ctx.getSystemService(NotificationManager::class.java).notify(id, n)
        }

        fun json(url: String): Any? {
            val c = URL(url).openConnection() as HttpURLConnection
            c.connectTimeout = 12000
            c.readTimeout = 20000
            c.setRequestProperty("Accept", "application/json")
            return try {
                if (c.responseCode != 200) return null
                val body = c.inputStream.bufferedReader().readText()
                if (body.startsWith("[")) JSONArray(body) else JSONObject(body)
            } finally {
                c.disconnect()
            }
        }

        /** Sleeper's own idea of the week, which is the one the league scores on. */
        fun nflWeek(): Int? {
            val s = json("https://api.sleeper.app/v1/state/nfl") as? JSONObject ?: return null
            val w = s.optInt("week", 0)
            return if (w > 0) w else null
        }
    }
}
