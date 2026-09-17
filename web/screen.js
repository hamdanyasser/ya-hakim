/* The projector. Renders GameState, runs the ECG, and owns the flatline. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var params = new URLSearchParams(location.search);

  var code = params.get('c');
  var FLAT = params.get('flat') === '1';   /* the one-flag 3D kill switch */
  var MULTI = params.get('multi') === '1'; /* phones are opt-in, not default */
  var DEMO_MODE = params.get('demo') === '1';

  var ecg = new Ecg($('ecg'));
  ecg.onBeat = function () { beep(); };
  var room3d = null;
  var ws = null;
  var running = false;
  var raf = null;
  var lastFrame = 0;

  /* Clock arrives at 1Hz but renders at 60fps, so it is interpolated locally.
     A clock that stutters is very visible on a projector. */
  var clockBase = null, clockAt = 0;

  var spokenUpto = 0;
  var lastFeedSig = null, feedSeen = 0, lastSub = null;
  var flatlined = false;
  var lastPhase = null;

  /* Mirrors engine/mood.py's MOODS dict. Python owns the logic that picks a
     mood; this is presentation only, the same split the project already uses
     for status colours (engine picks stable/declining/critical, CSS owns what
     that looks like). "flatline" has no entry on purpose -- once he is gone,
     the overlay and the reveal own the screen and the mood line is moot. */
  var MOOD_META = {
    guarded:   { icon: '🛡', label: 'Guarded',   tier: 'dim' },
    uneasy:    { icon: '😕', label: 'Uneasy',    tier: 'dim' },
    defensive: { icon: '✋',       label: 'Defensive', tier: 'warn' },
    resigned:  { icon: '😔', label: 'Resigned',  tier: 'warn' },
    rattled:   { icon: '😬', label: 'Rattled',   tier: 'bad' },
    scared:    { icon: '😨', label: 'Scared',    tier: 'bad' },
    pleading:  { icon: '🙏', label: 'Pleading',  tier: 'bad' }
  };

  /* fps meter, so Gate 5 is a measurement rather than an opinion */
  var fpsFrames = 0, fpsSince = 0, fpsValue = 0;
  var lastHr = null, tellTimer = null;

  function flagTell() {
    var card = $('vHr').closest('.vital');
    if (!card) return;
    card.classList.remove('tell');
    void card.offsetWidth;          /* restart the animation */
    card.classList.add('tell');
    clearTimeout(tellTimer);
    tellTimer = setTimeout(function () { card.classList.remove('tell'); }, 5200);
  }

  /* ------------------------------------------------------------- audio */
  var audio = null, osc = null, gain = null;
  var muted = false;

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

  /* The jolt at the top of the flatline sequence -- three sharp beeps before
     the long continuous tone. This is the "scary" part; the tone that follows
     is the "held breath" part. Independent of startTone/stopTone so it can
     never leave a stray oscillator behind if the sequence is interrupted. */
  function alarmBeeps(n, freq) {
    ensureAudio();
    if (!audio) return;
    if (audio.state === 'suspended') audio.resume();
    var i = 0;
    (function beep() {
      if (i >= n) return;
      i++;
      var o = audio.createOscillator();
      var g = audio.createGain();
      o.type = 'square';
      o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, audio.currentTime);
      g.gain.exponentialRampToValueAtTime(0.22, audio.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.16);
      o.connect(g);
      g.connect(audio.destination);
      o.start();
      o.stop(audio.currentTime + 0.18);
      setTimeout(beep, 220);
    })();
  }

  /* ------------------------------------------------------- the monitor */
  /* Everyone in the room already knows this sound, which is why it is worth
     the thirty lines. Real pulse oximeters drop their pitch as saturation
     falls, so as he deteriorates the beep sinks -- the room hears him dying
     before it reads a number. */
  var spo2Now = 98;

  function beep() {
    if (!audio || muted) return;
    var t = audio.currentTime;

    /* 98% -> 880Hz down to 85% -> 600Hz, the way a real probe behaves. */
    var pitch = 600 + Math.max(0, Math.min(1, (spo2Now - 85) / 13)) * 280;

    var o = audio.createOscillator();
    var g = audio.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(pitch, t);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.075, t + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.085);
    o.connect(g); g.connect(audio.destination);
    o.start(t); o.stop(t + 0.1);
  }

  /* --------------------------------------------------------------- tts */
  var patientVoice = {};
  function speak(text) { Voice.speak(text, patientVoice); }   /* M mutes the monitor, not the patient */
  function hush() { Voice.hush(); }

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
    patientVoice = { sex: s.patient_sex, age: s.patient_age };
    $('ask').placeholder = (s.patient_sex === 'female' ? 'Ask her' : 'Ask him') + ' anything, then press enter' +
      (Voice.canListen ? ' \u2014 or tap the mic' : '');
    $('patient').innerHTML = esc(s.patient_name) +
      '<span>' + s.patient_age + '</span>';

    var meta = MOOD_META[s.mood];
    var sub = '';
    if (meta) {
      sub += '<span class="moodBadge mood-' + meta.tier + '">' +
             meta.icon + ' ' + meta.label + '</span>';
    }
    if (s.description) {
      sub += (sub ? ' <span class="sep">•</span> ' : '') + esc(s.description);
    }
    /* State arrives every second. Rewriting unchanged markup restarts its
       animations, so only touch the DOM when something actually changed. */
    if (sub !== lastSub) { $('patientSub').innerHTML = sub; lastSub = sub; }

    $('vHr').innerHTML = s.vitals.hr + '<small>bpm</small>';
    $('vSpo2').innerHTML = s.vitals.spo2 + '<small>%</small>';
    $('vBp').innerHTML = s.vitals.bp + '<small>mmHg</small>';
    $('vRr').innerHTML = s.vitals.rr + '<small>/min</small>';

    $('vHr').className = 'val num status-' + s.status;
    $('vSpo2').className = 'val num status-' + s.status;
    $('clock').className = 'num status-' + s.status;
    document.body.setAttribute('data-status', s.status);

    /* THE TELL.
       He answers calmly and his pulse jumps. Previously that was a number
       changing by fifteen, which nobody sees from the back of a room. Now the
       heart-rate card flares and calls it. */
    if (lastHr !== null && s.vitals.hr - lastHr >= 9 && s.status !== 'flatline') {
      flagTell();
    }
    lastHr = s.vitals.hr;

    spo2Now = s.vitals.spo2;
    ecg.set(s.vitals.hr, s.status);
    if (room3d) {
      room3d.setStatus(s.status);
      room3d.setRespiratoryRate(s.vitals.rr);
    }

    /* Rebuild the transcript only when a message arrives, and animate only
       the new ones. Rebuilding on every one-second tick made the whole
       conversation fade out and back in, once a second, on the projector. */
    var last = s.messages[s.messages.length - 1];
    var feedSig = s.messages.length + '|' + (last ? last.who + ':' + last.text : '');
    if (feedSig !== lastFeedSig) {
      var feed = $('feed');
      var shownFrom = Math.max(0, s.messages.length - 4);
      feed.innerHTML = '';
      s.messages.slice(shownFrom).forEach(function (m, i) {
        var d = document.createElement('div');
        d.className = 'msg ' + m.kind + (shownFrom + i >= feedSeen ? ' new' : '');
        d.innerHTML = '<span class="who">' + esc(m.who) + '</span>' +
                      '<div class="body">' + esc(m.text) + '</div>';
        feed.appendChild(d);
      });
      feedSeen = s.messages.length;
      lastFeedSig = feedSig;
    }

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

    /* 0. the jolt: a red vignette, a shake, three sharp alarm beeps. Losing
          should not fade in -- it should land. This is the part the room
          asked for by name: "make the screen become like red". */
    $('page').classList.add('codeRed');
    alarmBeeps(3, 660);

    /* 1. the trace flattens where it stands, mid-beat */
    ecg.onBeat = null;           /* the beeping stops with the heart */
    ecg.kill();
    ecg.draw();

    setTimeout(function () {
      $('page').classList.remove('codeRed');

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
          host('reveal');
        }, 2000);
      }, 1200);
    }, 900);
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

    renderCaseFile(r);

    $('nextBtn').style.display = r.is_last ? 'none' : '';
    $('nextBtn').textContent = 'Next patient';
    $('reveal').classList.add('show');
  }

  /* The case file. The round's punchline: what he hid, who caught it, what
     nobody asked and why it would have mattered. Everything here arrives only
     in the reveal payload, after the diagnosis is already on screen. */
  function renderCaseFile(r) {
    var cf = r.case_file;
    $('caseFile').style.display = cf ? '' : 'none';
    $('awards').innerHTML = '';
    if (!cf) return;

    var she = /^She /.test(r.headline || '');
    $('cfHidTitle').textContent = she ? 'What she hid' : 'What he hid';
    $('cfLie').textContent = cf.lie;
    $('cfTruth').textContent = cf.truth;

    var caught = [];
    if (cf.lie_heard) {
      caught.push('<b>' + esc(cf.lie_heard.by) + '</b> drew out the lie at ' + esc(cf.lie_heard.at) +
                  ' <span class="rv-dim">&mdash; the heart rate jumped as ' + (she ? 'she' : 'he') + ' answered.</span>');
    } else {
      caught.push('Nobody asked about ' + esc(cf.lie_topic || 'it') + '. The lie was never even told.');
    }
    if (cf.cracked) {
      caught.push('<b>' + esc(cf.cracked.by) + '</b> got the truth at ' + esc(cf.cracked.at) +
                  ': <span class="rv-dim">&ldquo;' + esc(cf.cracked.question) + '&rdquo;</span>');
    } else if (cf.lie_heard) {
      caught.push('Nobody pushed back. ' + (she ? 'She' : 'He') + ' took the truth to the grave.');
    }
    if (cf.fatal_guess) {
      caught.push('<b>' + esc(cf.fatal_guess.by) + '</b> called it &ldquo;' + esc(cf.fatal_guess.guess) + '&rdquo;. That killed ' + (she ? 'her' : 'him') + '.');
    }
    $('cfCaught').innerHTML = caught.map(function (c) { return '<div>' + c + '</div>'; }).join('');

    $('cfMissed').innerHTML = cf.missed.length
      ? cf.missed.map(function (m) {
          return '<div class="rv-miss"><div class="rv-q">&ldquo;' + esc(m.topic) + '?&rdquo;</div>' +
                 '<div class="rv-why">' + esc(m.why) + '</div></div>';
        }).join('')
      : '<div class="rv-miss rv-all"><div class="rv-q">Nothing. The room asked every question that mattered.</div></div>';

    $('cfFound').innerHTML = cf.found.length
      ? '<span class="rv-dim">Found:</span> ' + cf.found.map(function (f) {
          return '<span class="rv-chip">' + esc(f.topic) + ' <em>' + esc(f.by) + '</em></span>';
        }).join('')
      : '';
    $('cfPearl').textContent = cf.pearl || '';
    $('cfPearl').style.display = cf.pearl ? '' : 'none';

    $('awards').innerHTML = (r.awards || []).map(function (a, i) {
      return '<div class="rv-award" style="animation-delay:' + (1.4 + i * 0.35) + 's">' +
             '<div class="rv-award-title">' + esc(a.title) + '</div>' +
             '<div class="rv-award-who">' + esc(a.who) + '</div>' +
             '<div class="rv-award-why">' + esc(a.why) + '</div></div>';
    }).join('');
  }

  /* -------------------------------------------------------- level card */
  function showCard(level, levels, lines, then) {
    $('cardLevel').textContent = 'Patient ' + level + ' of ' + levels;
    $('level').textContent = 'Patient ' + level + ' of ' + levels;
    var box = $('cardLines');
    box.innerHTML = '';
    (lines || []).forEach(function (line) {
      var d = document.createElement('div');
      d.textContent = line;
      box.appendChild(d);
    });
    $('card').classList.add('show');

    var go = function () {
      if (!$('card').classList.contains('show')) return;
      $('card').classList.remove('show');
      document.removeEventListener('keydown', onKey);
      $('card').removeEventListener('click', go);
      then();
    };
    var onKey = function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    };
    /* A card you cannot dismiss stops the whole demo, so anything gets you
       past it: the button, a click anywhere, enter, or space. */
    $('cardGo').onclick = go;
    $('card').addEventListener('click', go);
    document.addEventListener('keydown', onKey);
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
  function send(path, text, who) {
    return fetch('/api/' + code + '/' + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: who || 'You', text: text })
    });
  }

  /* Starting, revealing, advancing, killing and resetting the round need the
     key this screen got when it claimed the room. Phones never have it. */
  var hostKey = null;
  function hostKeyStore() { return 'yh_host_' + code; }
  function host(path) {
    return fetch('/api/' + code + '/' + path, {
      method: 'POST',
      headers: { 'X-Host-Key': hostKey || '' }
    }).then(function (r) {
      if (r.status === 403) notice('Another screen is hosting this room -- controls are off here');
      return r;
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
  /* Talk to the patient. What you say lands in the box, then asks itself. */
  Voice.attach($('micBtn'), $('ask'), function () { $('askBtn').click(); });

  /* Next patient: carries scores forward, shows the card, starts the round. */
  $('nextBtn').onclick = function () {
    $('nextBtn').textContent = 'Loading...';
    host('next')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.done) { $('nextBtn').style.display = 'none'; return; }
        resetForNextRound();
        showCard(d.level, d.levels, d.card, function () {
          host('start');
          startLoop();
          if (DEMO_MODE) runDemo();
        });
      });
  };


  function resetForNextRound() {
    $('reveal').classList.remove('show');
    $('page').classList.remove('draining', 'blank', 'codeRed');
    $('overlay').classList.remove('show');
    flatlined = false;
    spokenUpto = 0;
    lastFeedSig = null;
    feedSeen = 0;
    lastSub = null;
    lastHr = null;
    lastPhase = null;
    ecg.revive();
    ecg.onBeat = function () { beep(); };
    if (room3d) room3d.unfreeze();
  }

  /* Debug: K flatlines on demand, R reloads. Gate 3 asks for the sequence to
     land ten times in a row, which should not mean ten full rounds. */
  document.addEventListener('keydown', function (e) {
    if (document.activeElement === $('ask')) return;
    if (e.key === 'k' || e.key === 'K') host('kill');
    if (e.key === 'r' || e.key === 'R') location.reload();
    if (e.key === 'm' || e.key === 'M') { muted = !muted; notice(muted ? 'Monitor muted' : 'Monitor on'); }
  });

  /* -------------------------------------------------- bedside inspection */
  /* Touch the man instead of picking from a menu. The cursor tells you what is
     under it and the finding lands in the feed for the whole room. */
  function wireInspection() {
    if (!room3d || !room3d.ok) return;
    var canvas = $('room3d');

    canvas.style.cursor = 'crosshair';

    canvas.addEventListener('mousemove', function (e) {
      room3d.pointerAt(e.clientX, e.clientY, canvas.getBoundingClientRect());
      var hit = room3d.hovered;
      $('examTip').textContent = hit ? hit.userData.label : '';
      $('examTip').classList.toggle('show', !!hit);
      canvas.style.cursor = hit ? 'pointer' : 'crosshair';
    });

    canvas.addEventListener('mouseleave', function () {
      room3d.pointerAt(-9999, -9999, canvas.getBoundingClientRect());
      $('examTip').classList.remove('show');
    });

    canvas.addEventListener('click', function (e) {
      room3d.pointerAt(e.clientX, e.clientY, canvas.getBoundingClientRect());
      var hit = room3d.pickHotspot();
      if (!hit) return;
      var id = hit.userData.examId;

      fetch('/api/' + code + '/examine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exam_id: id })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.finding) {
            room3d.markExamined(id);
          } else if (d.reason === 'already') {
            notice('You have already examined that');
          } else if (d.reason === 'not_playing') {
            notice('The round is not running');
          }
        })
        .catch(function () { notice('Lost the server'); });
    });
  }

  /* --------------------------------------------------------------- demo */
  /* ?demo=1 plays the whole show on its own: the questions land on a timer,
     the lie arrives where it should, and it ends on the flatline.
     Two reasons this exists. A judge opening the link sees the entire thing
     without anyone presenting it, and on stage nobody has to type into a text
     box in front of two hundred people while their hands shake. */
  /* A small room of doctors, so the reveal has a story to tell: who drew out
     the lie, who broke him, who wasted their breath, who called it. */
  var DEMO = [
    [1500,  'Dr Sara', 'good evening. what brings you in tonight?'],
    [6000,  'Omar',    'do you like football?'],
    [10500, 'Dr Sara', 'how much do you drink?'],     /* >8s after her first: the room cooldown */
    [15000, 'Lina',    'have your eyes or your skin gone yellow at all?'],
    [20000, 'Omar',    'any holidays planned this year?'],
    [23000, 'Dr Sara', 'has your belly been swelling?'],
    [30000, 'Omar',    'what did you have for lunch?'],
    [33000, 'Lina',    'what does your wife think is going on?'],
    [41000, 'Dr Sara', 'do you bruise easily?']
  ];

  function runDemo() {
    DEMO.forEach(function (step) {
      setTimeout(function () { send('ask', step[2], step[1]); }, step[0]);
    });
    setTimeout(function () { send('guess', 'his liver is failing', 'Lina'); }, 47000);
    /* Let the last answer breathe, then end it. */
    setTimeout(function () {
      host('kill');
    }, 52000);
  }

  /* ------------------------------------------------------------- start */
  $('begin').onclick = function () {
    if ($('title').classList.contains('hide')) return;
    ensureAudio();                     /* the gesture that unblocks audio */
    if (audio && audio.state === 'suspended') audio.resume();
    $('title').classList.add('hide');

    fetch('/api/' + code + '/card')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        showCard(d.level, d.levels, d.card, function () {
          host('start');
          startLoop();
          if (DEMO_MODE) runDemo();
        });
      });
  };

  /* Demo mode plays itself. Browsers only allow sound after a real click, and
     this demo is mostly sound -- the monitor, the voice, the flatline tone --
     so it asks for one click, and starts on its own (silently) if nobody
     gives it. */
  if (DEMO_MODE) {
    $('begin').textContent = '\u25B6  Play the one-minute demo  \u00B7  sound on';
    var autoGo = function () {
      var go = $('cardGo');
      if (go && $('card').classList.contains('show')) go.click();
    };
    var clicked = false;
    $('begin').addEventListener('click', function () {
      if (clicked) return;
      clicked = true;
      setTimeout(autoGo, 3300);
    });
    setTimeout(function () { if (!clicked) $('begin').click(); }, 8000);
  }

  (function init() {
    if (!code) {
      fetch('/api/room', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          try { localStorage.setItem('yh_host_' + d.code, d.host_key); } catch (e) {}
          params.set('c', d.code);
          location.search = params.toString();
        })
        .catch(function () { notice('Could not reach the server'); });
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
      /* The 3D is the disposable layer. If anything in it throws, the round
         must still play -- last time a bad geometry call killed init() before
         it reached connect(), so no state ever arrived and every number on the
         page sat at a dash. */
      try {
        room3d = new Room3D($('room3d'), $('ecg'));
        if (room3d && room3d.ok) {
          wireInspection();
        } else {
          room3d = null;
          document.body.classList.add('flat');
        }
      } catch (e) {
        room3d = null;
        document.body.classList.add('flat');
        if (window.console) console.error('3D disabled:', e);
      }
    }

    try { hostKey = localStorage.getItem(hostKeyStore()); } catch (e) {}
    fetch('/api/' + code + '/host', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: hostKey })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok) {
          hostKey = res.d.host_key;
          try { localStorage.setItem(hostKeyStore(), hostKey); } catch (e) {}
        } else {
          hostKey = null;
          notice('Another screen is hosting this room -- controls are off here');
        }
      })
      .catch(function () { notice('Could not reach the server'); })
      .then(function () { connect(); });
    ecg.frame(performance.now());
  })();
})();
