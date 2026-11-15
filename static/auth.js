/* Sign-in / sign-up behaviour. No inline handlers (strict CSP). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var qp = new URLSearchParams(location.search);

  /* only same-origin absolute paths are accepted as the post-login destination (prevents open redirects) */
  function safeNext(v) { return typeof v === 'string' && /^\/(?!\/)[^\s\\]*$/.test(v) && v.indexOf('://') < 0 ? v : '/app'; }
  var next = safeNext(qp.get('next'));

  function showError(msg) { var e = $('auth-error'); e.textContent = msg; e.hidden = !msg; }
  function toast(msg) { var t = $('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(function () { t.classList.remove('show'); }, 3200); }

  function setTab(which) {
    var up = which === 'signup';
    $('tab-signin').setAttribute('aria-selected', String(!up)); $('tab-signup').setAttribute('aria-selected', String(up));
    $('form-signin').hidden = up; $('form-signup').hidden = !up;
    $('auth-title').textContent = up ? 'Create your account' : 'Welcome back';
    $('auth-sub').textContent = up ? 'Start saving projects, runs and reports.' : 'Sign in to your workspace.';
    showError('');
    history.replaceState(null, '', up ? '#signup' : location.pathname + location.search);
    $(up ? 'su-email' : 'si-email').focus();
  }
  $('tab-signin').addEventListener('click', function () { setTab('signin'); });
  $('tab-signup').addEventListener('click', function () { setTab('signup'); });

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-toggle-pw]'); if (!b) return;
    var input = $(b.getAttribute('data-toggle-pw')), show = input.type === 'password';
    input.type = show ? 'text' : 'password'; b.textContent = show ? 'Hide' : 'Show'; b.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });

  /* lightweight strength hint (the server enforces the real policy) */
  $('su-password').addEventListener('input', function () {
    var v = $('su-password').value, score = 0;
    if (v.length >= 10) score++; if (v.length >= 14) score++; if (/[a-z]/.test(v) && /[A-Z]/.test(v)) score++; if (/\d/.test(v)) score++; if (/[^A-Za-z0-9]/.test(v)) score++;
    var bar = $('pw-bar'); bar.style.width = Math.min(100, score * 20) + '%'; bar.style.background = score >= 4 ? 'var(--good)' : score >= 2 ? 'var(--apricot)' : 'var(--bad)';
    $('pw-label').textContent = !v ? 'Strength: enter a password' : 'Strength: ' + (score >= 4 ? 'strong' : score >= 2 ? 'fair, add length or variety' : 'weak');
  });

  function errorText(res, data) {
    var d = data && data.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map(function (x) { return x.msg; }).join('; ');
    return 'Request failed (HTTP ' + res.status + ').';
  }
  async function post(path, body, btn) {
    btn.disabled = true; btn.classList.add('is-busy'); showError('');
    try {
      var res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), credentials: 'same-origin' });
      var data = null; try { data = await res.json(); } catch (e) { /* non-JSON */ }
      if (!res.ok) { showError(errorText(res, data)); return; }
      window.location.assign(next);
    } catch (e) { showError('Could not reach the server. Check that it is running.'); }
    finally { btn.disabled = false; btn.classList.remove('is-busy'); }
  }
  $('form-signin').addEventListener('submit', function (e) {
    e.preventDefault();
    var email = $('si-email').value.trim(), pw = $('si-password').value;
    if (!email || !pw) { showError('Enter your email and password.'); return; }
    post('/api/v1/auth/login', { email: email, password: pw }, $('si-submit'));
  });
  $('form-signup').addEventListener('submit', function (e) {
    e.preventDefault();
    var email = $('su-email').value.trim(), pw = $('su-password').value;
    if (!email || !pw) { showError('Enter an email and a password.'); return; }
    post('/api/v1/auth/register', { email: email, password: pw, display_name: $('su-name').value.trim() }, $('su-submit'));
  });

  /* already signed in? go straight to the app. registration closed? hide the tab. */
  fetch('/api/v1/auth/me', { credentials: 'same-origin' }).then(function (r) { if (r.ok) window.location.replace(next); }).catch(function () {});
  fetch('/api/health').then(function (r) { return r.json(); }).then(function (h) {
    if (!h.registration_open) { $('tab-signup').hidden = true; $('tab-signin').parentNode.style.gridTemplateColumns = '1fr'; }
  }).catch(function () {});
  if (location.hash === '#signup') setTab('signup'); else $('si-email').focus();
})();
