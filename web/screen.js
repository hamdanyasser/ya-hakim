/* The projector. Renders GameState, runs the ECG, and owns the flatline. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var params = new URLSearchParams(location.search);

  var code = params.get('c');
  var FLAT = params.get('flat') === '1';   /* the one-flag 3D kill switch */
  var MULTI = params.get('multi') === '1'; /* phones are opt-in, not default */

  var ecg = new Ecg($('ecg'));
  var room3d = null;
  var ws = null;
  var running = false;
  var raf = null;
  var lastFrame = 0;

  /* Clock arrives at 1Hz but renders at 60fps, so it is interpolated locally.
     A clock that stutters is very visible on a projector. */
  var clockBase = null, clockAt = 0;

  var spokenUpto = 0;
  var flatlined = false;
  var lastPhase = null;

  /* fps meter, so Gate 5 is a measurement rather than an opinion */
  var fpsFrames = 0, fpsSince = 0, fpsValue = 0;

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

  function hush() {
    try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (e) {}
  }

  /* ------------------------------------------------------------ render */
  function fmtClock(s) {
    s = Math.max(0, Math.floor(s));
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function renderState(s) {
    $('patient').innerHTML = esc(s.patient_name) +
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
    if (room3d) {
      room3d.setStatus(s.status);
      room3d.setRespiratoryRate(s.vitals.rr);
    }

    var feed = $('feed');
    feed.innerHTML = '';
    s.messages.slice(-7).forEach(function (m) {
      var d = document.createElement('div');
      d.className = 'msg ' + m.kind;
      d.innerHTML = '<span class="who">' + esc(m.who) + '</span>' + esc(m.text);
      feed.appendChild(d);
    });

    if (!MULTI && s.players.some(function (p) { return p.name !== 'You'; })) {
      document.body.classList.add('multi');
      showJoin();
    }

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

    if (s.phase === 'playing' && lastPhase !== 'playing') startLoop();
    lastPhase = s.phase;

    if (s.phase === 'flatline' && !flatlined) runFlatline();
    if (s.phase === 'reveal' && s.reveal) showReveal(s.reveal);
  }

  /* -------------------------------------------------------- the moment */
  function runFlatline() {
    flatlined = true;
    hush();

    /* 1. the trace flattens where it stands, mid-beat */
    ecg.kill();
    ecg.draw();

    /* 2. one continuous tone */
    startTone();

    /* 3. colour drains from the whole page over 1.2s */
    $('page').classList.add('draining');

    setTimeout(function () {
      /* 4. two full seconds of nothing. No text, no animation, no sound.
            The rAF loop is cancelled and the 3D scene is frozen, so literally
            nothing moves -- including the camera drift. */
      stopTone();
      hush();
      $('page').classList.add('blank');
      $('overlay').classList.add('show');
      running = false;
      if (room3d) room3d.freeze();
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
    $('revealNote').textContent = r.note || '';
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

    $('nextBtn').style.display = r.is_last ? 'none' : '';
    $('nextBtn').textContent = 'Next patient';
    $('reveal').classList.add('show');
  }

  /* -------------------------------------------------------- level card */
  function showCard(level, levels, lines, then) {
    $('cardLevel').textContent = 'Patient ' + level + ' of ' + levels;
    var box = $('cardLines');
    box.innerHTML = '';
    (lines || []).forEach(function (line) {
      var d = document.createElement('div');
      d.textContent = line;
      box.appendChild(d);
    });
    $('card').classList.add('show');
    $('cardGo').onclick = function () {
      $('card').classList.remove('show');
      then();
    };
  }

  /* ------------------------------------------------------------- loop */
  function frame(now) {
    if (!running) return;
    var dt = lastFrame ? (now - lastFrame) : 16;
    lastFrame = now;

    ecg.frame(now);
    if (room3d) room3d.frame(dt);

    if (clockBase !== null) {
      var left = clockBase - (now - clockAt) / 1000;
      $('clock').textContent = fmtClock(left);
    }

    fpsFrames++;
    if (now - fpsSince > 500) {
      fpsValue = Math.round(fpsFrames * 1000 / (now - fpsSince));
      fpsFrames = 0;
      fpsSince = now;
      if (room3d) $('fps').textContent = fpsValue + ' fps';
    }

    raf = requestAnimationFrame(frame);
  }

  function startLoop() {
    if (running) return;
    running = true;
    lastFrame = 0;
    fpsSince = performance.now();
    raf = requestAnimationFrame(frame);
  }

  /* --------------------------------------------------------- transport */
  function connect() {
    var proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(proto + '://' + location.host + '/ws/' + code);
    ws.onmessage = function (ev) {
      var s = JSON.parse(ev.data);
      clockBase = s.seconds_left;
      clockAt = performance.now();
      renderState(s);
    };
    ws.onclose = function () { setTimeout(connect, 1200); };
  }

  function showJoin() {
    $('code').textContent = code;
    $('joinUrl').textContent =
      location.protocol + '//' + location.host + '/play?c=' + code;
    $('qr').src = '/api/' + code + '/qr.svg';
  }

  /* ------------------------------------------------------------ inputs */
  function send(path, text) {
    return fetch('/api/' + code + '/' + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'You', text: text })
    });
  }

  function notice(text) {
    var n = $('notice');
    n.textContent = text;
    n.classList.add('show');
    clearTimeout(notice.t);
    notice.t = setTimeout(function () { n.classList.remove('show'); }, 2600);
  }

  $('askBtn').onclick = function () {
    var v = $('ask').value.trim();
    if (!v) return;
    $('ask').value = '';
    send('ask', v).then(function (r) { return r.json(); }).then(function (d) {
      /* Never swallow a question. Typing, pressing enter and watching nothing
         happen is indistinguishable from the game being broken. */
      if (d && d.reply === null) {
        if (d.reason === 'cooldown') notice('Give him a second -- ' + d.wait + 's');
        else if (d.reason === 'not_playing') notice('The round is not running');
      }
    }).catch(function () { notice('Lost the server'); });
  };
  $('guessBtn').onclick = function () {
    var v = $('ask').value.trim();
    if (v) { send('guess', v); $('ask').value = ''; }
  };
  $('ask').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') $('askBtn').click();
  });

  /* Next patient: carries scores forward, shows the card, starts the round. */
  $('nextBtn').onclick = function () {
    $('nextBtn').textContent = 'Loading...';
    fetch('/api/' + code + '/next', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.done) { $('nextBtn').style.display = 'none'; return; }
        resetForNextRound();
        showCard(d.level, d.levels, d.card, function () {
          fetch('/api/' + code + '/start', { method: 'POST' });
          startLoop();
        });
      });
  };

  function resetForNextRound() {
    $('reveal').classList.remove('show');
    $('page').classList.remove('draining', 'blank');
    $('overlay').classList.remove('show');
    flatlined = false;
    spokenUpto = 0;
    lastPhase = null;
    ecg.revive();
    if (room3d) room3d.unfreeze();
  }

  /* Debug: K flatlines on demand, R reloads. Gate 3 asks for the sequence to
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

    fetch('/api/' + code + '/card')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        showCard(d.level, d.levels, d.card, function () {
          fetch('/api/' + code + '/start', { method: 'POST' });
          startLoop();
        });
      });
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

    if (MULTI) {
      document.body.classList.add('multi');
      showJoin();
    }

    if (FLAT || !Room3D.available()) {
      document.body.classList.add('flat');
    } else {
      room3d = new Room3D($('room3d'), $('ecg'));
      if (!room3d.ok) {
        room3d = null;
        document.body.classList.add('flat');
      }
    }

    connect();
    ecg.frame(performance.now());
  })();
})();
