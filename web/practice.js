/* The encounter. One learner, one patient, twelve minutes.
   Left: the patient (monitor, conversation). Right: the work (chart, examine,
   investigate, treat, notes). Bottom: commit. Then the debrief, in place. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var esc = Debrief.esc, mmss = Debrief.mmss;
  var encId = location.pathname.split('/').pop();
  var enc = null, catalog = null, ecg = null, raf = null, pollT = null;
  var tab = 'chart', clockBase = 0, clockAt = 0, lastSeenPhase = null, differentials = [];
  var voiceOn = false;
  var feedSig = null, feedSeen = 0;

  function drawVoiceBtn() {
    var b = $('voiceBtn');
    if (!b) return;
    b.innerHTML = voiceOn ? '&#128266; Voice on' : '&#128264; Voice off';
    b.setAttribute('aria-pressed', voiceOn ? 'true' : 'false');
  }

  var MOOD = {
    guarded: ['🛡', 'Guarded', 'dim'], uneasy: ['😕', 'Uneasy', 'dim'],
    defensive: ['✋', 'Defensive', 'warn'], resigned: ['😔', 'Resigned', 'warn'],
    rattled: ['😬', 'Rattled', 'bad'], scared: ['😨', 'Scared', 'bad'], pleading: ['🙏', 'Pleading', 'bad']
  };

  function api(path, body, method) {
    return fetch(path, { method: method || (body ? 'POST' : 'GET'), headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined, credentials: 'same-origin' })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.status === 401) { location.href = '/app/login?next=' + encodeURIComponent(location.pathname); throw new Error('Sign in'); }
        if (!r.ok) throw new Error(d.detail || 'Request failed'); return d; }); });
  }
  var toastT = null;
  function toast(msg, bad) { var t = $('toast'); t.textContent = msg; t.className = 'toast show' + (bad ? ' bad' : ''); clearTimeout(toastT); toastT = setTimeout(function () { t.className = 'toast'; }, 3000); }
  function fail(e) { toast(e.message || String(e), true); }
  function modal(html, sticky) { $('modalBody').innerHTML = html; $('modal').classList.add('show'); $('modal').dataset.sticky = sticky ? '1' : ''; }
  function closeModal() { if ($('modal').dataset.sticky) return; $('modal').classList.remove('show'); }
  $('modal').addEventListener('click', function (e) { if (e.target === $('modal')) closeModal(); });

  /* ------------------------------------------------------------- shell */
  function shell() {
    var c = enc.chart;
    $('root').innerHTML = '<div class="enc">' +
      '<div class="enc-top"><a class="brand" href="/app"><span class="mark">YH</span></a>' +
      '<div class="who">' + esc(c.name) + '<span>' + c.age + (c.sex ? ' · ' + c.sex : '') + '</span></div>' +
      '<span class="mood dim" id="mood"></span><div class="spacer"></div>' +
      '<button class="btn ghost sm" id="voiceBtn" title="Hear the patient speak" aria-pressed="false">&#128264; Voice off</button>' +
      '<span class="chip" id="monitorChip">stable</span><span class="clock num" id="clock">12:00</span>' +
      '<button class="btn primary" id="commit">Commit diagnosis</button></div>' +
      '<div class="enc-body">' +
      '<div class="patient-col"><div class="monitor"><canvas id="ecg"></canvas><div class="vitals">' +
      '<div class="vital"><div class="lbl">Heart rate</div><div class="val num" id="vHr">—<small>bpm</small></div></div>' +
      '<div class="vital"><div class="lbl">SpO₂</div><div class="val num" id="vSpo2">—<small>%</small></div></div>' +
      '<div class="vital"><div class="lbl">BP</div><div class="val num" id="vBp">—<small>mmHg</small></div></div>' +
      '<div class="vital"><div class="lbl">Resp</div><div class="val num" id="vRr">—<small>/min</small></div></div></div></div>' +
      '<div class="feed" id="feed"></div>' +
      '<form class="ask" id="askForm"><input id="ask" autocomplete="off" placeholder="Ask the patient anything…" maxlength="300">' +
      '<button class="btn ghost mic" type="button" id="micBtn" title="Talk to the patient" aria-label="Talk to the patient" aria-pressed="false" style="display:none">&#127908;</button>' +
      '<button class="btn primary" type="submit" id="askBtn">Ask</button></form></div>' +
      '<div class="work-col"><div class="work-tabs" id="tabs">' +
      ['chart|Chart', 'examine|Examine', 'investigate|Investigate', 'treat|Treat', 'notes|Notes'].map(function (t) { var p = t.split('|'); return '<button data-tab="' + p[0] + '"' + (p[0] === tab ? ' class="active"' : '') + '>' + p[1] + '<span class="count hide" id="cnt-' + p[0] + '"></span></button>'; }).join('') +
      '</div><div class="work" id="work"></div></div></div></div>';
    ecg = new Ecg($('ecg'));
    $('tabs').querySelectorAll('button').forEach(function (b) { b.onclick = function () { tab = b.dataset.tab; $('tabs').querySelectorAll('button').forEach(function (x) { x.classList.toggle('active', x === b); }); renderWork(); }; });
    $('askForm').onsubmit = ask;
    Voice.attach($('micBtn'), $('ask'), function () { $('askForm').requestSubmit(); });
    if (!Voice.canSpeak) $('voiceBtn').style.display = 'none';
    try { voiceOn = localStorage.getItem('yh_voice') === '1'; } catch (e) {}
    drawVoiceBtn();
    $('voiceBtn').onclick = function () {
      voiceOn = !voiceOn;
      if (!voiceOn) Voice.hush();
      try { localStorage.setItem('yh_voice', voiceOn ? '1' : '0'); } catch (e) {}
      drawVoiceBtn();
    };
    $('commit').onclick = function () { openCommit(false); };
    document.addEventListener('keydown', function (e) { if (e.key === '/' && document.activeElement !== $('ask')) { e.preventDefault(); $('ask').focus(); } });
    loop();
  }

  function loop() {
    function frame(now) {
      ecg.frame(now);
      var left = clockBase - (now - clockAt) / 1000;
      $('clock').textContent = mmss(left);
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
  }

  /* ------------------------------------------------------------ render */
  function apply(d, opts) {
    var v = d.view;
    enc = d;
    clockBase = v.seconds_left; clockAt = performance.now();
    $('vHr').innerHTML = v.vitals.hr + '<small>bpm</small>';
    $('vSpo2').innerHTML = v.vitals.spo2 + '<small>%</small>';
    $('vBp').innerHTML = v.vitals.bp + '<small>mmHg</small>';
    $('vRr').innerHTML = v.vitals.rr + '<small>/min</small>';
    ['vHr', 'vSpo2', 'clock'].forEach(function (id) { $(id).className = ($(id).className.replace(/status-\S+/g, '') + ' status-' + v.monitor).trim(); });
    $('monitorChip').textContent = v.monitor;
    $('monitorChip').className = 'chip ' + ({ stable: 'ok', declining: 'warn', critical: 'bad', flatline: '' }[v.monitor] || '');
    ecg.set(v.vitals.hr, v.monitor);
    var m = MOOD[v.mood];
    $('mood').className = 'mood ' + (m ? m[2] : 'dim');
    $('mood').textContent = m ? m[0] + ' ' + m[1] : '';

    /* Polled every few seconds: rebuild the conversation only when it changed,
       and animate only messages the learner has not seen yet. */
    var feed = $('feed'), atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
    var thinking = !!(opts && opts.thinking);
    var lastMsg = v.messages[v.messages.length - 1];
    var sig = v.messages.length + '|' + (lastMsg ? lastMsg.kind + ':' + lastMsg.text : '') + '|' + thinking;
    if (sig !== feedSig) {
      feed.innerHTML = v.messages.map(function (msg, i) {
        var who = msg.kind === 'reply' ? enc.chart.name : msg.kind === 'question' ? 'You' : 'Nurse';
        return '<div class="msg ' + msg.kind + (i >= feedSeen ? ' new' : '') + '"><span class="who">' + esc(who) + ' · ' + mmss(msg.t) + '</span>' + esc(msg.text) + '</div>';
      }).join('') + (thinking ? '<div class="msg reply thinking new"><span class="who">' + esc(enc.chart.name) + '</span>…</div>' : '');
      feedSeen = v.messages.length;
      feedSig = sig;
    }
    if (atBottom || (opts && opts.scroll)) feed.scrollTop = feed.scrollHeight;

    $('cnt-examine').textContent = v.exams.length; $('cnt-examine').classList.toggle('hide', !v.exams.length);
    var pending = v.investigations.filter(function (i) { return !i.ready; }).length, ready = v.investigations.length - pending;
    $('cnt-investigate').textContent = pending ? pending + '…' : ready; $('cnt-investigate').classList.toggle('hide', !v.investigations.length);
    $('cnt-treat').textContent = v.treatments.length; $('cnt-treat').classList.toggle('hide', !v.treatments.length);

    if (v.status !== 'active' && lastSeenPhase === 'active') {
      if (v.outcome === 'arrested') { ecg.kill(); document.body.classList.add('codeRed'); setTimeout(function () { document.body.classList.remove('codeRed'); }, 900); }
      openCommit(true);
    }
    if (v.status !== 'active') { $('ask').disabled = true; $('askBtn').disabled = true; $('ask').placeholder = v.outcome === 'arrested' ? 'The patient has arrested.' : 'Time is up.'; }
    lastSeenPhase = v.status;
    if (d.report) { showDebrief(d); return; }
    renderWork();
  }

  function renderWork() {
    var v = enc.view, c = enc.chart, w = $('work');
    if (tab === 'chart') {
      var h = c.history || {}, p = c.presentation || {}, t = c.vitals_at_triage || {};
      function li(arr) { return arr && arr.length ? '<ul>' + arr.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '<span class="muted">Not recorded</span>'; }
      w.innerHTML = '<div class="chart"><div class="card tight" style="margin-bottom:12px"><h3>' + esc(c.title || 'Presentation') + '</h3><p class="muted" style="margin:0 0 8px">' + esc(c.setting || '') + '</p>' +
        '<dl><dt>Complaint</dt><dd><b>' + esc(p.complaint || '') + '</b></dd><dt>Duration</dt><dd>' + esc(p.duration || '') + '</dd><dt>Triage note</dt><dd>' + esc(p.triage_note || '') + '</dd>' +
        '<dt>Obs at triage</dt><dd class="num">HR ' + t.hr + ' · SpO₂ ' + t.spo2 + '% · BP ' + t.bp + ' · RR ' + t.rr + '</dd></dl></div>' +
        '<div class="card tight" style="margin-bottom:12px"><h3>About the patient</h3><p style="margin:0">' + esc(c.description || '') + '</p></div>' +
        '<div class="card tight"><h3>Records</h3><dl><dt>Past medical</dt><dd>' + li(h.past_medical) + '</dd><dt>Medications</dt><dd>' + li(h.medications) + '</dd><dt>Allergies</dt><dd>' + li(h.allergies) + '</dd></dl>' +
        '<p class="muted" style="margin:10px 0 0;font-size:13px">Social and family history are not in the record. Ask.</p></div></div>';
    } else if (tab === 'examine') {
      var done = {}; v.exams.forEach(function (e) { done[e.id] = e; });
      w.innerHTML = '<div class="muted" style="font-size:13px;margin-bottom:10px">Tap a system to examine it. Findings appear here and in the debrief timeline.</div>' +
        catalog.exams.map(function (e) {
          var f = done[e.id];
          return f ? '<div class="finding"><b>' + esc(e.name) + ' · ' + mmss(f.t) + '</b>' + esc(f.finding) + '</div>' :
            '<button class="opt" style="width:100%;text-align:left;cursor:pointer;font:inherit;color:inherit" data-exam="' + esc(e.id) + '"><span>' + esc(e.name) + '</span><span class="meta">Examine →</span></button>';
        }).join('');
      w.querySelectorAll('[data-exam]').forEach(function (b) { b.onclick = function () { act('/examine', { exam_id: b.dataset.exam }, b); }; });
    } else if (tab === 'investigate') {
      var ordered = {}; v.investigations.forEach(function (o) { ordered[o.id] = o; });
      var groups = {}; catalog.investigations.forEach(function (i) { (groups[i.group] = groups[i.group] || []).push(i); });
      var results = v.investigations.slice().sort(function (a, b) { return a.ordered_t - b.ordered_t; }).map(function (o) {
        return o.ready ? '<div class="finding' + (o.abnormal ? ' abn' : '') + '"><b>' + esc(o.name) + (o.abnormal ? ' · <span style="color:var(--warn)">abnormal</span>' : ' · normal') + '</b>' + esc(o.text) + '</div>'
          : '<div class="finding pending"><b>' + esc(o.name) + '</b>Result in ' + o.eta_seconds + 's…</div>';
      }).join('');
      w.innerHTML = (results ? '<div style="margin-bottom:14px">' + results + '</div>' : '<div class="muted" style="font-size:13px;margin-bottom:10px">Order investigations. Results take realistic time — bedside tests are fast, imaging is not.</div>') +
        Object.keys(groups).map(function (g) {
          return '<div class="group">' + esc(g) + '</div>' + groups[g].map(function (i) {
            var o = ordered[i.id];
            return '<button class="opt' + (o ? ' done' : '') + '" style="width:100%;text-align:left;cursor:pointer;font:inherit;color:inherit" data-test="' + esc(i.id) + '"' + (o ? ' disabled' : '') + '><span>' + esc(i.name) + '</span><span class="meta">' + (o ? (o.ready ? 'Resulted' : 'Pending') : '~' + i.minutes + ' min') + '</span></button>';
          }).join('');
        }).join('');
      w.querySelectorAll('[data-test]').forEach(function (b) { b.onclick = function () { act('/order', { test_id: b.dataset.test }, b); }; });
    } else if (tab === 'treat') {
      var given = {}; v.treatments.forEach(function (x) { given[x.id] = x; });
      var tg = {}; catalog.treatments.forEach(function (t) { (tg[t.group] = tg[t.group] || []).push(t); });
      w.innerHTML = '<div class="muted" style="font-size:13px;margin-bottom:6px">Treatments take effect on the monitor. You will learn in the debrief which ones helped, which were harmful, and why.</div>' +
        Object.keys(tg).map(function (g) {
          return '<div class="group">' + esc(g) + '</div>' + tg[g].map(function (t) {
            var x = given[t.id];
            return '<button class="opt' + (x ? ' done' : '') + '" style="width:100%;text-align:left;cursor:pointer;font:inherit;color:inherit" data-treat="' + esc(t.id) + '"' + (x ? ' disabled' : '') + '><span>' + esc(t.name) + '</span><span class="meta">' + (x ? 'Given ' + mmss(x.t) : 'Give →') + '</span></button>';
          }).join('');
        }).join('');
      w.querySelectorAll('[data-treat]').forEach(function (b) { b.onclick = function () { act('/treat', { treatment_id: b.dataset.treat }, b); }; });
    } else if (tab === 'notes') {
      w.innerHTML = '<label>Your working notes</label><textarea id="notes" style="min-height:52vh" placeholder="Problem list, differentials, what you want to rule out…">' + esc(v.notes || '') + '</textarea><div class="help">Saved automatically. Notes count toward your plan in the debrief.</div>';
      var t = null;
      $('notes').oninput = function () { clearTimeout(t); t = setTimeout(function () { api('/api/encounters/' + encId + '/notes', { notes: $('notes').value }).catch(function () {}); }, 800); };
    }
  }

  function act(path, body, btn) {
    if (btn) btn.disabled = true;
    api('/api/encounters/' + encId + path, body).then(function (d) { apply(d); })
      .catch(function (e) { fail(e); if (btn) btn.disabled = false; });
  }

  function ask(e) {
    e.preventDefault();
    var text = $('ask').value.trim();
    if (!text) return;
    $('ask').value = ''; $('askBtn').disabled = true;
    var optimistic = JSON.parse(JSON.stringify(enc));
    optimistic.view.messages = optimistic.view.messages.concat([{ who: 'learner', text: text, kind: 'question', t: optimistic.view.elapsed }]);
    apply(optimistic, { thinking: true, scroll: true });
    api('/api/encounters/' + encId + '/ask', { text: text }).then(function (d) {
      apply(d, { scroll: true });
      if (voiceOn && d.reply) Voice.speak(d.reply, { sex: enc.chart.sex, age: enc.chart.age });
    })
      .catch(function (err) {
        /* The question never reached the patient: take the optimistic copy
           back off the screen and give the learner their words back. */
        fail(err);
        $('ask').value = text;
        return api('/api/encounters/' + encId).then(function (d) { apply(d); }).catch(function () {});
      })
      .finally(function () { if (enc.view.status === 'active') { $('askBtn').disabled = false; $('ask').focus(); } });
  }

  /* ------------------------------------------------------------ commit */
  function openCommit(forced) {
    var v = enc.view;
    var banner = forced ? '<div class="error" style="margin-bottom:14px">' + (v.outcome === 'arrested' ? 'The patient has gone into cardiac arrest. The encounter is over — commit to what you would have said.' : 'Time is up. Commit to your diagnosis and plan.') + '</div>' : '';
    modal('<h2>Commit</h2>' + banner + '<form id="f">' +
      '<div class="field"><label>Working diagnosis</label><input name="diagnosis" required placeholder="What is wrong with this patient?" autofocus></div>' +
      '<div class="field"><label>Differentials <span class="muted">(press Enter to add)</span></label><input id="diffIn" placeholder="Add a differential…"><div class="chips" id="diffs" style="margin-top:8px"></div></div>' +
      '<div class="field"><label>Immediate plan</label><textarea name="plan" placeholder="What you will do in the next hour, and who you will call."></textarea></div>' +
      '<div class="field"><label>Reasoning</label><textarea name="reasoning" placeholder="Which findings drove your diagnosis? What would change your mind?" style="min-height:70px"></textarea></div>' +
      '<div class="row">' + (forced ? '' : '<button class="btn ghost" type="button" id="cancel">Keep working</button>') + '<span class="spacer"></span><button class="btn primary lg" type="submit">Submit for debrief</button></div></form>', forced);
    function drawDiffs() { $('diffs').innerHTML = differentials.map(function (d, i) { return '<span class="chip">' + esc(d) + ' <button type="button" data-i="' + i + '">×</button></span>'; }).join(''); $('diffs').querySelectorAll('button').forEach(function (b) { b.onclick = function () { differentials.splice(+b.dataset.i, 1); drawDiffs(); }; }); }
    drawDiffs();
    $('diffIn').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); var val = $('diffIn').value.trim(); if (val && differentials.length < 5) { differentials.push(val); $('diffIn').value = ''; drawDiffs(); } } });
    if ($('cancel')) $('cancel').onclick = function () { $('modal').classList.remove('show'); };
    $('f').onsubmit = function (e) {
      e.preventDefault(); var b = e.target.querySelector('[type=submit]'); b.disabled = true; b.textContent = 'The attending is reviewing your encounter…';
      var fd = new FormData(e.target);
      api('/api/encounters/' + encId + '/submit', { diagnosis: fd.get('diagnosis'), differentials: differentials, plan: fd.get('plan'), reasoning: fd.get('reasoning') })
        .then(function (d) { $('modal').dataset.sticky = ''; $('modal').classList.remove('show'); showDebrief(d); })
        .catch(function (err) { fail(err); b.disabled = false; b.textContent = 'Submit for debrief'; });
    };
  }

  function showDebrief(d) {
    if (raf) cancelAnimationFrame(raf); clearInterval(pollT);
    document.title = 'Debrief — Ya Hakim';
    api('/api/encounters/' + encId + '/report').then(function (r) {
      var actions = '<div class="row wrap no-print"><a class="btn" href="/app">← Home</a><a class="btn" href="/app/progress">My progress</a><button class="btn" onclick="window.print()">Print / PDF</button><button class="btn primary" id="again">Attempt again</button></div>';
      Debrief.render($('root'), r, { actions: actions, transcript: false });
      document.querySelectorAll('#again').forEach(function (b) { b.onclick = function () { api('/api/encounters', { case_id: r.case_id }).then(function (x) { location.href = '/practice/' + x.id; }).catch(fail); }; });
      window.scrollTo(0, 0);
    }).catch(fail);
  }

  /* -------------------------------------------------------------- boot */
  Promise.all([api('/api/encounters/' + encId), api('/api/catalog')]).then(function (res) {
    enc = res[0]; catalog = res[1];
    if (enc.report) { return showDebrief(enc); }
    shell();
    lastSeenPhase = enc.view.status;
    apply(enc, { scroll: true });
    if (enc.view.status !== 'active') openCommit(true);
    pollT = setInterval(function () {
      if (document.hidden) return;
      api('/api/encounters/' + encId).then(function (d) { if (!d.report) apply(d); }).catch(function () {});
    }, 2500);
    setTimeout(function () { $('ask').focus(); }, 200);
  }).catch(function (e) { $('root').innerHTML = '<div class="page wrap"><div class="error">' + esc(e.message) + '</div><p style="margin-top:12px"><a class="btn" href="/app">Back to the app</a></p></div>'; });
})();
