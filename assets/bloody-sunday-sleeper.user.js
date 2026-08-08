// ==UserScript==
// @name         Bloody Sunday — draft on Sleeper
// @namespace    https://github.com/fabfreebird23/draft-dashboard
// @version      1.0.0
// @description  Take the player you picked in Bloody Sunday and stage him in the Sleeper draft room, so you never type a name mid-draft.
// @match        https://sleeper.com/draft/*
// @match        https://sleeper.app/draft/*
// @match        https://www.sleeper.com/draft/*
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
  const say = (...a) => console.log('%c[Bloody Sunday]', 'color:#ff336c;font-weight:700', ...a);

  const load = () => { try { return JSON.parse(localStorage.getItem(LS)) || {}; } catch (e) { return {}; } };
  const save = (s) => localStorage.setItem(LS, JSON.stringify(s));
  const autoOn = () => localStorage.getItem(LS_AUTO) === '1';

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

  /* The search box. Learned selector first, then heuristics, because a draft room
     usually has exactly one visible text input and it is the player filter. */
  function findSearch() {
    const s = load().search;
    if (s) { const el = document.querySelector(s); if (vis(el)) return el; }
    const cands = [...document.querySelectorAll('input[type="text"], input:not([type]), input[type="search"]')]
      .filter(vis)
      .filter(i => /search|player|find/i.test((i.placeholder || '') + ' ' + (i.getAttribute('aria-label') || '')));
    return cands[0] || [...document.querySelectorAll('input')].filter(vis)[0] || null;
  }

  /* React inputs ignore `el.value = x` — the framework owns the value and will
     overwrite it on the next render. Set through the native setter and dispatch
     a bubbling input event so React's onChange actually runs. */
  function setInput(el, text) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
    setter.call(el, text);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
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
      if (!el || !vis(el)) continue;
      const len = (el.innerText || '').length;
      if (len < bestLen) { best = el; bestLen = len; }
    }
    return best;
  }

  function findDraftButton(scope) {
    const s = load().draft;
    if (s) { const el = document.querySelector(s); if (vis(el)) return el; }
    const all = [...(scope || document).querySelectorAll('button, [role="button"], div[class*="button" i]')];
    return all.filter(vis).find(b => /^(draft|select|pick|draft player)$/i.test((b.innerText || '').trim())) || null;
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
  .bs-hit{outline:3px solid #ff336c !important;outline-offset:2px;
    border-radius:6px;scroll-margin:120px}`;

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
          <button id="bs-learn">Teach it</button>
        </div>
        <label class="tog"><input type="checkbox" id="bs-auto"> auto-click Draft
          <span class="warn" id="bs-autow"></span></label>
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

    function stage(name) {
      staged = name;
      who.textContent = name || 'Nothing staged';
      const box = findSearch();
      if (box) { box.focus(); setInput(box, name); }
      // Sleeper filters asynchronously; give the list a beat to re-render.
      setTimeout(() => {
        document.querySelectorAll('.bs-hit').forEach(e => e.classList.remove('bs-hit'));
        const row = findRow(name);
        if (!row) {
          sub.innerHTML = box
            ? 'Search filled — <b>could not spot the row</b>. Pick him in the list.'
            : '<b>No search box found.</b> Use “Teach it”.';
          return;
        }
        row.classList.add('bs-hit');
        row.scrollIntoView({ block: 'center', behavior: 'smooth' });
        if (autoOn()) {
          const b = findDraftButton(row) || findDraftButton(document);
          if (b) { sub.innerHTML = 'Auto-drafting…'; b.click(); return; }
          sub.innerHTML = 'Found him — <b>no Draft button</b>. Click it yourself.';
          return;
        }
        sub.innerHTML = 'Found and highlighted. <b>You</b> press Draft.';
      }, 420);
    }

    p.querySelector('#bs-paste').onclick = async () => {
      const t = await readClip();
      if (!t) { sub.textContent = 'Clipboard was empty.'; return; }
      if (t.length > 60) { sub.textContent = 'That does not look like a name.'; return; }
      stage(t);
    };
    p.querySelector('#bs-again').onclick = () => staged ? stage(staged) : (sub.textContent = 'Nothing staged yet.');

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
        e.preventDefault(); e.stopPropagation();
        sel[steps[i][0]] = pathOf(e.target);
        say('learned', steps[i][0], sel[steps[i][0]]);
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

  // The draft room is a SPA; the body it mounts may arrive after this script does.
  const boot = () => document.body ? panel() : setTimeout(boot, 400);
  boot();
  new MutationObserver(() => { if (!document.getElementById('bs-panel')) panel(); })
    .observe(document.documentElement, { childList: true, subtree: true });
})();
