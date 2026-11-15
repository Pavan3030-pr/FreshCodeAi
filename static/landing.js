/* Landing page behaviour: live proof from /api, ROI calculator. No inline handlers (strict CSP). */
(function () {
  'use strict';
  var FC = window.FC, $ = function (id) { return document.getElementById(id); };
  var metric = function (v, l) { return '<div class="metric"><b>' + FC.esc(v) + '</b><small>' + FC.esc(l) + '</small></div>'; };

  function paintRoi() {
    var r = FC.roi({ reqPerDay: parseFloat($('roi-req').value), tokensPerReq: parseFloat($('roi-tokens').value), pricePerMTok: parseFloat($('roi-price').value), savingsPct: parseFloat($('roi-pct').value) });
    var usd = function (x) { return '$' + Math.round(x).toLocaleString('en-US'); };
    $('roi-out').innerHTML = metric(FC.fmtNum(Math.round(r.monthlyTokens)), 'INPUT TOKENS / MONTH') + metric(FC.fmtNum(Math.round(r.savedTokens)), 'TOKENS SAVED / MONTH') + metric(usd(r.monthlyCost), 'COST / MONTH') + metric(usd(r.savedCost), 'SAVED / MONTH');
  }
  ['roi-req', 'roi-tokens', 'roi-price', 'roi-pct'].forEach(function (id) { $(id).addEventListener('input', paintRoi); });
  paintRoi();

  function loadProof() {
    var pill = $('proof-status');
    fetch('/api/v1/eval', { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(function (e) {
      var d = e.drift_detector, c = e.compression, x = e.claim_extraction, passed = d.details.filter(function (k) { return k.pass; }).length;
      $('proof-eval').innerHTML = metric(passed + '/' + d.cases, 'VERSION-DRIFT CASES PASSED') + metric(FC.fmtPct(c.fact_retention), 'KEY FACT KEPT AFTER COMPRESSION') + metric(FC.fmtPct(c.avg_saved_percent), 'AVG TOKENS SAVED (EST.)') + metric(FC.fmtPct(x.accuracy), 'CLAIM EXTRACTION ACCURACY');
      pill.textContent = 'server online'; pill.className = 'pill good';
    }).catch(function () {
      pill.textContent = 'server unreachable'; pill.className = 'pill warn';
      $('proof-eval').innerHTML = '<p class="hint">Start the backend (make run) to see live numbers here.</p>';
    });
  }
  loadProof();
})();
