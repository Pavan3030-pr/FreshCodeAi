const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.join(__dirname, '..', '..', 'static');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));

test('every $(id) used by app.js exists in index.html', () => {
  const used = new Set([...js.matchAll(/\$\('([^']+)'\)/g)].map(m => m[1]));
  const dynamic = new Set(['r-copy', 'r-download', 'r-test', 'd-test', 'd-copy', 'v-report', 'v-copyfix', 'confirm-pw', 'empty-new']); // created inside rendered results
  for (const id of used) assert.ok(ids.has(id) || dynamic.has(id), 'missing element #' + id);
  for (const k of ['generate','verify-btn','bench-btn','test-btn']) assert.ok(ids.has(k));
});
test('html has no duplicate ids, inline handlers or inline scripts (strict CSP)', () => {
  const all = [...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
  assert.equal(all.length, new Set(all).size);
  assert.ok(!/\son[a-z]+="/i.test(html));
  assert.ok(!/<script(?![^>]*\ssrc=)[^>]*>/i.test(html));
  assert.ok(!/https?:\/\/(fonts|cdn)/i.test(html + fs.readFileSync(path.join(root, 'style.css'), 'utf8')));
});
test('every data-view / data-go / data-preset target exists', () => {
  const views = new Set([...html.matchAll(/id="view-([a-z]+)"/g)].map(m => m[1]));
  for (const m of html.matchAll(/data-(?:view|go)="([a-z]+)"/g)) assert.ok(views.has(m[1]), 'bad view ' + m[1]);
  const presets = [...js.matchAll(/'((?:agent|verify|test)-\d)':/g)].map(m => m[1]);
  for (const m of html.matchAll(/data-preset="([^"]+)"/g)) assert.ok(presets.includes(m[1]), 'bad preset ' + m[1]);
});

function makeEnv(fetchImpl, opts) {
  const els = {};
  const assigned = [];
  const mk = id => ({ id, value: '', textContent: '', innerHTML: '', hidden: false, disabled: false, dataset: {}, className: '', style: {},
    classList: { toggle() {}, add() {}, remove() {} }, setAttribute() {}, removeAttribute() {}, addEventListener() {}, focus() {}, dispatchEvent() {},
    querySelector: () => mk('q'), querySelectorAll: () => [], appendChild() {}, remove() {}, click() {}, getAttribute: () => null });
  const document = { getElementById: id => els[id] || (els[id] = mk(id)), querySelector: () => mk('q'), querySelectorAll: () => [],
    addEventListener() {}, removeEventListener() {}, documentElement: { dataset: {} }, createElement: () => mk('x'), body: { appendChild() {} }, hidden: false, title: '' };
  const location = { hash: (opts && opts.hash) || '', pathname: '/app', assign: u => assigned.push(u), replace: u => assigned.push(u) };
  const mem = () => ({ getItem: () => null, setItem() {} });
  const win = { FC: require('../../static/lib.js'), location, history: { replaceState() {} }, localStorage: mem(), sessionStorage: mem(), FCTheme: {},
    matchMedia: () => ({ matches: false }), scrollTo() {}, addEventListener() {}, confirm: () => true };
  const ctx = vm.createContext({ window: win, document, location, history: win.history, fetch: fetchImpl, navigator: {}, setTimeout, clearTimeout,
    setInterval: () => 0, requestAnimationFrame: f => f(), URL, URLSearchParams, Blob, TextDecoder, AbortController, Event: function () {}, console });
  return { ctx, els, assigned, win };
}
const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const ROUTES = {
  '/api/v1/auth/me': () => json({ user: { id: 1, email: 'ada@example.com', display_name: 'Ada', role: 'admin' }, csrf: 'tok', usage: {} }),
  '/api/v1/system': () => json({ version: '5.0.0', bifrost_configured: false, tavily_configured: false, bifrost_verified: false, tavily_verified: false, environment: 'development', runner_mode: 'local', runner_isolated: false,
    limits: { per_minute: 1, heavy_per_minute: 1, daily_runs: 5, agent_timeout_seconds: 9 }, upstream: {}, uptime_seconds: 3, database: { engine: 'sqlite', schema_version: 2 }, cache: { bifrost: { hits: 0, misses: 0 }, tavily: { hits: 0, misses: 0 } }, test_languages: ['python'] }),
  '/api/v1/stats': () => json({ total_runs: 0, avg_token_savings_pct: null, test_pass_rate: null, avg_latency_ms: null, provider_tokens_total: 0 }),
  '/api/v1/runs': () => json({ runs: [] }),
  '/api/v1/projects': () => json({ projects: [{ id: 1, name: 'Gateway', language: 'java', archived: false, context_budget: 600, constraints: '' }] })
};
const router = calls => async (url) => { calls.push(url); const key = Object.keys(ROUTES).find(k => url.split('?')[0] === k); return key ? ROUTES[key]() : json({}, 404); };
const tick = () => new Promise(r => setTimeout(r, 40));

test('app.js boots signed-in: loads user, projects, system and stats; shows the user', async () => {
  const calls = [];
  const { ctx, els, assigned } = makeEnv(router(calls));
  vm.runInContext(js, ctx);
  await tick();
  assert.ok(['/api/v1/auth/me', '/api/v1/system', '/api/v1/stats', '/api/v1/projects'].every(p => calls.some(c => c.startsWith(p))), calls.join(','));
  assert.deepEqual(assigned, []);
  assert.equal(els['conn-title'].textContent, 'Demo mode'); assert.equal(els['user-name'].textContent, 'Ada'); assert.equal(els['user-avatar'].textContent, 'A');
  assert.equal(els['kpi-runs'].textContent, '0'); assert.ok(els['project-select'].innerHTML.includes('Gateway'));
});
test('app.js redirects an anonymous visitor to /login with a safe next parameter', async () => {
  const { ctx, assigned } = makeEnv(async () => json({ detail: 'x' }, 401));
  vm.runInContext(js, ctx);
  await tick();
  assert.equal(assigned.length, 1); assert.ok(assigned[0].startsWith('/login?next=')); assert.ok(!assigned[0].includes('//evil'));
});
test('app.js guest mode (#demo) does not redirect, hides the user chip and shows the banner', async () => {
  const { ctx, els, assigned } = makeEnv(async url => url.includes('auth/me') ? json({}, 401) : json({ detail: 'x' }, 401), { hash: '#demo' });
  vm.runInContext(js, ctx);
  await tick();
  assert.deepEqual(assigned, []); assert.equal(els['guest-banner'].hidden, false); assert.equal(els['user-chip'].hidden, true); assert.equal(els['conn-title'].textContent, 'Guest demo');
});
test('app.js shows a clear state when the backend is unreachable', async () => {
  const { ctx, els, assigned } = makeEnv(async () => { throw new Error('down'); });
  vm.runInContext(js, ctx);
  await tick();
  assert.ok(assigned.length === 1 && assigned[0].startsWith('/login'));  // cannot confirm a session => send to sign-in
});
