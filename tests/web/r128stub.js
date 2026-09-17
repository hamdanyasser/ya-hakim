/* A THREE that has exactly what r128 has, and nothing newer.
 * Building the room against this catches the class of bug where code written
 * against a modern three.js throws on the pinned revision -- which is invisible
 * until a browser runs it, and which takes the whole page down with it. */
function V3(x, y, z) { this.x = x||0; this.y = y||0; this.z = z||0; }
V3.prototype.set = function (x, y, z) { this.x=x; this.y=y; this.z=z; return this; };
V3.prototype.copy = function (v) { return this.set(v.x, v.y, v.z); };

function Obj() {
  this.position = new V3(); this.rotation = new V3(); this.scale = new V3(1,1,1);
  this.children = []; this.userData = {};
}
Obj.prototype.add = function (o) { this.children.push(o); return this; };
Obj.prototype.lookAt = function () {};
Obj.prototype.clone = function () { var o = new Obj(); o.material = this.material; return o; };
Obj.prototype.updateProjectionMatrix = function () {};

function Geo(n) { this.type = n; this.attributes = { position: {
  count: 64,
  getX: function(){return 0;}, getY: function(){return 0;}, getZ: function(){return 0;},
  setZ: function(){}, needsUpdate: false
} }; }
Geo.prototype.computeVertexNormals = function () {};

function Mat(p) { Object.assign(this, p || {}); this.color = { setHex: function(){} }; }

var THREE = {
  Scene: function () { var o = new Obj(); o.fog = null; o.background = null; return o; },
  Group: function () { return new Obj(); },
  Mesh: function (g, m) { var o = new Obj(); o.geometry = g; o.material = m || new Mat(); return o; },
  Color: function () { return { setHex: function(){} }; },
  Fog: function () { return {}; },
  Raycaster: function () {
    return { setFromCamera: function(){}, intersectObjects: function(){ return []; } };
  },
  Vector2: function (x, y) { return { x: x||0, y: y||0 }; },
  PerspectiveCamera: function () { var o = new Obj(); o.aspect = 1; return o; },

  /* geometries present in r128 */
  PlaneGeometry: function(){ return new Geo('plane'); },
  BoxGeometry: function(){ return new Geo('box'); },
  SphereGeometry: function(){ return new Geo('sphere'); },
  CylinderGeometry: function(){ return new Geo('cylinder'); },
  ConeGeometry: function(){ return new Geo('cone'); },
  CircleGeometry: function(){ return new Geo('circle'); },
  /* CapsuleGeometry deliberately absent: it arrived in r142 */

  MeshStandardMaterial: function(p){ return new Mat(p); },
  MeshBasicMaterial: function(p){ return new Mat(p); },

  AmbientLight: function(){ return new Obj(); },
  HemisphereLight: function(){ return new Obj(); },
  DirectionalLight: function(){ return new Obj(); },
  PointLight: function(){ var o = new Obj(); o.color = { setHex: function(){} }; o.intensity = 1; return o; },
  SpotLight: function(){
    var o = new Obj();
    o.target = new Obj();
    o.shadow = { mapSize: {}, camera: {}, bias: 0, radius: 0 };
    return o;
  },

  CanvasTexture: function(){ return { wrapS:0, wrapT:0, repeat:{set:function(){}}, needsUpdate:false }; },
  WebGLRenderer: function(){
    return {
      setPixelRatio: function(){}, setSize: function(){}, render: function(){},
      dispose: function(){}, shadowMap: {}, outputEncoding: 0,
      toneMapping: 0, toneMappingExposure: 1
    };
  },
  PCFSoftShadowMap: 1, sRGBEncoding: 1, ACESFilmicToneMapping: 1,
  DoubleSide: 2, RepeatWrapping: 1000
};
module.exports = THREE;
