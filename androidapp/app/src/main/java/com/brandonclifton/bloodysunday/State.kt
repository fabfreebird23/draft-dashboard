package com.brandonclifton.bloodysunday

import android.content.Context
import org.json.JSONObject

/**
 * What the watcher remembers between polls, and the two big reads it caches.
 *
 * Sleeper's player file is five megabytes and changes about once a day; the
 * week's projections change during games but not minute to minute. Both are
 * kept on disk so a fifteen-minute check costs one small matchup call, not six
 * megabytes of download on his data plan.
 */
class State(private val ctx: Context) {

    private val sp = ctx.getSharedPreferences("bs", Context.MODE_PRIVATE)

    fun getBool(key: String): Boolean? =
        if (!sp.contains(key)) null else sp.getBoolean(key, false)

    fun putBool(key: String, v: Boolean) = sp.edit().putBoolean(key, v).apply()

    /** His league ids, discovered once from his Sleeper user and then kept. */
    fun leagueId(slug: String): String? {
        val key = "lid_$slug"
        sp.getString(key, null)?.let { return it }
        val season = (Watcher.json("https://api.sleeper.app/v1/state/nfl") as? JSONObject)
            ?.optString("season") ?: return null
        val list = Watcher.json(
            "https://api.sleeper.app/v1/user/$USER/leagues/nfl/$season") as? org.json.JSONArray
            ?: return null
        var found: String? = null
        for (i in 0 until list.length()) {
            val lg = list.getJSONObject(i)
            val name = lg.optString("name", "").lowercase()
            val norm = name.replace(Regex("[^a-z0-9]+"), "-").removePrefix("the-")
            if (norm.startsWith(slug)) { found = lg.optString("league_id"); break }
        }
        found?.let { sp.edit().putString(key, it).apply() }
        return found
    }

    /** Which roster in that league is his. */
    fun rosterId(leagueId: String): Int? {
        val key = "rid_$leagueId"
        if (sp.contains(key)) return sp.getInt(key, -1).takeIf { it > 0 }
        val rosters = Watcher.json("https://api.sleeper.app/v1/league/$leagueId/rosters")
            as? org.json.JSONArray ?: return null
        for (i in 0 until rosters.length()) {
            val r = rosters.getJSONObject(i)
            if (r.optString("owner_id") == USER_ID) {
                val rid = r.optInt("roster_id")
                sp.edit().putInt(key, rid).apply()
                return rid
            }
        }
        return null
    }

    fun players(): JSONObject? = cached("players.json", 24 * 3600_000L) {
        "https://api.sleeper.app/v1/players/nfl"
    }

    fun projections(week: Int): JSONObject? {
        val season = (Watcher.json("https://api.sleeper.app/v1/state/nfl") as? JSONObject)
            ?.optString("season") ?: return null
        val raw = cached("proj_${season}_$week.json", 3600_000L) {
            "https://api.sleeper.app/projections/nfl/$season/$week?season_type=regular"
        } ?: return null
        // {pid: {pts_half_ppr: n}} -> {pid: n}. Half PPR is what three of the
        // four leagues score; the alert is a comparison, so the scale matters
        // less than using ONE scale for both men.
        val out = JSONObject()
        val it = raw.keys()
        while (it.hasNext()) {
            val k = it.next()
            val row = raw.optJSONObject(k) ?: continue
            out.put(k, row.optDouble("pts_half_ppr", row.optDouble("pts_ppr", 0.0)))
        }
        return out
    }

    private fun cached(name: String, ttlMs: Long, url: () -> String): JSONObject? {
        val f = java.io.File(ctx.cacheDir, name)
        if (f.exists() && System.currentTimeMillis() - f.lastModified() < ttlMs) {
            return try { JSONObject(f.readText()) } catch (e: Exception) { null }
        }
        val fresh = Watcher.json(url())
        val obj = when (fresh) {
            is JSONObject -> fresh
            is org.json.JSONArray -> JSONObject().also { o ->
                // the projections endpoint answers with a list keyed by player_id
                for (i in 0 until fresh.length()) {
                    val row = fresh.optJSONObject(i) ?: continue
                    val pid = row.optString("player_id", "")
                    if (pid.isNotEmpty()) o.put(pid, row.optJSONObject("stats") ?: row)
                }
            }
            else -> null
        } ?: return if (f.exists()) JSONObject(f.readText()) else null
        try { f.writeText(obj.toString()) } catch (e: Exception) { /* cache is optional */ }
        return obj
    }

    companion object {
        /** His Sleeper handle and id — the same account in all three Sleeper leagues. */
        const val USER = "fabfreebird"
        const val USER_ID = "964703051971887104"
    }
}
