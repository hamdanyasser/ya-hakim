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
  var lastPhase = null;

  /* Same small vocabulary as screen.js's MOOD_META -- see the comment there.
     No build step in this project, so this is duplicated, not imported. */
  var MOOD_LABEL = {
    guarded: '🛡 guarded', uneasy: '😕 uneasy',
    defensive: '✋ defensive', resigned: '😔 resigned',
    rattled: '😬 rattled', scared: '😨 scared',
    pleading: '🙏 pleading'
  };

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
    ws.onclose = function (ev) {
      if (ev.code === 4404) {
        /* The room is gone (the server restarted, or the round was cleared).
           Keep trying slowly: the projector brings it back when it reconnects. */
        $('status').textContent = 'waiting for the projector';
        setTimeout(connect, 4000);
        return;
      }
      $('status').textContent = 'reconnecting';
      setTimeout(connect, 1200);
    };
  }

  function render(s) {
    $('who').textContent = s.patient_name + ', ' + s.patient_age;
    $('patientSub').textContent = s.description || '';

    if (s.phase === 'reveal' && s.reveal) {
      var mine = (s.reveal.awards || []).filter(function (a) { return a.who === name; })
        .map(function (a) { return a.title; });
      $('status').textContent = s.reveal.headline + ' ' + s.reveal.diagnosis +
        (mine.length ? '  \u2605 You: ' + mine.join(', ') : '');
    } else if (s.phase === 'flatline') {
      $('status').textContent = 'he is gone';
    } else if (s.phase === 'lobby') {
      $('status').textContent = 'waiting to start';
    } else {
      $('status').textContent = s.seconds_left + 's left  ' +
        s.vitals.hr + 'bpm  ' + s.status +
        (MOOD_LABEL[s.mood] ? '  ' + MOOD_LABEL[s.mood] : '');
    }

    /* The jolt, felt in the hand: a hard red wash the instant he flatlines.
       Only on the transition, so a reconnect mid-flatline does not re-flash. */
    if (s.phase === 'flatline' && lastPhase !== 'flatline') {
      document.body.classList.add('flashRed');
      setTimeout(function () { document.body.classList.remove('flashRed'); }, 900);
    }
    lastPhase = s.phase;

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

  function joinError(text) {
    var el = $('joinErr');
    el.textContent = text;
    el.classList.remove('hide');
  }

  $('joinBtn').onclick = function () {
    code = ($('code').value || '').trim().toUpperCase();
    name = ($('name').value || '').trim() || 'Doctor';
    if (code.length !== 4) { $('code').focus(); return; }
    try { localStorage.setItem('yh_name', name); } catch (e) {}
    var btn = $('joinBtn');
    btn.disabled = true;
    $('joinErr').classList.add('hide');
    /* Register the player without saying anything, and only then open the
       game -- a mistyped code used to drop you on a screen that reconnected
       forever to a room that did not exist. */
    post('join', '').then(function (r) {
      if (r.status === 404) { joinError('No room with that code. Check the projector.'); return; }
      if (!r.ok) { joinError('Could not join right now. Try again.'); return; }
      $('join').classList.add('hide');
      $('game').classList.remove('hide');
      connect();
    }).catch(function () {
      joinError('Could not reach the server.');
    }).then(function () { btn.disabled = false; });
  };

  $('askBtn').onclick = function () {
    var v = $('text').value.trim();
    if (!v) return;
    if (Date.now() - lastAsk < COOLDOWN) return;
    lastAsk = Date.now();
    $('text').value = '';
    cooldown();
    post('ask', v).then(function (r) { return r.json(); }).then(function (d) {
      /* Never swallow a question: say why it did not land. */
      if (d && d.reply === null) {
        if (d.reason === 'cooldown') $('status').textContent = 'too fast -- wait ' + d.wait + 's';
        else if (d.reason === 'not_playing') $('status').textContent = 'the round is not running';
        $('text').value = v;
      }
    }).catch(function () { $('status').textContent = 'lost the server'; $('text').value = v; });
  };

  $('guessBtn').onclick = function () {
    var v = $('text').value.trim();
    if (!v || guessed) return;
    guessed = true;
    $('guessBtn').disabled = true;
    $('text').value = '';
    post('guess', v).then(function (r) {
      if (!r.ok) throw new Error('guess failed');
    }).catch(function () {
      /* The guess never reached the server, so it has not been used up. */
      guessed = false;
      $('guessBtn').disabled = false;
      $('text').value = v;
      $('status').textContent = 'lost the server -- try again';
    });
  };

  $('text').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') $('askBtn').click();
  });
  /* Talk instead of type: what you say is sent as your question. */
  Voice.attach($('micBtn'), $('text'), function () { $('askBtn').click(); });
})();
