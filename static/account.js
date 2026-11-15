/* Projects and Account screens. Depends on app.js (window.FCApp). No inline handlers (strict CSP). */
(function () {
  'use strict';
  var A = window.FCApp, FC = window.FC;
  if (!A) return;
  var esc = FC.esc, $ = function (id) { return document.getElementById(id); }, qsa = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var api = A.api, toast = A.toast, pill = A.pill, state = A.state;
  var LANGS = { python: 'Python', javascript: 'JavaScript', java: 'Java', typescript: 'TypeScript', go: 'Go', rust: 'Rust' };

  /* ================= Projects ================= */
  function projectCard(p) {
    var runs = p.run_count === 1 ? '1 run' : p.run_count + ' runs';
    return '<article class="card project-card' + (p.archived ? ' archived' : '') + '" data-pid="' + p.id + '">' +
      '<div class="card-head"><div><h3>' + esc(p.name) + '</h3><p>' + esc(p.description || 'No description') + '</p></div>' + (p.archived ? pill('Archived', 'muted') : pill(LANGS[p.language] || p.language, 'peach')) + '</div>' +
      '<p class="hint">' + esc(runs) + ' · budget ' + esc(p.context_budget) + ' tokens' + (p.constraints ? ' · ' + esc(p.constraints) : '') + '</p>' +
      '<div class="btn-row">' +
      '<button class="btn-sm" data-pact="use" data-id="' + p.id + '"' + (p.archived ? ' disabled' : '') + '>Use in workspace</button>' +
      '<button class="btn-sm" data-pact="edit" data-id="' + p.id + '">Edit</button>' +
      '<button class="btn-sm" data-pact="archive" data-id="' + p.id + '">' + (p.archived ? 'Restore' : 'Archive') + '</button>' +
      '<button class="btn-sm danger" data-pact="delete" data-id="' + p.id + '">Delete…</button></div></article>';
  }
  var searchTimer;
  async function renderProjects() {
    var host = $('project-list');
    host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    try {
      var q = $('project-search').value.trim(), archived = $('project-archived').checked;
      var d = await api('/api/v1/projects?include_archived=' + archived + (q ? '&q=' + encodeURIComponent(q) : ''));
      host.innerHTML = d.projects.length ? d.projects.map(projectCard).join('') :
        '<div class="empty card"><b>' + (q ? 'No projects match your search' : 'No projects yet') + '</b><small>' + (q ? 'Try a different name.' : 'Create a project to group runs and save default settings for the agent.') + '</small>' + (q ? '' : '<button class="btn primary" id="empty-new" type="button">Create your first project</button>') + '</div>';
      await A.loadProjects();
    } catch (e) { host.innerHTML = A.errorCard(e.message); }
  }
  function openForm(p) {
    $('project-form-card').hidden = false;
    $('project-form-title').textContent = p ? 'Edit project' : 'New project';
    $('pf-id').value = p ? p.id : ''; $('pf-name').value = p ? p.name : ''; $('pf-desc').value = p ? p.description : '';
    $('pf-language').value = p ? p.language : 'python'; $('pf-constraints').value = p ? p.constraints : ''; $('pf-budget').value = p ? p.context_budget : 900;
    $('pf-error').hidden = true; $('pf-name').focus();
  }
  function closeForm() { $('project-form-card').hidden = true; }
  $('project-new').addEventListener('click', function () { openForm(null); });
  $('pf-cancel').addEventListener('click', closeForm);
  document.addEventListener('click', function (e) { if (e.target && e.target.id === 'empty-new') openForm(null); });
  $('project-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    var id = $('pf-id').value, body = { name: $('pf-name').value.trim(), description: $('pf-desc').value.trim(), language: $('pf-language').value, constraints: $('pf-constraints').value.trim(), context_budget: Number($('pf-budget').value) || 900 };
    var err = $('pf-error'); err.hidden = true;
    if (!body.name) { err.textContent = 'Give the project a name.'; err.hidden = false; return; }
    var btn = $('pf-save'); A.busy(btn, true);
    try {
      await api(id ? '/api/v1/projects/' + id : '/api/v1/projects', body, id ? 'PATCH' : 'POST');
      toast(id ? 'Project updated' : 'Project created'); closeForm(); await renderProjects();
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
    finally { A.busy(btn, false); }
  });
  $('project-search').addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(renderProjects, 250); });
  $('project-archived').addEventListener('change', renderProjects);
  document.addEventListener('click', async function (e) {
    var b = e.target.closest('[data-pact]'); if (!b) return;
    var id = Number(b.getAttribute('data-id')), p = state.projects.find(function (x) { return x.id === id; }) || {};
    var act = b.getAttribute('data-pact');
    try {
      if (act === 'edit') { openForm(p); window.scrollTo({ top: 0, behavior: 'smooth' }); }
      else if (act === 'use') { state.projectId = String(id); A.paintProjectSelect(); $('project-select').dispatchEvent(new Event('change')); A.navigate('agent'); }
      else if (act === 'archive') { await api('/api/v1/projects/' + id, { archived: !p.archived }, 'PATCH'); toast(p.archived ? 'Project restored' : 'Project archived'); await renderProjects(); }
      else if (act === 'delete') {
        var ok = await A.confirmDialog({ title: 'Delete "' + (p.name || 'project') + '"?', message: 'The project is removed. Its runs stay in your history but are no longer filed under it.', confirmLabel: 'Delete project' });
        if (ok) { await api('/api/v1/projects/' + id, undefined, 'DELETE'); toast('Project deleted'); await renderProjects(); }
      }
    } catch (ex) { toast(ex.message); }
  });

  /* ================= Account ================= */
  var PANELS = ['profile', 'security', 'usage', 'audit', 'preferences'];
  function showPanel(name) {
    PANELS.forEach(function (n) { var el = $('acct-' + n); if (el) el.hidden = n !== name; });
    qsa('[data-acct]').forEach(function (b) { b.setAttribute('aria-selected', String(b.getAttribute('data-acct') === name)); });
    if (name === 'security') renderSessions();
    if (name === 'usage') renderUsage();
    if (name === 'audit') renderAudit();
    if (name === 'profile') fillProfile();
  }
  document.addEventListener('click', function (e) { var t = e.target.closest('[data-acct]'); if (t) showPanel(t.getAttribute('data-acct')); });

  function fillProfile() { var u = state.user || {}; $('pr-email').value = u.email || ''; $('pr-name').value = u.display_name || ''; $('pr-role').textContent = u.role === 'admin' ? 'Administrator (can view the deployment-wide audit trail)' : 'Member'; }
  $('profile-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    try { var d = await api('/api/v1/auth/profile', { display_name: $('pr-name').value.trim() }, 'PATCH'); state.user = Object.assign({}, state.user, d.user); A.applyUser(); toast('Profile saved'); }
    catch (ex) { toast(ex.message); }
  });

  $('password-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    var err = $('pw-error'); err.hidden = true;
    var cur = $('pw-current').value, nw = $('pw-new').value;
    if (!cur || !nw) { err.textContent = 'Enter your current and new password.'; err.hidden = false; return; }
    try {
      var d = await api('/api/v1/auth/password', { current_password: cur, new_password: nw });
      $('pw-current').value = ''; $('pw-new').value = ''; toast('Password updated' + (d.revoked_sessions ? ' · ' + d.revoked_sessions + ' other session(s) signed out' : '')); renderSessions();
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  });

  async function renderSessions() {
    var host = $('session-list'); host.innerHTML = '<div class="skeleton"></div>';
    try {
      var d = await api('/api/v1/auth/sessions');
      host.innerHTML = d.sessions.map(function (s) {
        return '<div class="list-item"><div class="grow"><b>' + esc(shortUA(s.user_agent)) + (s.current ? ' ' + '<span class="pill good">This device</span>' : '') + '</b><small>' + esc(s.ip || 'unknown address') + ' · last active ' + esc(FC.ago(s.last_seen_at)) + ' · expires ' + esc(new Date(s.expires_at * 1000).toLocaleString()) + '</small></div>' +
          (s.current ? '' : '<button class="btn-sm" data-revoke="' + s.id + '">Sign out</button>') + '</div>';
      }).join('') || '<div class="empty"><b>No active sessions</b></div>';
    } catch (ex) { host.innerHTML = A.errorCard(ex.message); }
  }
  function shortUA(ua) {
    ua = ua || ''; var br = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
    var os = /Mac OS X/.test(ua) ? 'macOS' : /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Linux/.test(ua) ? 'Linux' : 'unknown OS';
    return br + ' on ' + os;
  }
  document.addEventListener('click', async function (e) {
    var b = e.target.closest('[data-revoke]'); if (!b) return;
    try { await api('/api/v1/auth/sessions/' + b.getAttribute('data-revoke'), undefined, 'DELETE'); toast('Session signed out'); renderSessions(); } catch (ex) { toast(ex.message); }
  });
  $('revoke-others').addEventListener('click', async function () {
    var ok = await A.confirmDialog({ title: 'Sign out other sessions?', message: 'Every other browser and device signed in to your account will be signed out.', confirmLabel: 'Sign them out' });
    if (!ok) return;
    try { var d = await api('/api/v1/auth/sessions/revoke-others', {}); toast(d.revoked + ' session(s) signed out'); renderSessions(); } catch (ex) { toast(ex.message); }
  });
  $('delete-account').addEventListener('click', async function () {
    var pw = await A.confirmDialog({ title: 'Delete your account?', message: 'This permanently deletes your account, projects, runs and sessions. It cannot be undone.', needPassword: true, confirmLabel: 'Delete everything' });
    if (!pw) return;
    try { await api('/api/v1/auth/delete-account', { password: pw }); window.location.assign('/'); } catch (ex) { toast(ex.message); }
  });

  async function renderUsage() {
    var host = $('usage-body'); host.innerHTML = '<div class="skeleton"></div>';
    try {
      var u = await api('/api/v1/usage'), q = u.quota, t = u.totals, pct = Math.min(100, Math.round(100 * q.runs_used / q.runs_limit));
      host.innerHTML = '<p class="hint">Heavy runs (agent, freshness, benchmark, tests) in a rolling 24 hours.</p>' +
        '<div class="quota"><div class="quota-bar" role="progressbar" aria-valuemin="0" aria-valuemax="' + q.runs_limit + '" aria-valuenow="' + q.runs_used + '" aria-label="Daily runs used"><i style="width:' + pct + '%"></i></div><b>' + q.runs_used + ' / ' + q.runs_limit + '</b></div>' +
        '<div class="metrics">' + A.metric('RUNS REMAINING TODAY', FC.fmtNum(q.runs_remaining)) + A.metric('TOTAL RUNS SAVED', FC.fmtNum(t.total_runs)) + A.metric('PROVIDER INPUT TOKENS', FC.fmtNum(t.provider_tokens_in), 'Gateway-reported') + A.metric('PROVIDER OUTPUT TOKENS', FC.fmtNum(t.provider_tokens_out), 'Gateway-reported') + A.metric('EST. SPEND', t.estimated_spend_usd != null ? '$' + t.estimated_spend_usd : 'not configured', 'Estimate from PRICE_*_PER_MTOK; not billing data') + '</div>' +
        '<p class="hint">Rate limits: ' + esc(u.rate_limits.per_minute) + ' requests/min, ' + esc(u.rate_limits.heavy_per_minute) + '/min for heavy endpoints. Spend is an estimate and appears only when prices are configured.</p>';
    } catch (ex) { host.innerHTML = A.errorCard(ex.message); }
  }

  async function renderAudit() {
    var host = $('audit-list'); host.innerHTML = '<div class="skeleton"></div>';
    $('audit-all-wrap').hidden = !(state.user && state.user.role === 'admin');
    try {
      var d = await api('/api/v1/audit?limit=100' + ($('audit-all').checked ? '&scope=all' : ''));
      host.innerHTML = d.events.length ? d.events.map(function (e) {
        return '<div class="list-item"><div class="grow"><b>' + esc(e.action.replace(/_/g, ' ')) + '</b><small>' + esc(e.email || 'system') + (e.detail ? ' · ' + esc(e.detail) : '') + ' · ' + esc(e.ip || '') + (e.request_id ? ' · req ' + esc(e.request_id) : '') + '</small></div><time>' + esc(FC.ago(e.ts)) + '</time></div>';
      }).join('') : '<div class="empty"><b>No events yet</b></div>';
    } catch (ex) { host.innerHTML = A.errorCard(ex.message); }
  }
  $('audit-all').addEventListener('change', renderAudit);

  /* hooks called by app.js navigate() */
  window.FCHooks = { projects: renderProjects, account: function () { showPanel('profile'); } };
})();
