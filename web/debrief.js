/* The debrief renderer. Shared by the encounter page (right after submitting)
   and the app (instructors reviewing any report). Pure DOM, no state. */
(function (global) {
  'use strict';

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function mmss(s) { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function ringColour(total) { return total >= 70 ? 'var(--ok)' : total >= 50 ? 'var(--warn)' : 'var(--bad)'; }

  function domain(d) {
    var pct = d.max ? Math.round(100 * d.score / d.max) : 0;
    var cls = pct >= 70 ? '' : pct >= 45 ? 'warn' : 'bad';
    var items = d.items.map(function (it) {
      var tick = it.met ? 'yes' : (it.partial ? 'half' : 'no');
      var sym = it.met ? '✓' : (it.partial ? '~' : (it.harm ? '!' : '✕'));
      return '<div class="it"><span class="tick ' + tick + '">' + sym + '</span><div>' + esc(it.label) +
        (it.detail ? '<small>' + esc(it.detail) + '</small>' : '') + '</div></div>';
    }).join('');
    return '<div class="card domain"><div class="head"><b>' + esc(d.name) + '</b><span class="num">' + d.score + ' / ' + d.max +
      '</span></div><div class="bar ' + cls + '"><i style="width:' + pct + '%"></i></div>' +
      '<div class="items">' + items + '</div></div>';
  }

  function render(el, data, opts) {
    opts = opts || {};
    var r = data.report, n = r.narrative || {};
    var dx = r.diagnosis || {};
    var learner = data.learner && data.learner.name ? data.learner.name : null;
    var outcome = { arrested: 'The patient arrested', time_up: 'Time ran out', submitted: 'Submitted in time' }[r.outcome] || '';
    var head = '<div class="card hero" style="margin-bottom:18px">' +
      '<div class="score-ring" style="--p:' + r.total + ';--ring:' + ringColour(r.total) + '"><div><b>' + r.total + '</b><small>grade ' + esc(r.grade) + '</small></div></div>' +
      '<div><div class="row wrap" style="margin-bottom:6px">' +
      (learner ? '<span class="chip info">' + esc(learner) + '</span>' : '') +
      (r.specialty ? '<span class="chip">' + esc(r.specialty) + '</span>' : '') +
      '<span class="chip ' + (r.outcome === 'submitted' ? 'ok' : 'bad') + '">' + esc(outcome) + '</span>' +
      (r.duration != null ? '<span class="chip">' + mmss(r.duration) + ' · ' + r.question_count + ' questions</span>' : '') +
      '</div><h2 style="margin-bottom:6px">' + esc(r.title || 'Debrief') + '</h2>' +
      '<p style="color:var(--text-2);margin:0 0 10px">' + esc(n.summary || '') + '</p>' +
      '<div class="row wrap"><span class="chip ' + (dx.correct ? 'ok' : dx.partial ? 'warn' : 'bad') + '">' +
      (dx.correct ? 'Correct diagnosis' : dx.partial ? 'Right area' : 'Missed') + '</span>' +
      '<span style="font-size:14px">You said: <b>' + esc(dx.submitted || '—') + '</b> &nbsp;·&nbsp; It was: <b>' + esc(dx.actual) + '</b></span></div>' +
      (r.modifiers && r.modifiers.length ? '<div class="muted" style="margin-top:8px;font-size:13px">' + r.modifiers.map(function (m) {
        return esc(m.label) + ' (' + (m.delta > 0 ? '+' : '') + m.delta + ')'; }).join(' · ') + '</div>' : '') +
      '<div class="muted" style="font-size:12px;margin-top:8px">' + (r.narrative_source === 'model' ? 'Narrative by the attending model; scores from the mark sheet.' : 'Checklist debrief (no model key on this server).') + '</div>' +
      '</div></div>';

    var doms = '<div class="grid cols-3" style="margin-bottom:18px">' + (r.domains || []).map(domain).join('') + '</div>';

    var words = '<div class="grid cols-3" style="margin-bottom:18px">' +
      '<div class="card"><h4>Data gathering</h4><p style="font-size:14.5px">' + esc(n.data_gathering || '') + '</p></div>' +
      '<div class="card"><h4>Clinical management</h4><p style="font-size:14.5px">' + esc(n.clinical_management || '') + '</p></div>' +
      '<div class="card"><h4>Communication</h4><p style="font-size:14.5px">' + esc(n.interpersonal || '') + '</p></div></div>';

    function ul(items, cls) {
      if (!items || !items.length) return '<div class="muted">Nothing here.</div>';
      return '<div class="list">' + items.map(function (s) { return '<div class="item"><span class="tick ' + cls + '">' + (cls === 'yes' ? '✓' : '→') + '</span><div>' + esc(s) + '</div></div>'; }).join('') + '</div>';
    }
    var lists = '<div class="grid cols-2" style="margin-bottom:18px">' +
      '<div class="card"><h3>What went well</h3>' + ul(n.strengths, 'yes') + '</div>' +
      '<div class="card"><h3>Next time</h3>' + ul((n.next_time && n.next_time.length) ? n.next_time : n.improvements, 'half') + '</div></div>';

    var missed = (r.missed || []).map(function (m) {
      var kind = { question: 'Ask', exam: 'Examine', investigation: 'Order', treatment: 'Give' }[m.kind] || m.kind;
      return '<div class="item"><span class="chip">' + kind + '</span><div><b>' + esc(m.label) + '</b>' + (m.why ? '<div class="muted" style="font-size:13px">' + esc(m.why) + '</div>' : '') + '</div></div>';
    }).join('');
    var missedCard = '<div class="card" style="margin-bottom:18px"><h3>What you did not do, and what it would have shown</h3>' +
      (missed ? '<div class="list">' + missed + '</div>' : '<div class="muted">You covered everything on the sheet.</div>') + '</div>';

    var teach = r.teaching || {};
    var teachCard = '<div class="card" style="margin-bottom:18px"><h3>Teaching points</h3><p style="color:var(--text-2)">' + esc(teach.summary || '') + '</p>' +
      '<div class="stack">' + (teach.pearls || []).map(function (p) { return '<div class="pearl">' + esc(p) + '</div>'; }).join('') + '</div></div>';

    var cites = (r.citations || []).map(function (c) {
      return '<a class="cite" href="' + esc(c.url) + '" target="_blank" rel="noopener"><div><div class="org">' + esc(c.org) + ' · ' + esc(c.code) + '</div><div>' + esc(c.title) + '</div></div></a>';
    }).join('');
    var citeCard = '<div class="card" style="margin-bottom:18px"><h3>Guidance this was marked against</h3><div class="stack">' + (cites || '<div class="muted">No citations.</div>') + '</div>' +
      '<div class="muted" style="font-size:12px;margin-top:10px">Citations are chosen by id from a curated registry; the model cannot write a source that is not in it.</div></div>';

    var tl = (r.timeline || []).map(function (e) {
      return '<div class="tl ' + esc(e.kind) + '"><span class="t">' + mmss(e.t) + '</span><span>' + esc(e.text) +
        (e.effect === 'harmed' ? ' <span class="chip bad">harmed</span>' : e.effect === 'helped' ? ' <span class="chip ok">helped</span>' : '') + '</span></div>';
    }).join('');
    var tlCard = '<div class="card"><h3>Timeline</h3><div class="timeline">' + tl + '</div></div>';

    var transcript = '';
    if (data.transcript && opts.transcript) {
      transcript = '<div class="card" style="margin-top:18px"><h3>Transcript</h3><div class="stack">' + data.transcript.map(function (m) {
        return '<div style="font-size:14px"><span class="muted num" style="font-size:12px">' + mmss(m.t) + '</span> <b style="color:' + (m.kind === 'reply' ? 'var(--ok)' : m.kind === 'system' ? 'var(--bad)' : 'var(--info)') + '">' + esc(m.who) + '</b> ' + esc(m.text) + '</div>';
      }).join('') + '</div></div>';
    }

    el.innerHTML = '<div class="debrief wrap">' + (opts.actions || '') + head + doms + words + lists + missedCard + teachCard +
      '<div class="grid cols-2">' + citeCard + tlCard + '</div>' + transcript + (opts.actions ? '<div style="margin-top:22px">' + opts.actions + '</div>' : '') + '</div>';
  }

  global.Debrief = { render: render, esc: esc, mmss: mmss };
})(window);
