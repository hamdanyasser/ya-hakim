/* Voice, both directions, with no server and no key.

   Listening uses the browser's own speech recognition (Chrome, Edge, Safari).
   Speaking uses speechSynthesis with a voice chosen to fit the patient. Both
   are progressive: where the browser has neither, the buttons never appear
   and typing works exactly as before. */
(function (global) {
  'use strict';

  var Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;

  var FEMALE = /female|zira|susan|samantha|victoria|karen|hazel|aria|jenny|libby|sonia|moira|tessa|fiona|serena|joanna|salli|kimberly|emma|amy|olivia/i;
  var MALE = /\bmale|david|mark|daniel|george|guy|ryan|thomas|alex|fred|arthur|oliver|james|matthew|brian|justin|joey|christopher|eric/i;

  var voices = [];
  function loadVoices() {
    try { voices = global.speechSynthesis ? global.speechSynthesis.getVoices() : []; } catch (e) { voices = []; }
  }
  if (global.speechSynthesis) {
    loadVoices();
    global.speechSynthesis.onvoiceschanged = loadVoices;
  }

  function pickVoice(sex) {
    var english = voices.filter(function (v) { return /^en/i.test(v.lang); });
    var pool = english.length ? english : voices;
    var want = sex === 'female' ? FEMALE : MALE;
    var avoid = sex === 'female' ? MALE : FEMALE;
    var match = pool.filter(function (v) { return want.test(v.name) && !(sex === 'female' ? false : avoid.test(v.name)); });
    return match[0] || pool[0] || null;
  }

  /* Speak as the patient: a voice that fits, a little slower and lower when
     older, and never so eager that one reply talks over the next. */
  function speak(text, who) {
    if (!global.speechSynthesis || !text) return;
    who = who || {};
    try {
      var u = new SpeechSynthesisUtterance(text);
      var v = pickVoice(who.sex);
      if (v) u.voice = v;
      var age = +who.age || 40;
      u.rate = age >= 55 ? 0.92 : 0.98;
      u.pitch = who.sex === 'female' ? (age >= 55 ? 0.95 : 1.08) : (age >= 55 ? 0.78 : 0.88);
      global.speechSynthesis.speak(u);
    } catch (e) { /* speech is a bonus, never a dependency */ }
  }

  function hush() {
    try { if (global.speechSynthesis) global.speechSynthesis.cancel(); } catch (e) {}
  }

  /* Turn a button into a push-to-talk microphone for an input.
     Interim words appear in the box as you speak; when you stop, onFinal(text)
     fires with what was heard -- the page decides whether to send it. */
  function attach(button, input, onFinal) {
    if (!Recognition || !button || !input) {
      if (button) button.style.display = 'none';
      return null;
    }
    button.style.display = '';
    var rec = null, listening = false, finalText = '';

    function stop() {
      listening = false;
      button.classList.remove('listening');
      button.setAttribute('aria-pressed', 'false');
    }

    button.addEventListener('click', function (e) {
      e.preventDefault();
      if (listening && rec) { rec.stop(); return; }
      hush();                                   /* do not transcribe the patient */
      rec = new Recognition();
      rec.lang = 'en-GB';
      rec.interimResults = true;
      rec.continuous = false;
      rec.maxAlternatives = 1;
      finalText = '';
      rec.onresult = function (ev) {
        var interim = '';
        for (var i = ev.resultIndex; i < ev.results.length; i++) {
          if (ev.results[i].isFinal) finalText += ev.results[i][0].transcript;
          else interim += ev.results[i][0].transcript;
        }
        input.value = (finalText + interim).trim();
      };
      rec.onerror = function () { stop(); };
      rec.onend = function () {
        stop();
        var text = (finalText || input.value || '').trim();
        if (text && onFinal) onFinal(text);
      };
      try {
        rec.start();
        listening = true;
        button.classList.add('listening');
        button.setAttribute('aria-pressed', 'true');
      } catch (err) { stop(); }
    });
    return { available: true };
  }

  global.Voice = { speak: speak, hush: hush, attach: attach, canListen: !!Recognition,
                   canSpeak: !!global.speechSynthesis };
})(window);
