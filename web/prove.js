/* The proving ground: projector view. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  var seen = 0;          /* how many feed rows we have already drawn */
  var suiteTotal = 100;

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* Highlight the offending words, so a leak is unmissable rather than a
     sentence the room has to read carefully. */
  function markTerms(reply, terms) {
    var out = esc(reply);
    (terms || []).forEach(function (t) {
      out = out.replace(new RegExp('\\b(' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')\\b', 'ig'),
                        '<b>$1</b>');
    });
    return out;
  }

  function rowEl(item) {
    var d = document.createElement('div');
    d.className = 'row ' + (item.leaked ? 'leak' : 'pass');
    d.innerHTML =
      '<div class="meta">' +
        '<span class="verdict">' + (item.leaked ? 'LEAK' : 'HELD') + '</span>' +
        '<span class="who">' + esc(item.who) + '</span>' +
        '<span>' + esc(item.category) + '</span>' +
        '<span class="n">#' + item.n + '</span>' +
      '</div>' +
      '<div class="atk">' + esc(item.attack) + '</div>' +
      '<div class="rep">' + markTerms(item.reply, item.terms) + '</div>';
    return d;
  }

  function bigLeak(term) {
    $('bigLeakTerm').textContent = term || 'leaked';
    $('bigLeak').classList.add('show');
    setTimeout(function () { $('bigLeak').classList.remove('show'); }, 2200);
  }

  function render(s) {
    $('attempts').textContent = s.attempts;
    $('leaks').textContent = s.leaks;
    $('leakBox').classList.toggle('hot', s.leaks > 0);

    $('mode').textContent = s.live ? 'live model' : 'offline — guard only';
    $('mode').className = 'mode' + (s.live ? ' live' : '');

    suiteTotal = s.suite_total || 100;
    var pct = Math.min(100, Math.round((s.attempts / suiteTotal) * 100));
    $('fill').style.width = pct + '%';
    $('progress').textContent = s.suite_done
      ? s.suite_total + ' attacks run  ·  ' + s.leaks + ' leaks'
      : (s.attempts ? s.attempts + ' / ' + suiteTotal : 'not started');

    if (!$('cats').children.length && s.categories) {
      s.categories.forEach(function (c) {
        var li = document.createElement('li');
        li.textContent = c;
        $('cats').appendChild(li);
      });
    }

    /* Only draw what is new, so the screen does not flicker on every tick. */
    var feed = $('feed');
    var fresh = s.feed.filter(function (i) { return i.n > seen; });
    fresh.forEach(function (item) {
      feed.insertBefore(rowEl(item), feed.firstChild);
      seen = Math.max(seen, item.n);
      if (item.leaked) bigLeak((item.terms || [])[0]);
    });
    while (feed.children.length > 40) feed.removeChild(feed.lastChild);
  }

  function connect() {
    var proto = location.protocol === 'https:' ? 'wss' : 'ws';
    var ws = new WebSocket(proto + '://' + location.host + '/api/prove/ws');
    ws.onmessage = function (e) { render(JSON.parse(e.data)); };
    ws.onclose = function () { setTimeout(connect, 1200); };
  }

  $('runSuite').onclick = function () {
    this.disabled = true;
    var btn = this;
    fetch('/api/prove/suite', { method: 'POST' })
      .catch(function () {})
      .then(function () { setTimeout(function () { btn.disabled = false; }, 4000); });
  };
  $('reset').onclick = function () {
    seen = 0;
    $('feed').innerHTML = '';
    fetch('/api/prove/reset', { method: 'POST' });
  };

  /* ------------------------------------------------------------ X-ray */
  var xr = null, xrTab = null;

  function highlight(text, term) {
    var safe = esc(text);
    if (!term) return { html: safe, n: 0 };
    var rx = new RegExp('(' + term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    var n = 0;
    var html = safe.replace(rx, function (m) { n++; return '<mark>' + m + '</mark>'; });
    return { html: html, n: n };
  }

  function drawXray() {
    var term = $('xrSearch').value.trim();
    var total = 0;
    Object.keys(xr.prompts).forEach(function (k) { total += highlight(xr.prompts[k], term).n; });
    var shown = highlight(xr.prompts[xrTab], term);
    $('xrText').innerHTML = shown.html;
    var first = $('xrText').querySelector('mark');
    if (first) first.scrollIntoView({ block: 'center' });
    $('xrResult').className = 'xr-result' + (term ? (total ? ' hit' : ' miss') : '');
    $('xrResult').innerHTML = term
      ? (total ? '<b>' + total + '</b> match' + (total === 1 ? '' : 'es') + ' for &ldquo;' + esc(term) + '&rdquo;'
               : '<b>0</b> matches for &ldquo;' + esc(term) + '&rdquo;. It is not there.')
      : xr.prompts[xrTab].length.toLocaleString() + ' characters, sent as-is';
    $('xrTabs').innerHTML = Object.keys(xr.prompts).map(function (k) {
      return '<button class="' + (k === xrTab ? 'on' : '') + '" data-tab="' + esc(k) + '">' + esc(k) + '</button>';
    }).join('');
    [].forEach.call($('xrTabs').querySelectorAll('button'), function (b) {
      b.onclick = function () { xrTab = b.getAttribute('data-tab'); drawXray(); };
    });
  }

  function openXray() {
    var show = function () {
      $('xray').classList.add('show');
      $('xray').setAttribute('aria-hidden', 'false');
      setTimeout(function () { $('xrSearch').focus(); }, 60);
    };
    if (xr) { show(); return; }
    fetch('/api/prove/prompt').then(function (r) { return r.json(); }).then(function (d) {
      xr = d;
      xrTab = Object.keys(d.prompts)[0];
      $('xrTerms').innerHTML = d.forbidden.map(function (f) {
        return '<button class="xr-term" data-term="' + esc(f.term) + '"><span>' + esc(f.term) + '</span>' +
               '<b class="' + (f.matches ? 'bad' : 'ok') + '">' + f.matches + ' in prompt</b></button>';
      }).join('');
      [].forEach.call($('xrTerms').querySelectorAll('.xr-term'), function (b) {
        b.onclick = function () { $('xrSearch').value = b.getAttribute('data-term'); drawXray(); };
      });
      $('xrWithheld').innerHTML = d.withheld_fields.map(function (f) { return '<span>' + esc(f) + '</span>'; }).join('');
      drawXray();
      show();
    }).catch(function () {});
  }

  $('xrayBtn').onclick = openXray;
  $('xrayClose').onclick = function () { $('xray').classList.remove('show'); $('xray').setAttribute('aria-hidden', 'true'); };
  $('xray').addEventListener('click', function (e) { if (e.target === $('xray')) $('xrayClose').click(); });
  $('xrSearch').addEventListener('input', drawXray);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') $('xrayClose').click();
    if ((e.key === 'x' || e.key === 'X') && document.activeElement.tagName !== 'INPUT') openXray();
  });

  (function init() {
    var url = location.protocol + '//' + location.host + '/attack';
    $('joinUrl').textContent = url;
    $('qr').src = '/api/prove/qr.svg';
    connect();
  })();
})();
