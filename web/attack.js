/* The phone: throw an attack at the patient, see it land on the big screen. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  try { $('who').value = localStorage.getItem('yh_who') || ''; } catch (e) {}

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  $('go').onclick = function () {
    var text = $('text').value.trim();
    if (!text) { $('text').focus(); return; }
    var who = $('who').value.trim() || 'anon';
    try { localStorage.setItem('yh_who', who); } catch (e) {}

    var btn = this;
    btn.disabled = true;
    btn.textContent = 'Asking him…';

    fetch('/api/prove/attack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, who: who })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var el = document.createElement('div');
        el.className = 'r' + (d.leaked ? ' leak' : '');
        el.innerHTML =
          '<div class="v">' + (d.leaked ? 'you broke it' : 'he held') + '</div>' +
          '<div class="a">' + esc(text) + '</div>' +
          '<div class="p">' + esc(d.reply || '') + '</div>';
        $('result').insertBefore(el, $('result').firstChild);
        $('text').value = '';
      })
      .catch(function () {
        var el = document.createElement('div');
        el.className = 'r';
        el.innerHTML = '<div class="v">lost the server</div>';
        $('result').insertBefore(el, $('result').firstChild);
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = 'Send it to the screen';
      });
  };

  $('text').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('go').click();
  });
})();
