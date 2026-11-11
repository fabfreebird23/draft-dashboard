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
 * few hundred milliseconds, so the phone asks it directly. Three things are
 * worth a buzz — each one something he can ACT on:
 *
 *   LOCK    — a starter is questionable or out and a man on his bench plays the
 *             same week at the same slot for more points (or, ruled out, nobody
 *             covers him). Once per player per STATUS per week — so a downgrade
 *             to Out still buzzes — and only while both games are still to play.
 *   SWEEP   — about ninety minutes before a kickoff window, one digest of every
 *             starter in those games who carries a designation, all leagues.
 *   WAIVERS — after a waiver run, what he won and what he lost.
 *
 * (A fourth, FLIP — "the matchup changed hands" — was removed: it interrupted
 * him for something he could do nothing about.)
 *
 * Designations come from ESPN's league-wide injury report, which is minutes
 * old; Sleeper's player file, which the phone keeps for a day, is only the
 * fallback.
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
            sched = schedule()
            games = sched.mapValues { it.value.first }
            fresh = freshStatuses()
            val flagged = ArrayList<Flag>()
            for (lg in Config.LEAGUES) {
                val id = state.leagueId(lg.slug) ?: continue
                try {
                    lock(ctx, state, lg, id, week, flagged)
                    waivers(ctx, state, lg, id, week)
                } catch (e: Exception) {
                    Log.w(TAG, "${lg.label}: ${e.message}")
                }
            }
            try { sweep(ctx, state, flagged) } catch (e: Exception) { Log.w(TAG, "sweep: ${e.message}") }
        }

        private data class Flag(val league: String, val name: String, val status: String, val kick: Long)

        /**
         * One digest before each kickoff window: every starter in those games
         * with a designation, across the leagues. Sent once per window, between
         * 100 and 20 minutes before it — late enough for the inactives, early
         * enough to act — and not at all when nobody is flagged.
         */
        private fun sweep(ctx: Context, state: State, flagged: List<Flag>) {
            val now = System.currentTimeMillis()
            val soon = flagged.filter { it.kick - now in (20 * 60_000L)..(100 * 60_000L) }
            val first = soon.minByOrNull { it.kick } ?: return
            val key = "sweep_${first.kick / (30 * 60_000L)}"
            if (state.getBool(key) != null) return
            state.putBool(key, true)
            val rows = flagged.filter { it.kick >= first.kick - 5 * 60_000L && it.kick <= first.kick + 45 * 60_000L }
            val at = java.text.SimpleDateFormat("h:mm", java.util.Locale.US).format(java.util.Date(first.kick))
            notify(ctx, key.hashCode(),
                "${rows.size} starter${if (rows.size == 1) "" else "s"} to check before $at",
                rows.joinToString("\n") { "${it.league}: ${it.name} — ${it.status.lowercase()}" })
        }

        /** What the last waiver run did for him: won, and lost. */
        private fun waivers(ctx: Context, state: State, lg: Config.League, id: String, week: Int) {
            val me = state.rosterId(id) ?: return
            val tx = json("https://api.sleeper.app/v1/league/$id/transactions/$week") as? JSONArray
                ?: return
            val key = "wv_seen_${lg.slug}"
            val last = state.getLong(key)
            var newest = last ?: 0L
            val won = ArrayList<String>()
            val lost = ArrayList<String>()
            val players = state.players()
            for (i in 0 until tx.length()) {
                val t = tx.getJSONObject(i)
                if (t.optString("type") != "waiver") continue
                val rids = t.optJSONArray("roster_ids") ?: continue
                var mine = false
                for (j in 0 until rids.length()) if (rids.optInt(j) == me) mine = true
                if (!mine) continue
                val ts = t.optLong("status_updated", t.optLong("created", 0L))
                if (ts > newest) newest = ts
                if (last == null || ts <= last) continue
                val adds = t.optJSONObject("adds") ?: continue
                val bid = t.optJSONObject("settings")?.optInt("waiver_bid", 0) ?: 0
                val it = adds.keys()
                while (it.hasNext()) {
                    val pid = it.next()
                    val p = players?.optJSONObject(pid)
                    val name = p?.let { (it.optString("first_name") + " " + it.optString("last_name")).trim() }
                        ?.takeIf { it.isNotEmpty() } ?: "a player"
                    when (t.optString("status")) {
                        "complete" -> won.add(if (bid > 0) "$name (\$$bid)" else name)
                        "failed" -> lost.add(name)
                    }
                }
            }
            if (newest > (last ?: 0L)) state.putLong(key, newest)
            if (last == null) return                 // first look: set the mark quietly
            if (won.isEmpty() && lost.isEmpty()) return
            val text = listOfNotNull(
                if (won.isNotEmpty()) "Won: " + won.joinToString(", ") else null,
                if (lost.isNotEmpty()) "Lost: " + lost.joinToString(", ") +
                    " — the Wire tab has the next best." else null).joinToString("\n")
            notify(ctx, key.hashCode() + newest.toInt(),
                "${lg.label} waivers: won ${won.size}, lost ${lost.size}", text)
        }

        /**
         * A starter he should look at, and the bench man who would do better.
         *
         * Sleeper carries the injury status on the player record and the week's
         * projections on its own endpoint, so the whole judgement is available
         * here: same position, actually plays this week, and worth more.
         */
        private fun lock(ctx: Context, state: State, lg: Config.League, id: String, week: Int,
                         flagged: MutableList<Flag>) {
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
                val status = statusOf(p)
                if (status !in setOf("Questionable", "Doubtful", "Out", "IR")) continue
                // kicked off = locked in his slot; nothing to tell him
                if (!open(p.optString("team", ""))) continue
                sched[p.optString("team", "")]?.let { g ->
                    flagged.add(Flag(lg.label,
                        (p.optString("first_name", "") + " " + p.optString("last_name", "")).trim(),
                        status, g.second))
                }
                val pos = p.optString("position", "")
                val mine_pts = proj.optDouble(pid, 0.0)
                var best: Pair<String, Double>? = null
                for (b in bench) {
                    val bp = players.optJSONObject(b) ?: continue
                    if (bp.optString("position", "") != pos) continue
                    if (statusOf(bp) in setOf("Out", "IR")) continue
                    if (!open(bp.optString("team", ""))) continue
                    val bpts = proj.optDouble(b, 0.0)
                    if (bpts <= mine_pts) continue
                    if (best == null || bpts > best!!.second) best = b to bpts
                }
                val name0 = (p.optString("first_name", "") + " " + p.optString("last_name", "")).trim()
                // keyed by STATUS too: Friday's "questionable" must not swallow
                // Sunday's "ruled out" — that downgrade is the alert that matters
                val key = "lock_${lg.slug}_${week}_${pid}_$status"
                if (state.getBool(key) != null) continue     // said once per status
                val swap = best
                if (swap == null) {
                    // ruled out with nobody on the bench to cover: the wire is the move
                    if (status in setOf("Out", "IR")) {
                        state.putBool(key, true)
                        notify(ctx, key.hashCode(), "${lg.label}: $name0 is ${status.lowercase()}",
                            "Nobody on your bench covers the $pos — check the wire before his game.")
                    }
                    continue
                }
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

        /** Team (Sleeper's abbreviation) -> ("pre" / "in" / "post", kickoff ms) for this
         *  week, from ESPN's public scoreboard. Empty when it can't be read, which
         *  means "assume everyone is still to play" rather than going quiet. */
        @Volatile private var sched: Map<String, Pair<String, Long>> = emptyMap()
        @Volatile private var games: Map<String, String> = emptyMap()

        private fun schedule(): Map<String, Pair<String, Long>> {
            val sb = json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard")
                as? JSONObject ?: return emptyMap()
            val out = HashMap<String, Pair<String, Long>>()
            val evs = sb.optJSONArray("events") ?: return out
            for (i in 0 until evs.length()) {
                val ev = evs.getJSONObject(i)
                val state = ev.optJSONObject("status")?.optJSONObject("type")?.optString("state") ?: continue
                val kick = try {
                    java.time.OffsetDateTime.parse(ev.optString("date")).toInstant().toEpochMilli()
                } catch (e: Exception) { 0L }
                val comps = ev.optJSONArray("competitions")?.optJSONObject(0)?.optJSONArray("competitors") ?: continue
                for (j in 0 until comps.length()) {
                    val abbr = comps.getJSONObject(j).optJSONObject("team")?.optString("abbreviation") ?: continue
                    out[TEAM[abbr] ?: abbr] = state to kick
                }
            }
            return out
        }

        private val TEAM = mapOf("WSH" to "WAS", "JAC" to "JAX", "LA" to "LAR")

        /** "name|TEAM" -> designation from ESPN's league-wide report ("" = active).
         *  Held ten minutes: it is about a megabyte and the game-day service asks
         *  every minute. */
        @Volatile private var fresh: Map<String, String> = emptyMap()
        @Volatile private var freshAt = 0L

        private fun norm(name: String): String =
            name.lowercase().replace(Regex("\\b(jr|sr|ii|iii|iv|v)\\b\\.?"), "").replace(Regex("[^a-z]"), "")

        private fun freshStatuses(): Map<String, String> {
            if (fresh.isNotEmpty() && System.currentTimeMillis() - freshAt < 10 * 60_000L) return fresh
            val doc = try {
                json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries") as? JSONObject
            } catch (e: Exception) { null } ?: return fresh
            val out = HashMap<String, String>()
            val teams = doc.optJSONArray("injuries") ?: return fresh
            for (i in 0 until teams.length()) {
                val list = teams.getJSONObject(i).optJSONArray("injuries") ?: continue
                for (j in 0 until list.length()) {
                    val row = list.getJSONObject(j)
                    val a = row.optJSONObject("athlete") ?: continue
                    val st = when (row.optString("status").lowercase()) {
                        "questionable" -> "Questionable"
                        "doubtful" -> "Doubtful"
                        "out" -> "Out"
                        "injured reserve" -> "IR"
                        "active" -> ""
                        else -> null
                    } ?: continue
                    val team = a.optJSONObject("team")?.optString("abbreviation") ?: ""
                    out[norm(a.optString("displayName")) + "|" + (TEAM[team] ?: team)] = st
                }
            }
            if (out.isNotEmpty()) { freshAt = System.currentTimeMillis() }
            return if (out.isNotEmpty()) out else fresh
        }

        /** His designation now: the fresh report if it lists him, else Sleeper's
         *  (day-old) one. "Active" on the report clears a soft tag, never an IR. */
        private fun statusOf(p: JSONObject): String {
            val old = p.optString("injury_status", "").let { if (it == "null") "" else it }
            val key = norm(p.optString("first_name", "") + " " + p.optString("last_name", "")) +
                "|" + p.optString("team", "")
            val f = fresh[key] ?: return old
            if (f.isEmpty()) return if (old in setOf("Questionable", "Doubtful", "Out")) "" else old
            return f
        }

        /** Still to play: his game hasn't kicked off (or we can't tell). */
        private fun open(team: String): Boolean = games[team]?.let { it == "pre" } ?: true

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
