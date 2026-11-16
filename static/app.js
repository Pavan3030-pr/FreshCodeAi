/* FreshCode AI v5 front-end. No inline handlers (strict CSP). All dynamic text is escaped via FC.esc. */
(function () {
  'use strict';
  const { traceRows, markChange, roi, reportMarkdown, esc, fmtNum, fmtMs, fmtPct, ago, safeUrl, host, renderRich, verdictMeta, trustMeta, barWidths, kindLabel, slug, fileExt, highlight, finalStages } = window.FC;
  const $ = id => document.getElementById(id);
  const qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const store = {
    get(k, area) { try { return (area || window.localStorage).getItem(k); } catch (e) { return null; } },
    set(k, v, area) { try { (area || window.localStorage).setItem(k, v); } catch (e) { /* storage may be blocked */ } }
  };
  const state = { health: null, lastCode: '', lastLang: 'python', view: 'overview', user: null, csrf: '', guest: false, projects: [], projectId: '', abort: null, lastTests: '', lastResult: null, timer: null, t0: 0 };
  const VIEWS = { overview: 'Overview', agent: 'Engineering agent', verify: 'Freshness intelligence', benchmarks: 'Evaluation lab', tests: 'Test lab', history: 'History & reports', settings: 'Integrations', projects: 'Projects', account: 'Account & security' };

  /* ---------- feedback ---------- */
  let toastTimer;
  function toast(msg) { const el = $('toast'); el.textContent = msg; el.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 3200); }
  function busy(btn, on) { btn.disabled = on; btn.classList.toggle('is-busy', on); }
  function reveal(id, html) { const el = $(id); el.innerHTML = html; el.hidden = false; }
  function skeleton(id) { reveal(id, '<div class="skeleton"></div><div class="skeleton"></div>'); }
  const pill = (text, tone) => `<span class="pill ${tone || 'muted'}">${esc(text)}</span>`;
  const metric = (label, value, title, kind) => `<div class="metric${kind ? ' ' + kind : ''}"${title ? ` title="${esc(title)}"` : ''}><b>${esc(value)}</b><small>${esc(label)}</small>${kind ? `<em>${kind === 'measured' ? 'MEASURED BY PROVIDER' : 'ESTIMATED LOCALLY'}</em>` : ''}</div>`;
  const callout = (tone, html) => `<div class="callout ${tone}">${html}</div>`;
  const errorCard = msg => `<article class="result">${callout('bad', '<b>Request failed.</b> ' + esc(msg))}</article>`;
  function download(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 500);
  }
  const copy = text => (navigator.clipboard ? navigator.clipboard.writeText(text).then(() => toast('Copied to clipboard')) : Promise.reject()).catch(() => toast('Clipboard unavailable in this browser'));

  /* ---------- API ---------- */
  function authHeaders(method) { return method && method !== 'GET' && state.csrf ? { 'X-CSRF-Token': state.csrf } : {}; }
  function toLogin() { if (state.guest) return; const next = encodeURIComponent(location.pathname + (location.hash || '')); window.location.assign('/login?next=' + next); }
  async function request(path, opts) {
    const method = (opts && opts.method) || 'GET';
    const res = await fetch(path, Object.assign({ cache: 'no-store', credentials: 'same-origin' }, opts, { headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders(method), (opts && opts.headers) || {}) }));
    return res;
  }
  const errMessage = (res, data) => { const d = data && data.detail; return typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg).join('; ') : `Request failed (HTTP ${res.status})`; };
  async function api(path, body, method) {
    const res = await request(path, { method: method || (body === undefined ? 'GET' : 'POST'), body: body === undefined ? undefined : JSON.stringify(body) });
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON error body */ }
    const sessionEnded = res.status === 401 && (!data || !data.error || data.error.code === 'auth_required');  // 401 with another code is a wrong password, not an expired session
    if (sessionEnded) { if (state.guest) throw new Error('Sign in to use this feature.'); toLogin(); throw new Error('Your session has ended. Redirecting to sign in…'); }
    if (res.status === 403 && data && data.error && data.error.code === 'csrf_failed') { await loadMe(); throw new Error('Your security token was refreshed. Please try that again.'); }
    if (!res.ok) throw new Error(errMessage(res, data));
    return data;
  }
  async function loadMe() {
    const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin', cache: 'no-store' });
    if (!res.ok) return false;
    const d = await res.json(); state.user = d.user; state.csrf = d.csrf; state.usage = d.usage; return true;
  }

  /* ---------- confirmation dialog ---------- */
  function confirmDialog(opts) {
    return new Promise(resolve => {
      const box = $('confirm'); $('confirm-title').textContent = opts.title || 'Are you sure?'; $('confirm-msg').textContent = opts.message || '';
      $('confirm-extra').innerHTML = opts.needPassword ? '<label class="field-label" for="confirm-pw">Confirm your password</label><input id="confirm-pw" class="control" type="password" autocomplete="current-password">' : '';
      $('confirm-ok').textContent = opts.confirmLabel || 'Confirm'; box.hidden = false;
      const first = opts.needPassword ? $('confirm-pw') : $('confirm-cancel'); first.focus();
      const done = v => { box.hidden = true; $('confirm-ok').onclick = $('confirm-cancel').onclick = null; document.removeEventListener('keydown', onKey); resolve(v); };
      const onKey = e => { if (e.key === 'Escape') done(null); };
      document.addEventListener('keydown', onKey);
      $('confirm-cancel').onclick = () => done(null);
      $('confirm-ok').onclick = () => done(opts.needPassword ? ($('confirm-pw').value || null) : true);
    });
  }

  /* ---------- navigation ---------- */
  function navigate(view, opts) {
    if (!VIEWS[view]) view = 'overview';
    if (state.guest && view !== 'overview') { toast('Sign in to use this part of the workspace.'); view = 'overview'; }
    state.view = view; closeDrawer();
    qsa('.view').forEach(el => { el.hidden = el.id !== 'view-' + view; });
    qsa('.nav-item').forEach(el => { if (el.dataset.view === view) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current'); });
    $('crumb').textContent = VIEWS[view];
    document.title = `${VIEWS[view]} · FreshCode AI`;
    if (!(opts && opts.fromHash) && location.hash !== '#' + view) history.replaceState(null, '', '#' + view);
    if (!(opts && opts.keepScroll)) window.scrollTo({ top: 0 });
    if (view === 'overview') refreshStats();
    if (view === 'history') loadHistory();
    if (view === 'settings') renderSettings();
    if (window.FCHooks && window.FCHooks[view]) window.FCHooks[view]();
    const h = document.querySelector(`#view-${view} h1`); if (h && !(opts && opts.fromHash)) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
  }
  document.addEventListener('click', e => {
    const nav = e.target.closest('[data-view]'); if (nav) { e.preventDefault(); navigate(nav.dataset.view); if (nav.dataset.acctOpen) setTimeout(() => { const t = document.querySelector(`[data-acct="${nav.dataset.acctOpen}"]`); if (t) t.click(); }, 0); return; }
    const go = e.target.closest('[data-go]'); if (go) { navigate(go.dataset.go); return; }
    const chip = e.target.closest('[data-preset]'); if (chip) applyPreset(chip.dataset.preset);
  });
  window.addEventListener('hashchange', () => { if (location.hash === '#demo') { history.replaceState(null, '', '#overview'); navigate('overview', { fromHash: true }); runDemo(); } else navigate(location.hash.slice(1), { fromHash: true }); });

  /* ---------- shell: collapsible sidebar (desktop) and drawer (mobile) ---------- */
  const shell = $('app-shell');
  function closeDrawer() { shell.classList.remove('drawer-open'); $('menu-btn').setAttribute('aria-expanded', 'false'); }
  $('menu-btn').addEventListener('click', () => { const open = !shell.classList.contains('drawer-open'); shell.classList.toggle('drawer-open', open); $('menu-btn').setAttribute('aria-expanded', String(open)); if (open) { const f = document.querySelector('#sidebar .nav-item:not(:disabled)'); if (f) f.focus(); } });
  $('drawer-scrim').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && shell.classList.contains('drawer-open')) { closeDrawer(); $('menu-btn').focus(); } });
  function setCollapsed(on) { shell.classList.toggle('collapsed', on); const b = $('collapse-nav'); b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', on ? 'Expand sidebar' : 'Collapse sidebar'); b.title = b.getAttribute('aria-label'); store.set('fc_nav', on ? 'collapsed' : 'open'); }
  $('collapse-nav').addEventListener('click', () => setCollapsed(!shell.classList.contains('collapsed')));
  if (store.get('fc_nav') === 'collapsed') setCollapsed(true);

  /* ---------- presets ---------- */
  const PRESETS = {
    'agent-1': { task: 'Build a Java 21 REST endpoint that validates a JWT, checks expiration, extracts the user ID and returns correct HTTP status codes. Include unit tests.', language: 'java', constraints: 'Java 21, Spring Boot 3.x' },
    'agent-2': { task: 'Implement a thread-safe token-bucket rate limiter class with allow(key) and configurable rate and burst. Include tests for refill timing and burst limits using an injectable clock.', language: 'python', constraints: 'Python 3.11, standard library only' },
    'agent-3': { task: 'Write a debounce utility with leading/trailing options and a cancel() method, fully typed. Include unit tests using fake timers.', language: 'typescript', constraints: 'TypeScript 5, no dependencies' },
    'verify-1': { text: 'Spring Boot 3.4 is the latest stable version. Java 17 is the newest LTS release. The Python requests library is at version 2.28 and is the current release.' },
    'verify-2': { text: 'The service costs $19 per month on the Pro plan. The current API uses the /v1/accounts endpoint and supports the include parameter. The free tier allows 1,000 requests per day as of 2023.' },
    'test-1': { code: 'def add(a, b):\n    return a + b\n', tests: 'from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n\ndef test_negative():\n    assert add(-1, 1) == 0\n' },
    'test-2': { code: 'def add(a, b):\n    return a - b\n', tests: 'from solution import add\n\ndef test_add():\n    assert add(2, 3) == 5\n' },
    'test-3': { code: 'import os\n\ndef run():\n    return os.listdir(".")\n', tests: 'from solution import run\n\ndef test_run():\n    assert run() is not None\n' },
    'test-4': { lang: 'javascript', code: 'exports.add = (a, b) => a + b;\n', tests: "const test = require('node:test');\nconst assert = require('node:assert');\nconst { add } = require('./solution');\n\ntest('adds', () => { assert.equal(add(2, 3), 5); });\ntest('negatives', () => { assert.equal(add(-1, 1), 0); });\n" }
  };
  function applyPreset(key) {
    const p = PRESETS[key]; if (!p) return;
    if (key.startsWith('agent')) { $('task').value = p.task; $('language').value = p.language; $('constraints').value = p.constraints; $('task').focus(); }
    else if (key.startsWith('verify')) { $('verify-text').value = p.text; $('verify-text').focus(); }
    else { $('test-lang').value = p.lang || 'python'; syncTestLang(); $('test-code').value = p.code; $('test-suite').value = p.tests; }
    toast('Example loaded. Press Run, or Ctrl+Enter.');
  }

  /* ---------- health / status ---------- */
  async function refreshHealth() {
    if (state.guest) { $('conn-dot').className = 'dot'; $('conn-title').textContent = 'Guest demo'; $('conn-detail').textContent = 'Sign in to connect your own services.'; paintProv('bifrost', null); paintProv('tavily', null); return; }
    try {
      const h = await api('/api/v1/system');
      state.health = h;
      const live = h.bifrost_verified && h.tavily_verified, conf = h.bifrost_configured && h.tavily_configured;
      $('conn-dot').className = 'dot' + (live ? ' good' : '');
      $('conn-title').textContent = live ? 'Live and verified' : conf ? 'Configured' : h.bifrost_configured || h.tavily_configured ? 'Partly configured' : 'Demo mode';
      $('conn-detail').textContent = live ? 'Both services answered a real request.' : conf ? 'Keys present; verified after the first request.' : 'Add keys on the server for live runs.';
      $('env-pill').textContent = String(h.environment || 'local').toUpperCase();
      paintProv('bifrost', h); paintProv('tavily', h);
      const mode = h.runner_mode === 'off' ? 'EXECUTION OFF' : h.runner_isolated ? 'DOCKER ISOLATED' : 'LOCAL RUNNER · NOT A SANDBOX';
      $('runner-mode').textContent = mode; $('runner-mode').className = 'tag ' + (h.runner_isolated ? 'green' : 'amber');
      $('agent-runner-note').textContent = h.runner_mode === 'off' ? 'Generated tests will not run: code execution is disabled on this server.' : h.runner_isolated ? 'Generated tests run in a disposable, network-less container.' : 'Generated tests run in the local runner. It enforces limits but is not a security sandbox.';
      if (state.view === 'overview') paintProviders();
      $('bench-model').textContent = h.bifrost_configured ? h.bifrost_model : 'Bifrost not configured';
      $('runner-hint').textContent = h.runner_mode === 'off' ? 'Code execution is disabled on this deployment' : h.runner_isolated ? 'Runs in an isolated container' : 'Local runner: limits enforced, not a sandbox';
      if (state.view === 'settings') renderSettings();
    } catch (e) {
      $('conn-dot').className = 'dot'; $('conn-title').textContent = 'Backend unreachable'; $('conn-detail').textContent = 'Start the server and refresh.'; paintProv('bifrost', null); paintProv('tavily', null);
    }
  }
  function paintProv(name, h) {
    const conf = h && h[name + '_configured'], ver = h && h[name + '_verified'];
    $('pdot-' + name).className = 'dot' + (ver ? ' good' : '');
    $('ptxt-' + name).textContent = !h ? 'unknown' : ver ? 'verified' : conf ? 'configured' : 'not set';
    $('prov-' + name).title = !h ? 'Status unavailable' : ver ? 'A real upstream request succeeded' : conf ? 'Key present, not yet verified by a request' : 'No key configured on the server';
  }
  function paintProviders() {
    const h = state.health, el = $('ov-providers'); if (!h) return;
    const row = (name, conf, ver, extra) => `<div class="list-item"><div class="grow"><b>${name}</b><small>${esc(extra)}</small></div>${pill(ver ? 'Verified' : conf ? 'Configured' : 'Not configured', ver ? 'good' : conf ? 'warn' : 'muted')}</div>`;
    el.innerHTML = row('Bifrost gateway', h.bifrost_configured, h.bifrost_verified, h.bifrost_configured ? `Model ${h.bifrost_model}` : 'Add BIFROST_API_KEY on the server') + row('Tavily search', h.tavily_configured, h.tavily_verified, h.tavily_configured ? 'Live research enabled' : 'Add TAVILY_API_KEY on the server');
  }
  function connCard(name, logo, desc, configured, verified, up, extra) {
    const s = up || {};
    return `<article class="card conn"><div class="logo" aria-hidden="true">${logo}</div><div><h3>${name}</h3><p>${desc}</p><div class="pills">${pill(configured ? 'Configured' : 'Not configured', configured ? 'good' : 'warn')}${pill(verified ? 'Verified ' + ago(s.last_ok_at) : 'Not yet verified', verified ? 'good' : 'muted')}${s.last_latency_ms != null ? pill(fmtMs(s.last_latency_ms), 'muted') : ''}${s.failures ? pill(s.failures + ' failure(s)', 'warn') : ''}</div>${extra || ''}${s.last_error ? `<p class="hint">Last error: ${esc(s.last_error)}</p>` : ''}</article>`;
  }
  function renderSettings() {
    const h = state.health; if (!h) return;
    const up = h.upstream || {};
    $('conn-grid').innerHTML = connCard('Bifrost gateway', 'B', 'OpenAI-compatible inference, routing and provider usage.', h.bifrost_configured, h.bifrost_verified, up.bifrost, h.bifrost_configured ? `<p class="hint">Model <code>${esc(h.bifrost_model)}</code> · host <code>${esc(h.bifrost_host)}</code></p>` : '')
      + connCard('Tavily Search', 'T', 'Live web research and technical source retrieval.', h.tavily_configured, h.tavily_verified, up.tavily, '');
    const rows = [['Version', h.version], ['Environment', h.environment], ['Uptime', fmtMs(h.uptime_seconds * 1000)], ['Code execution', h.runner_mode === 'off' ? 'Disabled' : h.runner_isolated ? 'Isolated container (docker)' : 'Local runner (policy + limits, NOT a sandbox)'], ['Database', `${h.database.engine} · schema v${h.database.schema_version}`], ['Rate limits', `${h.limits.per_minute}/min · ${h.limits.heavy_per_minute}/min heavy · ${h.limits.daily_runs} runs/day per user`], ['Agent timeout', h.limits.agent_timeout_seconds + ' s'], ['Model routing', `primary ${h.bifrost_model || '—'} · assessor ${h.bifrost_fast_model || 'same as primary'} · fallback ${h.bifrost_fallback_model || 'none'}`], ['Cache', `Bifrost ${h.cache.bifrost.hits} hit / ${h.cache.bifrost.misses} miss · Tavily ${h.cache.tavily.hits} hit / ${h.cache.tavily.misses} miss`], ['Auto-tested languages', (h.test_languages || []).join(', ') || 'none'], ['Status semantics', h.service_state_semantics]];
    $('deploy-dl').innerHTML = rows.map(r => `<dt>${esc(r[0])}</dt><dd>${esc(r[1])}</dd>`).join('');
  }

  /* ---------- overview data ---------- */
  function historyRow(r, withActions) {
    const tone = r.status === 'ok' ? 'good' : r.status === 'setup_required' || r.status === 'unmeasured' ? 'warn' : 'bad';
    const acts = !withActions ? `<span class="row-actions"><a class="btn-sm" href="/api/v1/runs/${r.id}/report.md" download>Report</a></span>` : withActions ? `<span class="row-actions"><button class="btn-sm" data-trace="${r.id}">Trace</button><a class="btn-sm" href="/api/v1/runs/${r.id}/report.md" download>Report</a>${r.kind === 'benchmark' ? `<a class="btn-sm" href="/api/v1/runs/${r.id}/benchmark.csv" download>CSV</a>` : ''}<button class="btn-sm" data-export="${r.id}">JSON</button></span>` : '';
    return `<div class="list-item"><div class="grow"><b>${esc(r.title)}</b><small>${esc(kindLabel(r.kind))} · ${esc(r.summary || '')}${r.latency_ms != null ? ' · ' + esc(fmtMs(r.latency_ms)) : ''}</small></div>${pill(r.status.replace(/_/g, ' '), tone)}<time datetime="${new Date(r.created_at * 1000).toISOString()}">${esc(ago(r.created_at))}</time>${acts}</div>${withActions ? `<div class="trace-slot" id="trace-${r.id}" hidden></div>` : ''}`;
  }
  async function refreshStats() {
    if (state.guest) return;
    try {
      const [s, h] = await Promise.all([api('/api/v1/stats'), api('/api/v1/runs?limit=5')]);
      $('kpi-savings').textContent = s.avg_token_savings_pct == null ? '—' : fmtPct(s.avg_token_savings_pct);
      $('kpi-savings-foot').textContent = s.avg_token_savings_pct == null ? 'Run a benchmark with Bifrost to measure.' : `Average of ${s.benchmark_runs_measured} measured run(s) · best ${fmtPct(s.best_token_savings_pct)}`;
      $('kpi-pass').textContent = s.test_pass_rate == null ? '—' : s.test_pass_rate + '%';
      $('kpi-pass-foot').textContent = s.test_runs ? `${s.test_runs} test run(s) executed` : 'No test runs yet.';
      $('kpi-runs').textContent = fmtNum(s.total_runs);
      $('kpi-runs-foot').textContent = s.provider_tokens_total ? `${fmtNum(s.provider_tokens_total)} provider tokens used` + (s.estimated_spend_usd != null ? ` · ~$${s.estimated_spend_usd} est.` : '') : 'Saved to your account.';
      $('kpi-latency').textContent = fmtMs(s.avg_latency_ms);
      if (s.avg_token_savings_pct != null && !state.roiTouched) { $('roi-pct').value = s.avg_token_savings_pct; $('roi-src').textContent = '(measured average)'; paintRoi(); }
      paintProviders(); paintOverviewProjects();
      api('/api/v1/usage').then(u => { const q = u.quota, pct = Math.min(100, Math.round(100 * q.runs_used / q.runs_limit)); $('ov-usage').innerHTML = `<div class="quota"><div class="quota-bar" role="img" aria-label="${pct}% of daily runs used"><i style="width:${pct}%"></i></div><b>${esc(q.runs_used)} / ${esc(q.runs_limit)}</b></div><p class="hint">${esc(q.runs_remaining)} runs remaining · ${esc(q.window)}${u.totals.provider_tokens_total ? ' · ' + esc(fmtNum(u.totals.provider_tokens_total)) + ' provider tokens used' : ''}</p>`; }).catch(() => { $('ov-usage').innerHTML = '<p class="hint">Usage is unavailable right now.</p>'; });
      const badge = $('nav-history-count'); badge.hidden = !s.total_runs; badge.textContent = s.total_runs;
      $('recent').innerHTML = h.runs.length ? h.runs.map(r => historyRow(r, false)).join('') : '<div class="empty"><b>No activity yet</b><small>Run the demo or an agent task to see it here.</small></div>';
    } catch (e) { /* stats are non-critical */ }
  }
  function paintOverviewProjects() {
    const live = state.projects.filter(p => !p.archived);
    $('ov-projects').innerHTML = live.length ? live.slice(0, 5).map(p => `<div class="list-item"><div class="grow"><b>${esc(p.name)}</b><small>${esc(p.language)} · budget ${esc(p.context_budget)} tokens</small></div>${pill(p.run_count === 1 ? '1 run' : p.run_count + ' runs', p.run_count ? 'brand' : 'muted')}</div>`).join('') : '<div class="empty"><b>No projects yet</b><small>Projects keep language, constraints and budget together.</small><button class="btn primary" data-go="projects" type="button">Create a project</button></div>';
  }
  async function loadHistory() {
    skeleton('history-list'); $('history-list').hidden = false;
    const qs = new URLSearchParams({ limit: '100' });
    if ($('hist-q').value.trim()) qs.set('q', $('hist-q').value.trim());
    if ($('hist-kind').value) qs.set('kind', $('hist-kind').value);
    if ($('hist-status').value) qs.set('status', $('hist-status').value);
    if ($('hist-project').checked && state.projectId) qs.set('project_id', state.projectId);
    try {
      const d = await api('/api/v1/runs?' + qs.toString());
      const filtered = qs.has('q') || qs.has('kind') || qs.has('status') || qs.has('project_id');
      $('history-list').innerHTML = d.runs.length ? d.runs.map(r => historyRow(r, true)).join('') : `<div class="empty"><b>${filtered ? 'No runs match these filters' : 'No runs yet'}</b><small>${filtered ? 'Clear the filters to see everything.' : 'Everything you run is saved here with its trace and report.'}</small></div>`;
    } catch (e) { $('history-list').innerHTML = errorCard(e.message); }
  }
  let histTimer; ['hist-q'].forEach(id => $(id).addEventListener('input', () => { clearTimeout(histTimer); histTimer = setTimeout(loadHistory, 250); }));
  ['hist-kind', 'hist-status', 'hist-project'].forEach(id => $(id).addEventListener('change', loadHistory));
  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-export]'); if (!b) return;
    try { const item = await api('/api/v1/runs/' + encodeURIComponent(b.dataset.export)); download(`freshcode-run-${b.dataset.export}.json`, JSON.stringify(item, null, 2)); } catch (err) { toast(err.message); }
  });
  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-trace]'); if (!b) return;
    const slot = $('trace-' + b.dataset.trace); if (!slot) return;
    if (!slot.hidden) { slot.hidden = true; return; }
    try {
      const item = await api('/api/v1/runs/' + encodeURIComponent(b.dataset.trace));
      const t = item.payload && item.payload.trace;
      slot.innerHTML = t ? traceMarkup(t) : '<p class="hint">This run type has no trace (traces are recorded for engineering-agent runs).</p>';
      slot.hidden = false;
    } catch (err) { toast(err.message); }
  });
  $('export-history').addEventListener('click', () => { window.location.assign('/api/v1/runs/export.csv'); });
  $('clear-history').addEventListener('click', async () => {
    const ok = await confirmDialog({ title: 'Clear your run history?', message: 'This permanently deletes every saved run, trace and report on your account. Projects are kept.', confirmLabel: 'Delete history' });
    if (!ok) return;
    try { const d = await api('/api/v1/runs', undefined, 'DELETE'); toast(`Deleted ${d.deleted} run(s)`); loadHistory(); refreshStats(); } catch (e) { toast(e.message); }
  });

  /* ---------- shared renderers ---------- */
  function sourceMarkup(s) {
    const t = trustMeta(s.trust);
    return `<div class="source"><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.title || s.url || 'Source')} ↗</a><p>${esc(s.content || 'No snippet supplied.')}</p><div class="meta">${s.trust ? pill(t.label, t.tone) : ''}<span>${esc(host(s.url))}</span><span>· ${esc(s.published_date || 'publication date unavailable')}</span>${s.relevance != null ? `<span>· relevance ${Math.round(s.relevance * 100)}%</span>` : ''}</div></div>`;
  }
  const proofLine = m => m && (m.request_id || m.response_time != null) ? `<p class="proofline">Proof of live retrieval — Tavily request <code>${esc(m.request_id || 'n/a')}</code>${m.response_time != null ? ' · ' + esc(m.response_time) + ' s' : ''}${m.cached ? ' · served from cache' : ''}</p>` : '';
  const sourcesCard = (title, list, note, meta) => list && list.length ? `<article class="result"><h3>${esc(title)}</h3><p class="hint">${esc(note || '')}</p>${proofLine(meta)}<div class="sources">${list.map(sourceMarkup).join('')}</div></article>` : '';
  function traceMarkup(trace) {
    const rows = traceRows(trace);
    if (!rows.length) return '';
    return `<div class="trace" role="list" aria-label="Run trace">${rows.map(r => `<div class="trace-row" role="listitem"><b>${esc(r.name)}</b><div class="track"><div class="seg${r.error ? ' err' : ''}" style="left:${r.left}%;width:${Math.min(r.width, 100 - r.left)}%"></div></div><time>${esc(fmtMs(r.ms))}</time>${r.detail || r.error ? `<div class="trace-detail${r.error ? ' err' : ''}">${esc(r.error || r.detail)}</div>` : ''}</div>`).join('')}</div>`;
  }
  const proseOnly = a => String(a || '').replace(/```[\s\S]*?```/g, '').trim();

  function claimMarkup(c) {
    const v = verdictMeta(c.verdict), drift = c.version_drift || {};
    const stale = c.possibly_outdated, contra = c.verdict === 'contradicted';
    const rec = c.freshness_score == null ? 'Source date unknown' : `Source recency ${c.freshness_score}/100`;
    return `<article class="claim${stale ? ' stale' : ''}${contra ? ' contra' : ''}"><div class="claim-top">${pill(c.kind || 'claim', 'brand')}${stale ? pill('Possibly outdated', 'warn') : ''}${pill(v.label, v.tone)}${pill(rec, 'muted')}${c.confidence != null ? pill('Confidence ' + c.confidence + '%', 'muted') : ''}</div><blockquote>${esc(c.claim)}</blockquote>${stale ? callout('warn', `<b>Newer version detected.</b> ${esc(drift.detail || '')} <span class="hint">Deterministic text check on retrieved snippets — confirm on the official page.</span>`) : ''}${c.suggested_correction ? `<div class="fix"><b>Suggested correction</b><br><span class="from">${esc(c.suggested_correction.from)}</span> → ${markChange(c.suggested_correction.corrected, c.suggested_correction.to)}<small>${esc(c.suggested_correction.note)}</small></div>` : ''}${drift.status === 'version_mentioned_in_sources' ? `<p class="hint">${esc(drift.detail)}</p>` : ''}<p class="hint">${esc(c.reason || 'Manual review required.')}</p>${c.error ? `<p class="hint">Search error: ${esc(c.error)}</p>` : ''}${proofLine(c.retrieval)}${c.sources && c.sources.length ? `<details${stale || contra ? ' open' : ''}><summary>${c.sources.length} source${c.sources.length > 1 ? 's' : ''} checked</summary><div class="sources">${c.sources.map(sourceMarkup).join('')}</div></details>` : '<p class="hint">No sources found. Manual verification required.</p>'}</article>`;
  }

  /* ---------- engineering agent: three-region workspace ---------- */
  const STAGE_KEYS = ['received', 'research', 'evidence', 'optimize', 'generate', 'extract', 'test', 'diagnose', 'repair', 'final', 'saved'];
  const PROGRESS_TO_STAGE = { research: 'research', optimize: 'optimize', generate: 'generate', verify: 'test' };
  const pad = n => String(n).padStart(2, '0');
  function logActivity(stage, st, msg) {
    const el = $('activity'); if (!el) return;
    const d = new Date(), t = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    const cls = st === 'done' ? 'ok' : st === 'error' ? 'er' : 'st';
    const row = document.createElement('div');
    row.innerHTML = `<span class="t">${t}</span>  <span class="${cls}">[${esc(stage)}]</span> ${esc(msg || st)}`;
    el.appendChild(row); el.scrollTop = el.scrollHeight;
  }
  function resetPipeline() { qsa('#pipeline li').forEach(li => { li.className = ''; li.querySelector('em').textContent = 'Waiting'; li.querySelector('i').textContent = STAGE_KEYS.indexOf(li.dataset.stage) + 1; }); }
  function setStage(stage, st, msg) {
    const li = document.querySelector(`#pipeline li[data-stage="${stage}"]`); if (!li) return;
    li.className = st === 'done' ? 'done' : st === 'error' ? 'error' : st === 'skipped' ? 'skipped' : 'active';
    li.querySelector('em').textContent = msg || st;
    li.querySelector('i').textContent = st === 'done' ? '✓' : st === 'error' ? '!' : st === 'skipped' ? '–' : STAGE_KEYS.indexOf(stage) + 1;
  }
  function setRunState(text, tone) { const el = $('run-state'); el.textContent = text; el.className = 'pill ' + (tone || 'muted'); }
  function tickElapsed() { const ms = Date.now() - state.t0, s = ms / 1000; $('elapsed').textContent = `${pad(Math.floor(s / 60))}:${(s % 60).toFixed(1).padStart(4, '0')}`; }
  function startTimer() { state.t0 = Date.now(); clearInterval(state.timer); tickElapsed(); state.timer = setInterval(tickElapsed, 100); }
  function stopTimer() { clearInterval(state.timer); state.timer = null; if (state.t0) tickElapsed(); }

  function codePane(id, title, code, lang, hiddenPane) {
    return `<div class="code-pane" data-pane-id="${id}"${hiddenPane ? ' hidden' : ''}><pre class="code-block" tabindex="0" aria-label="${esc(title)}"><code>${highlight(code, lang)}</code></pre></div>`;
  }
  function renderAgent(d) {
    const tr = d.token_report || {}, u = d.provider_usage || {}, comp = d.compression || {}, v = d.verification || {};
    const compMetric = metric('EVIDENCE (EST. TOKENS)', comp.original_tokens != null ? `${fmtNum(comp.original_tokens)} → ${fmtNum(comp.compressed_tokens)}` : '—', 'Estimated tokens before and after compression', 'est');
    let main = '', exec = '';
    if (d.mode === 'setup_required') {
      main = `<article class="result"><div class="result-head"><div><h3>Prompt prepared — generation needs Bifrost</h3><p>${esc(d.message)}</p></div><span class="tag amber">SETUP REQUIRED</span></div><details open><summary>Inspect the compact prompt</summary><pre class="code-block"><code>${esc(d.prompt_preview)}</code></pre></details>${callout('info', 'No code was generated and no tests were run. Add Bifrost credentials on the server, or use <b>Run the 60-second demo</b> on Overview.')}</article>`;
      exec = `<article class="card"><h3>Token estimates</h3><div class="metrics">${metric('EST. INPUT TOKENS', fmtNum(d.estimated_input_tokens), 'Local estimate, not provider data', 'est')}${compMetric}${metric('SOURCES', d.sources.length)}</div></article>`;
    } else {
      const lang = state.lastLang, hasTests = !!d.tests;
      const tabs = `<div class="code-tabs" role="tablist" aria-label="Generated files"><button type="button" role="tab" data-code-tab="impl" aria-selected="true">Implementation</button>${hasTests ? '<button type="button" role="tab" data-code-tab="tests" aria-selected="false">Tests</button>' : ''}${proseOnly(d.answer) ? '<button type="button" role="tab" data-code-tab="notes" aria-selected="false">Notes</button>' : ''}</div>`;
      main = d.code ? `<article class="result" id="code-card"><div class="result-head"><div><h3>Generated implementation</h3><p>Model ${esc(d.model || 'configured')}${d.routing && d.routing.provider ? ` via ${esc(d.routing.provider)}${d.routing.fallback_index > 0 ? ' (fallback)' : ''}` : ''} · request ${esc(d.request_id || 'n/a')} · ${esc(fmtMs(d.latency_ms))}. Review before use.</p></div><span class="tag green">LIVE · BIFROST</span></div>${tabs}${codePane('impl', 'Generated implementation', d.code, lang, false)}${hasTests ? codePane('tests', 'Generated tests', d.tests, lang, true) : ''}${proseOnly(d.answer) ? `<div class="code-pane rich" data-pane-id="notes" hidden>${renderRich(proseOnly(d.answer))}</div>` : ''}<div class="btn-row"><button class="btn-sm" data-act="copy-code">Copy code</button><button class="btn-sm" data-act="download-code">Download code</button>${hasTests ? '<button class="btn-sm" data-act="copy-tests">Copy tests</button><button class="btn-sm" data-act="download-tests">Download tests</button><button class="btn-sm" data-act="to-testlab">Open in Test Lab →</button>' : ''}<button class="btn-sm" data-act="expand" aria-pressed="false">Expand viewer</button></div></article>` : `<article class="result">${callout('bad', '<b>No code block was found</b> in the model reply, so nothing was extracted or tested.')}${proseOnly(d.answer) ? `<div class="rich">${renderRich(proseOnly(d.answer))}</div>` : ''}</article>`;
      exec = `<article class="card"><h3>Bifrost usage</h3><div class="metrics">${metric('PROVIDER INPUT TOKENS', tr.cache_hit ? '0 (cache)' : fmtNum(tr.provider_input_tokens), 'Reported by the gateway; 0 when served from cache', 'measured')}${metric('PROVIDER TOTAL TOKENS', tr.cache_hit ? '0 (cache)' : fmtNum(u.total_tokens), '', 'measured')}${compMetric}${metric('LLM CALLS', tr.llm_calls == null ? '—' : tr.llm_calls)}</div></article>`;
      if (v.ran) exec += `<article class="card ${v.passed ? 'verified' : ''}"><div class="result-head"><div><h3>Verification</h3><p>${esc(v.tests_passed)} passed · ${esc(v.tests_failed)} failed · ${esc(fmtMs(v.duration_ms))} · ${esc(v.attempts)} attempt(s)</p></div>${v.passed ? '<span class="tag green">TESTS PASSED</span>' : v.blocked ? '<span class="tag amber">BLOCKED BY POLICY</span>' : '<span class="tag amber">TESTS FAILED</span>'}</div>${v.repaired ? callout('good', '<b>Self-repaired.</b> The first attempt failed; one compact repair prompt fixed it.') : ''}<details${v.passed ? '' : ' open'}><summary>Test output</summary><pre class="code-block"><code>${esc(v.output)}</code></pre></details></article>`;
      else if (v.reason) exec += `<article class="card">${callout('info', '<b>Tests not run:</b> ' + esc(String(v.reason).replace(/_/g, ' ')))}</article>`;
    }
    if (d.research_error) exec += `<article class="card">${callout('warn', '<b>Research degraded gracefully:</b> ' + esc(d.research_error))}</article>`;
    if (d.sources && d.sources.length) exec += `<article class="card research"><h3>Tavily sources</h3><p class="hint">Retrieved live. Open the originals to check relevance.</p>${proofLine(d.research_meta)}<div class="sources">${d.sources.map(sourceMarkup).join('')}</div></article>`;
    if (d.trace) exec += `<article class="card"><div class="result-head"><div><h3>Run trace</h3><p>${esc(fmtMs(d.trace.total_ms))} total, recorded with the run.</p></div><span class="tag blue">GLASS BOX</span></div>${traceMarkup(d.trace)}</article>`;
    reveal('agent-output', main); reveal('agent-result', exec);
    const fs = finalStages(d); Object.keys(fs).forEach(k => setStage(k, fs[k].state, fs[k].msg));
    if (d.mode === 'setup_required') { setStage('generate', 'error', 'Bifrost not configured'); }
    else { qsa('#pipeline li[data-stage="test"]').forEach(li => { if (!li.classList.contains('done') && !li.classList.contains('skipped')) li.className = ''; }); }
  }
  function agentFail(msg) { reveal('agent-output', errorCard(msg)); setRunState('Failed', 'bad'); }
  async function runAgent() {
    const task = $('task').value.trim(); if (task.length < 8) { toast('Describe the coding task in a little more detail.'); return $('task').focus(); }
    const btn = $('generate'); busy(btn, true); $('cancel-run').hidden = false; $('retry-run').hidden = true; resetPipeline(); $('activity').innerHTML = ''; $('agent-result').innerHTML = '';
    reveal('agent-output', '<div class="skeleton"></div><div class="skeleton"></div>'); setRunState('Running', 'brand'); startTimer(); setStage('received', 'running', 'Sending request');
    logActivity('run', 'running', 'Started: ' + task.slice(0, 70)); state.lastLang = $('language').value; if (window.innerWidth <= 1280) paneTo('exec');
    try {
      state.abort = new AbortController();
      const res = await request('/api/v1/code/stream', { method: 'POST', signal: state.abort.signal, body: JSON.stringify({ task, language: $('language').value, constraints: $('constraints').value, verify_facts: $('verify-facts').checked, auto_test: $('auto-test').checked, auto_repair: $('auto-repair').checked, context_budget: Number($('budget').value), project_id: state.projectId ? Number(state.projectId) : null }) });
      if (res.status === 401) { toLogin(); throw new Error('Your session has ended. Redirecting to sign in…'); }
      if (!res.ok) { let m = 'Agent request failed'; try { m = errMessage(res, await res.json()); } catch (e) { /* keep default */ } throw new Error(m); }
      setStage('received', 'done', 'Accepted by server');
      const reader = res.body.getReader(), dec = new TextDecoder(); let buf = '', result = null;
      for (;;) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const ev = (block.match(/^event: (.+)$/m) || [])[1], data = (block.match(/^data: (.+)$/m) || [])[1]; if (!ev || !data) continue;
          const p = JSON.parse(data);
          if (ev === 'progress') {
            const key = PROGRESS_TO_STAGE[p.stage] || p.stage;
            setStage(key, p.state, p.message); logActivity(p.stage, p.state, p.message);
            if (p.stage === 'research' && p.state === 'done') setStage('evidence', p.sources ? 'done' : 'skipped', p.sources ? `${p.sources} source(s) collected` : 'No sources');
          } else if (ev === 'result') result = p; else if (ev === 'error') throw new Error(p.message);
        }
      }
      if (!result) throw new Error('The agent stream ended without a result.');
      state.lastCode = result.code || ''; state.lastTests = result.tests || ''; state.lastResult = result;
      stopTimer(); logActivity('run', 'done', 'Finished in ' + fmtMs(result.trace ? result.trace.total_ms : null)); renderAgent(result);
      const ver = result.verification || {}; setRunState(result.mode === 'setup_required' ? 'Setup required' : ver.ran && !ver.passed ? 'Tests failed' : 'Complete', result.mode === 'setup_required' || (ver.ran && !ver.passed) ? 'warn' : 'good');
      refreshStats(); refreshHealth();
    } catch (e) {
      stopTimer();
      if (e.name === 'AbortError') { logActivity('run', 'error', 'Stopped by you'); reveal('agent-output', `<article class="result">${callout('info', '<b>Run stopped.</b> The server cancels the agent when the connection closes. Nothing was saved for this run.')}</article>`); setRunState('Stopped', 'warn'); }
      else { qsa('#pipeline li.active').forEach(li => { li.className = 'error'; li.querySelector('em').textContent = 'Failed'; }); logActivity('run', 'error', e.message); agentFail(e.message); toast(e.message); }
    }
    finally { busy(btn, false); $('cancel-run').hidden = true; $('retry-run').hidden = false; state.abort = null; }
  }
  $('generate').addEventListener('click', runAgent);
  $('retry-run').addEventListener('click', runAgent);
  $('cancel-run').addEventListener('click', () => { if (state.abort) state.abort.abort(); });
  $('budget').addEventListener('input', () => { $('budget-val').textContent = $('budget').value; });
  document.addEventListener('click', e => {
    const tab = e.target.closest('[data-code-tab]');
    if (tab) { const card = tab.closest('.result'); qsa('[data-code-tab]', card).forEach(b => b.setAttribute('aria-selected', String(b === tab))); qsa('.code-pane', card).forEach(p => { p.hidden = p.dataset.paneId !== tab.dataset.codeTab; }); return; }
    const a = e.target.closest('[data-act]'); if (!a) return;
    const base = slug($('task').value), ext = fileExt(state.lastLang);
    if (a.dataset.act === 'copy-code') copy(state.lastCode);
    else if (a.dataset.act === 'copy-tests') copy(state.lastTests);
    else if (a.dataset.act === 'download-code') download(`${base}.${ext}`, state.lastCode);
    else if (a.dataset.act === 'download-tests') download(`${base}.test.${ext}`, state.lastTests);
    else if (a.dataset.act === 'to-testlab') { $('test-lang').value = state.lastLang === 'javascript' ? 'javascript' : 'python'; syncTestLang(); $('test-code').value = state.lastCode; $('test-suite').value = state.lastTests; navigate('tests'); }
    else if (a.dataset.act === 'expand') { const on = a.getAttribute('aria-pressed') !== 'true'; a.setAttribute('aria-pressed', String(on)); a.textContent = on ? 'Collapse viewer' : 'Expand viewer'; qsa('#code-card .code-block').forEach(p => p.classList.toggle('expanded', on)); }
  });
  /* workspace panels on narrower screens + agent project selector */
  function paneTo(name) { $('ws').dataset.pane = name; qsa('.ws-tabs [data-pane]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.pane === name))); }
  qsa('.ws-tabs [data-pane]').forEach(b => b.addEventListener('click', () => paneTo(b.dataset.pane)));
  function paintAgentProject() {
    const sel = $('agent-project'); sel.innerHTML = '<option value="">No project</option>' + state.projects.filter(p => !p.archived).map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join(''); sel.value = state.projectId || '';
  }
  $('agent-project').addEventListener('change', () => { $('project-select').value = $('agent-project').value; $('project-select').dispatchEvent(new Event('change')); });

  /* ---------- freshness ---------- */
  async function runVerify() {
    const text = $('verify-text').value.trim(); if (text.length < 8) { toast('Paste an answer to verify.'); return $('verify-text').focus(); }
    const btn = $('verify-btn'); busy(btn, true); skeleton('verify-result');
    try {
      const d = await api('/api/v1/verify', { text, project_id: state.projectId ? Number(state.projectId) : null }), s = d.summary || {};
      let html = `<article class="result"><div class="result-head"><div><h3>Evidence audit</h3><p>${esc(d.note)}</p></div><span class="tag ${d.live_verification ? 'green' : 'amber'}">${d.live_verification ? 'LIVE SEARCH' : 'SEARCH NOT CONFIGURED'}</span></div><div class="metrics">${metric('CLAIMS CHECKED', d.claims_found)}${metric('POSSIBLY OUTDATED', s.possibly_outdated || 0)}${metric('CONTRADICTED', s.contradicted || 0)}${metric('SUPPORTED', s.supported || 0)}${metric('AVG SOURCE RECENCY', d.overall_freshness == null ? '—' : d.overall_freshness + '/100')}</div>${!d.live_verification ? callout('info', 'Add <code>TAVILY_API_KEY</code> to check claims against live sources. Claims are still extracted and ranked by risk.') : ''}${d.live_verification && !d.assessment_available ? callout('info', 'LLM verdicts need Bifrost. Version-drift detection still runs without it.') : ''}</article>`;
      if (!d.claims.length) html += `<article class="result">${callout('info', '<b>No change-sensitive claims detected.</b> Try including versions, prices, API details, release dates or policies.')}</article>`;
      if (d.corrected_text) html += `<article class="result"><div class="result-head"><div><h3>Corrected answer (suggested)</h3><p>${esc(d.corrections_count)} stale claim(s) rewritten from retrieved evidence. Confirm on the official source before using.</p></div><span class="tag green">AUTO-FIX</span></div><div class="rich"><p>${esc(d.corrected_text)}</p></div><div class="btn-row"><button class="btn-sm" id="v-copyfix">Copy corrected answer</button></div></article>`;
      html += d.claims.map(claimMarkup).join('');
      html += `<div class="btn-row"><button class="btn-sm" id="v-report">Download report (.md)</button></div>`;
      reveal('verify-result', html); refreshStats();
      if ($('v-copyfix')) $('v-copyfix').onclick = () => copy(d.corrected_text);
      $('v-report').onclick = () => download('freshcode-freshness-report.md', reportMarkdown(d));
    } catch (e) { reveal('verify-result', errorCard(e.message)); }
    finally { busy(btn, false); }
  }
  $('verify-btn').addEventListener('click', runVerify);

  /* ---------- evaluation lab (benchmark suite) ---------- */
  async function runBench() {
    const task = $('bench-task').value.trim(); if (task.length < 8) { toast('Enter a benchmark task.'); return $('bench-task').focus(); }
    const extra = $('bench-extra').value.split('\n').map(x => x.trim()).filter(x => x.length >= 8).slice(0, 4);
    const btn = $('bench-btn'); busy(btn, true); skeleton('bench-result');
    try {
      const d = await api('/api/v1/benchmark', { task, extra_tasks: extra, language: $('bench-lang').value, project_id: state.projectId ? Number(state.projectId) : null });
      if (d.mode === 'setup_required') { reveal('bench-result', `<article class="result">${callout('warn', '<b>Connect Bifrost to benchmark.</b> ' + esc(d.message))}</article>`); return; }
      const g = d.aggregate || {}, first = (d.tasks || [])[0] || {}, w = barWidths(first.baseline_input_tokens, first.optimized_input_tokens);
      const rows = (d.tasks || []).map((t, i) => `<tr><td>${i + 1}</td><td>${esc(t.task.slice(0, 80))}</td><td>${esc(fmtNum(t.baseline_input_tokens))}</td><td>${esc(fmtNum(t.optimized_input_tokens))}</td><td>${esc(fmtPct(t.token_savings_percent))}</td><td>${t.measured ? pill('measured', 'good') : pill('not measured', 'warn')}</td></tr>`).join('');
      reveal('bench-result', `<article class="result"><div class="result-head"><div><h3>Paired benchmark result</h3><p>Model ${esc(d.model || 'configured')} · ${esc((d.tasks || []).length)} task(s) · ${esc(d.repetitions)} paired samples each · alternating call order</p></div><span class="tag ${d.measured ? 'green' : 'amber'}">${d.measured ? 'PROVIDER MEASURED' : 'NOT MEASURED'}</span></div>${d.measured ? `<div class="big-saving">${esc(fmtPct(g.median_savings_pct))} <small class="hint">median input-token saving</small></div><p class="hint">Range ${esc(fmtPct(g.min_savings_pct))} to ${esc(fmtPct(g.max_savings_pct))} across ${esc(g.measured_tasks)} task(s); FreshCode used fewer tokens on ${esc(g.tasks_improved)}.</p>` : callout('warn', '<b>Not measured.</b> The gateway did not return usage for every call (or models differed). No saving is claimed.')}<div class="bars" role="img" aria-label="Median input tokens for the first task, baseline versus FreshCode"><div class="bar-row"><span>Baseline (task 1)</span><div class="bar-track"><div class="bar-fill" data-w="${w[0]}"></div></div><b>${esc(fmtNum(first.baseline_input_tokens))}</b></div><div class="bar-row"><span>FreshCode (task 1)</span><div class="bar-track"><div class="bar-fill brand" data-w="${w[1]}"></div></div><b>${esc(fmtNum(first.optimized_input_tokens))}</b></div></div><div class="table-wrap"><table class="score-table"><caption class="sr-only">Per-task results</caption><thead><tr><th>#</th><th>Task</th><th>Baseline</th><th>FreshCode</th><th>Saving</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>${g.estimated_cost_saved_per_1k_runs_usd != null ? `<p class="hint">Estimated input-cost saving per 1,000 runs: ~$${esc(g.estimated_cost_saved_per_1k_runs_usd)} (from your configured price; an estimate, not billing data).</p>` : ''}<p class="hint">${esc(d.statistical_note)}</p><div class="btn-row">${d.run_id ? `<a class="btn-sm" href="/api/v1/runs/${d.run_id}/benchmark.csv" download>Download raw CSV</a><a class="btn-sm" href="/api/v1/runs/${d.run_id}/report.md" download>Download Markdown report</a>` : ''}</div></article>`);
      requestAnimationFrame(() => requestAnimationFrame(() => qsa('.bar-fill').forEach(el => { el.style.width = el.dataset.w + '%'; })));
      refreshStats();
    } catch (e) { reveal('bench-result', errorCard(e.message)); }
    finally { busy(btn, false); }
  }
  $('bench-btn').addEventListener('click', runBench);

  /* ---------- tests ---------- */
  function syncTestLang() {
    const js = $('test-lang').value === 'javascript';
    $('test-code-label').textContent = js ? 'solution.js' : 'solution.py'; $('test-suite-label').textContent = js ? 'solution.test.js' : 'test_solution.py';
  }
  $('test-lang').addEventListener('change', syncTestLang);
  async function runTests() {
    const code = $('test-code').value, tests = $('test-suite').value; if (!code.trim() || !tests.trim()) return toast('Add both the solution and its tests.');
    const btn = $('test-btn'); busy(btn, true); skeleton('test-result');
    try {
      const d = await api('/api/v1/test', { language: $('test-lang').value, code, tests, project_id: state.projectId ? Number(state.projectId) : null });
      const tag = d.passed ? '<span class="tag green">ALL TESTS PASSED</span>' : d.blocked ? '<span class="tag amber">BLOCKED</span>' : '<span class="tag amber">TESTS FAILED</span>';
      reveal('test-result', `<article class="result"><div class="result-head"><div><h3>Test execution report</h3><p>${esc(d.warning)}</p></div>${tag}</div><div class="metrics">${metric('PASSED', d.tests_passed)}${metric('FAILED', d.tests_failed)}${metric('DURATION', fmtMs(d.duration_ms))}${metric('EXIT CODE', d.exit_code)}</div><pre class="code-block"><code>${esc(d.output || 'No output')}</code></pre></article>`);
      refreshStats();
    } catch (e) { reveal('test-result', errorCard(e.message)); }
    finally { busy(btn, false); }
  }
  $('test-btn').addEventListener('click', runTests);

  /* ---------- judge demo ---------- */
  async function runDemo() {
    const btn = $('run-demo'); busy(btn, true); $('demo-result').hidden = false; skeleton('demo-result');
    try {
      const d = await api('/api/v1/demo', {}), t = d.tests || {}, comp = d.compression || {}, claim = d.verification.claims[0], drift = claim.version_drift || {};
      reveal('demo-result', `<article class="result"><div class="result-head"><div><h3>End-to-end demo complete</h3><p>${esc(d.notice)}</p></div><span class="tag amber">FIXTURES + REAL LOCAL ENGINE</span></div><div class="metrics">${metric(t.blocked ? 'PYTEST RUN' : 'REAL PYTEST RUN', t.blocked ? 'Blocked' : (t.passed ? `${t.tests_passed} passed` : 'failed'), t.blocked ? 'Code execution is disabled on this deployment' : 'Executed just now by the local runner')}${metric('REAL EVIDENCE COMPRESSION', `${fmtNum(comp.original_tokens)} → ${fmtNum(comp.compressed_tokens)}`, 'Estimated tokens, computed locally')}${metric('SAVED (EST.)', fmtPct(comp.saved_percent))}${metric('VERSION DRIFT', drift.status === 'newer_version_found' ? 'Detected' : 'None', 'Deterministic check')}</div><ol class="steps">${d.pipeline.map((p, i) => `<li class="${p.state === 'done' ? 'done' : (p.state === 'skipped' ? 'skipped' : 'error')}"><i>${p.state === 'done' ? '✓' : (p.state === 'skipped' ? '–' : '!')}</i><span><b>${esc(p.stage)}</b><small>${esc(p.message)}</small></span></li>`).join('')}</ol>${callout('warn', `<b>Stale answer caught:</b> the claim “${esc(claim.claim)}” — ${esc(drift.detail)}`)}<details><summary>Fixture sources used</summary><div class="sources">${claim.sources.map(sourceMarkup).join('')}</div></details><details><summary>Sample code and real test output</summary><pre class="code-block"><code>${esc(d.coding.code)}</code></pre><pre class="code-block"><code>${esc(t.output || '')}</code></pre></details><div class="btn-row"><button class="btn-sm" id="d-test">Open in Test Lab →</button><button class="btn-sm" id="d-copy">Copy sample code</button></div><p class="hint">${esc(d.benchmark.note)}</p></article>`);
      $('d-test').onclick = () => { $('test-code').value = d.coding.code; $('test-suite').value = d.test_code; navigate('tests'); };
      $('d-copy').onclick = () => copy(d.coding.code);
      refreshStats();
    } catch (e) { reveal('demo-result', errorCard(e.message)); }
    finally { busy(btn, false); }
  }
  $('run-demo').addEventListener('click', runDemo);

  /* ---------- self-check ---------- */
  async function runEval() {
    const btn = $('eval-btn'); busy(btn, true);
    try {
      const r = await api('/api/v1/eval'), d = r.drift_detector, c = r.compression;
      $('eval-result').innerHTML = `<div class="metrics">${metric('DRIFT ACCURACY', fmtPct(d.accuracy), d.cases + ' labelled cases')}${metric('PRECISION', fmtPct(d.precision))}${metric('RECALL', fmtPct(d.recall))}${metric('CLAIM EXTRACTION', fmtPct(r.claim_extraction.accuracy), r.claim_extraction.cases + ' labelled texts · recall ' + fmtPct(r.claim_extraction.recall))}${metric('FACT RETENTION', fmtPct(c.fact_retention), 'Answer-bearing fact kept after compression')}${metric('AVG TOKENS SAVED (EST.)', fmtPct(c.avg_saved_percent))}</div><p class="hint">${esc(r.note)}</p><details><summary>Show every case</summary><div class="sources">${d.details.map(x => `<div class="source"><p>${x.pass ? '✓' : '✗'} <b>${esc(x.id)}</b> — ${esc(x.claim)} (expected ${x.expected_outdated ? 'outdated' : 'ok'}, got ${x.predicted_outdated ? 'outdated' : 'ok'})</p></div>`).join('')}</div></details>`;
      refreshStats();
    } catch (e) { $('eval-result').innerHTML = errorCard(e.message); }
    finally { busy(btn, false); }
  }
  $('eval-btn').addEventListener('click', runEval);

  /* ---------- ROI model ---------- */
  function paintRoi() {
    const r = roi({ reqPerDay: parseFloat($('roi-req').value), tokensPerReq: parseFloat($('roi-tokens').value), pricePerMTok: parseFloat($('roi-price').value), savingsPct: parseFloat($('roi-pct').value) });
    const usd = x => '$' + Math.round(x).toLocaleString('en-US');
    $('roi-out').innerHTML = metric('INPUT TOKENS / MONTH', fmtNum(Math.round(r.monthlyTokens))) + metric('TOKENS SAVED / MONTH', fmtNum(Math.round(r.savedTokens))) + metric('COST / MONTH', usd(r.monthlyCost)) + metric('SAVED / MONTH', usd(r.savedCost));
  }
  ['roi-req', 'roi-tokens', 'roi-price', 'roi-pct'].forEach(id => $(id).addEventListener('input', paintRoi));
  $('roi-pct').addEventListener('input', () => { state.roiTouched = true; $('roi-src').textContent = '(your value)'; });
  paintRoi();

  /* ---------- settings ---------- */
  $('refresh').addEventListener('click', () => { refreshHealth(); refreshStats(); toast('Status refreshed'); });
  $('settings-refresh').addEventListener('click', () => { refreshHealth(); toast('Status refreshed'); });

  /* ---------- command palette & shortcuts ---------- */
  const COMMANDS = [
    { label: 'Run the 60-second demo', hint: 'Overview', run: () => { navigate('overview'); runDemo(); } },
    { label: 'New coding task', hint: 'G A', run: () => navigate('agent') }, { label: 'Open Freshness lab', hint: 'G F', run: () => navigate('verify') },
    { label: 'Open Benchmarks', hint: 'G B', run: () => navigate('benchmarks') }, { label: 'Open Test lab', hint: 'G T', run: () => navigate('tests') },
    { label: 'Run detector self-check', hint: 'Freshness', run: () => { navigate('verify'); runEval(); } }, { label: 'Open History', hint: 'G H', run: () => navigate('history') }, { label: 'Open Integrations', hint: 'G C', run: () => navigate('settings') }, { label: 'Open Projects', hint: 'G P', run: () => navigate('projects') }, { label: 'Open Account', hint: 'G U', run: () => navigate('account') },
    { label: 'Toggle sidebar', hint: '', run: () => setCollapsed(!shell.classList.contains('collapsed')) }, { label: 'Refresh service status', hint: '', run: () => { refreshHealth(); refreshStats(); } }
  ];
  let palIdx = 0, palList = COMMANDS;
  function paintPalette() {
    $('palette-list').innerHTML = palList.map((c, i) => `<li role="option" data-i="${i}" aria-selected="${i === palIdx}"><span>${esc(c.label)}</span><span class="hint">${esc(c.hint)}</span></li>`).join('') || '<li class="hint">No matching command</li>';
  }
  function openPalette() { $('palette').hidden = false; $('palette-input').value = ''; palList = COMMANDS; palIdx = 0; paintPalette(); $('palette-input').focus(); }
  function closePalette() { $('palette').hidden = true; }
  function runPalette(i) { const c = palList[i]; closePalette(); if (c) c.run(); }
  $('open-palette').addEventListener('click', openPalette);
  $('palette').addEventListener('click', e => { if (e.target === $('palette')) closePalette(); const li = e.target.closest('li[data-i]'); if (li) runPalette(Number(li.dataset.i)); });
  $('palette-input').addEventListener('input', e => { const q = e.target.value.toLowerCase(); palList = COMMANDS.filter(c => c.label.toLowerCase().includes(q)); palIdx = 0; paintPalette(); });
  $('palette-input').addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { palIdx = Math.min(palList.length - 1, palIdx + 1); paintPalette(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { palIdx = Math.max(0, palIdx - 1); paintPalette(); e.preventDefault(); }
    else if (e.key === 'Enter') { runPalette(palIdx); e.preventDefault(); }
  });
  const SUBMIT = { task: 'generate', 'verify-text': 'verify-btn', 'bench-task': 'bench-btn', 'test-code': 'test-btn', 'test-suite': 'test-btn' };
  let gPending = false;
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('palette').hidden ? openPalette() : closePalette(); return; }
    if (e.key === 'Escape' && !$('palette').hidden) { closePalette(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && SUBMIT[e.target.id]) { e.preventDefault(); $(SUBMIT[e.target.id]).click(); return; }
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || '')); if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (gPending) { gPending = false; const map = { a: 'agent', f: 'verify', b: 'benchmarks', t: 'tests', h: 'history', c: 'settings', o: 'overview', p: 'projects', u: 'account' }; if (map[e.key]) navigate(map[e.key]); return; }
    if (e.key === 'g') { gPending = true; setTimeout(() => { gPending = false; }, 900); }
  });

  /* ---------- session + project plumbing ---------- */
  function applyUser() {
    const u = state.user;
    $('user-chip').hidden = !u; $('signin-link').hidden = !!u;
    if (u) { $('user-avatar').textContent = (u.display_name || u.email || '?').trim().charAt(0).toUpperCase(); $('user-name').textContent = u.display_name || u.email; }
    $('guest-banner').hidden = !state.guest;
    qsa('.nav-item').forEach(el => { const off = state.guest && el.dataset.view !== 'overview'; el.disabled = off; el.title = off ? 'Sign in to use this' : ''; });
    $('project-select').hidden = state.guest;
  }
  $('signout').addEventListener('click', async () => {
    try { await api('/api/v1/auth/logout', {}); } catch (e) { /* session may already be gone */ }
    window.location.assign('/login');
  });
  function paintProjectSelect() {
    const sel = $('project-select'), cur = state.projectId;
    sel.innerHTML = '<option value="">All projects</option>' + state.projects.filter(p => !p.archived).map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
    sel.value = state.projects.some(p => String(p.id) === String(cur) && !p.archived) ? cur : '';
    state.projectId = sel.value; paintAgentProject();
  }
  async function loadProjects() {
    try { const d = await api('/api/v1/projects?include_archived=true'); state.projects = d.projects; } catch (e) { state.projects = []; }
    paintProjectSelect();
    return state.projects;
  }
  function applyProjectDefaults() {
    const p = state.projects.find(x => String(x.id) === String(state.projectId)); if (!p) return;
    $('language').value = p.language; $('constraints').value = p.constraints || ''; $('budget').value = p.context_budget; $('budget-val').textContent = p.context_budget;
    $('bench-lang').value = ['java', 'python', 'typescript'].includes(p.language) ? p.language : $('bench-lang').value;
  }
  $('project-select').addEventListener('change', () => {
    state.projectId = $('project-select').value; store.set('fc_project', state.projectId, window.sessionStorage);
    $('agent-project').value = state.projectId; if (state.projectId) { applyProjectDefaults(); toast('Project defaults applied to the agent form.'); }
    if (state.view === 'history') loadHistory();
  });

  window.FCApp = { api, request, toast, esc, pill, metric, callout, errorCard, busy, reveal, skeleton, navigate, state, confirmDialog, download, loadProjects, paintProjectSelect, applyUser, refreshStats, errMessage };

  /* ---------- boot ---------- */
  async function start() {
    const signedIn = await loadMe().catch(() => false);
    if (!signedIn) {
      if (location.hash === '#demo') state.guest = true; else { toLogin(); return; }
    }
    state.projectId = store.get('fc_project', window.sessionStorage) || '';
    applyUser();
    if (!state.guest) await loadProjects();
    if (location.hash === '#demo') { history.replaceState(null, '', '#overview'); navigate('overview', { fromHash: true }); runDemo(); }
    else navigate(location.hash.slice(1) || 'overview', { fromHash: true, keepScroll: true });
    refreshHealth();
    setInterval(() => { if (!document.hidden && !state.guest) refreshHealth(); }, 30000);
  }
  start();
})();
