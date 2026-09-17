/* Construct the whole room against r128 and report what it made. */
const THREE = require('./r128stub.js');
global.window = global;
global.THREE = THREE;
global.addEventListener = function () {};
global.devicePixelRatio = 1;

const ctx2d = () => ({
  fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){},
  getImageData(){ return { data: new Uint8ClampedArray(16) }; },
  putImageData(){}, setTransform(){}, drawImage(){}, clearRect(){},
  fillStyle:'', strokeStyle:'', lineWidth:1
});
global.document = {
  createElement: () => ({ width:0, height:0, getContext: ctx2d })
};

require('../../web/room3d.js');

const canvas = {
  clientWidth: 1200, clientHeight: 640,
  getContext: ctx2d, getBoundingClientRect: () => ({left:0,top:0,width:1200,height:640}),
  style: {}, addEventListener(){}
};
const ecgCanvas = { width: 1200, height: 208, getContext: ctx2d };

const room = new window.Room3D(canvas, ecgCanvas);
if (!room.ok) { console.error('FAIL: Room3D did not initialise'); process.exit(1); }

const counts = {};
(function walk(o){
  (o.children||[]).forEach(c => {
    const k = c.geometry ? c.geometry.type : 'group/light';
    counts[k] = (counts[k]||0)+1;
    walk(c);
  });
})(room.scene);

console.log('  Room3D built OK on r128');
console.log('  hotspots:', room.hotspots.length, '->', room.hotspots.map(h=>h.userData.examId).join(', '));
console.log('  patient present:', !!room.patient);
console.log('  scene objects:', JSON.stringify(counts));
room.frame(16);
room.setStatus('critical');
room.setRespiratoryRate(22);
room.freeze(); room.unfreeze();
console.log('  frame/setStatus/freeze all survive');
