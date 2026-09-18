/* Construct the v2 room and its monitor against r128 and report what they made.
 *
 * The v2 room draws far more of itself in code than v1 did -- painted canvas
 * textures, a monitor face with three live traces, bones placed by their
 * endpoints -- so the 2D context here has to be a real stub rather than the
 * four no-ops v1 needed. A missing method on this context is exactly the kind
 * of thing that throws in a browser and takes the whole page down with it.
 */
const THREE = require('./r128stub.js');
global.window = global;
global.THREE = THREE;
global.addEventListener = function () {};
global.removeEventListener = function () {};
global.devicePixelRatio = 1;

/* A 2D context with everything the textures and the monitor face touch. */
function ctx2d() {
  return {
    canvas: null,
    font: '', textAlign: '', textBaseline: '',
    fillStyle: '', strokeStyle: '', lineWidth: 1, lineJoin: '', lineCap: '',
    shadowColor: '', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    globalAlpha: 1,
    save() {}, restore() {}, setTransform() {}, translate() {}, rotate() {}, scale() {},
    beginPath() {}, closePath() {}, moveTo() {}, lineTo() {}, arc() {}, arcTo() {},
    quadraticCurveTo() {}, bezierCurveTo() {}, rect() {},
    stroke() {}, fill() {}, clip() {},
    fillRect() {}, strokeRect() {}, clearRect() {},
    fillText() {}, strokeText() {},
    measureText() { return { width: 24 }; },
    drawImage() {},
    createLinearGradient() { return { addColorStop() {} }; },
    createRadialGradient() { return { addColorStop() {} }; },
    createPattern() { return {}; },
    getImageData(x, y, w, h) {
      return { data: new Uint8ClampedArray(Math.max(4, w * h * 4)), width: w, height: h };
    },
    putImageData() {}
  };
}

function makeCanvas(w, h) {
  const c = {
    width: w || 0, height: h || 0, style: {},
    getContext: ctx2d,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: c.width, height: c.height }),
    addEventListener() {}
  };
  return c;
}

global.document = { createElement: () => makeCanvas(0, 0) };

require('../../v2/web/monitor.js');
require('../../v2/web/room3d.js');

/* ---- the monitor face ---- */
const monitor = new window.Monitor(900, 562);
let beats = 0;
monitor.onBeat = () => { beats++; };
monitor.setPatient('Kamal Haddad', '54 M');
monitor.setClock('2:30');

for (const st of ['stable', 'declining', 'critical']) {
  monitor.setStatus(st);
  monitor.setVitals({ hr: st === 'critical' ? 148 : 96, spo2: st === 'critical' ? 84 : 97,
                      bp: '128/82', rr: 18 });
  monitor.flashHr();
  for (let i = 0; i < 90; i++) monitor.frame(16);
}
console.log('  Monitor built OK, beats fired:', beats);
if (!beats) { console.error('FAIL: the monitor never fired a beat'); process.exit(1); }

monitor.kill();
for (let i = 0; i < 40; i++) monitor.frame(16);
console.log('  Monitor survives flatline');

/* ---- the room ---- */
const canvas = makeCanvas(1200, 700);
canvas.clientWidth = 1200;
canvas.clientHeight = 700;

const room = new window.Room3D(canvas, monitor.canvas);
if (!room.ok) { console.error('FAIL: Room3D did not initialise'); process.exit(1); }

const counts = {};
(function walk(o) {
  (o.children || []).forEach(c => {
    const k = c.geometry ? c.geometry.type : 'group/light';
    counts[k] = (counts[k] || 0) + 1;
    walk(c);
  });
})(room.scene);

console.log('  Room3D built OK on r128');
console.log('  hotspots:', room.hotspots.length, '->',
            room.hotspots.map(h => h.userData.examId).join(', '));
console.log('  patient present:', !!room.patient);
console.log('  scene objects:', JSON.stringify(counts));

room.frame(16);
['stable', 'declining', 'critical', 'flatline'].forEach(s => room.setStatus(s));
room.setRespiratoryRate(26);
/* all five bodies, the way the server hands them over */
const MODELS = [
  { build: 1.10, frame: 1.06, head: 1.00, beard: true,  longHair: false },
  { build: 0.90, frame: 0.95, head: 0.98, beard: true,  longHair: false },
  { build: 0.99, frame: 1.04, head: 1.00, beard: false, longHair: false },
  { build: 0.90, frame: 0.93, head: 0.95, beard: false, longHair: true },
  { build: 0.88, frame: 0.92, head: 0.95, beard: false, longHair: true }
];
MODELS.forEach((m, i) => {
  room.setPatientLook(Object.assign({ skin: 0x8E5A34, hair: 0x2C2320, gown: 0x4C7A8E }, m));
  room.frame(16);
});
console.log('  all', MODELS.length, 'patient models applied');
room.setPatientLook({});          /* an empty look must not throw either */
room.markExamined('hands');
room.freeze(); room.frame(16); room.unfreeze();
canvas.clientWidth = 800; canvas.clientHeight = 420;
room.resize(canvas);
room.frame(16);
console.log('  frame/setStatus/setPatientLook/resize/freeze all survive');
