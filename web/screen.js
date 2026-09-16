/* The projector. Renders GameState, runs the ECG, and owns the flatline. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var code = new URLSearchParams(location.search).get('c');
  var state = null;
  var ecg = new Ecg($('ecg'));
  var ws = null;
  var running = false;
  var raf = null;

  /* Clock arrives at 1Hz but renders at 60fps, so it is interpolated locally.
     A clock that stutters is very visible on a projector. */
  var clockBase = null, clockAt = 0;

  var spokenUpto = 0;
  var flatlined = false;

  /* ------------------------------------------------------------- audio */
  var audio = null, osc = null, gain = null;

  function ensureAudio() {
    if (audio) return;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    audio = new AC();
  }

  function startTone() {
    ensureAudio();
    if (!audio || osc) return;
    if (audio.state === 'suspended') audio.resume();
    osc = audio.createOscillator();
    gain = audio.createGain();
    osc.type = 'sine';
    osc.frequency.value = 989;
    /* Ramp in over 25ms so it does not click. */
    gain.gain.setValueAtTime(0.0001, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.16, audio.currentTime + 0.025);
    osc.connect(gain);
    gain.connect(audio.destination);
    osc.start();
  }

  function stopTone() {
    if (!osc || !audio) return;
    var t = audio.currentTime;
    gain.gain.cancelScheduledValues(t);
    gain.gain.setValueAtTime(gain.gain.value, t);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.04);
    osc.stop(t + 0.06);
    osc = null;
    gain = null;
  }

  /* --------------------------------------------------------------- tts */
  function speak(text) {
    if (!window.speechSynthesis) return;
    try {
      var u = new SpeechSynthesisUtterance(text);
      u.rate = 0.97;
      u.pitch = 0.85;
      window.speechSynthesis.speak(u);
    } catch (e) { /* speech is a bonus, never a dependency */ }
  }

  /* ------------------------------------------------------------ render */
  function fmtClock(s) {
    s = Math.max(0, Math.floor(s));
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  function renderState(s) {
    $('patient').innerHTML = s.patient_name +
      '<span>' + s.patient_age + '</span>';

    $('vHr').innerHTML = s.vitals.hr + '<small>bpm</small>';
    $('vSpo2').innerHTML = s.vitals.spo2 + '<small>%</small>';
    $('vBp').innerHTML = s.vitals.bp + '<small>mmHg</small>';
    $('vRr').innerHTML = s.vitals.rr + '<small>/min</small>';

    var cls = 'val num status-' + s.status;
    $('vHr').className = cls;
    $('vSpo2').className = cls;
    $('clock').className = 'num status-' + s.status;

    ecg.set(s.vitals.hr, s.status);

    var feed = $('feed');
    feed.innerHTML = '';
    s.messages.slice(-9).forEach(function (m) {
      var d = document.createElement('div');
      d.className = 'msg ' + m.kind;
      d.innerHTML = '<span class="who">' + esc(m.who) + '</span>' + esc(m.text);
      feed.appendChild(d);
    });

    var board = $('board');
    board.innerHTML = '';
    s.players.forEach(function (p) {
      var d = document.createElement('div');
      d.className = 'row';
      d.innerHTML = '<span class="nm">' + esc(p.name) + '</span>' +
                    '<span class="sc num">' + p.score + '</span>';
      board.appendChild(d);
    });

    /* Speak only what is new, so a reconnect does not replay the round. */
    for (var i = spokenUpto; i < s.messages.length; i++) {
      if (s.messages[i].kind === 'reply') speak(s.messages[i].text);
    }
    spokenUpto = s.messages.length;

    if (s.phase === 'flatline' && !flatlined) runFlatline();
    if (s.phase === 'reveal' && s.reveal) showReveal(s.reveal);
  }

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* -------------------------------------------------------- the moment */
  function runFlatline() {
    flatlined = true;

    /* 1. the trace flattens where it stands, mid-beat */
    ecg.kill();
    ecg.draw();

    /* 2. one continuous tone */
    startTone();

    /* 3. colour drains from the whole page over 1.2s */
    $('page').classList.add('draining');

    setTimeout(function () {
      /* 4. two full seconds of nothing. No text, no animation, no sound.
            The rAF loop is cancelled so literally nothing moves. */
      stopTone();
      $('page').classList.add('blank');
      $('overlay').classList.add('show');
      running = false;
      if (raf) { cancelAnimationFrame(raf); raf = null; }

      setTimeout(function () {
        /* 5. the reveal */
        fetch('/api/' + code + '/reveal', { method: 'POST' });
      }, 2000);
    }, 1200);
  }

  function showReveal(r) {
    $('overlay').classList.remove('show');
    $('revealHead').textContent = r.headline;
    $('revealDx').textContent = r.diagnosis;
    $('revealWho').textContent = r.winners.length
      ? 'Called it: ' + r.winners.join(', ')
      : 'Nobody called it.';
    var box = $('revealScores');
    box.innerHTML = '';
    r.scores.forEach(function (p) {
      var d = document.createElement('div');
      d.className = 'row';
      d.innerHTML = '<span class="nm">' + esc(p.name) + '</span>' +
                    '<span class="sc num">' + p.score + '</span>';
      box.appendChild(d);
    });
    $('reveal').classList.add('show');
  }

  /* ------------------------------------------------------------- loop */
  function frame(now) {
    if (!running) return;
    ecg.frame(now);
    if (clockBase !== null) {
      var left = clockBase - (now - clockAt) / 1000;
      $('clock').textContent = fmtClock(left);
    }
    raf = requestAnimationFrame(frame);
  }

  function startLoop() {
    if (running) return;
    running = true;
    raf = requestAnimationFrame(frame);
  }

  /* --------------------------------------------------------- transport */
  function connect() {
    var proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(proto + '://' + location.host + '/ws/' + code);
    ws.onmessage = function (ev) {
      state = JSON.parse(ev.data);
      clockBase = state.seconds_left;
      clockAt = performance.now();
      renderState(state);
    };
    ws.onclose = function () { setTimeout(connect, 1200); };
  }

  function showJoin() {
    var url = location.protocol + '//' + location.host + '/play?c=' + code;
    $('code').textContent = code;
    $('joinUrl').textContent = url;
    $('qr').src = '/api/' + code + '/qr.svg';
  }

  /* ------------------------------------------------------------ inputs */
  function send(path, text) {
    return fetch('/api/' + code + '/' + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Room', text: text })
    });
  }

  $('askBtn').onclick = function () {
    var v = $('ask').value.trim();
    if (v) { send('ask', v); $('ask').value = ''; }
  };
  $('guessBtn').onclick = function () {
    var v = $('ask').value.trim();
    if (v) { send('guess', v); $('ask').value = ''; }
  };
  $('ask').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') $('askBtn').click();
  });

  /* Debug: K flatlines on demand, R resets. Gate 3 asks for the sequence to
     land ten times in a row, which should not mean ten full rounds. */
  document.addEventListener('keydown', function (e) {
    if (document.activeElement === $('ask')) return;
    if (e.key === 'k' || e.key === 'K') fetch('/api/' + code + '/kill', { method: 'POST' });
    if (e.key === 'r' || e.key === 'R') location.reload();
  });

  /* ------------------------------------------------------------- start */
  $('begin').onclick = function () {
    ensureAudio();                     /* the gesture that unblocks audio */
    if (audio && audio.state === 'suspended') audio.resume();
    $('title').classList.add('hide');
    fetch('/api/' + code + '/start', { method: 'POST' });
    startLoop();
  };

  (function init() {
    if (!code) {
      fetch('/api/room', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
        .then(function (r) { return r.json(); })
        .then(function (d) { location.search = '?c=' + d.code; });
      return;
    }
    code = code.toUpperCase();
    showJoin();
    connect();
    ecg.frame(performance.now());
  })();
})();
