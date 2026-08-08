// ==UserScript==
// @name         Bloody Sunday — draft on Sleeper
// @namespace    https://github.com/fabfreebird23/draft-dashboard
// @version      2.0.1
// @description  Take the player you picked in Bloody Sunday and stage him in the Sleeper draft room, so you never type a name mid-draft.
// @match        https://sleeper.com/*
// @match        https://sleeper.app/*
// @match        https://www.sleeper.com/*
// @updateURL    https://raw.githubusercontent.com/fabfreebird23/draft-dashboard/main/assets/bloody-sunday-sleeper.user.js
// @downloadURL  https://raw.githubusercontent.com/fabfreebird23/draft-dashboard/main/assets/bloody-sunday-sleeper.user.js
// @run-at       document-idle
// @grant        none
// ==/UserScript==

/*
 WHY THIS EXISTS AS A USERSCRIPT AND NOT AN API CALL
 ---------------------------------------------------
 Sleeper's public API is read-only — their own docs say "you cannot modify
 contents via this API". There is no endpoint that submits a pick, official or
 otherwise. FantasyPros has exactly the same constraint: their "Draft on Sleeper"
 button only works if you install their browser extension, because the click has
 to happen inside the draft room page. This is that, for our board.

 HOW IT TALKS TO THE DASHBOARD
 -----------------------------
 The clipboard. The dashboard runs on streamlit.app and the draft room runs on
 sleeper.com; they are different origins, so localStorage, BroadcastChannel and
 postMessage are all unavailable, and a background relay would mean holding a
 Sleeper credential — which is exactly the thing worth not doing. Copy in one
 tab, paste in the other. No token, no server, nothing to leak.

 WHAT IT WILL NOT DO BY DEFAULT
 ------------------------------
 Confirm the pick. It fills the search and highlights the player; you press
 Sleeper's own draft button. A misfire here spends a real pick in a real league
 and cannot be undone, and the selectors below are guesses about someone else's
 markup. Auto-confirm exists, is off, and warns when you turn it on.
*/

(function () {
  'use strict';

  const LS = 'bs_sleeper_selectors';
  const LS_AUTO = 'bs_sleeper_autoconfirm';
  const LS_WATCH = 'bs_sleeper_watch';
  const say = (...a) => console.log('%c[Bloody Sunday]', 'color:#ff336c;font-weight:700', ...a);

  const load = () => { try { return JSON.parse(localStorage.getItem(LS)) || {}; } catch (e) { return {}; } };
  const save = (s) => localStorage.setItem(LS, JSON.stringify(s));
  const autoOn = () => localStorage.getItem(LS_AUTO) === '1';
  const watchOn = () => localStorage.getItem(LS_WATCH) === '1';

  /* Does this look like a player somebody copied, or is it just whatever else was
     on the clipboard? The watcher acts with no keypress behind it, so the bar for
     touching a string has to be higher than for a deliberate paste. */
  function plausibleName(t) {
    if (!t) return false;
    t = t.trim();
    if (t.length < 3 || t.length > 40) return false;
    const words = t.split(/\s+/);
    return words.length >= 2 && words.length <= 4 && /^[A-Za-z' .-]+$/.test(t);
  }

  // ---------------------------------------------------------------- utilities

  /* A CSS path stable enough to survive a re-render but specific enough to find
     one element. Deliberately NOT nth-child chains: Sleeper's draft room reorders
     rows constantly, so a positional path would point at whatever slid into that
     slot. Prefers stable-looking class names and bails out at 4 levels. */
  function pathOf(el) {
    const junk = /^(css-|sc-|jsx-|[a-z]{1,2}\d{2,})/;   // emotion/styled-components noise
    const seg = (n) => {
      const cls = [...n.classList].filter(c => !junk.test(c)).slice(0, 2);
      return n.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
    };
    const parts = [];
    let n = el;
    for (let i = 0; n && n.nodeType === 1 && i < 4; i++, n = n.parentElement) {
      parts.unshift(seg(n));
      if (n.id) { parts[0] = '#' + CSS.escape(n.id); break; }
    }
    return parts.join(' > ');
  }

  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  };

  /* Our own panel is part of the page, and every search below would happily match
     it. Teaching once recorded "#bs-dbg" — the Debug button — as the player search
     box, and from then on staging called an <input> value setter on a <button>,
     threw, and silently did nothing. Everything that looks at the page excludes us. */
  const mine = (el) => !!(el && el.closest && el.closest('#bs-panel'));

  const usableInput = (el) => !!el && vis(el) && !mine(el) &&
    (el.tagName === 'TEXTAREA' ||
     (el.tagName === 'INPUT' && /^(text|search|)$/i.test(el.type || '')));

  /* `el instanceof HTMLElement` is wrong across realms: an element belonging to a
     different document (an iframe, a portal) is a perfectly good HTMLElement in ITS
     window and fails the check in ours. Ask the element's own window instead. It
     also means a real button could be rejected for reasons that have nothing to do
     with the button, which is the hardest kind of failure to read from outside. */
  const isEl = (el) => {
    const w = el && el.ownerDocument && el.ownerDocument.defaultView;
    return !!(w && (el instanceof w.HTMLElement || el instanceof w.Element)) &&
           typeof el.click === 'function';
  };

  /* Visible enough to click. Strict vis() demands a non-zero box, but a control
     mid-transition (Sleeper animates the Draft button in when you go on the clock)
     can measure zero for a frame while being entirely real. offsetParent is the
     cheaper truth: null means display:none or detached. */
  const clickableEl = (el) => !!el && !mine(el) && isEl(el) &&
    (vis(el) || el.offsetParent !== null);

  /* The search box. A learned selector is only trusted if it still resolves to
     something you can actually type into — a stale or mistaught one is worse than
     none, because it silently beats the heuristic that would have worked.
     Confirmed live: Sleeper's is placeholder="Find player ⌘ U". */
  function findSearch() {
    const s = load().search;
    if (s) { const el = document.querySelector(s); if (usableInput(el)) return el; }
    const all = [...document.querySelectorAll('input[type="text"], input:not([type]), input[type="search"], textarea')]
      .filter(usableInput);
    return all.find(i => /search|player|find/i.test((i.placeholder || '') + ' ' + (i.getAttribute('aria-label') || '')))
        || all[0] || null;
  }

  /* React inputs ignore `el.value = x` — the framework owns the value and will
     overwrite it on the next render. Set through the native setter and dispatch
     a bubbling input event so React's onChange actually runs. */
  function setInput(el, text) {
    // Guard the illegal-invocation that the mistaught "#bs-dbg" selector caused:
    // an input value setter applied to a <button> throws and takes staging with it.
    if (!(el instanceof HTMLInputElement) && !(el instanceof HTMLTextAreaElement)) {
      say('refusing to type into', el && el.tagName); return false;
    }
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
    setter.call(el, text);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  const norm = (s) => (s || '')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/gi, '')
    .replace(/[^a-z ]/gi, '').replace(/\s+/g, ' ').trim().toLowerCase();

  /* The smallest element whose text contains the name — the row, not the page.
     Walking up from the deepest match avoids matching a container that happens to
     hold every player on the board. */
  function findRow(name) {
    const target = norm(name);
    if (!target) return null;
    const last = target.split(' ').slice(-1)[0];
    let best = null, bestLen = Infinity;
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const t = norm(n.nodeValue);
      if (!t || (!t.includes(target) && !(last.length > 3 && t.includes(last)))) continue;
      let el = n.parentElement, hops = 0;
      while (el && hops < 6 && el.getBoundingClientRect().height < 24) { el = el.parentElement; hops++; }
      // The panel prints the staged name in its own header, so from the second
      // pick onward the closest text match on the page can be US — and then we
      // highlight, click and hunt for a Draft button inside our own widget.
      if (!el || !vis(el) || mine(el)) continue;
      const len = (el.innerText || '').length;
      if (len < bestLen) { best = el; bestLen = len; }
    }
    return best;
  }

  /* Everything that could plausibly be a clickable control. Sleeper does not use
     <button> for all of them, and a div with an onclick looks identical to a user. */
  const CLICKABLE = 'button, [role="button"], a[href="#"], div[class*="button" i], div[class*="btn" i]';

  /* Labels that contain "draft" but are navigation, not the act of drafting.
     Clicking "Draft Board" instead of "Draft" is a harmless mis-click; clicking
     "Draft Recap" while auto-confirm is armed just wastes the countdown. Either
     way it means the real button never gets pressed, so exclude them explicitly. */
  const NOT_DRAFT = /board|order|recap|result|history|settings|mock|queue|log|pick ?em|grade/i;

  function draftish(el) {
    const t = ((el.innerText || el.getAttribute('aria-label') || '').trim());
    if (!t || t.length > 24 || NOT_DRAFT.test(t)) return false;
    return /^(draft|select|pick|draft player|draft now)$/i.test(t) || /^draft\b/i.test(t);
  }

  /* Search outward, not globally. The right button is the one attached to the
     player you just staged — a page-wide scan can find a "Draft" control belonging
     to someone else entirely, which is the one mistake that actually costs a pick. */
  /* Sleeper's real markup, read off the live draft room: the control is
     .draft-button inside .draft-button-wrapper, and it only exists while you are
     on the clock. Worth checking by name before falling back to label-guessing. */
  const KNOWN_DRAFT = '.draft-button-wrapper .draft-button, .draft-button, [class*="draft-button"]';

  /* Two elements are on the same visual row if their nearest shared ancestor is
     row-sized. Climbing by WIDTH was wrong: the first ancestor ≥320px wide sailed
     past the list row into a container holding the entire draft room, and the
     "leftmost control" in that was the → arrow on board pick 1.1. */
  function sameRow(a, b) {
    let n = a;
    while (n && !n.contains(b)) n = n.parentElement;
    return !!n && n.getBoundingClientRect().height <= 90;
  }

  /* THE draft control on Sleeper is the green ⊕ at the left of each player row —
     there is no page-level Draft button, which is why three rounds of dumps found
     nothing and why clicking around opened a player card instead of drafting.
     Identify it by shape and position rather than class: a small square control at
     the far-left edge of the row. The ☆ watchlist and the queue icon sit to the
     RIGHT of the name, so leftmost wins. */
  function findRowPlus(nameEl) {
    /* Find it by GEOMETRY relative to the name, not by walking the DOM. The ⊕ is a
       small square control sitting on the same line as the player, immediately to
       his left. Anything on another line — the board above, another player's row —
       is excluded by the vertical band, which is what ancestry failed to do. */
    const nr = nameEl.getBoundingClientRect();
    const cy = nr.top + nr.height / 2;
    const band = Math.max(18, nr.height * 0.9);

    const cands = [...document.querySelectorAll('body *')].filter(e => {
      if (mine(e) || !vis(e)) return false;
      const r = e.getBoundingClientRect();
      if (Math.abs((r.top + r.height / 2) - cy) > band) return false;   // same line
      if (r.right > nr.left + 4) return false;                          // left of him
      if (nr.left - r.right > 320) return false;                        // still his row
      const squarish = r.width >= 14 && r.width <= 52 && r.height >= 14 && r.height <= 52
                    && Math.abs(r.width - r.height) <= 12;
      if (!squarish) return false;
      return getComputedStyle(e).cursor === 'pointer' || e.matches(CLICKABLE)
          || e.tagName.toLowerCase() === 'svg';
    }).filter(e => sameRow(e, nameEl));

    /* Prefer an icon, then the leftmost. "Nearest to the name" would pick the rank
       number — it is the same size and, if the row carries cursor:pointer, passes
       the clickable test too. The ⊕ is drawn as an <svg> and sits furthest left. */
    const icons = cands.filter(e => e.tagName.toLowerCase() === 'svg' || e.querySelector('svg'));
    const pool = icons.length ? icons : cands;
    pool.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
    const hit = pool[0];
    if (!hit) return null;
    // an <svg> has no click(); walk up to the element that actually handles it
    return (isEl(hit) ? hit : hit.parentElement) || null;
  }

  function findDraftButton(scope) {
    const s = load().draft;
    // A learned selector that resolves to an SVG <path> — which is what you get by
    // clicking the icon inside the button — has no .click() and would throw.
    if (s) { const el = document.querySelector(s); if (clickableEl(el)) return el; }
    const known = [...document.querySelectorAll(KNOWN_DRAFT)].filter(clickableEl)[0];
    if (known) return known;
    const scopes = [];
    if (scope && scope !== document) {
      scopes.push(scope);
      for (let n = scope.parentElement, i = 0; n && i < 4; n = n.parentElement, i++) scopes.push(n);
    }
    // a modal/sheet, if one opened over the board
    document.querySelectorAll('[role="dialog"], [class*="modal" i], [class*="sheet" i]')
      .forEach(d => vis(d) && scopes.push(d));
    scopes.push(document);
    for (const sc of scopes) {
      const hit = [...sc.querySelectorAll(CLICKABLE)].filter(clickableEl).find(draftish);
      if (hit) return hit;
    }
    return null;
  }

  /* Every visible control on screen, for when the guesses above come up empty and
     I need to see what this page actually calls things. */
  /* Sleeper builds its UI from plain divs with no "button" in the class, so a
     class/tag-based sweep sees almost nothing — two dumps in a row returned the
     team columns and three filters and missed every real control on the page.
     cursor:pointer is what the site actually uses to mean "clickable". */
  function dumpControls() {
    const seen = new Set();
    const rows = [...document.querySelectorAll('body *')]
      .filter(e => !e.closest('#bs-panel') && vis(e))
      .filter(e => e.matches(CLICKABLE) || getComputedStyle(e).cursor === 'pointer')
      .filter(e => {                                  // keep the innermost only
        const t = (e.innerText || '').trim();
        if (!t && !e.getAttribute('aria-label')) return false;
        if (t.length > 40) return false;
        const k = t + '|' + e.tagName;
        if (seen.has(k)) return false;
        seen.add(k); return true;
      })
      .slice(0, 60)
      .map(b => ({ tag: b.tagName.toLowerCase(), text: (b.innerText || '').trim().slice(0, 40),
                   cls: String(b.className || '').slice(0, 46),
                   aria: b.getAttribute('aria-label') || '' }));
    say('visible controls:', rows.length); console.table(rows);
    const blob = rows.map(r => `${r.tag}: "${r.text}"${r.aria ? ' [' + r.aria + ']' : ''}`).join('\n');
    navigator.clipboard.writeText(blob).then(
      () => say('copied to clipboard — paste it to Claude'),
      () => say('copy failed; select from the table above'));
    return rows.length;
  }

  // ------------------------------------------------------------------ the panel

  const css = `
  #bs-panel{position:fixed;right:14px;bottom:14px;z-index:2147483647;width:274px;
    font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f2eef0;
    background:#161415;border:1px solid #332e30;border-radius:12px;
    box-shadow:0 10px 30px rgba(0,0,0,.55);overflow:hidden}
  #bs-panel .hd{display:flex;align-items:center;gap:7px;padding:9px 11px;background:#232022;
    border-bottom:1px solid #332e30;cursor:grab;font-weight:800;letter-spacing:-.01em}
  #bs-panel .mk{width:9px;height:9px;border-radius:50%;background:#ff336c;flex:none}
  #bs-panel .bd{padding:11px}
  #bs-panel .who{font-size:15px;font-weight:800;margin-bottom:2px;word-break:break-word}
  #bs-panel .sub{font-size:11.5px;color:#a2989c;margin-bottom:9px}
  #bs-panel button{width:100%;font:700 12.5px/1 inherit;padding:9px 10px;margin-bottom:6px;
    border-radius:8px;border:1px solid #332e30;background:#232022;color:#f2eef0;cursor:pointer}
  #bs-panel button.pri{background:#e02557;border-color:#e02557;color:#fff}
  #bs-panel button:hover{filter:brightness(1.14)}
  #bs-panel .row{display:flex;gap:6px}
  #bs-panel .row button{margin-bottom:0}
  #bs-panel .tog{display:flex;align-items:center;gap:6px;font-size:11px;color:#a2989c;margin-top:8px}
  #bs-panel .warn{color:#f0b357}
  #bs-panel .min{padding:0;width:auto;border:none;background:transparent;margin:0 0 0 auto;
    color:#a2989c;font-size:15px;line-height:1}
  #bs-cd{margin-top:9px;padding:9px 10px;border-radius:8px;background:#3a1020;
    border:1px solid #5a1b30;font-size:12px;line-height:1.4}
  #bs-cd b{color:#ff8fae}
  #bs-cd button{margin:7px 0 0;background:#232022;border-color:#5a1b30}
  .bs-hit{outline:3px solid #ff336c !important;outline-offset:2px;
    border-radius:6px;scroll-margin:120px}
  .bs-plus{outline:3px solid #7fd8b4 !important;outline-offset:3px;border-radius:50%;
    box-shadow:0 0 0 6px rgba(127,216,180,.22) !important}`;

  function panel() {
    if (document.getElementById('bs-panel')) return;
    document.head.appendChild(Object.assign(document.createElement('style'), { textContent: css }));
    const p = document.createElement('div');
    p.id = 'bs-panel';
    p.innerHTML = `
      <div class="hd"><span class="mk"></span>Bloody Sunday<button class="min" title="collapse">–</button></div>
      <div class="bd">
        <div class="who" id="bs-who">Nothing staged</div>
        <div class="sub" id="bs-sub">Copy a player in the dashboard, then hit Paste.</div>
        <button class="pri" id="bs-paste">Paste pick from clipboard</button>
        <div class="row">
          <button id="bs-again">Re-find</button>
          <button id="bs-learn" title="right-click to forget">Teach it</button>
          <button id="bs-dbg">Debug</button>
        </div>
        <label class="tog"><input type="checkbox" id="bs-watch"> watch clipboard (no keypress)</label>
        <label class="tog"><input type="checkbox" id="bs-auto"> auto-click Draft
          <span class="warn" id="bs-autow"></span></label>
        <div id="bs-cd" style="display:none"></div>
      </div>`;
    document.body.appendChild(p);

    const who = p.querySelector('#bs-who'), sub = p.querySelector('#bs-sub');
    const auto = p.querySelector('#bs-auto');
    auto.checked = autoOn();
    p.querySelector('#bs-autow').textContent = autoOn() ? '— on, be careful' : '';
    auto.onchange = () => {
      if (auto.checked && !confirm(
        'Auto-click Draft?\n\nThis spends a real pick the moment it finds a match, with no ' +
        'confirmation step. If it matches the wrong row you cannot undo it.\n\nTurn it on?')) {
        auto.checked = false; return;
      }
      localStorage.setItem(LS_AUTO, auto.checked ? '1' : '0');
      p.querySelector('#bs-autow').textContent = auto.checked ? '— on, be careful' : '';
    };

    // collapse
    let open = true;
    p.querySelector('.min').onclick = (e) => {
      e.stopPropagation(); open = !open;
      p.querySelector('.bd').style.display = open ? '' : 'none';
      e.target.textContent = open ? '–' : '+';
    };

    // drag by the header
    let drag = null;
    p.querySelector('.hd').addEventListener('mousedown', (e) => {
      if (e.target.classList.contains('min')) return;
      const r = p.getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
      e.preventDefault();
    });
    addEventListener('mousemove', (e) => {
      if (!drag) return;
      p.style.left = (e.clientX - drag.dx) + 'px'; p.style.top = (e.clientY - drag.dy) + 'px';
      p.style.right = 'auto'; p.style.bottom = 'auto';
    });
    addEventListener('mouseup', () => { drag = null; });

    let staged = '';

    async function readClip() {
      try { return (await navigator.clipboard.readText() || '').trim(); }
      catch (e) { return prompt('Clipboard is blocked here — paste the player name:') || ''; }
    }

    const cd = p.querySelector('#bs-cd');
    let cdTimer = null;

    function cancelCountdown(why) {
      clearInterval(cdTimer); cdTimer = null;
      cd.style.display = 'none'; cd.innerHTML = '';
      if (why) sub.textContent = why;
    }

    /* Fire the Draft click, but only after a visible countdown when nothing the
       user did directly caused it. An explicit ⌥⇧V is a decision and goes
       immediately; the clipboard watcher is a guess about intent, and a wrong
       guess spends a real pick. Three seconds is the difference between "it
       drafted for me" and "it drafted someone else for me". */
    function fire(btn, name, immediate) {
      if (immediate) { sub.innerHTML = 'Drafting…'; btn.click(); return; }
      let left = 3;
      cd.style.display = '';
      const paint = () => {
        cd.innerHTML = `Drafting <b>${name}</b> in ${left}…<button id="bs-x">Cancel</button>`;
        cd.querySelector('#bs-x').onclick = () => cancelCountdown('Cancelled — draft him yourself.');
      };
      paint();
      cdTimer = setInterval(() => {
        if (--left > 0) return paint();
        cancelCountdown();
        sub.innerHTML = 'Drafting…';
        btn.click();
      }, 1000);
    }

    /* Sleeper's rows are divs, not buttons, and the handler may sit on a parent or
       a child of whatever the text walker landed on. Try the nearest real control,
       then the element itself. */
    function clickThrough(el) {
      const t = el.closest(CLICKABLE) || el.querySelector(CLICKABLE) || el;
      t.click();
    }

    const WAIT_MS = 15 * 60 * 1000;    // long enough for a slow room, short enough
    let waitTimer = null;              // that it never lurks for a 24h clock
    function stopWaiting() { clearInterval(waitTimer); waitTimer = null; }

    /* Hold the staged player until the Draft button appears — i.e. until you are on
       the clock. Re-checks that he is still on the board before firing: between
       staging and your turn, somebody else may have taken him, and drafting into a
       stale highlight is exactly how you end up with the wrong player. */
    function waitForClock(name, fromWatch) {
      stopWaiting();
      waitForClock._snapped = false;      // one snapshot per wait, not per session
      const started = Date.now();
      cd.style.display = '';
      const tick = () => {
        const waited = Date.now() - started;
        if (waited > WAIT_MS) {
          stopWaiting(); cd.style.display = 'none';
          sub.innerHTML = 'Gave up waiting. Hit <b>Re-find</b> when you are on the clock.';
          return;
        }
        const row = findRow(name);
        if (!row) {
          stopWaiting(); cd.style.display = 'none';
          sub.innerHTML = `<b>${name}</b> is off the board — someone took him. Pick again.`;
          who.textContent = 'Nothing staged'; staged = '';
          return;
        }
        const b = findDraftButton(row);
        if (!b) {
          const s = Math.round(waited / 1000);
          /* One automatic snapshot a few seconds in. If the button IS on screen and
             we still can't see it, this is the moment that proves it — and it can't
             depend on someone clicking Debug during the seconds it's on the clock. */
          if (s >= 4 && !waitForClock._snapped) {
            waitForClock._snapped = true;
            const near = [...document.querySelectorAll('*')].filter(e =>
              /draft/i.test(String(e.className || '')) && !mine(e)).slice(0, 25)
              .map(e => ({ tag: e.tagName, cls: String(e.className).slice(0, 70),
                           txt: (e.innerText || '').trim().slice(0, 24),
                           box: (r => `${Math.round(r.width)}x${Math.round(r.height)}`)(e.getBoundingClientRect()),
                           offsetParent: e.offsetParent !== null, clickFn: typeof e.click === 'function' }));
            say('WAITING SNAPSHOT — elements with "draft" in the class:', near.length);
            console.table(near);
          }
          cd.innerHTML = `Staged <b>${name}</b> — waiting for your pick (${s}s)`
                       + '<button id="bs-x">Cancel</button>';
          cd.querySelector('#bs-x').onclick = () => {
            stopWaiting(); cd.style.display = 'none'; sub.textContent = 'Stopped waiting.';
          };
          return;
        }
        stopWaiting(); cd.style.display = 'none';
        if (autoOn()) { fire(b, name, false); return; }   // never instant off a wait
        sub.innerHTML = `You are on the clock — <b>Draft</b> is live for ${name}.`;
      };
      tick();
      waitTimer = setInterval(tick, 900);
    }

    function stage(name, fromWatch) {
      stopWaiting();
      cancelCountdown();
      staged = name;
      who.textContent = name || 'Nothing staged';
      const box = findSearch();
      if (box) { box.focus(); setInput(box, name); }
      // Sleeper filters asynchronously; give the list a beat to re-render.
      setTimeout(() => {
        document.querySelectorAll('.bs-hit').forEach(e => e.classList.remove('bs-hit'));
        document.querySelectorAll('.bs-plus').forEach(e => e.classList.remove('bs-plus'));
        const row = findRow(name);
        if (!row) {
          sub.innerHTML = box
            ? 'Search filled — <b>could not spot the row</b>. Pick him in the list.'
            : '<b>No search box found.</b> Use “Teach it”.';
          return;
        }
        row.classList.add('bs-hit');
        row.scrollIntoView({ block: 'center', behavior: 'smooth' });

        /* On Sleeper the Draft button usually does not exist until the player is
           opened — the board shows rows, and the control lives in the detail sheet
           that appears when you tap one. So a first pass that finds nothing is
           expected, not a failure: open the row and look again. Selecting a player
           is reversible; only the button we are hunting for is not. */
        const proceed = (b) => {
          if (b) { autoOn() ? fire(b, name, !fromWatch) : (sub.innerHTML =
            'Found him. <b>Draft</b> is ready — press it.'); return true; }
          return false;
        };

        /* The ⊕ on HIS row is the whole job. Do NOT click the row first: that opens
           the player card, which is what happened last time and is why a countdown
           ended in a profile page instead of a pick. */
        const plus = findRowPlus(row);
        if (plus) {
          plus.classList.add('bs-plus');
          if (autoOn()) { fire(plus, name, !fromWatch); return; }
          sub.innerHTML = 'Found him — the <b>⊕</b> is ringed. Click it to draft.';
          return;
        }
        setTimeout(() => {
          if (proceed(findDraftButton(row))) return;
          /* No Draft control anywhere. On Sleeper that is the NORMAL state when it
             is not your pick — the button only exists while you are on the clock,
             which a control dump from a mock confirmed: filters and team columns,
             nothing draft-like. So this is not a failure to report, it is a clock
             to wait for. */
          waitForClock(name, fromWatch);
        }, 450);
      }, 420);
    }

    p.querySelector('#bs-paste').onclick = async () => {
      const t = await readClip();
      if (!t) { sub.textContent = 'Clipboard was empty.'; return; }
      if (t.length > 60) { sub.textContent = 'That does not look like a name.'; return; }
      stage(t);
    };
    p.querySelector('#bs-again').onclick = () => staged ? stage(staged) : (sub.textContent = 'Nothing staged yet.');

    /* The clipboard watcher — this is what removes the keypress.
       Two hard constraints from the browser, both load-bearing:
         - readText() throws unless the document is FOCUSED, so this can only work
           while the Sleeper tab is the one you are looking at. That is fine: it
           means copy in the dashboard, switch tabs, and it stages on arrival.
         - the first read needs a user gesture to raise Chrome's permission prompt,
           which is why arming it is a checkbox and not something on by default.
       Seeded with whatever is already on the clipboard so enabling it does not
       immediately act on a name left over from ten minutes ago. */
    const watch = p.querySelector('#bs-watch');
    let lastSeen = null;
    watch.checked = watchOn();
    watch.onchange = async () => {
      if (watch.checked) {
        try { lastSeen = (await navigator.clipboard.readText() || '').trim(); }
        catch (e) {
          watch.checked = false;
          sub.innerHTML = '<b>Clipboard read refused.</b> Allow clipboard for sleeper.com, or use ⌥⇧V.';
          return;
        }
        sub.textContent = 'Watching. Copy in the dashboard, then come back to this tab.';
      }
      localStorage.setItem(LS_WATCH, watch.checked ? '1' : '0');
    };

    setInterval(async () => {
      if (!watchOn() || cdTimer || !document.hasFocus()) return;
      let t;
      try { t = (await navigator.clipboard.readText() || '').trim(); } catch (e) { return; }
      if (t === lastSeen) return;
      lastSeen = t;
      if (t && t !== staged && plausibleName(t)) stage(t, true);
    }, 700);

    // A bad learned selector beats a good heuristic and fails silently, so there
    // has to be a way back without opening devtools.
    p.querySelector('#bs-learn').oncontextmenu = (e) => {
      e.preventDefault();
      localStorage.removeItem(LS);
      sub.innerHTML = '<b>Forgot</b> the taught selectors — back to auto-detect.';
    };

    p.querySelector('#bs-dbg').onclick = () => {
      const n = dumpControls();
      sub.innerHTML = `Copied <b>${n}</b> controls to your clipboard — paste them to Claude. `
                    + '(Also in the console.)';
    };

    /* Learn mode. The selectors above are guesses about markup I cannot see —
       Sleeper's draft room is behind a login. Three clicks record the real ones. */
    p.querySelector('#bs-learn').onclick = () => {
      const steps = [
        ['search', 'Click the player SEARCH BOX in the draft room.'],
        ['draft', 'Now click the DRAFT button (do NOT confirm if it asks).'],
      ];
      let i = 0;
      const sel = load();
      sub.textContent = steps[0][1];
      const grab = (e) => {
        // Never learn our own UI. Clicking Debug during step 1 is exactly how
        // "#bs-dbg" got saved as the player search box and broke staging outright.
        if (mine(e.target)) return;
        e.preventDefault(); e.stopPropagation();

        /* Resolve what was clicked to something usable. You aim at a button and hit
           the <svg><path> inside it; you aim at a search field and hit its wrapper.
           Record the working element, not the pixel you happened to land on. */
        const kind = steps[i][0];
        let t = null;
        if (kind === 'search') {
          t = e.target.closest('input,textarea')
            || (e.target.closest('div,form,label') || document).querySelector('input,textarea');
          if (!usableInput(t)) { sub.innerHTML = '<b>That is not a text field.</b> Click the box you type player names into.'; return; }
        } else {
          t = e.target.closest(KNOWN_DRAFT) || e.target.closest(CLICKABLE)
            || (e.target.parentElement && e.target.parentElement.closest(CLICKABLE));
          if (!clickableEl(t)) { sub.innerHTML = '<b>That is not clickable.</b> Click the Draft button itself.'; return; }
        }

        sel[kind] = pathOf(t);
        // Only keep it if the saved path still finds the same element back.
        const back = document.querySelector(sel[kind]);
        if (back !== t) { delete sel[kind]; sub.innerHTML = '<b>Could not pin that down</b> — the heuristics will handle it.'; }
        say('learned', kind, sel[kind], '->', t.tagName);
        if (++i < steps.length) { sub.textContent = steps[i][1]; return; }
        removeEventListener('click', grab, true);
        save(sel); sub.innerHTML = '<b>Learned.</b> Paste a pick to try it.';
      };
      addEventListener('click', grab, true);
    };

    // ⌥⇧V anywhere on the page, so you never have to aim at the panel.
    addEventListener('keydown', (e) => {
      if (e.altKey && e.shiftKey && (e.key === 'v' || e.key === 'V')) {
        e.preventDefault(); p.querySelector('#bs-paste').click();
      }
    });

    say('ready — ⌥⇧V pastes the staged pick');
  }

  /* Match all of sleeper.com and decide HERE whether we are in a draft room.
     Matching /draft/* looked tidier but is a guess about their routing — mock
     drafts in particular may live somewhere else entirely, and a wrong @match
     fails as "nothing happens", which is the worst way for this to fail. So:
     broad match, narrow mount. */
  function inDraftRoom() {
    if (/draft|mock/i.test(location.pathname + location.hash)) return true;
    // Fallback for a route that says nothing: a player search plus something that
    // looks like a draft control on the same screen.
    return !!(findSearch() && findDraftButton(document));
  }

  function sync() {
    const here = inDraftRoom();
    const panelEl = document.getElementById('bs-panel');
    if (here && !panelEl) panel();
    if (!here && panelEl) panelEl.remove();
  }

  const boot = () => document.body ? sync() : setTimeout(boot, 400);
  boot();

  // SPA navigation changes the route without a reload, so re-check on both the
  // history calls and the DOM settling.
  for (const m of ['pushState', 'replaceState']) {
    const orig = history[m];
    history[m] = function () { const r = orig.apply(this, arguments); setTimeout(sync, 250); return r; };
  }
  addEventListener('popstate', () => setTimeout(sync, 250));
  let t = 0;
  new MutationObserver(() => { clearTimeout(t); t = setTimeout(sync, 300); })
    .observe(document.documentElement, { childList: true, subtree: true });

  // Escape hatch: if detection is wrong, run __bs() in the console to force it.
  window.__bs = panel;
  say('loaded on', location.pathname, '— draft room detected:', inDraftRoom());
})();
