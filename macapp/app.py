#!/usr/bin/env python3
"""Bloody Sunday as a Mac app: a window, a menu-bar line, one Streamlit.

    python3 macapp/app.py              # from the repo, for development
    open ~/Applications/BloodySunday.app

Shape, and why it is this shape: the bundle carries pywebview and PyObjC and
NOTHING else. Streamlit, pandas, requests and the whole draftkit live in the
repo's own .venv, and the app SHELLS OUT to it — `python -m streamlit run
app.py` on a fixed port, then a WKWebView pointed at 127.0.0.1. Packaging
Streamlit into py2app is possible and miserable (its static bundle, its own
CLI, its runtime file watching), and it would freeze the dashboard at build
time. This way a `git pull` updates the app; the bundle only ever changes when
the wrapper does.

Sportsbot's rule carries over: pywebview owns the Cocoa run loop, so the status
item is built on the main thread BEFORE `webview.start()` and simply lives in
the loop pywebview drives. One process, one window, one menu-bar item.

Closing the window hides it — quitting is a menu item, so a stray ⌘W does not
take a live Sunday down with it.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import objc
import webview
from AppKit import (NSApp, NSMenu, NSMenuItem, NSObject, NSStatusBar,
                    NSVariableStatusItemLength, NSWorkspace, NSURL)
from Foundation import NSLog

PORT = int(os.environ.get("BLOODY_SUNDAY_PORT", "8599"))
URL = f"http://127.0.0.1:{PORT}/?mac=1"
HEALTH = f"http://127.0.0.1:{PORT}/_stcore/health"
STATUS_EVERY = 90.0


SPLASH = """<!doctype html><meta charset="utf-8"><title>Bloody Sunday</title>
<style>
 html,body{height:100%;margin:0;background:#0E0D0E;color:#F4F1F2;
   font:500 13px/1.4 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif;
   display:flex;align-items:center;justify-content:center;-webkit-user-select:none}
 .w{text-align:center}
 .m{font:900 italic 30px/1 "Helvetica Neue",Arial,sans-serif;letter-spacing:-.04em}
 .m em{color:#E8384F;font-style:italic}
 .s{margin-top:10px;color:#8A8285;font-size:12px;letter-spacing:.04em}
 .b{margin:18px auto 0;width:180px;height:2px;background:#241F21;overflow:hidden;border-radius:2px}
 .b i{display:block;height:100%;width:38%;background:#E8384F;animation:s 1.15s ease-in-out infinite}
 @keyframes s{0%{transform:translateX(-100%)}100%{transform:translateX(360%)}}
</style>
<div class=w><div class=m>Bloody<em>Sunday</em></div>
<div class=s id=s>Waking the four leagues…</div><div class=b><i></i></div></div>
<script>const m=["Waking the four leagues…","Reading rosters and projections…",
"Building this week's boards…"];let i=0;
setInterval(()=>{i=(i+1)%m.length;document.getElementById("s").textContent=m[i]},3200);</script>
"""


def repo_dir() -> Path:
    """Where the dashboard actually lives.

    Inside the bundle __file__ is Contents/Resources/app.py, which holds the
    wrapper and none of the dashboard, so the bundle looks for the checkout.
    Running from the repo, the parent of macapp/ is already it.
    """
    env = os.environ.get("BLOODY_SUNDAY_DIR")
    if env and (Path(env) / "app.py").exists():
        return Path(env)
    here = Path(__file__).resolve().parent
    if (here.parent / "draftkit").is_dir():
        return here.parent
    return Path.home() / "draft-dashboard"


REPO = repo_dir()
LOG = Path.home() / "Library" / "Logs" / "BloodySunday.log"


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    NSLog("BloodySunday: %s" % msg)


def child_env() -> dict:
    """The environment for a child of the BUNDLE, scrubbed.

    py2app exports PYTHONHOME and PYTHONPATH pointing into Contents/Resources,
    and a 3.9 interpreter started under them dies before it can import
    encodings ("failed to get the Python codec of the filesystem encoding").
    The repo's venv must be left to find its own prefix.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE",
                        "PYTHONNOUSERSITE", "ARGVZERO", "RESOURCEPATH",
                        "EXECUTABLEPATH")}
    env["PYTHONUTF8"] = "1"
    env.setdefault("LANG", "en_US.UTF-8")
    return env


def venv_python() -> str:
    """The repo's interpreter — the one with streamlit and draftkit in it."""
    p = REPO / ".venv" / "bin" / "python"
    return str(p) if p.exists() else sys.executable


# ---------------------------------------------------------------- the server

def already_up() -> bool:
    try:
        urllib.request.urlopen(HEALTH, timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


class Server:
    """The Streamlit subprocess, in its own process group so it dies with us.

    A Streamlit left running after a crash would hold the port and the next
    launch would attach to a stale build, so the group gets killed on quit and
    Restart goes down and up rather than starting a second one.
    """

    def __init__(self):
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if already_up():
            _log(f"attached to an existing server on {PORT}")
            return
        env = child_env()
        env["STREAMLIT_SERVER_HEADLESS"] = "true"
        # Build every board in the background before he clicks one. Measured:
        # a cold first click cost 6–12s, a warm one 0.2–1.7s.
        env["DRAFTROOM_WARM"] = "1"
        env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        cmd = [venv_python(), "-m", "streamlit", "run", "app.py",
               "--server.port", str(PORT), "--server.address", "127.0.0.1",
               "--server.headless", "true", "--server.fileWatcherType", "none",
               "--browser.gatherUsageStats", "false"]
        _log(f"starting {' '.join(cmd)} in {REPO}")
        out = LOG.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=str(REPO), env=env,
                                     stdout=out, stderr=out,
                                     start_new_session=True)

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if not p or p.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            for _ in range(20):
                if p.poll() is not None:
                    return
                time.sleep(0.1)
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass

    def restart(self) -> None:
        self.stop()
        time.sleep(0.6)
        self.start()


SERVER = Server()


def wait_up(seconds: float = 90.0) -> bool:
    """Streamlit's first boot builds the player registry; it is not instant."""
    end = time.time() + seconds
    while time.time() < end:
        if already_up():
            return True
        time.sleep(0.4)
    return False


# ------------------------------------------------------------- the menu bar

def _menu_item(target, title, sel, key):
    it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
    it.setTarget_(target)
    return it


class MenuBar(NSObject):
    """The status item and its menu. Lives on the main thread.

    The scores come from `python -m draftkit.macstatus --loop`, a long-lived
    child of the repo venv that prints one JSON line per poll. Reading its
    stdout on a background thread keeps the registry build (seconds) off the
    main thread, where it would freeze the menu.
    """

    def initWithWindow_(self, window):
        self = objc.super(MenuBar, self).init()
        if self is None:
            return None
        self.window = window
        self.status_proc = None
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        self.item.button().setTitle_("Bloody Sunday")

        menu = NSMenu.alloc().init()
        self.head = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Starting…", None, "")
        self.head.setEnabled_(False)
        menu.addItem_(self.head)
        self.lines_from = menu.numberOfItems()
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(_menu_item(self, "Open Bloody Sunday", "open:", "o"))
        menu.addItem_(_menu_item(self, "Reload", "reload:", "r"))
        menu.addItem_(_menu_item(self, "Open in browser", "browser:", "b"))
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(_menu_item(self, "Restart server", "restart:", ""))
        menu.addItem_(_menu_item(self, "Show log", "log:", ""))
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(_menu_item(self, "Quit Bloody Sunday", "quit:", "q"))
        self.item.setMenu_(menu)
        self.menu = menu
        self.rows = []
        threading.Thread(target=self.pollLoop, daemon=True).start()
        return self

    # ---- polling
    def pollLoop(self):
        while True:
            try:
                self.status_proc = subprocess.Popen(
                    [venv_python(), "-m", "draftkit.macstatus", "--loop", str(STATUS_EVERY)],
                    cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, start_new_session=True, env=child_env())
                for line in self.status_proc.stdout:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "applyStatus:", data, False)
            except Exception as e:  # noqa: BLE001
                _log(f"status poller died: {e}")
            time.sleep(30)  # it exited; give it a beat before trying again

    def applyStatus_(self, data):
        try:
            self.item.button().setTitle_(data.get("title") or "Bloody Sunday")
            self.head.setTitle_(time.strftime("Updated %-I:%M %p"))
            for it in self.rows:
                self.menu.removeItem_(it)
            self.rows = []
            at = self.lines_from
            for text in (data.get("lines") or [])[:6]:
                it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(text, None, "")
                it.setEnabled_(False)
                self.menu.insertItem_atIndex_(it, at)
                self.rows.append(it)
                at += 1
        except Exception as e:  # noqa: BLE001
            _log(f"status apply failed: {e}")

    # ---- menu actions
    def open_(self, _sender):
        self.window.show()
        NSApp.activateIgnoringOtherApps_(True)

    def reload_(self, _sender):
        try:
            self.window.load_url(URL)
        except Exception as e:  # noqa: BLE001
            _log(f"reload failed: {e}")

    def browser_(self, _sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(URL))

    def restart_(self, _sender):
        def run():
            SERVER.restart()
            if wait_up():
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "reload:", None, False)
        threading.Thread(target=run, daemon=True).start()

    def log_(self, _sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(LOG)))

    def quit_(self, _sender):
        try:
            if self.status_proc and self.status_proc.poll() is None:
                os.killpg(os.getpgid(self.status_proc.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001
            pass
        SERVER.stop()
        NSApp.terminate_(self)


# ------------------------------------------------------------------- the app

def main() -> int:
    _log(f"start pid={os.getpid()} repo={REPO}")
    if not (REPO / "app.py").exists():
        _log(f"no dashboard at {REPO}")
    # The window opens on the splash, not on the URL: pointing WKWebView at a
    # port that is not listening yet paints Safari's "cannot connect" page, and
    # a cold boot is thirty seconds of it.
    window = webview.create_window(
        "Bloody Sunday", html=SPLASH, width=1440, height=940, min_size=(980, 640),
        background_color="#0E0D0E")

    def boot():
        SERVER.start()
        if wait_up():
            _log("server up")
            try:
                window.load_url(URL)
            except Exception:  # noqa: BLE001
                pass
        else:
            _log("server never came up; see the log")
    threading.Thread(target=boot, daemon=True).start()

    def on_closing():
        window.hide()
        return False
    window.events.closing += on_closing

    bar = MenuBar.alloc().initWithWindow_(window)   # noqa: F841  (kept alive)
    webview.start(debug=False)
    SERVER.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
