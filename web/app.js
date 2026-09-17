/* The app shell: auth, cases, progress, assignments, dashboards, cohorts,
   members, the case editor, billing. One file, no build step, path routing. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var esc = Debrief.esc;
  var me = null;            // {user, org, plan, live, features}

  /* ------------------------------------------------------------- utils */
  function api(path, body, method) {
    return fetch(path, {
      method: method || (body ? 'POST' : 'GET'),
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'same-origin'
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (r.status === 401 && !location.pathname.match(/\/app\/(login|signup|join)/)) {
          go('/app/login?next=' + encodeURIComponent(location.pathname));
          throw new Error('Sign in to continue.');
        }
        if (!r.ok) throw new Error(data.detail || data.error || ('Request failed (' + r.status + ')'));
        return data;
      });
    });
  }
  var toastT = null;
  function toast(msg, bad) {
    var t = $('toast'); t.textContent = msg; t.className = 'toast show' + (bad ? ' bad' : '');
    clearTimeout(toastT); toastT = setTimeout(function () { t.className = 'toast'; }, 3200);
  }
  function fail(e) { toast(e.message || String(e), true); }
  function modal(html) { $('modalBody').innerHTML = html; $('modal').classList.add('show'); }
  function closeModal() { $('modal').classList.remove('show'); }
  $('modal').addEventListener('click', function (e) { if (e.target === $('modal')) closeModal(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeModal(); });
  function when(ts) { if (!ts) return '—'; var d = new Date(ts * 1000); return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }); }
  function date(ts) { if (!ts) return '—'; return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
  function gradeChip(score, grade) {
    if (score == null) return '<span class="chip">—</span>';
    var cls = score >= 70 ? 'ok' : score >= 50 ? 'warn' : 'bad';
    return '<span class="chip ' + cls + '">' + score + ' · ' + esc(grade || '') + '</span>';
  }
  function qs() { return Object.fromEntries(new URLSearchParams(location.search)); }
  function form(el) { var o = {}; new FormData(el).forEach(function (v, k) { o[k] = v; }); return o; }
  function isStaff() { return me && me.user && me.user.role !== 'learner'; }
  function isAdmin() { return me && me.user && me.user.role === 'admin'; }

  /* ------------------------------------------------------------ router */
  var routes = [];
  function route(re, fn) { routes.push({ re: re, fn: fn }); }
  function go(path) { history.pushState(null, '', path); render(); }
  window.addEventListener('popstate', render);
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a');
    if (!a || a.target || a.origin !== location.origin || !a.pathname.startsWith('/app')) return;
    e.preventDefault(); go(a.pathname + a.search);
  });

  function render() {
    var path = location.pathname.replace(/\/$/, '') || '/app';
    for (var i = 0; i < routes.length; i++) {
      var m = path.match(routes[i].re);
      if (m) { window.scrollTo(0, 0); renderNav(); return routes[i].fn.apply(null, m.slice(1)); }
    }
    $('view').innerHTML = '<div class="page wrap"><div class="empty">Nothing here.</div></div>';
  }

  function renderNav() {
    var nav = $('nav'), um = $('usermenu');
    if (!me || !me.user) { nav.innerHTML = ''; um.innerHTML = '<a class="btn ghost sm" href="/app/login">Sign in</a>'; return; }
    var links = [['/app', 'Home'], ['/app/cases', 'Cases'], ['/app/progress', 'My progress']];
    if (isStaff()) links.push(['/app/dashboard', 'Dashboard'], ['/app/cohorts', 'Cohorts'], ['/app/editor', 'Case editor']);
    if (isAdmin()) links.push(['/app/admin', 'Admin']);
    nav.innerHTML = links.map(function (l) {
      var active = location.pathname === l[0] || (l[0] !== '/app' && location.pathname.startsWith(l[0]));
      return '<a href="' + l[0] + '" class="' + (active ? 'active' : '') + '">' + l[1] + '</a>';
    }).join('');
    var initials = (me.user.name || '?').split(/\s+/).map(function (s) { return s[0]; }).join('').slice(0, 2).toUpperCase();
    um.innerHTML = '<span class="avatar">' + esc(initials) + '</span><span>' + esc(me.user.name) + '<span class="org muted"> · ' + esc(me.org.name) + '</span></span>' +
      '<button class="btn ghost sm" id="logout">Sign out</button>';
    $('logout').onclick = function () { api('/api/auth/logout', {}).then(function () { me = { user: null }; go('/app/login'); }); };
  }

  function requireUser() {
    if (me && me.user) return true;
    go('/app/login?next=' + encodeURIComponent(location.pathname)); return false;
  }

  /* -------------------------------------------------------------- auth */
  function authView(kind) {
    var q = qs();
    var isLogin = kind === 'login', isJoin = kind === 'join';
    var title = isLogin ? 'Welcome back' : isJoin ? 'Join your school' : 'Create your school';
    var sub = isLogin ? 'Sign in to keep practising.' : isJoin ? 'Use the invite code your instructor gave you.' : 'Five seats free. Add more when you need them.';
    $('view').innerHTML = '<div class="auth"><div class="card"><h1>' + title + '</h1><p class="muted" style="margin-bottom:18px">' + sub + '</p>' +
      '<div id="authErr" class="error hide" style="margin-bottom:12px"></div>' +
      '<form id="authForm">' +
      (isJoin ? '<div class="field"><label>Invite code</label><input name="code" required autocapitalize="characters" maxlength="6" value="' + esc(q.code || '') + '" placeholder="ABC234"><div class="help" id="invitePreview"></div></div>' : '') +
      (!isLogin && !isJoin ? '<div class="field"><label>School or programme name</label><input name="org_name" required placeholder="St Elsewhere Medical School"></div>' : '') +
      (!isLogin ? '<div class="field"><label>Your name</label><input name="name" required placeholder="Dr Sara Haddad"></div>' : '') +
      '<div class="field"><label>Email</label><input name="email" type="email" required autocomplete="email"></div>' +
      '<div class="field"><label>Password</label><input name="password" type="password" required minlength="8" autocomplete="' + (isLogin ? 'current-password' : 'new-password') + '"><div class="help">At least 8 characters.</div></div>' +
      '<button class="btn primary block lg" type="submit">' + (isLogin ? 'Sign in' : isJoin ? 'Join' : 'Create school') + '</button></form>' +
      '<p class="muted" style="margin:16px 0 0;font-size:14px;text-align:center">' +
      (isLogin ? 'New here? <a href="/app/signup">Create a school</a> · <a href="/app/join">Have an invite code?</a>' :
        isJoin ? 'Already have an account? <a href="/app/login">Sign in</a> · <a href="/app/signup">Create a school instead</a>' :
          'Already have an account? <a href="/app/login">Sign in</a> · <a href="/app/join">Joining a school? Use your invite code</a>') +
      '</p></div></div>';
    if (isJoin) {
      var inp = $('authForm').code;
      var preview = function () {
        if (inp.value.length < 6) return;
        api('/api/auth/invite-preview', { code: inp.value }).then(function (d) {
          $('invitePreview').textContent = 'Joining ' + d.org_name + ' as ' + d.role + '.';
        }).catch(function () { $('invitePreview').textContent = ''; });
      };
      inp.addEventListener('input', preview); preview();
    }
    $('authForm').onsubmit = function (e) {
      e.preventDefault();
      var btn = e.target.querySelector('button'); btn.disabled = true;
      api('/api/auth/' + (isLogin ? 'login' : isJoin ? 'join' : 'signup'), form(e.target)).then(function () {
        return boot(true);
      }).then(function () {
        /* Only ever return to a page of this app; '//evil.example' starts with a slash too. */
        var next = q.next || '';
        if (/^\/practice\/[\w-]+$/.test(next)) { location.href = next; return; }
        go(/^\/app(\/[\w\-/]*)?$/.test(next) ? next : '/app');
      })
        .catch(function (err) { $('authErr').textContent = err.message; $('authErr').classList.remove('hide'); btn.disabled = false; });
    };
  }
  route(/^\/app\/login$/, function () { authView('login'); });
  route(/^\/app\/signup$/, function () { authView('signup'); });
  route(/^\/app\/join$/, function () { authView('join'); });

  /* -------------------------------------------------------------- home */
  route(/^\/app$/, function () {
    if (!requireUser()) return;
    if (isStaff()) return dashboardView();
    return homeView();
  });

  function caseCard(c, assignment) {
    var best = c.best_score != null ? gradeChip(c.best_score, c.best_score >= 85 ? 'A' : c.best_score >= 70 ? 'B' : c.best_score >= 55 ? 'C' : c.best_score >= 40 ? 'D' : 'E') : '<span class="chip">Not attempted</span>';
    return '<div class="card case-card" data-case="' + esc(c.id) + '"' + (assignment ? ' data-assignment="' + esc(assignment) + '"' : '') + '>' +
      '<div class="row between"><span class="chip">' + esc(c.specialty || 'Case') + '</span>' + (c.published === false ? '<span class="chip warn">Draft</span>' : '') + '</div>' +
      '<div class="who">' + esc(c.name || c.title) + (c.age ? '<span>' + c.age + (c.sex ? ' · ' + c.sex : '') + '</span>' : '') + '</div>' +
      '<div style="font-weight:600">' + esc(c.title) + '</div>' +
      '<div class="complaint">' + esc(c.complaint || '') + '</div>' +
      '<div class="muted" style="font-size:13px">' + esc(c.setting || '') + '</div>' +
      '<div class="foot">' + best + '<span class="btn primary sm">Start encounter →</span></div></div>';
  }
  function bindCaseCards(root) {
    root.querySelectorAll('.case-card').forEach(function (el) {
      el.onclick = function () { startEncounter(el.dataset.case, el.dataset.assignment); };
    });
  }
  function startEncounter(caseId, assignmentId) {
    api('/api/encounters', { case_id: caseId, assignment_id: assignmentId || null }).then(function (d) {
      location.href = '/practice/' + d.id;
    }).catch(fail);
  }

  function homeView() {
    $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><h1>Good to see you, ' + esc(me.user.name.split(' ')[0]) + '</h1><p>Pick a patient. Twelve minutes on the clock.</p></div></div>' +
      '<div id="assign"></div><h2 style="margin:26px 0 12px">Cases</h2><div class="grid cols-3" id="cases"><div class="muted">Loading…</div></div></div>';
    api('/api/my/assignments').then(function (d) {
      if (!d.assignments.length) return;
      $('assign').innerHTML = '<h2 style="margin:0 0 12px">Assigned to you</h2><div class="card tight"><table><thead><tr><th>Assignment</th><th>Cohort</th><th>Due</th><th>Best</th><th></th></tr></thead><tbody>' +
        d.assignments.map(function (a) {
          var overdue = a.due_at && a.due_at < Date.now() / 1000 && a.best_score == null;
          return '<tr><td><b>' + esc(a.title) + '</b><div class="muted" style="font-size:12.5px">' + esc(a.case_title) + '</div></td><td>' + esc(a.cohort) + '</td><td class="' + (overdue ? 'status-critical' : '') + '">' + date(a.due_at) + '</td><td>' + gradeChip(a.best_score, '') + '</td>' +
            '<td style="text-align:right"><button class="btn sm primary" data-start="' + esc(a.case_id) + '" data-asg="' + esc(a.id) + '">' + (a.attempts ? 'Try again' : 'Start') + '</button></td></tr>';
        }).join('') + '</tbody></table></div>';
      $('assign').querySelectorAll('[data-start]').forEach(function (b) { b.onclick = function () { startEncounter(b.dataset.start, b.dataset.asg); }; });
    }).catch(fail);
    api('/api/cases').then(function (d) {
      $('cases').innerHTML = d.cases.map(function (c) { return caseCard(c); }).join('') || '<div class="empty">No cases yet.</div>';
      bindCaseCards($('cases'));
    }).catch(fail);
  }

  route(/^\/app\/cases$/, function () {
    if (!requireUser()) return;
    $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><h1>Cases</h1><p>Every patient in your library.</p></div>' +
      (isStaff() ? '<a class="btn primary" href="/app/editor/new">+ New case</a>' : '') + '</div><div class="grid cols-3" id="cases"></div></div>';
    api('/api/cases').then(function (d) {
      $('cases').innerHTML = d.cases.map(function (c) { return caseCard(c); }).join('') || '<div class="empty">No cases yet.</div>';
      bindCaseCards($('cases'));
    }).catch(fail);
  });

  /* ---------------------------------------------------------- progress */
  route(/^\/app\/progress$/, function () {
    if (!requireUser()) return;
    $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><h1>My progress</h1><p>Every encounter, every debrief.</p></div></div><div id="prog" class="muted">Loading…</div></div>';
    api('/api/my/encounters').then(function (d) {
      var s = d.summary;
      var spark = s.trend.length ? '<div class="sparkline">' + s.trend.map(function (v) { return '<i style="height:' + Math.max(6, v) + '%" title="' + v + '"></i>'; }).join('') + '</div>' : '<div class="muted">Complete an encounter to see a trend.</div>';
      $('prog').innerHTML = '<div class="grid cols-4" style="margin-bottom:18px">' +
        '<div class="card kpi"><span class="v num">' + s.completed + '</span><span class="l">Encounters completed</span></div>' +
        '<div class="card kpi"><span class="v num">' + (s.average != null ? s.average : '—') + '</span><span class="l">Average score</span></div>' +
        '<div class="card kpi"><span class="v num">' + (s.best != null ? s.best : '—') + '</span><span class="l">Best score</span></div>' +
        '<div class="card"><span class="l muted" style="font-size:13px">Last 12</span>' + spark + '</div></div>' +
        '<div class="card tight"><table><thead><tr><th>When</th><th>Case</th><th>Status</th><th>Score</th><th></th></tr></thead><tbody>' +
        (d.encounters.map(function (e) {
          return '<tr><td class="muted">' + when(e.started_at) + '</td><td><b>' + esc(e.title) + '</b><div class="muted" style="font-size:12.5px">' + esc(e.specialty || '') + '</div></td>' +
            '<td>' + (e.status === 'complete' ? '<span class="chip ok">Complete</span>' : e.status === 'active' ? '<span class="chip info">In progress</span>' : '<span class="chip warn">Needs submission</span>') + '</td>' +
            '<td>' + gradeChip(e.score, e.grade) + '</td><td style="text-align:right">' +
            (e.status === 'complete' ? '<a class="btn sm" href="/app/report/' + esc(e.id) + '">Debrief</a>' : '<a class="btn sm primary" href="/practice/' + esc(e.id) + '">Resume</a>') + '</td></tr>';
        }).join('') || '<tr><td colspan="5" class="muted">No encounters yet.</td></tr>') + '</tbody></table></div>';
    }).catch(fail);
  });

  route(/^\/app\/report\/([^/]+)$/, function (id) {
    if (!requireUser()) return;
    $('view').innerHTML = '<div class="page wrap muted">Loading debrief…</div>';
    api('/api/encounters/' + id + '/report').then(function (d) {
      var actions = '<div class="row wrap no-print"><a class="btn" href="' + (isStaff() && d.learner.id !== me.user.id ? '/app/dashboard' : '/app/progress') + '">← Back</a>' +
        '<button class="btn" onclick="window.print()">Print / PDF</button>' +
        '<button class="btn primary" id="again">Attempt this case again</button></div>';
      Debrief.render($('view'), d, { actions: actions, transcript: true });
      document.querySelectorAll('#again').forEach(function (b) { b.onclick = function () { startEncounter(d.case_id); }; });
    }).catch(fail);
  });

  /* --------------------------------------------------------- dashboard */
  function bars(rows, keyLabel, keyVal, cls) {
    if (!rows.length) return '<div class="muted">No data yet.</div>';
    return rows.map(function (r) {
      var v = r[keyVal];
      return '<div class="trend-row"><div><div style="font-size:14px">' + esc(r[keyLabel]) + (r.attempts ? ' <span class="muted">· ' + r.attempts + '</span>' : '') + '</div>' +
        '<div class="bar ' + (cls || (v >= 70 ? '' : v >= 50 ? 'warn' : 'bad')) + '" style="margin-top:5px"><i style="width:' + v + '%"></i></div></div><b class="num">' + v + '</b></div>';
    }).join('');
  }
  function dashboardView() {
    $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><h1>Dashboard</h1><p>' + esc(me.org.name) + ' · how your learners are reasoning.</p></div>' +
      '<div class="row"><a class="btn" href="/app/cohorts">Cohorts</a><a class="btn primary" href="/app/editor/new">+ New case</a></div></div><div id="dash" class="muted">Loading…</div></div>';
    api('/api/org/dashboard').then(function (d) {
      var t = d.totals, dx = d.diagnosis, dxN = (dx.correct + dx.partial + dx.wrong) || 1;
      $('dash').innerHTML = '<div class="grid cols-4" style="margin-bottom:18px">' +
        '<div class="card kpi"><span class="v num">' + t.completed + '</span><span class="l">Debriefs on record</span></div>' +
        '<div class="card kpi"><span class="v num">' + (t.average != null ? t.average : '—') + '</span><span class="l">Average score</span></div>' +
        '<div class="card kpi"><span class="v num">' + t.active_learners_7d + '</span><span class="l">Active learners, 7 days</span></div>' +
        '<div class="card kpi"><span class="v num">' + Math.round(100 * dx.correct / dxN) + '%</span><span class="l">Correct diagnoses</span></div></div>' +
        '<div class="grid cols-3" style="margin-bottom:18px">' +
        '<div class="card"><h3>By domain</h3>' + bars(d.domains, 'name', 'pct') + '</div>' +
        '<div class="card"><h3>Most missed</h3><div class="list">' + (d.most_missed.map(function (m) { return '<div class="item" style="font-size:13.5px"><b class="num" style="min-width:26px">' + m.count + '</b><span>' + esc(m.label) + '</span></div>'; }).join('') || '<div class="muted">Nothing yet.</div>') + '</div>' +
        (d.harm.length ? '<h4 style="margin-top:14px">Harmful treatments given</h4><div class="list">' + d.harm.map(function (m) { return '<div class="item" style="font-size:13.5px;border-color:rgba(226,75,74,.4)"><b class="num">' + m.count + '</b><span>' + esc(m.label) + '</span></div>'; }).join('') + '</div>' : '') + '</div>' +
        '<div class="card"><h3>Outcomes</h3>' + bars([
          { l: 'Correct diagnosis', v: Math.round(100 * dx.correct / dxN) }, { l: 'Right area', v: Math.round(100 * dx.partial / dxN) }, { l: 'Missed', v: Math.round(100 * dx.wrong / dxN) },
          { l: 'Patient arrested', v: Math.round(100 * (d.outcomes.arrested || 0) / (t.completed || 1)) }], 'l', 'v', 'info') + '</div></div>' +
        '<div class="grid cols-2" style="margin-bottom:18px">' +
        '<div class="card"><h3>By case <span class="muted" style="font-weight:400;font-size:13px">hardest first</span></h3>' + bars(d.by_case, 'case', 'average') + '</div>' +
        '<div class="card"><h3>By learner <span class="muted" style="font-weight:400;font-size:13px">needs attention first</span></h3>' + bars(d.by_learner, 'learner', 'average') + '</div></div>' +
        '<div class="card tight"><h3 style="padding:6px 10px 0">Recent encounters</h3><table><thead><tr><th>When</th><th>Learner</th><th>Case</th><th>Score</th><th></th></tr></thead><tbody>' +
        (d.recent.map(function (e) {
          return '<tr><td class="muted">' + when(e.started_at) + '</td><td>' + esc(e.learner) + '</td><td>' + esc(e.case_title) + '</td><td>' + (e.status === 'complete' ? gradeChip(e.score, e.grade) : '<span class="chip info">' + esc(e.status.replace('_', ' ')) + '</span>') + '</td>' +
            '<td style="text-align:right">' + (e.status === 'complete' ? '<a class="btn sm" href="/app/report/' + esc(e.id) + '">Debrief</a>' : '') + '</td></tr>';
        }).join('') || '<tr><td colspan="5" class="muted">No encounters yet. Invite learners from Cohorts.</td></tr>') + '</tbody></table></div>';
    }).catch(fail);
  }
  route(/^\/app\/dashboard$/, function () { if (!requireUser()) return; if (!isStaff()) return go('/app'); dashboardView(); });

  /* ----------------------------------------------------------- cohorts */
  function inviteBox(inv, label) {
    var url = inv.url.startsWith('http') ? inv.url : location.origin + inv.url;
    return '<div class="notice"><b>' + esc(label || 'Invite') + '</b> — code <span class="kbd" style="font-size:14px">' + esc(inv.code) + '</span> · ' +
      '<a href="' + esc(url) + '">' + esc(url) + '</a> <button class="btn sm ghost" data-copy="' + esc(url) + '">Copy link</button></div>';
  }
  function bindCopy(root) {
    root.querySelectorAll('[data-copy]').forEach(function (b) {
      b.onclick = function () { navigator.clipboard.writeText(b.dataset.copy).then(function () { toast('Copied.'); }); };
    });
  }
  route(/^\/app\/cohorts$/, function () {
    if (!requireUser()) return; if (!isStaff()) return go('/app');
    $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><h1>Cohorts</h1><p>A cohort is a group of learners with its own invite link and assignments.</p></div>' +
      '<button class="btn primary" id="newCohort">+ New cohort</button></div><div id="list" class="grid cols-3"></div><div id="invites" style="margin-top:22px"></div></div>';
    function load() {
      api('/api/org/cohorts').then(function (d) {
        $('list').innerHTML = d.cohorts.map(function (c) {
          return '<a class="card case-card" href="/app/cohorts/' + esc(c.id) + '" style="min-height:120px;text-decoration:none"><div class="who">' + esc(c.name) + '</div><div class="muted">' + c.members + ' learner' + (c.members === 1 ? '' : 's') + ' · created ' + date(c.created_at) + '</div><div class="foot"><span></span><span class="btn sm">Open →</span></div></a>';
        }).join('') || '<div class="empty" style="grid-column:1/-1">No cohorts yet. Create one to get an invite link for your learners.</div>';
      }).catch(fail);
    }
    load();
    $('newCohort').onclick = function () {
      modal('<h2>New cohort</h2><form id="f"><div class="field"><label>Name</label><input name="name" required placeholder="Year 4 · 2026" autofocus></div><button class="btn primary block" type="submit">Create</button></form>');
      $('f').onsubmit = function (e) {
        e.preventDefault();
        api('/api/org/cohorts', form(e.target)).then(function (d) {
          modal('<h2>' + esc(d.name) + ' created</h2><p class="muted">Share this with the learners in the cohort. They will join your school and this cohort in one step.</p>' + inviteBox(d.invite, 'Learner invite') + '<div style="margin-top:14px"><a class="btn primary" href="/app/cohorts/' + esc(d.id) + '">Open cohort</a></div>');
          bindCopy($('modalBody')); load();
        }).catch(fail);
      };
    };
  });

  route(/^\/app\/cohorts\/([^/]+)$/, function (id) {
    if (!requireUser()) return; if (!isStaff()) return go('/app');
    $('view').innerHTML = '<div class="page wrap muted">Loading…</div>';
    Promise.all([api('/api/org/cohorts/' + id), api('/api/cases')]).then(function (res) {
      var d = res[0], cases = res[1].cases.filter(function (c) { return c.published !== false; });
      $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><a href="/app/cohorts" class="muted" style="font-size:13px">← Cohorts</a><h1>' + esc(d.cohort.name) + '</h1><p>' + d.learners.length + ' learners · ' + d.assignments.length + ' assignments</p></div>' +
        '<div class="row"><button class="btn" id="inviteBtn">Invite link</button><button class="btn primary" id="assignBtn">+ Assign a case</button></div></div>' +
        '<div id="inviteOut"></div>' +
        '<div class="grid cols-2"><div class="card tight"><h3 style="padding:6px 10px 0">Assignments</h3><table><thead><tr><th>Case</th><th>Due</th><th>Done</th><th>Avg</th></tr></thead><tbody>' +
        (d.assignments.map(function (a) { return '<tr><td><b>' + esc(a.title) + '</b><div class="muted" style="font-size:12.5px">' + esc(a.case_title) + '</div></td><td>' + date(a.due_at) + '</td><td class="num">' + a.completed + ' / ' + a.of + '</td><td>' + (a.average != null ? gradeChip(a.average, '') : '—') + '</td></tr>'; }).join('') || '<tr><td colspan="4" class="muted">Nothing assigned yet.</td></tr>') + '</tbody></table></div>' +
        '<div class="card tight"><h3 style="padding:6px 10px 0">Learners</h3><table><thead><tr><th>Name</th><th>Done</th><th>Avg</th><th>Last</th></tr></thead><tbody>' +
        (d.learners.map(function (l) { return '<tr><td><b>' + esc(l.name) + '</b><div class="muted" style="font-size:12.5px">' + esc(l.email) + '</div></td><td class="num">' + l.completed + '</td><td>' + (l.average != null ? gradeChip(l.average, '') : '—') + '</td><td>' + (l.last ? (l.last.status === 'complete' ? '<a href="/app/report/' + esc(l.last.id) + '">' + when(l.last.started_at) + '</a>' : when(l.last.started_at)) : '—') + '</td></tr>'; }).join('') || '<tr><td colspan="4" class="muted">No learners yet — share the invite link.</td></tr>') + '</tbody></table></div></div></div>';
      $('inviteBtn').onclick = function () {
        api('/api/org/invites', { role: 'learner', cohort_id: id }).then(function (inv) { $('inviteOut').innerHTML = inviteBox(inv, 'Learner invite for ' + d.cohort.name); bindCopy($('inviteOut')); }).catch(fail);
      };
      $('assignBtn').onclick = function () {
        modal('<h2>Assign a case</h2><form id="f"><div class="field"><label>Case</label><select name="case_id">' + cases.map(function (c) { return '<option value="' + esc(c.id) + '">' + esc(c.title) + ' — ' + esc(c.name) + '</option>'; }).join('') + '</select></div>' +
          '<div class="field"><label>Title (optional)</label><input name="title" placeholder="Week 3: the jaundiced patient"></div><div class="field"><label>Due date (optional)</label><input name="due" type="date"></div><button class="btn primary block" type="submit">Assign</button></form>');
        $('f').onsubmit = function (e) {
          e.preventDefault(); var f = form(e.target);
          api('/api/org/cohorts/' + id + '/assignments', { case_id: f.case_id, title: f.title, due_at: f.due ? new Date(f.due + 'T23:59:00').getTime() / 1000 : null })
            .then(function () { closeModal(); toast('Assigned.'); render(); }).catch(fail);
        };
      };
    }).catch(fail);
  });

  /* ------------------------------------------------------------ editor */
  route(/^\/app\/editor$/, function () {
    if (!requireUser()) return; if (!isStaff()) return go('/app');
    $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><h1>Case editor</h1><p>Write your own patients. A case publishes only when it passes the same checks as the built-in ones.</p></div>' +
      '<a class="btn primary" href="/app/editor/new">+ New case</a></div><div class="card tight"><table><thead><tr><th>Case</th><th>Specialty</th><th>Status</th><th></th></tr></thead><tbody id="rows"></tbody></table></div></div>';
    api('/api/cases').then(function (d) {
      $('rows').innerHTML = d.cases.map(function (c) {
        return '<tr><td><b>' + esc(c.title) + '</b><div class="muted" style="font-size:12.5px">' + esc(c.name) + ', ' + c.age + '</div></td><td>' + esc(c.specialty || '') + '</td>' +
          '<td>' + (c.builtin ? '<span class="chip info">Built-in</span>' : c.published ? '<span class="chip ok">Published</span>' : '<span class="chip warn">Draft</span>') + '</td>' +
          '<td style="text-align:right"><a class="btn sm" href="/app/editor/' + esc(c.id) + '">' + (c.builtin ? 'View' : 'Edit') + '</a></td></tr>';
      }).join('');
    }).catch(fail);
  });

  route(/^\/app\/editor\/([^/]+)$/, function (id) {
    if (!requireUser()) return; if (!isStaff()) return go('/app');
    var isNew = id === 'new';
    $('view').innerHTML = '<div class="page wrap muted">Loading…</div>';
    var load = isNew ? api('/api/org/case-template').then(function (d) {
      var c = d.case; c.title = 'Untitled case'; c.name = 'New patient'; delete c.id; return { case: c, published: false, builtin: false, problems: [] };
    }) : api('/api/org/cases/' + id);
    load.then(function (d) {
      var ro = d.builtin;
      $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><a href="/app/editor" class="muted" style="font-size:13px">← Case editor</a><h1 id="ttl">' + esc(d.case.title || 'Untitled') + '</h1><p id="status"></p></div>' +
        '<div class="row wrap">' +
        (ro ? '<button class="btn" id="dup">Duplicate to edit</button>' :
          '<button class="btn" id="draftBtn"' + (me.features.authoring ? '' : ' title="Needs an API key on the server" disabled') + '>✨ Draft with AI</button>' +
          '<button class="btn" id="save">Save draft</button><button class="btn primary" id="publish">Publish</button>') +
        '<button class="btn ghost" id="test">Test-drive</button></div></div>' +
        '<div class="editor"><div class="stack"><div class="card"><h3>Checks</h3><div id="problems" class="muted">Save to run checks.</div></div>' +
        '<div class="card"><h3>Anatomy of a case</h3><div class="muted" style="font-size:13px;line-height:1.55">' +
        '<b>Public to the model:</b> name, age, sex, description, history, personality, symptoms, lie_topic, lie, truth, cracks_when, red_herrings.<br><br>' +
        '<b>Secret:</b> diagnosis, accepted_answers, partial_answers, key_questions, key_keywords — never in a prompt, provably.<br><br>' +
        '<b>Revealed by action:</b> exam, investigations (ids from the catalog; only abnormal ones needed).<br><br>' +
        '<b>Marked in the debrief:</b> key_exams, key_investigations, key_treatments, harmful_treatments, management_points + keywords, teaching, guidelines.<br><br>' +
        'The first key question is the one the patient lies about. Keywords must not repeat across groups. Vitals must reach critical inside 150s of case time.</div></div></div>' +
        '<div class="card" style="padding:12px"><textarea id="json" spellcheck="false"' + (ro ? ' readonly' : '') + '></textarea></div></div></div>';
      $('json').value = JSON.stringify(d.case, null, 2);
      showProblems(d.problems, d.published);

      function parse() { try { return JSON.parse($('json').value); } catch (e) { toast('JSON error: ' + e.message, true); return null; } }
      function showProblems(problems, published) {
        $('status').textContent = ro ? 'Built-in case (read-only). Duplicate it to make your own version.' : (published ? 'Published — learners can see this case.' : 'Draft — not visible to learners.');
        $('problems').innerHTML = problems.length ? problems.map(function (p) { return '<div class="problem">' + esc(p) + '</div>'; }).join('') : '<span class="chip ok">All checks pass</span>';
      }
      function save(thenPublish) {
        var c = parse(); if (!c) return Promise.reject(new Error('Fix the JSON first.'));
        var p = isNew ? api('/api/org/cases', { case: c }) : api('/api/org/cases/' + id, { case: c }, 'PUT');
        return p.then(function (r) {
          if (isNew) { history.replaceState(null, '', '/app/editor/' + r.id); id = r.id; isNew = false; }
          $('ttl').textContent = c.title || 'Untitled';
          showProblems(r.problems, r.published);
          if (thenPublish) {
            if (r.problems.length) throw new Error('Fix the checks before publishing.');
            return api('/api/org/cases/' + id + '/publish', { published: true }).then(function () { showProblems([], true); toast('Published.'); });
          }
          toast('Saved.');
        });
      }
      if (!ro) {
        $('save').onclick = function () { save(false).catch(fail); };
        $('publish').onclick = function () { save(true).catch(fail); };
        $('draftBtn').onclick = function () {
          modal('<h2>Draft a case with AI</h2><p class="muted">Describe the patient in a sentence or two. You get a complete, validated draft to edit — history, personality, the lie, findings, results, teaching points, guideline ids.</p>' +
            '<form id="f"><div class="field"><label>Brief</label><textarea name="brief" required placeholder="A 68-year-old woman with three days of breathlessness who insists it is just her age. She stopped her water tablets because they made her go to the toilet at bingo."></textarea></div>' +
            '<div class="grid cols-2"><div class="field"><label>Specialty</label><input name="specialty" placeholder="Cardiology"></div><div class="field"><label>Difficulty</label><select name="difficulty"><option>standard</option><option>foundation</option><option>advanced</option></select></div></div>' +
            '<div class="field"><label>Language the patient speaks</label><input name="language" value="English"></div>' +
            '<button class="btn primary block" type="submit">Draft (takes about a minute)</button></form>');
          $('f').onsubmit = function (e) {
            e.preventDefault(); var b = e.target.querySelector('button'); b.disabled = true; b.textContent = 'Drafting…';
            api('/api/org/cases/draft', form(e.target)).then(function (r) {
              $('json').value = JSON.stringify(r.case, null, 2); $('ttl').textContent = r.case.title || 'Draft'; showProblems(r.problems, false); closeModal(); toast('Draft ready. Review it, then save.');
            }).catch(function (err) { fail(err); b.disabled = false; b.textContent = 'Draft'; });
          };
        };
      } else {
        $('dup').onclick = function () { api('/api/org/cases/' + id + '/duplicate', {}).then(function (r) { go('/app/editor/' + r.id); }).catch(fail); };
      }
      $('test').onclick = function () {
        var run = function () { api('/api/encounters', { case_id: id }).then(function (r) { location.href = '/practice/' + r.id; }).catch(fail); };
        if (ro) return run();
        save(false).then(run).catch(fail);
      };
    }).catch(fail);
  });

  /* ------------------------------------------------------------- admin */
  route(/^\/app\/admin$/, function () {
    if (!requireUser()) return; if (!isAdmin()) return go('/app');
    var q = qs();
    $('view').innerHTML = '<div class="page wrap"><div class="page-head"><div><h1>Admin</h1><p>' + esc(me.org.name) + '</p></div></div>' +
      (q.billing === 'success' ? '<div class="notice" style="margin-bottom:16px;border-color:rgba(93,202,165,.4)">Thank you — your seats will appear within a minute.</div>' : '') +
      '<div class="grid cols-2"><div class="card" id="plan">Loading…</div><div class="card"><h3>Staff invites</h3><p class="muted">Instructors see dashboards, cohorts and the case editor. Admins also manage billing and roles.</p>' +
      '<div class="row"><button class="btn" id="invInstr">Invite an instructor</button><button class="btn ghost" id="invAdmin">Invite an admin</button></div><div id="invOut" style="margin-top:12px"></div></div></div>' +
      '<div class="card tight" style="margin-top:18px"><h3 style="padding:6px 10px 0">Members</h3><table><thead><tr><th>Name</th><th>Role</th><th>Cohorts</th><th>Last seen</th><th></th></tr></thead><tbody id="members"></tbody></table></div></div>';
    api('/api/billing').then(function (p) {
      $('plan').innerHTML = '<h3>Plan</h3><div class="row wrap" style="margin-bottom:12px"><span class="chip ' + (p.plan === 'pro' ? 'ok' : '') + '">' + (p.plan === 'pro' ? 'School plan' : 'Free plan') + '</span><span class="chip">' + p.members + ' of ' + p.seats + ' seats used</span></div>' +
        '<div class="bar ' + (p.seats_left === 0 ? 'bad' : '') + '" style="margin-bottom:14px"><i style="width:' + Math.min(100, Math.round(100 * p.members / p.seats)) + '%"></i></div>' +
        (p.billing_available ?
          (p.plan === 'pro' ? '<button class="btn" id="portal">Manage billing</button>' :
            '<form id="buy" class="row"><input name="seats" type="number" min="1" value="25" style="width:110px"> <button class="btn primary" type="submit">Buy seats · $8 / seat / month</button></form>') :
          '<div class="notice">Billing is not configured on this server. Set STRIPE_SECRET_KEY, STRIPE_PRICE_SEAT and STRIPE_WEBHOOK_SECRET to sell seats; until then every school has ' + p.free_seats + ' free seats.</div>');
      if ($('buy')) $('buy').onsubmit = function (e) { e.preventDefault(); api('/api/billing/checkout', { seats: parseInt(form(e.target).seats, 10) }).then(function (r) { location.href = r.url; }).catch(fail); };
      if ($('portal')) $('portal').onclick = function () { api('/api/billing/portal', {}).then(function (r) { location.href = r.url; }).catch(fail); };
    }).catch(fail);
    function members() {
      api('/api/org/members').then(function (d) {
        $('members').innerHTML = d.members.map(function (m) {
          return '<tr><td><b>' + esc(m.name) + '</b><div class="muted" style="font-size:12.5px">' + esc(m.email) + '</div></td><td><select data-user="' + esc(m.id) + '" style="width:auto;padding:6px 10px">' +
            ['learner', 'instructor', 'admin'].map(function (r) { return '<option' + (r === m.role ? ' selected' : '') + '>' + r + '</option>'; }).join('') + '</select></td><td class="muted">' + esc(m.cohorts.join(', ')) + '</td><td class="muted">' + when(m.last_seen) + '</td><td></td></tr>';
        }).join('');
        $('members').querySelectorAll('select').forEach(function (s) {
          s.onchange = function () { api('/api/org/members/' + s.dataset.user + '/role', { role: s.value }).then(function () { toast('Role updated.'); }).catch(function (e) { fail(e); members(); }); };
        });
      }).catch(fail);
    }
    members();
    function inv(role) { api('/api/org/invites', { role: role }).then(function (i) { $('invOut').innerHTML = inviteBox(i, role + ' invite'); bindCopy($('invOut')); }).catch(fail); }
    $('invInstr').onclick = function () { inv('instructor'); };
    $('invAdmin').onclick = function () { inv('admin'); };
  });

  /* -------------------------------------------------------------- boot */
  function boot(silent) {
    return api('/api/me').then(function (d) { me = d; if (!silent) render(); });
  }
  boot().catch(function () { me = { user: null }; render(); });
})();
