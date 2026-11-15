/* Pure helpers (no DOM). Loaded in the browser as window.FC and in Node tests via require(). */
(function (root) {
  'use strict';
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ESC[c]);

  const fmtNum = n => (n == null || Number.isNaN(Number(n))) ? '—' : Number(n).toLocaleString('en-US');
  const fmtMs = ms => ms == null ? '—' : ms >= 1000 ? (ms / 1000).toFixed(1) + ' s' : Math.round(ms) + ' ms';
  const fmtPct = p => p == null ? '—' : (Math.round(p * 10) / 10) + '%';

  function ago(epochSeconds, now) {
    if (!epochSeconds) return '—';
    const s = Math.max(0, Math.round((now == null ? Date.now() / 1000 : now) - epochSeconds));
    if (s < 5) return 'just now';
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
  }

  /* Only http(s) URLs may become links. */
  const safeUrl = u => /^https?:\/\//i.test(String(u || '')) ? String(u) : '#';
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return ''; } };

  /* Render model text: fenced code becomes <pre><code>, everything else escaped paragraphs. Never injects raw HTML. */
  function renderRich(text) {
    const out = [];
    const re = /```([\w+#.-]*)[ \t]*\n([\s\S]*?)```/g;
    let last = 0, m;
    const para = s => s.trim() ? '<p>' + esc(s.trim()).replace(/\n/g, '<br>') + '</p>' : '';
    while ((m = re.exec(text || '')) !== null) {
      out.push(para(text.slice(last, m.index)));
      out.push('<pre class="code-block" data-lang="' + esc(m[1]) + '"><code>' + esc(m[2].replace(/\n$/, '')) + '</code></pre>');
      last = m.index + m[0].length;
    }
    out.push(para((text || '').slice(last)));
    return out.join('');
  }

  const VERDICTS = {
    supported: { label: 'Supported', tone: 'good' },
    contradicted: { label: 'Contradicted', tone: 'bad' },
    mixed: { label: 'Mixed evidence', tone: 'warn' },
    insufficient_evidence: { label: 'Insufficient evidence', tone: 'warn' },
    unassessed: { label: 'Not assessed by LLM', tone: 'muted' }
  };
  const verdictMeta = v => VERDICTS[v] || VERDICTS.unassessed;
  const TRUST = { primary: { label: 'Primary source', tone: 'good' }, secondary: { label: 'Secondary', tone: 'muted' }, community: { label: 'Community', tone: 'warn' } };
  const trustMeta = t => TRUST[t] || { label: 'Unclassified', tone: 'muted' };

  /* Width (0-100) of a bar relative to the largest value in the pair. */
  function barWidths(a, b) {
    const nums = [a, b].map(x => (typeof x === 'number' && x >= 0) ? x : null);
    const max = Math.max.apply(null, nums.map(x => x || 0));
    return nums.map(x => (x == null || max === 0) ? 0 : Math.round((x / max) * 100));
  }

  const KIND_LABEL = { code: 'Coding run', verify: 'Freshness audit', benchmark: 'Token benchmark', test: 'Test run', demo: 'Judge demo', eval: 'Self-check' };
  const kindLabel = k => KIND_LABEL[k] || k;

  const slug = s => String(s || 'solution').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'solution';
  const EXT = { python: 'py', java: 'java', typescript: 'ts', javascript: 'js', go: 'go', rust: 'rs' };
  const fileExt = lang => EXT[String(lang || '').toLowerCase()] || 'txt';

  /* Cost model. savingsPct is an explicit assumption or a measured value; never invented here. */
  function roi(o) {
    const n = x => (typeof x === 'number' && isFinite(x) && x >= 0) ? x : 0;
    const req = n(o.reqPerDay), tok = n(o.tokensPerReq), price = n(o.pricePerMTok), pct = Math.min(100, n(o.savingsPct));
    const monthlyTokens = req * tok * 30, saved = monthlyTokens * pct / 100;
    return { monthlyTokens, savedTokens: saved, monthlyCost: monthlyTokens / 1e6 * price, savedCost: saved / 1e6 * price };
  }

  function reportMarkdown(d) {
    const lines = ['# FreshCode freshness report', '', `Claims checked: ${d.claims_found} · possibly outdated: ${(d.summary || {}).possibly_outdated || 0} · contradicted: ${(d.summary || {}).contradicted || 0}`, ''];
    (d.claims || []).forEach((c, i) => {
      lines.push(`## ${i + 1}. ${c.claim}`, `- Kind: ${c.kind} · Verdict: ${verdictMeta(c.verdict).label}${c.possibly_outdated ? ' · POSSIBLY OUTDATED' : ''}`);
      if (c.possibly_outdated && c.version_drift) lines.push(`- ${c.version_drift.detail}`);
      if (c.suggested_correction) lines.push(`- Suggested correction (confirm first): ${c.suggested_correction.corrected}`);
      (c.sources || []).forEach(s => lines.push(`- Source: ${s.title} <${safeUrl(s.url)}>`));
      lines.push('');
    });
    lines.push('_Version drift is a deterministic text check; confirm against the official source._');
    return lines.join('\n');
  }

  /* Escape text and wrap the first occurrence of `needle` in <mark>. */
  function markChange(text, needle) {
    const t = String(text == null ? '' : text), n = String(needle || '');
    const i = n ? t.indexOf(n) : -1;
    if (i < 0) return esc(t);
    return esc(t.slice(0, i)) + '<mark>' + esc(n) + '</mark>' + esc(t.slice(i + n.length));
  }

  /* Turn a trace into waterfall rows: left/width are percentages of total time; attrs become short "k: v" text. */
  function traceRows(trace) {
    const spans = (trace && trace.spans) || [];
    const total = Math.max(1, (trace && trace.total_ms) || 0, ...spans.map(s => (s.start_ms || 0) + (s.duration_ms || 0)));
    const fmtAttr = ([k, v]) => v === null || v === undefined || v === false ? null : (v === true ? k.replace(/_/g, ' ') : k.replace(/_/g, ' ') + ': ' + v);
    return spans.map(s => ({
      name: String(s.name || 'step'),
      left: Math.min(98, Math.round(((s.start_ms || 0) / total) * 1000) / 10),
      width: Math.max(s.event ? 0.8 : 1.5, Math.round(((s.duration_ms || 0) / total) * 1000) / 10),
      ms: s.duration_ms || 0,
      error: s.error || null,
      detail: Object.entries(s.attrs || {}).map(fmtAttr).filter(Boolean).join(' · ')
    }));
  }


  /* Syntax highlighting: tokenises the RAW text and escapes every piece, so untrusted code can never inject markup. */
  const KW = new Set(('abstract as assert async await break case catch class const continue def default defer del do elif else enum except export extends false final finally fn for from func function go if implements import in instanceof interface is lambda let match mod new nil none None not null of or package pass private protected pub public raise return self static struct super switch this throw throws true True False try type typeof use var void while with yield int long double float boolean string str bool char byte').split(' '));
  function highlight(code, lang) {
    const text = String(code == null ? '' : code), hashComment = /^(python|ruby|shell|bash)$/i.test(String(lang || ''));
    const re = new RegExp((hashComment ? '(#[^\\n]*)' : '(\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/|#[^\\n]*)') + '|("(?:[^"\\\\\\n]|\\\\.)*"|\'(?:[^\'\\\\\\n]|\\\\.)*\'|`(?:[^`\\\\]|\\\\.)*`)|(\\b\\d[\\d_]*(?:\\.\\d+)?\\b)|([A-Za-z_][A-Za-z0-9_]*)(?=\\()|([A-Za-z_][A-Za-z0-9_]*)', 'g');
    let out = '', last = 0, m;
    while ((m = re.exec(text)) !== null) {
      out += esc(text.slice(last, m.index));
      if (m[1] !== undefined) out += '<span class="tk-c">' + esc(m[1]) + '</span>';
      else if (m[2] !== undefined) out += '<span class="tk-s">' + esc(m[2]) + '</span>';
      else if (m[3] !== undefined) out += '<span class="tk-n">' + esc(m[3]) + '</span>';
      else if (m[4] !== undefined) out += KW.has(m[4]) ? '<span class="tk-k">' + esc(m[4]) + '</span>' : '<span class="tk-f">' + esc(m[4]) + '</span>';
      else out += KW.has(m[5]) ? '<span class="tk-k">' + esc(m[5]) + '</span>' : esc(m[5]);
      last = m.index + m[0].length;
      if (m[0].length === 0) re.lastIndex++;
    }
    return out + esc(text.slice(last));
  }

  /* Stages 6-11 of the agent timeline are derived ONLY from fields the backend actually returned. */
  function finalStages(d) {
    const spans = (d && d.trace && d.trace.spans) || [], has = n => spans.find(s => s.name === n && !s.event), v = (d && d.verification) || {};
    const out = {};
    if (!d || d.mode === 'setup_required') { out.extract = { state: 'skipped', msg: 'No generation (Bifrost not configured)' }; ['test', 'diagnose', 'repair', 'final'].forEach(k => { out[k] = { state: 'skipped', msg: 'Not reached' }; }); }
    else {
      out.extract = d.code ? { state: 'done', msg: (d.tests ? 'Code and tests separated' : 'Code extracted, no tests returned') } : { state: 'error', msg: 'No code block in the model reply' };
      const off = !!v.blocked && /disabled/i.test(String(v.output || ''));  // runner switched off on this deployment, not a policy violation
      out.test = v.ran ? (v.blocked ? (off ? { state: 'skipped', msg: 'Not run · runner disabled' } : { state: 'error', msg: 'Blocked by runner policy' }) : { state: 'done', msg: `${v.tests_passed} passed · ${v.tests_failed} failed` }) : { state: 'skipped', msg: String(v.reason || 'not run').replace(/_/g, ' ') };
      const rep = has('repair');
      out.diagnose = rep ? { state: 'done', msg: 'Failure output fed to repair prompt' } : { state: 'skipped', msg: v.ran && v.passed ? 'Not needed, tests passed' : 'Not run' };
      out.repair = rep ? (rep.error ? { state: 'error', msg: rep.error } : { state: 'done', msg: v.repaired ? 'Repair accepted' : 'Repair not accepted' }) : { state: 'skipped', msg: 'Not needed' };
      out.final = v.ran ? (v.passed ? { state: 'done', msg: 'Tests passed' } : (v.blocked ? (off ? { state: 'skipped', msg: 'Not verified · runner off' } : { state: 'error', msg: 'Blocked by policy' }) : { state: 'error', msg: 'Tests failed' })) : { state: 'skipped', msg: 'No test verification' };
    }
    out.saved = d && d.run_id ? { state: 'done', msg: 'Run #' + d.run_id + ' saved' } : { state: 'skipped', msg: 'Not saved' };
    return out;
  }

  const api = { highlight, finalStages, traceRows, markChange, roi, reportMarkdown, esc, fmtNum, fmtMs, fmtPct, ago, safeUrl, host, renderRich, verdictMeta, trustMeta, barWidths, kindLabel, slug, fileExt };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.FC = api;
})(typeof window !== 'undefined' ? window : this);
