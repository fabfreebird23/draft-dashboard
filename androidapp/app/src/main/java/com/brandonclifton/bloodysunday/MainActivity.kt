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

    /**
     * Whether the PAGE is scrolled to its top — which is not the same question
     * as whether the WebView is.
     *
     * Streamlit scrolls an element inside the document, so the WebView's own
     * scroll position never leaves zero and SwipeRefreshLayout believes it is
     * always at the top: every downward swipe, including the one that just
     * means "go back up", reloaded the page. The inner scroller reports here
     * instead, and the refresh gesture is only armed when it is really at rest.
     */
    @Volatile private var atTop = true

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
            addJavascriptInterface(Bridge(), "BSHost")
            webChromeClient = object : android.webkit.WebChromeClient() {
                override fun onConsoleMessage(m: android.webkit.ConsoleMessage): Boolean {
                    if (BuildConfig.DEBUG) {
                        android.util.Log.d("bs-shell", "console: ${m.message()} @${m.lineNumber()}")
                    }
                    return true
                }
            }
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(v: WebView?, url: String?) {
                    refresher.isRefreshing = false
                    lastGood = System.currentTimeMillis()
                    offline.visibility = View.GONE
                    v?.evaluateJavascript(STRIP_CLOUD_CHROME, null)
                    v?.evaluateJavascript(WATCH_SCROLL, null)
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
            // Two sources, because either can be the one that moves: the page
            // inside (reported by the bridge) or the WebView's own document.
            setOnChildScrollUpCallback { _, _ -> !atTop || web.canScrollVertically(-1) }
            setOnRefreshListener {
                android.util.Log.d("bs-shell", "pull refresh (atTop=$atTop)")
                performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
                web.reload()
            }
        }
        root.addView(refresher, LinearLayout.LayoutParams(MATCH, 0, 1f))

        // ---- the tab bar --------------------------------------------------
        val nav = BottomNavigationView(this).apply {
            setBackgroundColor(PANEL)
            // Five tabs, five labels. Material hides the labels of unselected
            // items once there are more than three, which leaves four unnamed
            // glyphs and one word.
            labelVisibilityMode = com.google.android.material.navigation
                .NavigationBarView.LABEL_VISIBILITY_LABELED
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

    /** The page telling the shell where it is scrolled to. */
    inner class Bridge {
        @android.webkit.JavascriptInterface
        fun scroll(top: Int) {
            val was = atTop
            atTop = top <= 2
            if (was != atTop) android.util.Log.d("bs-shell", "scroll top=$top atTop=$atTop")
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        /**
         * Streamlit Cloud wraps the app in its own page and floats a "Manage
         * app" button and a badge over it. Those belong to the OUTER document,
         * where the dashboard's stylesheet cannot reach, so they are taken out
         * from here — once when the page settles, and again on any late arrival.
         */
        private const val STRIP_CLOUD_CHROME = """
            (function () {
              const kill = () => {
                document.querySelectorAll(
                  '[data-testid="manage-app-button"],[class*="_profileContainer_"],' +
                  '[class*="_viewerBadge_"],[class*="_terminalButton_"],' +
                  'iframe[src*="statuspage.io"]'
                ).forEach(e => e.style.display = 'none');
              };
              kill();
              new MutationObserver(kill).observe(document.body, {childList: true, subtree: true});
            })();
        """

        /**
         * Find whatever is actually scrolling and report it back. Cloud puts the
         * app in an iframe, so the element is a document down; it also arrives
         * late, hence the retry rather than a single attempt.
         */
        /**
         * Report where the page is scrolled to.
         *
         * Guessing which element scrolls was wrong twice — Cloud nests the app
         * in an iframe and Streamlit's scroller is not the document — so this
         * does not guess. A scroll event does not bubble, but it can be caught
         * on the way DOWN, so one capturing listener per same-origin document
         * sees every scroller there is and reports the one that moved. Frames
         * arrive late, hence the retry.
         */
        private const val WATCH_SCROLL = """
            (function () {
              function attach(d) {
                if (!d || d.__bsHooked) return;
                d.__bsHooked = true;
                d.addEventListener('scroll', function (e) {
                  const t = e.target;
                  const top = (t && t.scrollTop != null) ? t.scrollTop
                            : (d.scrollingElement ? d.scrollingElement.scrollTop : 0);
                  try { BSHost.scroll(Math.round(top)); } catch (err) {}
                }, true);
              }
              function sweep() {
                attach(document);
                document.querySelectorAll('iframe').forEach(function (f) {
                  // Cloud sometimes wraps the app in a same-origin frame and
                  // sometimes serves it flat; a cross-origin one (the status
                  // badge) simply refuses, which is fine — it never scrolls.
                  try { if (f.contentDocument) attach(f.contentDocument); } catch (err) {}
                });
              }
              sweep();
              let n = 0;
              const t = setInterval(function () { sweep(); if (++n > 60) clearInterval(t); }, 500);
            })();
        """

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
