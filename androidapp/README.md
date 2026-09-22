# Bloody Sunday for Android

A shell around the same dashboard the Mac app shows — nothing about the
dashboard is bundled, so a change to it needs no rebuild here.

    ./build.sh            # debug APK
    ./build.sh install    # ...and adb install onto the attached device

**What is native:** the league strip at the top, the five-tab bar at the bottom,
pull-to-refresh with a haptic tick, the offline bar (last screen it loaded, with
the time it loaded), and the watcher.

**What is the web page:** everything between those bars. Each tab is a deep link
(`?shell=android&key=<pin>&league=<slug>&tab=<name>`), which is why Back works
and why a notification can open a screen rather than the app.

**The watcher** polls Sleeper directly — no push service, no account, nothing to
keep running anywhere else. Every fifteen minutes through WorkManager, and once
a minute inside a game window through `GameDayService` (Android will not allow a
faster background job without the ongoing notification that service carries).
Two alerts, both raised once:

* a starter is questionable/doubtful/out **and** a bench man at the same
  position projects higher this week — with the swap and both numbers;
* his matchup changes hands.

**Configuration** is `Config.kt`: the Cloud URL, the PIN, the four leagues and
the five tabs. `State.kt` holds his Sleeper handle and caches the two big reads
(the 5 MB player file for a day, the week's projections for an hour) so a check
costs one small call rather than a download.
