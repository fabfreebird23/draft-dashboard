package com.brandonclifton.bloodysunday

/**
 * Everything about WHERE the app points, in one place.
 *
 * The dashboard is a Streamlit app on the cloud; this app is a shell around it,
 * exactly like the Mac one. A tab press is a deep link — the page is told which
 * shell is holding it, which league to open and which tab — so navigation is
 * native and the content is the same dashboard that runs on the desktop.
 */
object Config {
    /** No trailing slash. */
    const val BASE = "https://draft-dashboar-kbqgjjbr3vu9gu4bivzev4.streamlit.app"

    /** The app is public so a WebView can reach it at all; this is what keeps
     *  strangers out. It never has to be typed — it rides in every URL. */
    const val PIN = "476207"

    /** Label shown on the chip, and the league slug the page understands.
     *  A PREFIX is enough, so these survive a rename on Sleeper. */
    val LEAGUES = listOf(
        League("Kreeper", "kreeper"),
        League("B&B", "babies"),
        League("7½ Men", "7-1-2"),
        League("TD's", "show-us"),
    )

    /** Bottom bar, left to right. `tab` is the dashboard's own tab name;
     *  Today is the cross-league screen and has no league of its own. */
    val TABS = listOf(
        Tab("Today", null, R.drawable.ic_today),
        Tab("Live", "Live", R.drawable.ic_live),
        Tab("Lineup", "Lineup", R.drawable.ic_lineup),
        Tab("Wire", "Waivers", R.drawable.ic_wire),
        Tab("More", MORE, R.drawable.ic_more),
    )

    /** The tab bar holds five; the dashboard has more than five screens. The
     *  last pill opens these rather than standing for one of them. */
    const val MORE = "__more__"
    val MORE_TABS = listOf(
        "Command Center", "Rankings", "Matchup", "Trades", "Playoffs", "League", "Keepers",
    )

    data class League(val label: String, val slug: String)
    data class Tab(val label: String, val tab: String?, val icon: Int)

    /** The URL for a screen. Today has no league: it is all four at once. */
    fun url(tab: Tab, league: League): String {
        val sb = StringBuilder("$BASE/?shell=android&key=$PIN")
        if (tab.tab == null) {
            sb.append("&view=all")
        } else {
            sb.append("&league=").append(league.slug).append("&tab=").append(tab.tab)
        }
        return sb.toString()
    }
}
