/* Ya Hakim v2 -- one screen, five states.
   splash -> pick -> brief -> encounter -> reveal, with examine, diagnose,
   generate, record and x-ray as sheets on top.

   His vitals are not on this page any more. They are on the monitor at the
   head of the bed, which monitor.js paints and room3d.js hangs in the scene,
   so reading them means looking at the room. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var API = '/api/v2';

  var sid = null;
  var chosen = null;
  var cases = [];
  var canGenerate = false;
  var monitor = null;
  var room = null;
  var raf = null;
  var poll = null;
  var lastHr = null;
  var spoken = 0;
  var ending = false;
  var lastSig = '';
  var pending = null;
  var genJob = null;
  var genTimer = null;
  var genDifficulty = 'standard';

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function show(id) {
    /* Leaving the bedside silences him. Without this his queued phrases keep
       playing over the results screen and the picker -- speechSynthesis has a
       queue of its own and does not care that the round is over. */
    if (id !== 'encounter') silence();

    ['splash', 'pick', 'brief', 'reveal'].forEach(function (s) {
      $(s).classList.toggle('on', s === id);
    });
    $('encounter').classList.toggle('on', id === 'encounter');
  }

  /* Everything that can still be making a noise, stopped. */
  function silence() {
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (e) {}
    try { flatTone(false); } catch (e) {}
    if (monitor) monitor.onBeat = null;
  }

  function toast(msg) {
    var t = $('toast');
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { t.classList.remove('on'); }, 2600);
  }

  function sheet(id, on) { $(id).classList.toggle('on', !!on); }

  /* ------------------------------------------------------------ progress */
  /* v2 has no accounts and no database, so the only honest place to keep a
     level is the browser that earned it. Every read and write is wrapped:
     localStorage throws outright in some privacy modes, and a thrown getItem
     on line one would take the whole app down before the splash rendered. */

  var STORE = 'yahakim.v2.progress';

  function loadProgress() {
    var blank = { xp: 0, history: [] };
    try {
      var raw = localStorage.getItem(STORE);
      if (!raw) return blank;
      var p = JSON.parse(raw);
      if (!p || typeof p !== 'object') return blank;
      return {
        xp: typeof p.xp === 'number' && isFinite(p.xp) ? Math.max(0, p.xp) : 0,
        history: Object.prototype.toString.call(p.history) === '[object Array]' ? p.history : []
      };
    } catch (e) { return blank; }
  }

  function saveProgress() {
    try { localStorage.setItem(STORE, JSON.stringify(progress)); } catch (e) {}
  }

  var progress = loadProgress();

  function levelNeed(level) { return 200 + (level - 1) * 120; }

  function levelFor(xp) {
    var level = 1, floor = 0, need = levelNeed(1);
    while (xp >= floor + need && level < 99) {
      floor += need;
      level++;
      need = levelNeed(level);
    }
    return { level: level, into: xp - floor, need: need };
  }

  var RANKS = ['Medical student', 'Junior clerk', 'Intern', 'Senior intern',
               'Senior house officer', 'Registrar', 'Senior registrar',
               'Consultant', 'Attending', 'Head of department', 'Professor',
               'Ya Hakim'];
  function rankFor(level) {
    return RANKS[Math.min(RANKS.length - 1, Math.floor((level - 1) / 2))];
  }

  function bestFor(caseId) {
    var best = null;
    progress.history.forEach(function (h) {
      if (h && h.case === caseId && (best === null || h.accuracy > best)) best = h.accuracy;
    });
    return best;
  }

  function drawLadder() {
    var L = levelFor(progress.xp);
    $('rankBadge').textContent = L.level;
    $('rankName').textContent = rankFor(L.level);
    $('xpInto').textContent = L.into;
    $('xpNeed').textContent = L.need;
    $('xpFill').style.width = Math.round((L.into / L.need) * 100) + '%';

    var n = progress.history.length;
    if (!n) {
      $('ladderSub').textContent = 'No cases yet. Pick a patient.';
      return;
    }
    var hits = 0, sum = 0;
    progress.history.forEach(function (h) { if (h.correct) hits++; sum += (h.accuracy || 0); });
    $('ladderSub').textContent =
      n + ' case' + (n === 1 ? '' : 's') + ' · ' +
      hits + ' called right · ' + Math.round(sum / n) + '% average accuracy';
  }

  /* ---------------------------------------------------------- case picker */
  var FACE_BG = ['var(--saffron)', 'var(--sky)', 'var(--plum)',
                 'var(--teal)', 'var(--rose)', 'var(--clay)'];
  function faceBg(id) {
    var h = 0;
    for (var i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
    return FACE_BG[h % FACE_BG.length];
  }

  function caseCard(c) {
    var el = document.createElement('div');
    el.className = 'case';
    var best = bestFor(c.id);
    el.innerHTML =
      (best === null ? '' : '<div class="best">Best ' + best + '%</div>') +
      '<div class="face" style="background:' + faceBg(c.id) + '">' + esc(c.avatar) + '</div>' +
      '<div class="who">' + esc(c.name) + '</div>' +
      '<div class="sub">' + esc(c.age) + ' · ' + esc(c.setting) + '</div>' +
      '<div class="blurb">' + esc(c.blurb) + '</div>' +
      '<div class="foot">' +
        '<span class="tierbadge t' + (c.tier || 2) + '">' + esc(c.rank || 'Resident') + '</span>' +
        '<span class="xptag">' + (c.generated ? '✨ ' : '') + 'up to ' + (c.xp || 0) + ' XP</span>' +
      '</div>';
    el.onclick = function () { chosen = c; toBrief(); };
    return el;
  }

  function generateCard() {
    var el = document.createElement('div');
    el.className = 'case new-card' + (canGenerate ? '' : ' off');
    el.innerHTML =
      '<div class="big-plus">✨</div>' +
      '<div class="who">Write a new patient</div>' +
      '<div class="sub" style="margin:6px 0 0">' +
        (canGenerate
          ? 'A real case, drafted on the spot and checked before you play it'
          : 'Not available right now') +
      '</div>';
    el.onclick = function () {
      if (!canGenerate) {
        toast('Writing new patients is not available right now');
        return;
      }
      showGen('form');
      sheet('genSheet', true);
      setTimeout(function () { $('genBrief').focus(); }, 60);
    };
    return el;
  }

  function drawCases() {
    var list = $('caseList');
    list.innerHTML = '';
    cases.forEach(function (c) { list.appendChild(caseCard(c)); });
    list.appendChild(generateCard());
  }

  function refreshCases() {
    return fetch(API + '/cases')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        cases = d.cases || [];
        canGenerate = !!d.can_generate;
        drawCases();
      })
      .catch(function () { toast('Could not reach the server'); });
  }

  /* --------------------------------------------------------------- audio */
  var actx = null, muted = false, spo2 = 98;
  function audio() {
    if (!actx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (AC) actx = new AC();
    }
    if (actx && actx.state === 'suspended') actx.resume();
    return actx;
  }
  function beep() {
    if (!actx || muted) return;
    var t = actx.currentTime;
    var pitch = 600 + Math.max(0, Math.min(1, (spo2 - 85) / 13)) * 280;
    var o = actx.createOscillator(), g = actx.createGain();
    o.type = 'sine'; o.frequency.setValueAtTime(pitch, t);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.06, t + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.085);
    o.connect(g); g.connect(actx.destination);
    o.start(t); o.stop(t + 0.1);
  }
  /* A pop on anything you press. Short, soft, and pitched down on the way out
     so it reads as a physical button rather than a notification. */
  function pop(low) {
    var a = audio();
    if (!a || muted) return;
    var t = a.currentTime;
    var f0 = low ? 430 : 660;
    var o = a.createOscillator(), g = a.createGain();
    o.type = 'triangle';
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(f0 * 0.55, t + 0.075);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.085, t + 0.007);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.11);
    o.connect(g); g.connect(a.destination);
    o.start(t); o.stop(t + 0.13);
  }

  /* One delegated listener rather than a call in forty handlers -- anything
     that looks pressable gets it, including the cards and chips built later. */
  var PRESSABLE = '.btn, .chip, .case, .seg, .backbtn, .exam, .hrow';
  document.addEventListener('pointerdown', function (e) {
    var el = e.target && e.target.closest ? e.target.closest(PRESSABLE) : null;
    if (!el || el.disabled || el.classList.contains('off')) return;
    pop(el.classList.contains('backbtn') || el.classList.contains('ghost'));
  }, true);

  var tone = null;
  function flatTone(on) {
    if (!actx) return;
    if (on && !tone) {
      tone = actx.createOscillator();
      var g = actx.createGain();
      tone.type = 'sine'; tone.frequency.value = 989;
      g.gain.setValueAtTime(0.0001, actx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.14, actx.currentTime + 0.03);
      tone.connect(g); g.connect(actx.destination);
      tone._g = g; tone.start();
    } else if (!on && tone) {
      var t = actx.currentTime;
      try {
        tone._g.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
        tone.stop(t + 0.07);
      } catch (e) {}
      tone = null;
    }
  }

  /* ------------------------------------------------------------- his voice */
  var VOICES = [];
  var chosenVoice = null;

  function loadVoices() {
    VOICES = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    chosenVoice = null;
  }
  if (window.speechSynthesis) {
    loadVoices();
    speechSynthesis.onvoiceschanged = loadVoices;
  }

  /* Scored, not first-match.
     The old version took the first voice whose name contained "natural" OR
     "neural" OR "online" and used it for everybody -- so it would happily read
     a 54-year-old dock supervisor in a woman's voice, and it cached that one
     choice for the whole session, which meant Rita and Georges got Kamal's.
     Now every installed voice is scored on quality and on whether it matches
     the character, and the winner is cached per sex. */
  var FEMALE_NAMES = /zira|hazel|aria|jenny|ava|emma|libby|sonia|michelle|clara|natasha|susan|catherine|samantha|female|\bwoman\b/i;
  var MALE_NAMES   = /david|mark|george|ryan|guy|brian|andrew|christopher|james|william|liam|eric|steffan|male|\bman\b/i;

  function scoreVoice(v, wantFemale) {
    var n = (v.name || '');
    var lang = (v.lang || '');
    var s = 0;

    /* the Azure/Edge neural set is a different league from anything else */
    if (/natural|neural/i.test(n)) s += 120;
    if (/online/i.test(n)) s += 45;
    /* Chrome ships its own, which are decent */
    if (/^google/i.test(n)) s += 60;
    /* the old SAPI desktop voices are the robotic ones */
    if (/desktop/i.test(n)) s -= 50;
    if (/espeak|festival|pico|compact/i.test(n)) s -= 90;
    /* a remote voice is a synthesised-in-the-cloud voice, i.e. a good one */
    if (v.localService === false) s += 25;
    /* en-GB reads as a hospital rather than a satnav, but only just */
    if (/^en[-_]GB/i.test(lang)) s += 12;
    else if (/^en[-_]US/i.test(lang)) s += 8;
    else if (!/^en/i.test(lang)) s -= 60;

    var fem = FEMALE_NAMES.test(n);
    var male = MALE_NAMES.test(n);
    if (wantFemale) { if (fem) s += 40; if (male) s -= 35; }
    else { if (male) s += 40; if (fem) s -= 35; }

    return s;
  }

  function pickVoice(sex) {
    var wantFemale = sex === 'female';
    var key = wantFemale ? 'f' : 'm';
    if (chosenVoice && chosenVoice[key]) return chosenVoice[key];
    if (!VOICES.length) loadVoices();
    if (!VOICES.length) return null;

    var best = null, bestScore = -1e9;
    for (var i = 0; i < VOICES.length; i++) {
      var sc = scoreVoice(VOICES[i], wantFemale);
      if (sc > bestScore) { bestScore = sc; best = VOICES[i]; }
    }
    chosenVoice = chosenVoice || {};
    chosenVoice[key] = best;
    return best;
  }

  /* A neural voice already breathes; pushing its pitch down a fifth is what
     makes it sound like a broken toy. The old tuning was written for the SAPI
     voices, so it only applies to them. */
  function isNeural(v) {
    return !!v && (/natural|neural|online/i.test(v.name || '') || v.localService === false);
  }

  var VOICE_TUNE = {
    kamal:   { rate: 0.92, pitch: 0.78 },
    rita:    { rate: 1.04, pitch: 1.04 },
    georges: { rate: 0.86, pitch: 0.84 }
  };

  /* A case the model wrote five seconds ago has no entry in the table above,
     so the tuning falls back to the two things we are told about anybody. */
  function tuneFor(c) {
    if (c && VOICE_TUNE[c.id]) return VOICE_TUNE[c.id];
    var female = c && /^f/i.test(c.sex || '');
    var old = c && (c.age || 50) >= 60;
    return { rate: old ? 0.88 : 0.97, pitch: female ? 1.02 : 0.82 };
  }

  function speak(text) {
    if (!window.speechSynthesis || muted || !text) return;
    var voice = pickVoice((chosen && /^f/i.test(chosen.sex || '')) ? 'female' : 'male');
    var tune = tuneFor(chosen);

    /* On a good voice, stay near its natural settings and let it act. */
    if (isNeural(voice)) {
      var old = chosen && (chosen.age || 50) >= 60;
      tune = { rate: old ? 0.94 : 1.0, pitch: 1.0 };
    }

    var parts = String(text).match(/[^.!?,;:]+[.!?,;:]?/g) || [text];
    parts.forEach(function (part, i) {
      part = part.trim();
      if (!part) return;
      try {
        var u = new SpeechSynthesisUtterance(part);
        if (voice) u.voice = voice;
        /* drift each phrase a touch so the delivery is not metronomic */
        u.rate  = tune.rate  + (i % 2 ? 0.02 : -0.02);
        u.pitch = tune.pitch + (i % 3 === 0 ? 0.02 : -0.015);
        u.volume = 1;
        speechSynthesis.speak(u);
      } catch (e) {}
    });
  }

  /* -------------------------------------------------------------- render */
  function fmt(s) {
    s = Math.max(0, s | 0);
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  var MOOD = {
    guarded:   ['🛡', 'Guarded',   ''],
    defensive: ['✋', 'Defensive', 'saff'],
    rattled:   ['😬', 'Rattled',   'clay'],
    scared:    ['😨', 'Scared',    'rose'],
    resigned:  ['😔', 'Resigned',  'teal'],
    gone:      ['🕯', 'Gone',      '']
  };

  function bubble(kind, who, text) {
    var d = document.createElement('div');
    d.className = 'bubble ' + kind;
    d.innerHTML = '<div class="lbl">' + esc(who) + '</div>' +
                  '<div class="msg">' + esc(text) + '</div>';
    return d;
  }

  function thinking() {
    var d = document.createElement('div');
    d.className = 'bubble him';
    d.innerHTML = '<div class="lbl">' + esc(($('eName') || {}).textContent || '') + '</div>' +
                  '<div class="msg dots"><i></i><i></i><i></i></div>';
    return d;
  }

  function drawPips(covered, total) {
    var el = $('pips');
    total = total || 0;
    if (el.children.length !== total) {
      el.innerHTML = '';
      for (var i = 0; i < total; i++) el.appendChild(document.createElement('i'));
    }
    for (var k = 0; k < el.children.length; k++) {
      el.children[k].classList.toggle('on', k < covered);
    }
  }

  function render(v) {
    if (!v || !v.name) return;
    $('eName').textContent = v.name;
    $('eMeta').textContent = v.age + ' years old';
    $('avatar').textContent = v.avatar || '🧑';
    if (chosen && v.sex) chosen.sex = v.sex;

    var m = MOOD[v.mood] || MOOD.guarded;
    $('moodPill').textContent = m[0] + ' ' + m[1];
    $('moodPill').className = 'pill ' + (m[2] || '');

    $('vHr').textContent = v.vitals.hr;
    $('vSpo2').textContent = v.vitals.spo2;
    spo2 = v.vitals.spo2;

    $('clock').textContent = fmt(v.seconds_left);
    $('clock').className = 'clock num' +
      (v.status === 'critical' ? ' bad' : v.status === 'declining' ? ' warn' : '');

    drawPips(v.topics_covered || 0, v.topics_total || 0);

    if (monitor) {
      monitor.setVitals(v.vitals);
      monitor.setStatus(v.status);
      monitor.setClock(fmt(v.seconds_left));
      monitor.setPatient(v.name, v.age + (/^f/i.test(v.sex || '') ? ' F' : ' M'));
    }
    if (room) { room.setStatus(v.status); room.setRespiratoryRate(v.vitals.rr); }

    /* the tell: his pulse jumps while his mouth stays calm */
    if (lastHr !== null && v.vitals.hr - lastHr >= 9 && !v.over) {
      var c = $('cHr');
      c.classList.remove('tell'); void c.offsetWidth; c.classList.add('tell');
      setTimeout(function () { c.classList.remove('tell'); }, 5000);
      if (monitor) monitor.flashHr();
    }
    lastHr = v.vitals.hr;

    /* Only touch the DOM when the conversation actually changed. Rebuilding
       every bubble once a second made the whole thread flicker and re-animate,
       which read as lag even though nothing was slow. */
    var sig = v.log.length + ':' + (v.log.length ? v.log[v.log.length - 1].text : '');
    if (sig !== lastSig) {
      lastSig = sig;
      var talk = $('talk');
      talk.innerHTML = '';
      v.log.forEach(function (l) { talk.appendChild(bubble(l.kind, l.who, l.text)); });
      talk.scrollTop = talk.scrollHeight;
    }

    for (var i = spoken; i < v.log.length; i++) {
      if (v.log[i].kind === 'him') speak(v.log[i].text);
    }
    spoken = v.log.length;

    if (v.over && !ending) timeUp();
  }

  /* -------------------------------------------------------------- the room */
  /* Disposable by design: if three.js is missing or anything in the scene
     throws, the body gets .noroom, the conversation takes the full width and
     the round plays exactly as before -- except that the vitals chips in the
     top bar become the only reading, which is why they are there. */
  function buildRoom() {
    if (room || typeof Room3D === 'undefined' || !Room3D.available()) {
      if (!room) document.body.classList.add('noroom');
      return;
    }
    try {
      room = new Room3D($('room3d'), monitor.canvas);
      if (!room.ok) { room = null; document.body.classList.add('noroom'); return; }
    } catch (e) {
      room = null;
      document.body.classList.add('noroom');
      if (window.console) console.error('room disabled:', e);
      return;
    }

    var canvas = $('room3d');
    canvas.style.cursor = 'crosshair';

    canvas.addEventListener('mousemove', function (e) {
      room.pointerAt(e.clientX, e.clientY, canvas.getBoundingClientRect());
      var hit = room.hovered;
      $('examTip').textContent = hit ? hit.userData.label : '';
      $('examTip').classList.toggle('on', !!hit);
      canvas.style.cursor = hit ? 'pointer' : 'crosshair';
    });
    canvas.addEventListener('mouseleave', function () {
      room.pointerAt(-9999, -9999, canvas.getBoundingClientRect());
      $('examTip').classList.remove('on');
    });

    /* Touching him runs the same examination the sheet does. */
    canvas.addEventListener('click', function () {
      var hit = room.pickHotspot();
      if (!hit || !sid || ending) return;
      runExam(hit.userData.examId);
    });
  }

  function runExam(id) {
    return fetch(API + '/examine/' + sid, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exam: id })
    }).then(function (r) { return r.json(); }).then(function (v) {
      if (v.reason === 'already') { toast('Already examined that'); return v; }
      if (v.reason === 'over') { toast('The round is over'); return v; }
      if (v.reason === 'unknown') { toast('Cannot examine that'); return v; }
      if (room) room.markExamined(id);
      render(v);
      return v;
    }).catch(function () { toast('Lost the server'); });
  }

  /* ------------------------------------------------------------ the loop */
  var lastFrame = 0;
  function frame(now) {
    var dt = lastFrame ? now - lastFrame : 16;
    lastFrame = now;
    if (monitor) monitor.frame(dt);
    if (room) room.frame(dt);
    raf = requestAnimationFrame(frame);
  }
  function startLoop() {
    if (raf) return;
    lastFrame = 0;
    raf = requestAnimationFrame(frame);
  }

  function startPolling() {
    clearInterval(poll);
    poll = setInterval(function () {
      if (!sid || ending) return;
      fetch(API + '/state/' + sid)
        .then(function (r) { return r.json(); })
        .then(render)
        .catch(function () {});
    }, 1000);
  }

  /* ------------------------------------------------------------ the end */
  /* One way out of a round, whether he ran out of time or you called it.
     `ending` is claimed before any request goes out, because the 1s poll and
     the diagnose button used to be able to end the same round twice. */

  /* The clock ran out, or they gave up. Both ask the server to close the
     round and hand back the mark sheet. */
  function stopRound(final) {
    if (ending) return;
    ending = true;
    fetch(API + '/diagnose/' + sid, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: '', final: !!final })
    }).then(function (r) { return r.json(); })
      .then(function (d) { endRound(d); })
      .catch(function () { endRound(null); });
  }
  function timeUp() { stopRound(false); }

  function endRound(result) {
    clearInterval(poll);
    try { speechSynthesis.cancel(); } catch (e) {}
    if (monitor) { monitor.onBeat = null; monitor.kill(); }
    flatTone(true);
    $('encounter').classList.add('draining');

    setTimeout(function () {
      flatTone(false);
      $('encounter').classList.add('blank');
      if (room) room.freeze();
      if (raf) { cancelAnimationFrame(raf); raf = null; }
      setTimeout(function () { showReveal(result); }, 1600);
    }, 1200);
  }

  function award(result) {
    var before = levelFor(progress.xp).level;
    progress.xp += Math.max(0, result.xp || 0);
    progress.history.unshift({
      case: chosen ? chosen.id : '',
      name: result.name || (chosen ? chosen.name : ''),
      avatar: result.avatar || (chosen ? chosen.avatar : '🧑'),
      accuracy: result.accuracy || 0,
      correct: !!result.correct,
      xp: Math.max(0, result.xp || 0),
      diagnosis: result.diagnosis || '',
      called: result.called || '',
      seconds: result.stats ? result.stats.seconds_used : null,
      at: Date.now()
    });
    if (progress.history.length > 60) progress.history.length = 60;
    saveProgress();
    return { before: before, after: levelFor(progress.xp).level };
  }

  var REVEAL_TAG = {
    called:        ['You called it',              'teal'],
    out_of_tries:  ['Out of calls',               'rose'],
    gave_up:       ['You gave up',                'rose'],
    no_call:       ['Time up',                    'rose'],
    already:       ['Round over',                 'rose']
  };

  function showReveal(result) {
    $('encounter').classList.remove('on', 'draining', 'blank');

    if (!result) {
      $('revealTag').textContent = 'Lost him';
      $('revealTag').className = 'pill rose';
      $('revealDx').textContent = '';
      $('revealNote').textContent = 'The server stopped answering. Nothing was scored.';
      $('accNum').innerHTML = '0<small>%</small>';
      $('accFill').style.width = '0%';
      $('accXp').textContent = '+0 XP';
      $('revealScores').innerHTML = '';
      $('levelUp').style.display = 'none';
      show('reveal');
      return;
    }

    var tag = REVEAL_TAG[result.reason] ||
              (result.correct ? REVEAL_TAG.called : REVEAL_TAG.no_call);
    $('revealTag').textContent = tag[0];
    $('revealTag').className = 'pill ' + tag[1];

    $('revealDx').textContent = result.diagnosis || '';

    var tries = (result.guesses || []).length;
    var note = result.note;
    if (!note) {
      if (result.correct) note = 'You were right.';
      else if (result.reason === 'out_of_tries') note = 'Five calls, and none of them were it.';
      else if (result.reason === 'gave_up') note = 'You walked away. This is what he had.';
      else note = 'The clock beat you.';
    }
    if (tries && !result.correct) {
      note += ' You called: ' + result.guesses.join(', ') + '.';
    }
    $('revealNote').textContent = note;

    var acc = result.accuracy || 0;
    $('accNum').innerHTML = acc + '<small>%</small>';
    $('accFill').style.width = '0%';
    setTimeout(function () { $('accFill').style.width = acc + '%'; }, 60);
    $('accXp').textContent = '+' + Math.max(0, result.xp || 0) + ' XP' +
      (result.speed_bonus ? ' (' + result.speed_bonus + ' for speed)' : '');

    var box = $('revealScores');
    box.innerHTML = '';
    (result.rows || []).forEach(function (r) {
      var d = document.createElement('div');
      d.className = 'scorerow' + (r.got >= r.of ? ' full' : r.got === 0 ? ' none' : '');
      d.innerHTML =
        '<div><div class="what">' + esc(r.label) + '</div>' +
        '<div class="note">' + esc(r.note) + '</div></div>' +
        '<div class="got num">' + r.got + '<span style="opacity:.45">/' + r.of + '</span></div>';
      box.appendChild(d);
    });

    var jump = award(result);
    if (jump.after > jump.before) {
      $('levelUp').style.display = 'flex';
      $('luBadge').textContent = jump.after;
      $('luText').textContent = 'Level ' + jump.after + ' — ' + rankFor(jump.after);
      $('luSub').textContent = 'You were ' + rankFor(jump.before) + ' when you walked in.';
    } else {
      $('levelUp').style.display = 'none';
    }

    drawDebrief(result.debrief);
    drawLadder();
    show('reveal');
  }

  /* The teaching half. All of this was already written in the case file and
     never shown to anyone -- it only arrives once the round has resolved, so
     there is nothing here to leak mid-encounter. Collapsed by default: the
     score is the ending, this is for whoever wants it. */
  function drawDebrief(d) {
    var wrap = $('debrief'), body = $('debriefBody');
    if (!wrap || !body) return;
    if (!d) { wrap.style.display = 'none'; return; }

    var html = '';
    if (d.summary) html += '<p class="db-sum">' + esc(d.summary) + '</p>';

    if (d.threads && d.threads.length) {
      html += '<h4>The questions that mattered</h4><ol class="db-threads">';
      d.threads.forEach(function (t) {
        html += '<li><b>' + esc(t.question) + '</b><span>' + esc(t.why) + '</span></li>';
      });
      html += '</ol>';
    }

    if (d.traps && d.traps.length) {
      html += '<h4>What would have harmed him</h4><ul class="db-traps">';
      d.traps.forEach(function (t) {
        html += '<li><b>' + esc(t.what) + '</b> &mdash; ' + esc(t.why) + '</li>';
      });
      html += '</ul>';
    }

    if (d.management && d.management.length) {
      html += '<h4>What you would actually do</h4><ul class="db-list">';
      d.management.forEach(function (m) { html += '<li>' + esc(m) + '</li>'; });
      html += '</ul>';
    }

    if (d.pearls && d.pearls.length) {
      html += '<h4>Remember this</h4><ul class="db-pearls">';
      d.pearls.forEach(function (p) { html += '<li>' + esc(p) + '</li>'; });
      html += '</ul>';
    }

    if (d.guidelines && d.guidelines.length) {
      html += '<p class="db-refs">Real guidance this follows: ' +
              d.guidelines.map(esc).join(' &middot; ') + '</p>';
    }

    if (!html) { wrap.style.display = 'none'; return; }
    body.innerHTML = html;
    wrap.style.display = 'block';
    wrap.classList.remove('open');
    $('debriefToggle').innerHTML = 'What you should take away &#9662;';
  }

  /* -------------------------------------------------------------- flow */
  function toBrief() {
    $('briefTag').textContent = chosen.setting || 'Patient';
    $('briefName').textContent = chosen.name + ', ' + chosen.age;
    $('briefText').textContent = chosen.blurb;
    $('briefHint').textContent = '“' + chosen.opening + '”';

    var best = bestFor(chosen.id);
    $('briefMeta').innerHTML =
      '<span class="pill ' + (chosen.tier === 3 ? 'rose' : chosen.tier === 2 ? 'saff' : 'teal') + '">' +
        esc(chosen.rank || 'Resident') + '</span>' +
      '<span class="pill">up to ' + (chosen.xp || 0) + ' XP</span>' +
      '<span class="pill">' + (chosen.topics || 0) + ' threads to pull</span>' +
      (best === null ? '' : '<span class="pill plum">your best ' + best + '%</span>');
    show('brief');
  }

  function startRound(v) {
    sid = v.session;
    if (v.case) chosen = v.case;

    ending = false;
    pending = null;
    lastHr = null;
    lastSig = '';
    spoken = 0;
    triesLeft = v.tries_left != null ? v.tries_left : 5;
    triesAllowed = v.tries_allowed || 5;
    giveUpArmed = false;
    clearTimeout(giveUpTimer);
    $('btnGiveUp').textContent = 'I give up';
    $('dxMiss').style.display = 'none';
    $('dxInput').value = '';
    $('talk').innerHTML = '';
    $('encounter').classList.remove('draining', 'blank');
    show('encounter');

    if (!monitor) {
      monitor = new Monitor(900, 562);
    } else {
      monitor.revive();
    }
    /* No per-beat tick. A beep on every R peak is what a real bedside does
       and it drove everyone in the room mad within thirty seconds. The
       flatline tone stays, because that one has to land. */
    monitor.onBeat = null;

    buildRoom();
    if (room) {
      room.unfreeze();
      room.resetExams();
      room.setStatus('stable');
      if (chosen && chosen.look) room.setPatientLook(chosen.look);
    }

    startLoop();
    render(v);
    startPolling();
    $('ask').focus();
  }

  $('toCases').onclick = function () {
    audio();
    drawLadder();
    show('pick');
    refreshCases();
  };
  $('toProof').onclick = function () { openProof(); };
  $('statsBtn').onclick = function () { openStats(); };
  $('toStats').onclick = function () { openStats(); };

  /* back, one glyph in the same corner on every screen */
  $('pickBack').onclick = function () { show('splash'); };
  $('briefBack').onclick = function () { show('pick'); };
  $('debriefToggle').onclick = function () {
    var w = $('debrief'), open = w.classList.toggle('open');
    this.innerHTML = (open ? 'Hide that &#9652;' : 'What you should take away &#9662;');
  };

  $('revealBack').onclick = function () { $('againBtn').click(); };

  $('againBtn').onclick = function () {
    sid = null;
    proof = null;
    drawLadder();
    show('pick');
    refreshCases();
  };
  $('proofBtn').onclick = function () { openProof(); };

  function beginCase() {
    if (!chosen) { show('pick'); return; }
    audio();
    fetch(API + '/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case: chosen.id })
    }).then(function (r) { return r.json(); })
      .then(startRound)
      .catch(function () { toast('Could not start the round'); });
  }

  $('toEncounter').onclick = beginCase;

  /* Straight back in with the same patient. A fresh session, so the clock,
     the vitals and his guard all start over -- what you keep is the XP you
     already banked and the knowledge of what he is hiding. */
  $('replayBtn').onclick = function () {
    proof = null;
    $('reveal').classList.remove('on');
    beginCase();
  };

  /* ---------------------------------------------------------------- ask */
  function send() {
    var t = $('ask').value.trim();
    if (!t || pending || ending || !sid) return;
    $('ask').value = '';

    /* Your line and his three dots go up before the request leaves, so the
       screen answers the keypress rather than the network. */
    var talk = $('talk');
    talk.appendChild(bubble('you', 'You', t));
    var dots = thinking();
    talk.appendChild(dots);
    talk.scrollTop = talk.scrollHeight;
    pending = true;
    lastSig = '';                       // force a clean redraw when it lands

    fetch(API + '/ask/' + sid, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: t })
    }).then(function (r) { return r.json(); }).then(function (v) {
      pending = null;
      if (v.reason === 'wait') toast('Give him a second');
      else if (v.reason === 'over') toast('The round is over');
      render(v);
    }).catch(function () {
      pending = null;
      if (dots.parentNode) dots.parentNode.removeChild(dots);
      toast('Lost the server');
    });
  }

  /* Quick questions. Typing every line is slow on stage and slow for anyone
     who does not know what to ask a patient. These are deliberately generic:
     they used to be Kamal's, which meant two of the three written cases --
     and every case the model writes -- got a bar of questions about a wife
     who does not exist. */
  var QUICK = [
    ['What brings you in?',   'what brings you in tonight?'],
    ['How long?',             'how long has this been going on?'],
    ['Any pain?',             'are you in any pain?'],
    ['Medications?',          'what medications are you taking?'],
    ['Happened before?',      'has anything like this happened before?'],
    ['Anyone else unwell?',   'is anyone else at home feeling unwell?'],
    ['Be honest with me',     'be honest with me, what are you not telling me?']
  ];
  var qbar = $('quick');
  if (qbar) {
    QUICK.forEach(function (q) {
      var b = document.createElement('button');
      b.className = 'chip';
      b.textContent = q[0];
      b.onclick = function () { $('ask').value = q[1]; send(); };
      qbar.appendChild(b);
    });
  }

  $('btnAsk').onclick = send;
  $('ask').addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });

  /* ------------------------------------------------------------ examine */
  var examList = [];
  fetch(API + '/exams').then(function (r) { return r.json(); }).then(function (d) {
    examList = d.exams || [];
  }).catch(function () {});

  var ICONS = {
    general: '👁', hands: '🤲', hydration: '💧',
    cardiovascular: '🫀', respiratory: '🫁', abdominal: '🤰',
    neurological: '🧠', cognition: '💭', eyes: '👀',
    skin: '🩹', legs: '🦵', ent: '👂',
    genitourinary: '🚻', musculoskeletal: '🦴'
  };

  function drawExams(done) {
    $('examGrid').innerHTML = '';
    examList.forEach(function (e) {
      var el = document.createElement('div');
      var isDone = (done || []).indexOf(e.id) >= 0;
      el.className = 'exam' + (isDone ? ' done' : '');
      el.innerHTML = '<span class="ic">' + (ICONS[e.id] || '🩺') + '</span>' + esc(e.name);
      if (!isDone) {
        el.onclick = function () {
          runExam(e.id).then(function (v) {
            if (v && v.examined) drawExams(v.examined);
            sheet('examineSheet', false);
          });
        };
      }
      $('examGrid').appendChild(el);
    });
  }

  $('btnExamine').onclick = function () {
    if (!sid || ending) return;
    fetch(API + '/state/' + sid).then(function (r) { return r.json(); }).then(function (v) {
      drawExams(v.examined);
      sheet('examineSheet', true);
    }).catch(function () { toast('Lost the server'); });
  };
  $('closeExamine').onclick = function () { sheet('examineSheet', false); };

  /* ----------------------------------------------------------- diagnose */
  var triesLeft = 5;
  var triesAllowed = 5;

  function drawTries() {
    var el = $('dxTries');
    var spent = triesAllowed - triesLeft;
    var html = '';
    for (var i = 0; i < triesAllowed; i++) {
      html += '<i class="' + (i < spent ? 'spent' : '') + '"></i>';
    }
    html += '<b>' + triesLeft + ' of ' + triesAllowed + ' calls left</b>';
    el.innerHTML = html;
  }

  $('btnDiagnose').onclick = function () {
    if (!sid || ending) return;
    drawTries();
    $('dxMiss').style.display = 'none';
    $('dxInput').value = '';
    sheet('dxSheet', true);
    $('dxInput').focus();
  };
  $('closeDx').onclick = function () { sheet('dxSheet', false); };

  $('submitDx').onclick = function () {
    var t = $('dxInput').value.trim();
    if (!t || ending || !sid || submitDxBusy) return;
    submitDxBusy = true;

    fetch(API + '/diagnose/' + sid, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: t })
    }).then(function (r) { return r.json(); }).then(function (res) {
      submitDxBusy = false;

      /* A wrong call with tries left does not end anything. */
      if (res.resolved === false) {
        triesLeft = res.tries_left;
        triesAllowed = res.tries_allowed || triesAllowed;
        drawTries();
        $('dxInput').value = '';
        var m = $('dxMiss');
        m.textContent = res.partial
          ? 'Right area — but that is not the answer. ' + res.tries_left + ' left.'
          : 'Not that. ' + res.tries_left + ' left.';
        m.style.display = '';
        lastSig = '';
        render(res);
        $('dxInput').focus();
        return;
      }

      ending = true;
      sheet('dxSheet', false);
      endRound(res);
    }).catch(function () {
      submitDxBusy = false;
      toast('Lost the server');
    });
  };
  var submitDxBusy = false;

  $('dxInput').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') $('submitDx').click();
  });

  /* ------------------------------------------------------------ give up */
  $('btnGiveUp').onclick = function () {
    if (!sid || ending) return;
    if (giveUpArmed) { stopRound(true); return; }
    giveUpArmed = true;
    $('btnGiveUp').textContent = 'Sure? Click again';
    toast('Click again to walk away and see the answer');
    clearTimeout(giveUpTimer);
    giveUpTimer = setTimeout(function () {
      giveUpArmed = false;
      $('btnGiveUp').textContent = 'I give up';
    }, 4000);
  };
  var giveUpArmed = false;
  var giveUpTimer = null;

  /* ----------------------------------------------------------- generate */
  function showGen(state) {
    $('genForm').style.display = state === 'form' ? '' : 'none';
    $('genBusy').style.display = state === 'busy' ? '' : 'none';
    $('genErr').style.display  = state === 'err'  ? '' : 'none';
  }

  function genError(msg) {
    clearTimeout(genTimer);
    genJob = null;
    $('genErrMsg').textContent = msg;
    showGen('err');
  }

  Array.prototype.forEach.call($('genDiff').children, function (b) {
    b.onclick = function () {
      Array.prototype.forEach.call($('genDiff').children, function (o) {
        o.classList.toggle('on', o === b);
      });
      genDifficulty = b.getAttribute('data-v');
    };
  });

  $('closeGen').onclick = function () { sheet('genSheet', false); };
  $('genRetry').onclick = function () { showGen('form'); };
  $('genHide').onclick = function () {
    sheet('genSheet', false);
    toast('Still writing. It will appear in the list when it is done.');
  };

  $('genGo').onclick = function () {
    if (genJob) return;
    showGen('busy');
    $('genMsg').textContent = 'Writing the case…';
    fetch(API + '/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        brief: $('genBrief').value.trim(),
        specialty: $('genSpec').value.trim(),
        difficulty: genDifficulty
      })
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, body: j }; });
    }).then(function (res) {
      if (!res.ok || !res.body.job) {
        genError(res.body.message || 'The server would not start a case.');
        return;
      }
      genJob = res.body.job;
      pollGen();
    }).catch(function () { genError('Lost the server.'); });
  };

  function pollGen() {
    if (!genJob) return;
    fetch(API + '/generate/' + genJob)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error && d.state !== 'working') { genError(d.error); return; }
        $('genElapsed').textContent = (d.elapsed || 0) + 's';

        if (d.state === 'working') {
          var msgs = ['Writing the case…', 'Giving him a history…',
                      'Deciding what he will not tell you…', 'Checking it is safe to play…'];
          $('genMsg').textContent = msgs[Math.min(msgs.length - 1, Math.floor((d.elapsed || 0) / 22))];
          genTimer = setTimeout(pollGen, 2500);
          return;
        }
        if (d.state === 'done') {
          genJob = null;
          refreshCases().then(function () {
            sheet('genSheet', false);
            showGen('form');
            toast('New patient ready: ' + ((d.case && d.case.name) || 'case'));
          });
          return;
        }
        genError(d.error || 'The case could not be written.');
      })
      .catch(function () { genError('Lost the server.'); });
  }

  /* ------------------------------------------------------------- record */
  function openStats() {
    var n = progress.history.length;
    var hits = 0, sum = 0, bestAcc = 0;
    progress.history.forEach(function (h) {
      if (h.correct) hits++;
      sum += (h.accuracy || 0);
      if ((h.accuracy || 0) > bestAcc) bestAcc = h.accuracy || 0;
    });
    var L = levelFor(progress.xp);

    $('statTotals').innerHTML =
      '<div class="statbox"><div class="v">' + n + '</div><div class="k">cases</div></div>' +
      '<div class="statbox"><div class="v">' + hits + '</div><div class="k">called right</div></div>' +
      '<div class="statbox"><div class="v">' + (n ? Math.round(sum / n) : 0) + '%</div><div class="k">average</div></div>' +
      '<div class="statbox"><div class="v">' + bestAcc + '%</div><div class="k">best</div></div>' +
      '<div class="statbox"><div class="v">' + progress.xp + '</div><div class="k">total XP</div></div>' +
      '<div class="statbox"><div class="v">' + L.level + '</div><div class="k">level</div></div>';

    var list = $('historyList');
    list.innerHTML = '';
    if (!n) {
      list.innerHTML = '<div class="empty">Nothing yet. Finish a case and it shows up here.</div>';
    } else {
      progress.history.forEach(function (h) {
        var row = document.createElement('div');
        row.className = 'hrow';
        var when = '';
        try { when = new Date(h.at).toLocaleDateString(); } catch (e) {}
        row.innerHTML =
          '<div class="face">' + esc(h.avatar || '🧑') + '</div>' +
          '<div class="mid">' +
            '<div class="nm">' + esc(h.name || 'Patient') + '</div>' +
            '<div class="dx-line">' + esc(h.diagnosis || '') +
              (when ? ' · ' + esc(when) : '') + '</div>' +
          '</div>' +
          '<div class="verdict ' + (h.correct ? 'hit' : 'miss') + '">' +
            (h.correct ? 'called' : 'missed') + '</div>' +
          '<div class="pct">' + (h.accuracy || 0) + '%</div>';
        list.appendChild(row);
      });
    }
    sheet('statsSheet', true);
  }

  $('closeStats').onclick = function () { sheet('statsSheet', false); };
  $('wipeStats').onclick = function () {
    progress = { xp: 0, history: [] };
    saveProgress();
    drawLadder();
    drawCases();
    openStats();
    toast('Record cleared');
  };

  /* -------------------------------------------------------------- x-ray */
  var proof = null;
  function drawProof() {
    if (!proof) return;
    var q = $('proofSearch').value.trim();
    var body = esc(proof.prompt);
    var n = 0;
    if (q) {
      var rx = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
      body = body.replace(rx, function (m) {
        n++;
        return '<mark style="background:var(--rose);padding:1px 3px;border-radius:4px">' + m + '</mark>';
      });
    }
    $('proofText').innerHTML = body;
    var r = $('proofResult');
    if (!q) {
      r.className = 'pill';
      r.textContent = proof.chars.toLocaleString() + ' characters, sent exactly as you see them';
    } else if (n) {
      r.className = 'pill rose';
      r.textContent = n + ' match' + (n === 1 ? '' : 'es') + ' for "' + q + '"';
    } else {
      r.className = 'pill teal';
      r.textContent = '0 matches for "' + q + '". It is not in there.';
    }
  }

  function openProof() {
    var go = function () {
      sheet('proofSheet', true);
      setTimeout(function () { $('proofSearch').focus(); }, 60);
    };
    if (proof) { go(); return; }
    if (!sid) {
      /* from the splash, spin up a throwaway session just to read the prompt */
      fetch(API + '/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case: (chosen && chosen.id) || 'kamal' })
      }).then(function (r) { return r.json(); }).then(function (v) {
        loadProof(v.session, go);
      }).catch(function () { toast('Lost the server'); });
      return;
    }
    loadProof(sid, go);
  }
  function loadProof(id, then) {
    fetch(API + '/proof/' + id).then(function (r) { return r.json(); }).then(function (d) {
      proof = d;
      drawProof();
      then();
    }).catch(function () { toast('Lost the server'); });
  }
  $('proofSearch').addEventListener('input', drawProof);
  $('closeProof').onclick = function () { sheet('proofSheet', false); };

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      ['proofSheet', 'examineSheet', 'dxSheet', 'statsSheet', 'genSheet'].forEach(function (s) {
        sheet(s, false);
      });
    }
    if (document.activeElement &&
        (document.activeElement.tagName === 'INPUT' ||
         document.activeElement.tagName === 'TEXTAREA')) return;
    if (e.key === 'x' || e.key === 'X') openProof();
    if (e.key === 'm' || e.key === 'M') { muted = !muted; toast(muted ? 'Muted' : 'Sound on'); }
  });

  drawLadder();
})();
