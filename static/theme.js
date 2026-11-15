/* Motion preference only. FreshCode v5.1 is a light-only product: there is no theme switch and no saved theme. Loaded in <head> so the preference applies before first paint. */
(function (root) {
  'use strict';
  var MKEY = 'fc_motion';
  var store = {
    get: function (k) { try { return root.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { root.localStorage.setItem(k, v); } catch (e) { /* storage may be blocked */ } }
  };
  function motionOff() { return store.get(MKEY) === 'off'; }
  function sync() { Array.prototype.forEach.call(document.querySelectorAll('[data-motion-toggle]'), function (c) { c.checked = motionOff(); }); }
  function apply() { document.documentElement.setAttribute('data-motion', motionOff() ? 'off' : 'on'); sync(); }
  function setMotionOff(off) { store.set(MKEY, off ? 'off' : 'on'); apply(); }
  try { root.localStorage.removeItem('fc_theme'); } catch (e) { /* ignore */ }  // drop any theme saved by v5.0
  apply();
  document.addEventListener('DOMContentLoaded', sync);
  document.addEventListener('change', function (e) { if (e.target.matches && e.target.matches('[data-motion-toggle]')) setMotionOff(e.target.checked); });
  root.FCTheme = { motionOff: motionOff, setMotionOff: setMotionOff, apply: apply };
})(window);
