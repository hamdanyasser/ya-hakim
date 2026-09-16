/* The heart monitor.
 *
 * Original waveform, generated in code. A phase value in [0,1) walks one beat;
 * the trace is a sum of gaussians placed where a real complex has its features.
 * Phase advances by hr/60 beats per second, so the trace speeds up exactly as
 * the number on the panel does.
 *
 * Kept free of game logic so the 3D room can hand this same canvas to a
 * CanvasTexture rather than rebuilding any of it.
 */
(function (global) {
  'use strict';

  var PX_PER_SEC = 220;     // scroll speed
  var MAX_DT = 0.05;        // a tab hiccup must not fast-forward the trace

  var COLOURS = {
    stable:    '#5DCAA5',
    declining: '#EF9F27',
    critical:  '#E24B4A',
    flatline:  '#888780'
  };

  function gauss(x, centre, width) {
    var d = (x - centre) / width;
    return Math.exp(-d * d);
  }

  /* One beat, phase 0..1. Amplitude roughly -0.3 .. 1.0. */
  function beat(p) {
    return (
      0.12 * gauss(p, 0.160, 0.026) +   /* P wave  */
     -0.09 * gauss(p, 0.292, 0.008) +   /* Q       */
      1.00 * gauss(p, 0.320, 0.011) +   /* R spike */
     -0.24 * gauss(p, 0.356, 0.013) +   /* S       */
      0.26 * gauss(p, 0.580, 0.046)     /* T wave  */
    );
  }

  function Ecg(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.samples = [];
    this.phase = 0;
    this.hr = 96;
    this.status = 'stable';
    this.dead = false;
    this.carry = 0;
    this.last = null;
    this.grid = null;
    this.w = 0;
    this.h = 0;
    this.resize();

    var self = this;
    global.addEventListener('resize', function () { self.resize(); });
  }

  Ecg.prototype.resize = function () {
    var dpr = global.devicePixelRatio || 1;
    var r = this.canvas.getBoundingClientRect();
    var w = Math.max(320, Math.round(r.width));
    var h = Math.max(120, Math.round(r.height));
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w;
    this.h = h;
    while (this.samples.length > w) this.samples.shift();
    if (this.samples.length < w) this.prefill();
    this.buildGrid();
  };

  /* Paper grid, cached once per resize so it costs nothing per frame. */
  Ecg.prototype.buildGrid = function () {
    var dpr = global.devicePixelRatio || 1;
    var g = document.createElement('canvas');
    g.width = Math.round(this.w * dpr);
    g.height = Math.round(this.h * dpr);
    var c = g.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);

    var x, y;
    c.strokeStyle = 'rgba(44,44,42,0.55)';
    c.lineWidth = 1;
    c.beginPath();
    for (x = 0; x <= this.w; x += 10) { c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, this.h); }
    for (y = 0; y <= this.h; y += 10) { c.moveTo(0, y + 0.5); c.lineTo(this.w, y + 0.5); }
    c.stroke();

    c.strokeStyle = 'rgba(44,44,42,1)';
    c.beginPath();
    for (x = 0; x <= this.w; x += 50) { c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, this.h); }
    for (y = 0; y <= this.h; y += 50) { c.moveTo(0, y + 0.5); c.lineTo(this.w, y + 0.5); }
    c.stroke();

    this.grid = g;
  };

  /* Fill the buffer with a screen of history so the panel is never empty.
     Walked at the current rate rather than pasted, so the beats line up with
     what comes next and there is no seam. */
  Ecg.prototype.prefill = function () {
    var perSample = (this.hr / 60) / PX_PER_SEC;
    var phase = this.phase;
    var out = [];
    for (var i = 0; i < this.w; i++) {
      phase = (phase + perSample) % 1;
      out.push(this.dead ? 0 : beat(phase));
    }
    this.samples = out;
    this.phase = phase;
  };

  Ecg.prototype.set = function (hr, status) {
    if (typeof hr === 'number' && hr > 0) this.hr = hr;
    if (status) this.status = status;
    if (status === 'flatline') this.dead = true;
  };

  /* Cut the trace where it stands. Mid-beat is the point. */
  Ecg.prototype.kill = function () {
    this.dead = true;
    this.status = 'flatline';
  };

  Ecg.prototype.revive = function () {
    this.dead = false;
    this.phase = 0;
    this.status = 'stable';
    this.prefill();
  };

  Ecg.prototype.step = function (now) {
    if (this.last === null) this.last = now;
    var dt = Math.min(MAX_DT, (now - this.last) / 1000);
    this.last = now;

    var want = dt * PX_PER_SEC + this.carry;
    var n = Math.floor(want);
    this.carry = want - n;

    var perSample = (this.hr / 60) / PX_PER_SEC;   /* beats per pixel */
    for (var i = 0; i < n; i++) {
      if (this.dead) {
        this.samples.push(0);
      } else {
        this.phase = (this.phase + perSample) % 1;
        this.samples.push(beat(this.phase));
      }
    }
    while (this.samples.length > this.w) this.samples.shift();
  };

  Ecg.prototype.draw = function () {
    var ctx = this.ctx, w = this.w, h = this.h;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#16191F';
    ctx.fillRect(0, 0, w, h);
    if (this.grid) ctx.drawImage(this.grid, 0, 0, w, h);

    var n = this.samples.length;
    if (!n) return;

    var mid = h * 0.58;
    var amp = h * 0.40;
    var x0 = w - n;

    var colour = COLOURS[this.status] || COLOURS.stable;
    ctx.strokeStyle = colour;
    ctx.lineWidth = 2.4;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.shadowColor = colour;
    ctx.shadowBlur = 8;

    ctx.beginPath();
    for (var i = 0; i < n; i++) {
      var x = x0 + i;
      var y = mid - this.samples[i] * amp;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
  };

  Ecg.prototype.frame = function (now) {
    this.step(now);
    this.draw();
  };

  global.Ecg = Ecg;
})(window);
