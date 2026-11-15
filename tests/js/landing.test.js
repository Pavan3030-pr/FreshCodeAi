const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.join(__dirname, '..', '..', 'static');
const html = fs.readFileSync(path.join(root, 'landing.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'landing.js'), 'utf8');
const theme = fs.readFileSync(path.join(root, 'theme.js'), 'utf8');
const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]));

test('every id used by landing.js exists in landing.html', () => {
  for (const id of new Set([...js.matchAll(/\$\('([^']+)'\)/g)].map(m => m[1]))) assert.ok(ids.has(id), 'missing #' + id);
  for (const m of html.matchAll(/href="#([a-z]+)"/g)) assert.ok(ids.has(m[1]) || m[1] === 'top', 'dead anchor #' + m[1]);
});

function stubEl(id) { return { id, value: '', innerHTML: '', textContent: '', className: '', addEventListener() {} }; }
test('landing.js renders ROI and live proof from /api/eval', async () => {
  const els = {};
  const values = { 'roi-req': '1000', 'roi-tokens': '4000', 'roi-price': '3', 'roi-pct': '50' };
  const document = { getElementById: id => els[id] || (els[id] = Object.assign(stubEl(id), { value: values[id] || '' })) };
  const ev = { drift_detector: { cases: 2, details: [{ pass: true }, { pass: false }] }, compression: { fact_retention: 100, avg_saved_percent: 70 }, claim_extraction: { accuracy: 83.3 } };
  const ctx = vm.createContext({ window: { FC: require('../../static/lib.js') }, document, fetch: async () => ({ ok: true, json: async () => ev }), console });
  vm.runInContext(js, ctx);
  await new Promise(r => setTimeout(r, 20));
  assert.ok(els['roi-out'].innerHTML.includes('60,000,000') && els['roi-out'].innerHTML.includes('$180'));
  assert.ok(els['proof-eval'].innerHTML.includes('1/2') && els['proof-eval'].innerHTML.includes('100%'));
  assert.equal(els['proof-status'].textContent, 'server online');
});
test('landing.js degrades clearly when the server is unreachable', async () => {
  const els = {};
  const document = { getElementById: id => els[id] || (els[id] = Object.assign(stubEl(id), { value: '1' })) };
  const ctx = vm.createContext({ window: { FC: require('../../static/lib.js') }, document, fetch: async () => { throw new Error('down'); }, console });
  vm.runInContext(js, ctx);
  await new Promise(r => setTimeout(r, 20));
  assert.equal(els['proof-status'].textContent, 'server unreachable');
});

function themeEnv(initial) {
  const mem = Object.assign({}, initial), attrs = {}, removed = [];
  const document = { documentElement: { setAttribute: (k, v) => { attrs[k] = v; } }, querySelectorAll: () => [], addEventListener() {} };
  const window = { localStorage: { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = v; }, removeItem: k => { removed.push(k); delete mem[k]; } } };
  vm.runInContext(theme, vm.createContext({ window, document }));
  return { window, attrs, mem, removed };
}
test('theme.js is light-only: no theme attribute, no dark switch, legacy saved theme is discarded', () => {
  const e = themeEnv({ fc_theme: 'dark' });
  assert.equal(e.attrs['data-theme'], undefined);
  assert.ok(e.removed.includes('fc_theme'));
  assert.equal(typeof e.window.FCTheme.toggle, 'undefined');
});
test('theme.js keeps only the reduced-motion preference', () => {
  const e = themeEnv({ fc_motion: 'off' });
  assert.equal(e.attrs['data-motion'], 'off');
  e.window.FCTheme.setMotionOff(false); assert.equal(e.mem.fc_motion, 'on');
  assert.equal(themeEnv({ fc_motion: '<script>' }).attrs['data-motion'], 'on');
});
test('no static asset contains dark-theme CSS or a theme switch', () => {
  for (const f of ['style.css', 'landing.css', 'auth.css', 'index.html', 'landing.html', 'login.html', 'app.js']) {
    const t = fs.readFileSync(path.join(root, f), 'utf8');
    assert.ok(!/data-theme/.test(t), f + ' still references data-theme');
    assert.ok(!/☾|Dark mode|toggleTheme/.test(t), f + ' still offers a dark mode');
  }
});
