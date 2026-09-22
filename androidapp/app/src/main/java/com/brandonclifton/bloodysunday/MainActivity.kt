package com.brandonclifton.bloodysunday

import android.annotation.SuppressLint
import android.os.Build
import android.os.Bundle
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.bottomnavigation.BottomNavigationView

/**
 * The shell: a league strip, a WebView, a tab bar.
 *
 * Everything inside the WebView is the same dashboard the Mac app shows —
 * ?shell=android tells it to draw no chrome of its own, because the two things
 * around it here are native and a second set under them would be worse than
 * none. A tab press is a deep link, so Back behaves and each screen is an
 * address rather than a click path.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var refresher: SwipeRefreshLayout
    private lateinit var chips: LinearLayout
    private lateinit var offline: TextView
    private var league = Config.LEAGUES[0]
    private var tab = Config.TABS[0]
    private var lastGood = 0L

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(BG)
        }

        // ---- the league strip -------------------------------------------
        chips = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(10), dp(8), dp(10), dp(8))
        }
        val strip = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            setBackgroundColor(PANEL)
            addView(chips)
        }
        root.addView(strip, LinearLayout.LayoutParams(MATCH, WRAP))

        offline = TextView(this).apply {
            setBackgroundColor(0xFF3A2F1A.toInt())
            setTextColor(0xFFF0B357.toInt())
            textSize = 11f
            setPadding(dp(12), dp(6), dp(12), dp(6))
            visibility = View.GONE
        }
        root.addView(offline, LinearLayout.LayoutParams(MATCH, WRAP))

        // ---- the page ----------------------------------------------------
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            // Streamlit reflows to the width it is given; the phone layer in
            // theme.py does the rest. No desktop viewport, no pinch-zoom.
            settings.useWideViewPort = false
            settings.loadWithOverviewMode = false
            setBackgroundColor(BG)
            overScrollMode = View.OVER_SCROLL_NEVER
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(v: WebView?, url: String?) {
                    refresher.isRefreshing = false
                    lastGood = System.currentTimeMillis()
                    offline.visibility = View.GONE
                }

                override fun onReceivedError(v: WebView, req: WebResourceRequest,
                                             err: WebResourceError) {
                    if (!req.isForMainFrame) return
                    refresher.isRefreshing = false
                    // Not an error page: the last screen it managed to load,
                    // with a bar saying how old it is. A dead stadium Wi-Fi
                    // should still say where you stood ten minutes ago.
                    offline.text = if (lastGood == 0L) "No signal"
                        else "No signal · showing ${Ago.of(lastGood)}"
                    offline.visibility = View.VISIBLE
                }
            }
        }
        refresher = SwipeRefreshLayout(this).apply {
            setColorSchemeColors(CRIMSON)
            setProgressBackgroundColorSchemeColor(PANEL)
            addView(web, ViewGroup.LayoutParams(MATCH, MATCH))
            setOnRefreshListener {
                performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
                web.reload()
            }
        }
        root.addView(refresher, LinearLayout.LayoutParams(MATCH, 0, 1f))

        // ---- the tab bar --------------------------------------------------
        val nav = BottomNavigationView(this).apply {
            setBackgroundColor(PANEL)
            itemActiveIndicatorColor = android.content.res.ColorStateList.valueOf(0x22FF336C)
            Config.TABS.forEachIndexed { i, t ->
                menu.add(0, i, i, t.label).setIcon(t.icon)
            }
            setOnItemSelectedListener { item ->
                go(Config.TABS[item.itemId], league)
                true
            }
        }
        root.addView(nav, LinearLayout.LayoutParams(MATCH, WRAP))
        setContentView(root)

        // Let the page own the notch and the gesture bar, but keep the bars
        // themselves clear of both.
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(0, bars.top, 0, bars.bottom)
            insets
        }

        drawChips()
        go(tab, league)
        Watcher.schedule(this)
    }

    /** One chip per league, the current one in crimson. */
    private fun drawChips() {
        chips.removeAllViews()
        Config.LEAGUES.forEach { lg ->
            val on = lg.slug == league.slug
            val chip = TextView(this).apply {
                text = lg.label
                textSize = 13f
                setTextColor(if (on) 0xFFF2EEF0.toInt() else 0xFFA2989C.toInt())
                setPadding(dp(14), dp(7), dp(14), dp(7))
                background = Pill.of(on)
                setOnClickListener {
                    performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
                    league = lg
                    drawChips()
                    // Today is all four leagues at once, so a chip press there
                    // means "show me this one" — it moves to Live.
                    go(if (tab.tab == null) Config.TABS[1] else tab, lg)
                }
            }
            val lp = LinearLayout.LayoutParams(WRAP, WRAP)
            lp.rightMargin = dp(6)
            chips.addView(chip, lp)
        }
    }

    private fun go(t: Config.Tab, lg: Config.League) {
        tab = t
        web.loadUrl(Config.url(t, lg))
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        const val BG = 0xFF141314.toInt()
        const val PANEL = 0xFF191718.toInt()
        const val CRIMSON = 0xFFFF336C.toInt()
        const val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
        const val WRAP = ViewGroup.LayoutParams.WRAP_CONTENT
    }
}

/** "1:38pm" for the offline bar — the time it last had something to show. */
object Ago {
    fun of(ms: Long): String {
        val f = java.text.SimpleDateFormat("h:mma", java.util.Locale.US)
        return f.format(java.util.Date(ms)).lowercase()
    }
}

/** The chip background, drawn rather than shipped as nine-patches. */
object Pill {
    fun of(on: Boolean): android.graphics.drawable.GradientDrawable =
        android.graphics.drawable.GradientDrawable().apply {
            shape = android.graphics.drawable.GradientDrawable.RECTANGLE
            cornerRadius = 999f
            setColor(if (on) 0x1AFF336C else 0x00000000)
            setStroke(2, if (on) MainActivity.CRIMSON else 0xFF3D383A.toInt())
        }
}
