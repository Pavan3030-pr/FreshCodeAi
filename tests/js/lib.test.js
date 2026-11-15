const test = require('node:test');
const assert = require('node:assert/strict');
const FC = require('../../static/lib.js');

test('esc neutralises HTML metacharacters and handles null', () => {
  assert.equal(FC.esc('<img src=x onerror="a()">&\''), '&lt;img src=x onerror=&quot;a()&quot;&gt;&amp;&#39;');
  assert.equal(FC.esc(null), ''); assert.equal(FC.esc(0), '0');
});
test('renderRich escapes text and turns fences into code blocks', () => {
  const html = FC.renderRich('Hello <b>x</b>\n```python\nprint("<hi>")\n```\nBye');
  assert.ok(html.includes('&lt;b&gt;x&lt;/b&gt;') && !html.includes('<b>'));
  assert.ok(html.includes('<pre class="code-block" data-lang="python"><code>print(&quot;&lt;hi&gt;&quot;)</code></pre>'));
  assert.ok(html.includes('<p>Bye</p>'));
  assert.equal(FC.renderRich(''), '');
});
test('renderRich cannot break out through a malicious fence language', () => {
  const html = FC.renderRich('```"><script>alert(1)</script>\ncode\n```');
  assert.ok(!html.includes('<script>'));
});
test('safeUrl only allows http(s)', () => {
  assert.equal(FC.safeUrl('javascript:alert(1)'), '#'); assert.equal(FC.safeUrl('data:text/html,x'), '#');
  assert.equal(FC.safeUrl('https://a.com/x'), 'https://a.com/x'); assert.equal(FC.safeUrl(undefined), '#');
});
test('host strips www and tolerates garbage', () => {
  assert.equal(FC.host('https://www.docs.example.com/a'), 'docs.example.com'); assert.equal(FC.host('nope'), '');
});
test('formatters', () => {
  assert.equal(FC.fmtNum(1234567), '1,234,567'); assert.equal(FC.fmtNum(null), '—'); assert.equal(FC.fmtNum(undefined), '—');
  assert.equal(FC.fmtMs(450), '450 ms'); assert.equal(FC.fmtMs(2500), '2.5 s'); assert.equal(FC.fmtMs(null), '—');
  assert.equal(FC.fmtPct(66.66), '66.7%'); assert.equal(FC.fmtPct(null), '—');
});
test('ago', () => {
  assert.equal(FC.ago(null, 100), '—'); assert.equal(FC.ago(98, 100), 'just now'); assert.equal(FC.ago(70, 100), '30s ago');
  assert.equal(FC.ago(100 - 600, 100), '10m ago'); assert.equal(FC.ago(100 - 7200, 100), '2h ago'); assert.equal(FC.ago(100 - 200000, 100), '2d ago');
});
test('verdictMeta and trustMeta fall back safely', () => {
  assert.equal(FC.verdictMeta('supported').tone, 'good'); assert.equal(FC.verdictMeta('contradicted').tone, 'bad');
  assert.equal(FC.verdictMeta('whatever').label, 'Not assessed by LLM'); assert.equal(FC.trustMeta('primary').tone, 'good'); assert.equal(FC.trustMeta(undefined).label, 'Unclassified');
});
test('barWidths scales relative to the max and never invents numbers', () => {
  assert.deepEqual(FC.barWidths(900, 300), [100, 33]); assert.deepEqual(FC.barWidths(null, 300), [0, 100]); assert.deepEqual(FC.barWidths(0, 0), [0, 0]);
});
test('file helpers', () => {
  assert.equal(FC.slug('Build a JWT validator!'), 'build-a-jwt-validator'); assert.equal(FC.slug(''), 'solution');
  assert.equal(FC.fileExt('Python'), 'py'); assert.equal(FC.fileExt('cobol'), 'txt'); assert.equal(FC.kindLabel('verify'), 'Freshness audit');
});

test('roi computes from explicit inputs and clamps bad data', () => {
  const r = FC.roi({ reqPerDay: 1000, tokensPerReq: 4000, pricePerMTok: 3, savingsPct: 50 });
  assert.equal(r.monthlyTokens, 120000000); assert.equal(r.savedTokens, 60000000); assert.equal(Math.round(r.savedCost), 180);
  const bad = FC.roi({ reqPerDay: -5, tokensPerReq: NaN, pricePerMTok: 'x', savingsPct: 500 });
  assert.equal(bad.monthlyTokens, 0); assert.equal(bad.savedCost, 0);
});
test('reportMarkdown includes flags and only safe links', () => {
  const md = FC.reportMarkdown({ claims_found: 1, summary: { possibly_outdated: 1 }, claims: [{ claim: 'X 1.0 is latest', kind: 'version', verdict: 'unassessed', possibly_outdated: true, version_drift: { detail: 'X 2.0 appears' }, sources: [{ title: 'S', url: 'javascript:alert(1)' }] }] });
  assert.ok(md.includes('POSSIBLY OUTDATED') && md.includes('X 2.0 appears') && !md.includes('javascript:'));
});

test('markChange escapes and marks only the changed token', () => {
  assert.equal(FC.markChange('Spring Boot 3.5.1 is <b>latest', '3.5.1'), 'Spring Boot <mark>3.5.1</mark> is &lt;b&gt;latest');
  assert.equal(FC.markChange('<x>', 'nope'), '&lt;x&gt;'); assert.equal(FC.markChange(null, '1'), '');
});
test('reportMarkdown includes the suggested correction', () => {
  const md = FC.reportMarkdown({ claims_found: 1, claims: [{ claim: 'a', kind: 'version', verdict: 'unassessed', suggested_correction: { corrected: 'X 2.0 is latest' }, sources: [] }] });
  assert.ok(md.includes('Suggested correction') && md.includes('X 2.0 is latest'));
});

test('traceRows builds waterfall geometry and readable details', () => {
  const rows = FC.traceRows({ total_ms: 1000, spans: [
    { name: 'research', start_ms: 0, duration_ms: 200, attrs: { sources: 3, cached: false, enabled: true } },
    { name: 'generate', start_ms: 200, duration_ms: 800, attrs: { model: 'm', provider_input_tokens: 120 }, error: 'Boom' },
    { name: 'decision', start_ms: 1000, duration_ms: 0, attrs: {}, event: true }] });
  assert.equal(rows[0].left, 0); assert.equal(rows[0].width, 20); assert.equal(rows[1].left, 20); assert.equal(rows[1].width, 80);
  assert.equal(rows[0].detail, 'sources: 3 · enabled'); assert.equal(rows[1].error, 'Boom'); assert.ok(rows[2].left <= 98 && rows[2].width >= 0.8);
  assert.deepEqual(FC.traceRows(null), []); assert.deepEqual(FC.traceRows({}), []);
});

test('highlight escapes untrusted code and wraps tokens', () => {
  const out = FC.highlight('def f(x):\n  # <img src=x onerror=alert(1)>\n  return "<b>" + 1', 'python');
  assert.ok(!out.includes('<img') && !out.includes('<b>'));
  assert.ok(out.includes('<span class="tk-k">def</span>') && out.includes('tk-c') && out.includes('tk-s') && out.includes('tk-n'));
  assert.equal(FC.highlight('a < b && c', 'javascript'), 'a &lt; b &amp;&amp; c');
});
test('finalStages derives stages 6-11 only from real backend fields', () => {
  const ok = FC.finalStages({ mode: 'live', code: 'x', tests: 't', run_id: 7, verification: { ran: true, passed: true, tests_passed: 2, tests_failed: 0 }, trace: { spans: [{ name: 'test' }] } });
  assert.equal(ok.final.state, 'done'); assert.equal(ok.repair.state, 'skipped'); assert.equal(ok.saved.msg, 'Run #7 saved');
  const rep = FC.finalStages({ mode: 'live', code: 'x', run_id: 1, verification: { ran: true, passed: true, repaired: true, tests_passed: 1, tests_failed: 0 }, trace: { spans: [{ name: 'test' }, { name: 'repair' }] } });
  assert.equal(rep.repair.state, 'done'); assert.equal(rep.diagnose.state, 'done');
  const bad = FC.finalStages({ mode: 'live', code: 'x', verification: { ran: true, passed: false, tests_passed: 0, tests_failed: 1 }, trace: { spans: [{ name: 'test' }] } });
  assert.equal(bad.final.state, 'error'); assert.equal(bad.saved.state, 'skipped');
  assert.equal(FC.finalStages({ mode: 'live', code: '' , verification: {} }).extract.state, 'error');
  assert.equal(FC.finalStages({ mode: 'setup_required' }).test.state, 'skipped');
});
