/* The phone. Join, ask, guess. Nothing clever on purpose. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var COOLDOWN = 8000;

  var code = (new URLSearchParams(location.search).get('c') || '').toUpperCase();
  var name = '';
  var ws = null;
  var lastAsk = 0;
  var guessed = false;

  if (code) $('code').value = code;
  try { $('name').value = localStorage.getItem('yh_name') || ''; } catch (e) {}

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function connect() {
    var proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(proto + '://' + location.host + '/ws/' + code);
    ws.onopen = function () { $('status').textContent = 'connected'; };
    ws.onmessage = function (ev) { render(JSON.parse(ev.data)); };
    ws.onclose = function () {
      $('status').textContent = 'reconnecting';
      setTimeout(connect, 1200);
    };
  }

  function render(s) {
    $('who').textContent = s.patient_name + ', ' + s.patient_age;

    if (s.phase === 'reveal' && s.reveal) {
      $('status').textContent = s.reveal.headline + ' ' + s.reveal.diagnosis;
    } else if (s.phase === 'flatline') {
      $('status').textContent = 'he is gone';
    } else if (s.phase === 'lobby') {
      $('status').textContent = 'waiting to start';
    } else {
      $('status').textContent = s.seconds_left + 's left  ' +
        s.vitals.hr + 'bpm  ' + s.status;
    }

    var log = $('log');
    log.innerHTML = '';
    s.messages.slice(-14).forEach(function (m) {
      var d = document.createElement('div');
      d.className = 'm ' + m.kind;
      d.innerHTML = '<span class="w">' + esc(m.who) + '</span>' + esc(m.text);
      log.appendChild(d);
    });
    log.scrollTop = log.scrollHeight;

    var over = s.phase === 'flatline' || s.phase === 'reveal';
    $('askBtn').disabled = over;
    $('guessBtn').disabled = over || guessed;
  }

  function post(path, text) {
    return fetch('/api/' + code + '/' + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, text: text })
    });
  }

  /* One question per 8 seconds. Enforced server-side too; this is only so the
     phone can say why the button went quiet. */
  function cooldown() {
    var btn = $('askBtn');
    btn.disabled = true;
    var left = Math.ceil(COOLDOWN / 1000);
    btn.textContent = 'Wait ' + left + 's';
    var iv = setInterval(function () {
      left--;
      if (left <= 0) {
        clearInterval(iv);
        btn.disabled = false;
        btn.textContent = 'Ask';
      } else {
        btn.textContent = 'Wait ' + left + 's';
      }
    }, 1000);
  }

  $('joinBtn').onclick = function () {
    code = ($('code').value || '').trim().toUpperCase();
    name = ($('name').value || '').trim() || 'Doctor';
    if (code.length !== 4) { $('code').focus(); return; }
    try { localStorage.setItem('yh_name', name); } catch (e) {}
    $('join').classList.add('hide');
    $('game').classList.remove('hide');
    post('join', '');          /* registers the player without saying anything */
    connect();
  };

  $('askBtn').onclick = function () {
    var v = $('text').value.trim();
    if (!v) return;
    if (Date.now() - lastAsk < COOLDOWN) return;
    lastAsk = Date.now();
    post('ask', v);
    $('text').value = '';
    cooldown();
  };

  $('guessBtn').onclick = function () {
    var v = $('text').value.trim();
    if (!v || guessed) return;
    guessed = true;
    $('guessBtn').disabled = true;
    post('guess', v);
    $('text').value = '';
  };

  $('text').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') $('askBtn').click();
  });
})();
