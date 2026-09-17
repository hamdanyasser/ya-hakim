/* Ya Hakim v2 -- one screen, five states.
   splash -> pick -> brief -> encounter -> reveal, with the examine, diagnose
   and x-ray sheets on top of the encounter. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var API = '/api/v2';

  var sid = null;
  var chosen = null;
  var cases = [];
  var ecg = null;
  var raf = null;
  var lastHr = null;
  var poll = null;
  var spoken = 0;
  var flatlined = false;

  var MOOD = {
    guarded:   ['🛡', 'Guarded',   ''],
    defensive: ['✋', 'Defensive', 'saff'],
    rattled:   ['😬', 'Rattled',   'clay'],
    scared:    ['😨', 'Scared',    'rose'],
    resigned:  ['😔', 'Resigned',  'teal'],
    gone:      ['🕯', 'Gone',      '']
  };

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function show(id) {
    ['splash', 'pick', 'brief', 'reveal'].forEach(function (s) {
      $(s).classList.toggle('on', s === id);
    });
    $('encounter').classList.toggle('on', id === 'encounter');
  }

  function toast(msg) {
    var t = $('toast');
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { t.classList.remove('on'); }, 2400);
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
      tone._g.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
      tone.stop(t + 0.07); tone = null;
    }
  }
  function speak(text) {
    if (!window.speechSynthesis) return;
    try {
      var u = new SpeechSynthesisUtterance(text);
      u.rate = 0.97; u.pitch = 0.86;
      speechSynthesis.speak(u);
    } catch (e) {}
  }

  /* -------------------------------------------------------------- render */
  function fmt(s) {
    s = Math.max(0, s | 0);
    return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
  }

  function render(v) {
    if (!v || !v.name) return;
    $('eName').textContent = v.name;
    $('eMeta').textContent = v.age + ' years old';
    $('avatar').textContent = v.avatar || '🧑';

    var m = MOOD[v.mood] || MOOD.guarded;
    $('moodPill').textContent = m[0] + ' ' + m[1];
    $('moodPill').className = 'pill ' + (m[2] || '');

    $('vHr').innerHTML = v.vitals.hr + '<small>bpm</small>';
    $('vSpo2').innerHTML = v.vitals.spo2 + '<small>%</small>';
    $('vBp').innerHTML = v.vitals.bp + '<small>mmHg</small>';
    $('vRr').innerHTML = v.vitals.rr + '<small>/min</small>';
    spo2 = v.vitals.spo2;

    $('clock').textContent = fmt(v.seconds_left);
    $('clock').className = 'clock num' +
      (v.status === 'critical' ? ' bad' : v.status === 'declining' ? ' warn' : '');

    if (ecg) ecg.set(v.vitals.hr, v.status);

    /* the tell: his pulse jumps while his mouth stays calm */
    if (lastHr !== null && v.vitals.hr - lastHr >= 9 && !v.over) {
      var c = $('cHr');
      c.classList.remove('tell'); void c.offsetWidth; c.classList.add('tell');
      setTimeout(function () { c.classList.remove('tell'); }, 5000);
    }
    lastHr = v.vitals.hr;

    var talk = $('talk');
    talk.innerHTML = '';
    v.log.forEach(function (l) {
      var d = document.createElement('div');
      d.className = 'bubble ' + l.kind;
      d.innerHTML = '<div class="lbl">' + esc(l.who) + '</div>' +
                    '<div class="msg">' + esc(l.text) + '</div>';
      talk.appendChild(d);
    });
    talk.scrollTop = talk.scrollHeight;

    for (var i = spoken; i < v.log.length; i++) {
      if (v.log[i].kind === 'him') speak(v.log[i].text);
    }
    spoken = v.log.length;

    if (v.over && !flatlined) flatline();
  }

  /* ------------------------------------------------------------ the loop */
  function frame(now) {
    if (ecg) ecg.frame(now);
    raf = requestAnimationFrame(frame);
  }

  function startPolling() {
    clearInterval(poll);
    poll = setInterval(function () {
      fetch(API + '/state/' + sid).then(function (r) { return r.json(); }).then(render);
    }, 1000);
  }

  /* ------------------------------------------------------------ the end */
  function flatline() {
    flatlined = true;
    clearInterval(poll);
    try { speechSynthesis.cancel(); } catch (e) {}
    if (ecg) { ecg.onBeat = null; ecg.kill(); ecg.draw(); }
    flatTone(true);
    $('encounter').classList.add('draining');

    setTimeout(function () {
      flatTone(false);
      $('encounter').classList.add('blank');
      if (raf) { cancelAnimationFrame(raf); raf = null; }
      setTimeout(showReveal, 2000);     /* two seconds of nothing */
    }, 1200);
  }

  function showReveal(result) {
    $('encounter').classList.remove('on', 'draining', 'blank');
    if (result) {
      $('revealTag').textContent = result.correct ? 'You called it' : 'Wrong call';
      $('revealTag').className = 'pill ' + (result.correct ? 'teal' : 'rose');
      $('revealDx').textContent = result.diagnosis;
      $('revealNote').textContent = result.note ||
        (result.correct ? 'He died. You were right.' : 'He died. Nobody called it.');
      var box = $('revealScores');
      box.innerHTML = '';
      (result.breakdown || []).forEach(function (row) {
        var d = document.createElement('div');
        d.className = 'scorerow';
        d.innerHTML = '<span>' + esc(row[0]) + '</span><span class="num">+' + row[1] + '</span>';
        box.appendChild(d);
      });
      var tot = document.createElement('div');
      tot.className = 'scorerow';
      tot.style.background = 'var(--saffron)';
      tot.innerHTML = '<span>Total</span><span class="num">' + result.score + '</span>';
      box.appendChild(tot);
    } else {
      $('revealTag').textContent = 'Time up';
      $('revealTag').className = 'pill rose';
      $('revealDx').textContent = '';
      $('revealNote').textContent = 'The clock beat you. Open the answer below.';
      fetch(API + '/diagnose/' + sid, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: '' })
      }).then(function (r) { return r.json(); }).then(function (d) {
        $('revealDx').textContent = d.diagnosis;
        if (d.note) $('revealNote').textContent = d.note;
      });
    }
    show('reveal');
  }

  /* -------------------------------------------------------------- flow */
  fetch(API + '/cases').then(function (r) { return r.json(); }).then(function (d) {
    cases = d.cases;
    $('caseList').innerHTML = '';
    cases.forEach(function (c) {
      var el = document.createElement('div');
      el.className = 'case';
      el.innerHTML =
        '<div class="face" style="background:var(--' +
          ({ kamal: 'saffron', rita: 'sky', georges: 'plum' }[c.id] || 'teal') + ')">' +
          c.avatar + '</div>' +
        '<div class="who">' + esc(c.name) + '</div>' +
        '<div class="sub">' + c.age + ' &middot; ' + esc(c.setting) + '</div>' +
        '<div class="blurb">' + esc(c.blurb) + '</div>';
      el.onclick = function () { chosen = c; toBrief(); };
      $('caseList').appendChild(el);
    });
  });

  function toBrief() {
    $('briefTag').textContent = chosen.setting || 'Patient';
    $('briefName').textContent = chosen.name + ', ' + chosen.age;
    $('briefText').textContent = chosen.blurb;
    $('briefHint').textContent = '“' + chosen.opening + '”';
    show('brief');
  }

  $('toCases').onclick = function () { audio(); show('pick'); };
  $('toProof').onclick = function () { openProof(); };
  $('againBtn').onclick = function () { location.reload(); };
  $('proofBtn').onclick = function () { openProof(); };

  $('toEncounter').onclick = function () {
    audio();
    fetch(API + '/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case: chosen.id })
    }).then(function (r) { return r.json(); }).then(function (v) {
      sid = v.session;
      show('encounter');
      if (!ecg) {
        ecg = new Ecg($('ecg'));
        ecg.onBeat = beep;
        raf = requestAnimationFrame(frame);
      }
      render(v);
      startPolling();
      $('ask').focus();
    });
  };

  function send() {
    var t = $('ask').value.trim();
    if (!t) return;
    $('ask').value = '';
    fetch(API + '/ask/' + sid, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: t })
    }).then(function (r) { return r.json(); }).then(function (v) {
      if (v.reason === 'wait') toast('Give him a second');
      else if (v.reason === 'over') toast('The round is over');
      render(v);
    }).catch(function () { toast('Lost the server'); });
  }
  $('btnAsk').onclick = send;
  $('ask').addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });

  /* ------------------------------------------------------------ examine */
  var examList = [];
  fetch(API + '/exams').then(function (r) { return r.json(); }).then(function (d) {
    examList = d.exams;
  });

  var ICONS = {
    general: '👁', hands: '🤲', hydration: '💧', cardiovascular: '🫀',
    respiratory: '🫁', abdominal: '🤰', neurological: '🧠', cognition: '💭',
    eyes: '👀', skin: '🩹', legs: '🦵', ent: '👂',
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
          fetch(API + '/examine/' + sid, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ exam: e.id })
          }).then(function (r) { return r.json(); }).then(function (v) {
            render(v);
            drawExams(v.examined);
            $('examineSheet').classList.remove('on');
          });
        };
      }
      $('examGrid').appendChild(el);
    });
  }

  $('btnExamine').onclick = function () {
    fetch(API + '/state/' + sid).then(function (r) { return r.json(); }).then(function (v) {
      drawExams(v.examined);
      $('examineSheet').classList.add('on');
    });
  };
  $('closeExamine').onclick = function () { $('examineSheet').classList.remove('on'); };

  /* ----------------------------------------------------------- diagnose */
  $('btnDiagnose').onclick = function () { $('dxSheet').classList.add('on'); $('dxInput').focus(); };
  $('closeDx').onclick = function () { $('dxSheet').classList.remove('on'); };
  $('submitDx').onclick = function () {
    var t = $('dxInput').value.trim();
    if (!t) return;
    $('dxSheet').classList.remove('on');
    fetch(API + '/diagnose/' + sid, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: t })
    }).then(function (r) { return r.json(); }).then(function (res) {
      clearInterval(poll);
      flatlined = true;
      if (ecg) { ecg.onBeat = null; ecg.kill(); ecg.draw(); }
      flatTone(true);
      $('encounter').classList.add('draining');
      setTimeout(function () {
        flatTone(false);
        $('encounter').classList.add('blank');
        if (raf) { cancelAnimationFrame(raf); raf = null; }
        setTimeout(function () { showReveal(res); }, 2000);
      }, 1200);
    });
  };
  $('dxInput').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') $('submitDx').click();
  });

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
    var go = function () { $('proofSheet').classList.add('on'); setTimeout(function () { $('proofSearch').focus(); }, 60); };
    if (proof) { go(); return; }
    var id = sid;
    if (!id) {
      /* from the splash, spin up a throwaway session just to read the prompt */
      fetch(API + '/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case: 'kamal' })
      }).then(function (r) { return r.json(); }).then(function (v) {
        loadProof(v.session, go);
      });
      return;
    }
    loadProof(id, go);
  }
  function loadProof(id, then) {
    fetch(API + '/proof/' + id).then(function (r) { return r.json(); }).then(function (d) {
      proof = d;
      drawProof();
      then();
    });
  }
  $('proofSearch').addEventListener('input', drawProof);
  $('closeProof').onclick = function () { $('proofSheet').classList.remove('on'); };

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      $('proofSheet').classList.remove('on');
      $('examineSheet').classList.remove('on');
      $('dxSheet').classList.remove('on');
    }
    if (document.activeElement && document.activeElement.tagName === 'INPUT') return;
    if (e.key === 'x' || e.key === 'X') openProof();
    if (e.key === 'm' || e.key === 'M') { muted = !muted; toast(muted ? 'Muted' : 'Monitor on'); }
  });
})();
