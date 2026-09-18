/* The bedside monitor.
 *
 * This used to be a strip of DOM across the top of the page with the room
 * squeezed underneath it. Now it is a canvas that never enters the document:
 * the 3D room hangs it on a Philips-style screen at the head of the bed, and
 * the only place you read his vitals is by looking at the monitor in the room,
 * the way you would standing at the bedside.
 *
 * Self-contained on purpose. It generates its own waveforms from the heart and
 * respiratory rate the server sends, so nothing else has to stay in step with
 * it, and the old 2D ecg.js is no longer loaded by v2 at all.
 *
 * Three traces, because one is a heart monitor and three is a monitor:
 *   II     the ECG, a sum of gaussians placed where a real complex has its
 *          features -- same waveform the 2D panel used, carried over intact
 *   Pleth  the pulse oximeter, fast upstroke and a dicrotic notch
 *   Resp   the chest impedance trace, at his respiratory rate
 *
 * Swept rather than scrolled. Real monitors run a cursor left to right with a
 * short blank band ahead of it, and that blank band is most of what makes a
 * screenshot read as a hospital rather than as a graph.
 */
(function (global) {
  'use strict';

  var SWEEP_PX_PER_SEC = 168;   /* how fast the cursor crosses the screen */
  var MAX_DT = 0.05;            /* a tab hiccup must not fast-forward the trace */
  var R_PEAK = 0.32;            /* where the tall spike lands inside one beat */
  var BLANK = 22;               /* the erase band ahead of the cursor, in px */

  var COL = {
    screen:   '#04070C',
    chrome:   '#0D141D',
    line:     '#1B2733',
    grid:     'rgba(72,126,104,0.13)',
    gridBig:  'rgba(72,126,104,0.24)',
    ecg:      '#3AE27C',
    pleth:    '#36D3EF',
    resp:     '#F2D44B',
    bp:       '#E9F0F7',
    label:    '#74889C',
    value:    '#E9F0F7',
    alarm:    '#FF4257',
    warn:     '#FFA62E',
    flat:     '#7E91A4'
  };

  function gauss(x, c, w) {
    var d = (x - c) / w;
    return Math.exp(-d * d);
  }

  /* One cardiac cycle, phase 0..1, amplitude about -0.3 .. 1.0. */
  function beat(p) {
    return (0.12 * gauss(p, 0.160, 0.026) +   /* P wave  */
           -0.09 * gauss(p, 0.292, 0.008) +   /* Q       */
            1.00 * gauss(p, 0.320, 0.011) +   /* R spike */
           -0.24 * gauss(p, 0.356, 0.013) +   /* S       */
            0.26 * gauss(p, 0.580, 0.046));   /* T wave  */
  }

  /* A finger pleth: steep systolic upstroke, dicrotic notch, slow runoff. */
  function pleth(p) {
    return 0.94 * gauss(p, 0.20, 0.115) +
           0.30 * gauss(p, 0.46, 0.085) +
           0.06;
  }

  /* Chest impedance. Inspiration is quicker than expiration, so this is not
     a clean sine -- the asymmetry is what makes it look measured. */
  function resp(p) {
    var up = gauss(p, 0.30, 0.17);
    var down = gauss(p, 0.68, 0.24);
    return up * 0.95 - down * 0.35;
  }

  function roundRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  function Monitor(width, height) {
    this.W = width || 900;
    this.H = height || 562;

    this.canvas = document.createElement('canvas');
    this.canvas.width = this.W;
    this.canvas.height = this.H;
    this.ctx = this.canvas.getContext('2d');

    /* geometry: waveforms on the left, the numbers stacked down the right,
       exactly the way the bedside units are laid out */
    this.top = 46;
    this.padR = 268;
    this.traceW = this.W - this.padR;

    var laneH = Math.floor((this.H - this.top - 10) / 3);
    this.lanes = [
      { key: 'ecg',   label: 'II',     colour: COL.ecg,   y: this.top + 4,                 h: laneH, gain: 0.40 },
      { key: 'pleth', label: 'PLETH',  colour: COL.pleth, y: this.top + 4 + laneH,         h: laneH, gain: 0.34 },
      { key: 'resp',  label: 'RESP',   colour: COL.resp,  y: this.top + 4 + laneH * 2,     h: laneH, gain: 0.32 }
    ];

    /* one sample per pixel of trace width, per lane */
    this.samples = {};
    for (var i = 0; i < this.lanes.length; i++) {
      this.samples[this.lanes[i].key] = new Float32Array(this.traceW);
    }

    this.cursor = 0;
    this.phase = 0;          /* cardiac */
    this.rphase = 0;         /* respiratory */
    this.hr = 92;
    this.rr = 18;
    this.spo2 = 97;
    this.bp = '128/82';
    this.status = 'stable';
    this.dead = false;
    this.name = '';
    this.meta = '';
    this.clock = '';
    this.onBeat = null;
    this.hrFlash = 0;        /* the tell: his pulse jumps, the block pulses */
    this.blink = 0;

    this.buildGrid();
    this.prefill();
  }

  /* The graticule is fixed, so it is drawn once and blitted per frame. */
  Monitor.prototype.buildGrid = function () {
    var g = document.createElement('canvas');
    g.width = this.traceW;
    g.height = this.H - this.top;
    var c = g.getContext('2d');
    var x, y;

    c.strokeStyle = COL.grid;
    c.lineWidth = 1;
    c.beginPath();
    for (x = 0; x <= g.width; x += 16) { c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, g.height); }
    for (y = 0; y <= g.height; y += 16) { c.moveTo(0, y + 0.5); c.lineTo(g.width, y + 0.5); }
    c.stroke();

    c.strokeStyle = COL.gridBig;
    c.beginPath();
    for (x = 0; x <= g.width; x += 80) { c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, g.height); }
    for (y = 0; y <= g.height; y += 80) { c.moveTo(0, y + 0.5); c.lineTo(g.width, y + 0.5); }
    c.stroke();

    this.grid = g;
  };

  /* Fill the screen with history so the monitor is never blank on the first
     frame -- an empty monitor at the bedside reads as switched off. */
  Monitor.prototype.prefill = function () {
    for (var i = 0; i < this.traceW; i++) this.writeColumn(i);
    this.cursor = this.traceW - 1;
  };

  Monitor.prototype.writeColumn = function (i) {
    var perPx = (this.hr / 60) / SWEEP_PX_PER_SEC;
    var rPerPx = (this.rr / 60) / SWEEP_PX_PER_SEC;

    var before = this.phase;
    this.phase = (this.phase + perPx) % 1;
    this.rphase = (this.rphase + rPerPx) % 1;

    if (this.dead) {
      this.samples.ecg[i] = 0;
      this.samples.pleth[i] = 0;
      this.samples.resp[i] = 0;
      return;
    }

    this.samples.ecg[i] = beat(this.phase);
    this.samples.pleth[i] = pleth(this.phase) - 0.5;
    this.samples.resp[i] = resp(this.rphase);

    /* Fire on the R spike so the beep lands on the same frame as the peak,
       instead of on a second timer that drifts away from it. */
    if (this.onBeat && before < R_PEAK && (this.phase >= R_PEAK || this.phase < before)) {
      this.onBeat();
    }
  };

  Monitor.prototype.setVitals = function (v) {
    if (!v) return;
    if (typeof v.hr === 'number' && v.hr > 0) this.hr = v.hr;
    if (typeof v.rr === 'number' && v.rr > 0) this.rr = v.rr;
    if (typeof v.spo2 === 'number') this.spo2 = v.spo2;
    if (v.bp) this.bp = v.bp;
  };

  Monitor.prototype.setStatus = function (s) {
    if (!s) return;
    this.status = s;
    if (s === 'flatline') this.dead = true;
  };

  Monitor.prototype.setPatient = function (name, meta) {
    this.name = name || '';
    this.meta = meta || '';
  };

  Monitor.prototype.setClock = function (t) { this.clock = t || ''; };

  /* The tell. Called when his heart rate jumps while his mouth stays calm. */
  Monitor.prototype.flashHr = function () { this.hrFlash = 1; };

  Monitor.prototype.kill = function () {
    this.dead = true;
    this.status = 'flatline';
  };

  /* A new patient on the same screen. Cheaper and steadier than tearing the
     page down and building a second WebGL context for round two. */
  Monitor.prototype.revive = function () {
    this.dead = false;
    this.status = 'stable';
    this.phase = 0;
    this.rphase = 0;
    this.hrFlash = 0;
    this.carry = 0;
    this.prefill();
  };

  Monitor.prototype.frame = function (dtMs) {
    var dt = Math.min(MAX_DT, (dtMs || 16) / 1000);

    var advance = dt * SWEEP_PX_PER_SEC;
    var n = Math.floor(advance + (this.carry || 0));
    this.carry = advance + (this.carry || 0) - n;

    for (var k = 0; k < n; k++) {
      this.cursor = (this.cursor + 1) % this.traceW;
      this.writeColumn(this.cursor);
    }

    if (this.hrFlash > 0) this.hrFlash = Math.max(0, this.hrFlash - dt / 4);
    this.blink = (this.blink + dt) % 1;

    this.draw();
  };

  Monitor.prototype.draw = function () {
    var c = this.ctx, W = this.W, H = this.H;
    var critical = this.status === 'critical';
    var flat = this.status === 'flatline';

    c.fillStyle = COL.screen;
    c.fillRect(0, 0, W, H);

    this.drawChrome(critical, flat);
    this.drawTraces(flat);
    this.drawNumbers(critical, flat);

    /* a faint scanline wash, so the screen reads as a screen and not as a
       poster of a screen once it is a texture in the room */
    c.fillStyle = 'rgba(0,0,0,0.055)';
    for (var y = 0; y < H; y += 3) c.fillRect(0, y, W, 1);
  };

  Monitor.prototype.drawChrome = function (critical, flat) {
    var c = this.ctx, W = this.W;

    c.fillStyle = COL.chrome;
    c.fillRect(0, 0, W, this.top);
    c.strokeStyle = COL.line;
    c.lineWidth = 1;
    c.beginPath(); c.moveTo(0, this.top + 0.5); c.lineTo(W, this.top + 0.5); c.stroke();

    c.textBaseline = 'middle';
    c.font = '700 21px Consolas, "Cascadia Mono", monospace';
    c.fillStyle = COL.value;
    c.textAlign = 'left';
    c.fillText(this.name || 'BED 4', 16, this.top / 2);

    c.font = '600 14px Consolas, "Cascadia Mono", monospace';
    c.fillStyle = COL.label;
    var nameW = c.measureText(this.name || 'BED 4').width;
    c.fillText(this.meta || '', 26 + nameW * 1.32, this.top / 2 + 1);

    /* the alarm banner, which is the only thing that should ever flash */
    if (flat) {
      c.fillStyle = COL.flat;
      c.textAlign = 'center';
      c.font = '800 19px Consolas, "Cascadia Mono", monospace';
      c.fillText('* * *  A S Y S T O L E  * * *', W * 0.52, this.top / 2);
    } else if (critical && this.blink < 0.6) {
      c.fillStyle = COL.alarm;
      roundRect(c, W * 0.37, 8, 200, this.top - 16, 5);
      c.fill();
      c.fillStyle = '#FFFFFF';
      c.textAlign = 'center';
      c.font = '800 15px Consolas, "Cascadia Mono", monospace';
      c.fillText(this.spo2 < 88 ? 'SpO2 LOW' : 'HR HIGH', W * 0.37 + 100, this.top / 2);
    }

    c.textAlign = 'right';
    c.font = '700 20px Consolas, "Cascadia Mono", monospace';
    c.fillStyle = flat ? COL.flat : COL.ecg;
    c.fillText(this.clock || '', W - 16, this.top / 2);
  };

  Monitor.prototype.drawTraces = function (flat) {
    var c = this.ctx;
    var self = this;

    c.drawImage(this.grid, 0, this.top);

    this.lanes.forEach(function (lane) {
      var buf = self.samples[lane.key];
      var mid = lane.y + lane.h * 0.54;
      var amp = lane.h * lane.gain;
      var colour = flat ? COL.flat : lane.colour;

      /* the lead label, in the trace colour, top-left of its own lane */
      c.textAlign = 'left';
      c.textBaseline = 'top';
      c.font = '800 13px Consolas, "Cascadia Mono", monospace';
      c.fillStyle = colour;
      c.fillText(lane.label, 10, lane.y + 6);

      c.strokeStyle = colour;
      c.lineWidth = lane.key === 'ecg' ? 2.4 : 2.0;
      c.lineJoin = 'round';
      c.lineCap = 'round';
      c.shadowColor = colour;
      c.shadowBlur = lane.key === 'ecg' ? 7 : 5;

      /* Drawn as runs, so the blank band ahead of the cursor actually breaks
         the line instead of the trace wrapping across the screen. */
      var started = false;
      c.beginPath();
      for (var x = 0; x < self.traceW; x++) {
        var ahead = (x - self.cursor + self.traceW) % self.traceW;
        if (ahead > 0 && ahead < BLANK) { started = false; continue; }
        var y = mid - buf[x] * amp;
        if (!started) { c.moveTo(x, y); started = true; }
        else c.lineTo(x, y);
      }
      c.stroke();
      c.shadowBlur = 0;
    });
  };

  Monitor.prototype.drawNumbers = function (critical, flat) {
    var c = this.ctx;
    var x = this.traceW;
    var w = this.padR;
    var top = this.top;
    var h = (this.H - top) / 4;

    var hrCol = flat ? COL.flat : (this.hr > 140 ? COL.alarm : this.hr > 115 ? COL.warn : COL.ecg);
    var spCol = flat ? COL.flat : (this.spo2 < 88 ? COL.alarm : this.spo2 < 94 ? COL.warn : COL.pleth);

    var blocks = [
      { label: 'HR',    unit: 'bpm',  value: flat ? '0' : String(this.hr),   colour: hrCol, big: true },
      { label: 'SpO2',  unit: '%',    value: flat ? '0' : String(this.spo2), colour: spCol, big: true },
      { label: 'NIBP',  unit: 'mmHg', value: flat ? '0/0' : this.bp,         colour: flat ? COL.flat : COL.bp, big: false },
      { label: 'RESP',  unit: 'rpm',  value: flat ? '0' : String(this.rr),   colour: flat ? COL.flat : COL.resp, big: true }
    ];

    c.strokeStyle = COL.line;
    c.lineWidth = 1;
    c.beginPath(); c.moveTo(x + 0.5, top); c.lineTo(x + 0.5, this.H); c.stroke();

    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i];
      var by = top + i * h;

      if (i) {
        c.strokeStyle = COL.line;
        c.beginPath(); c.moveTo(x, by + 0.5); c.lineTo(this.W, by + 0.5); c.stroke();
      }

      /* the HR block lights up for a few seconds when his pulse gives him away */
      if (i === 0 && this.hrFlash > 0 && !flat) {
        c.fillStyle = 'rgba(255,66,87,' + (0.30 * this.hrFlash).toFixed(3) + ')';
        c.fillRect(x + 1, by + 1, w - 2, h - 2);
      }

      c.textBaseline = 'top';
      c.textAlign = 'left';
      c.font = '800 15px Consolas, "Cascadia Mono", monospace';
      c.fillStyle = b.colour;
      c.fillText(b.label, x + 16, by + 12);

      c.textAlign = 'right';
      c.font = '600 13px Consolas, "Cascadia Mono", monospace';
      c.fillStyle = COL.label;
      c.fillText(b.unit, this.W - 16, by + 14);

      c.textAlign = 'right';
      c.textBaseline = 'alphabetic';
      c.font = '800 ' + (b.big ? 72 : 46) + 'px Consolas, "Cascadia Mono", monospace';
      c.fillStyle = b.colour;
      if (!flat) { c.shadowColor = b.colour; c.shadowBlur = 12; }
      c.fillText(b.value, this.W - 16, by + h - 16);
      c.shadowBlur = 0;
    }
  };

  global.Monitor = Monitor;
})(window);
