/* The room behind the monitor.
 *
 * Every piece of geometry is a primitive built here. No models, no textures, no
 * downloaded assets. The only image in the scene is the ECG canvas that already
 * exists for the 2D panel, handed to a CanvasTexture -- the waveform is not
 * rebuilt in 3D.
 *
 * Pinned to three.js r128, which is the legacy API: THREE is a global from the
 * UMD build, lights are in pre-r155 intensity units, and colour management is
 * the old outputEncoding path. Using a modern API here gives a black screen.
 *
 * This whole layer is disposable. Room3D.available() is false if three.js did
 * not load, and ?flat=1 disables it outright, in which case screen.js simply
 * never calls in here and the flat projector view is what ships.
 */
(function (global) {
  'use strict';

  /* Where the camera sits. One definition, used by the constructor and by the
     drift, because having the value in two places is how it ended up pinned
     two metres away while three separate edits moved the other copy. */
  var CAM = [1.26, 1.52, 1.30];
  var LOOK = [-0.04, 0.80, -0.30];

  var STATUS_COLOUR = {
    stable:    0x5DCAA5,
    declining: 0xEF9F27,
    critical:  0xE24B4A,
    flatline:  0x888780
  };

  function available() {
    return typeof global.THREE !== 'undefined';
  }


  /* ---- textures, painted in code ----
     Flat-shaded primitives read as a blockout no matter how well they are lit,
     because real surfaces have grain. These are drawn to a canvas at load and
     cost nothing at runtime. Still nothing downloaded. */

  function canvasTex(w, h, draw, repeatX, repeatY) {
    var c = document.createElement('canvas');
    c.width = w; c.height = h;
    draw(c.getContext('2d'), w, h);
    var t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(repeatX || 1, repeatY || 1);
    t.anisotropy = 8;
    return t;
  }

  function noise(ctx, w, h, amount, alpha) {
    var img = ctx.getImageData(0, 0, w, h);
    var d = img.data;
    for (var i = 0; i < d.length; i += 4) {
      var n = (Math.sin(i * 12.9898) * 43758.5453) % 1;
      n = (n < 0 ? -n : n) * amount - amount / 2;
      d[i] += n; d[i + 1] += n; d[i + 2] += n;
      if (alpha !== undefined) d[i + 3] = alpha;
    }
    ctx.putImageData(img, 0, 0);
  }

  /* hospital vinyl: large tiles, soft speckle, visible seams */
  function floorTexture() {
    return canvasTex(512, 512, function (c, w, h) {
      c.fillStyle = '#6E7B88';
      c.fillRect(0, 0, w, h);
      noise(c, w, h, 26);
      c.strokeStyle = 'rgba(28,34,42,0.55)';
      c.lineWidth = 3;
      for (var i = 0; i <= 2; i++) {
        var p = (i * w) / 2;
        c.beginPath(); c.moveTo(p, 0); c.lineTo(p, h); c.stroke();
        c.beginPath(); c.moveTo(0, p); c.lineTo(w, p); c.stroke();
      }
      c.fillStyle = 'rgba(255,255,255,0.05)';
      c.fillRect(0, 0, w, 6);
    }, 8, 8);
  }

  /* wall: painted block with a dado rail band */
  function wallTexture() {
    return canvasTex(512, 512, function (c, w, h) {
      c.fillStyle = '#8C9AA8';
      c.fillRect(0, 0, w, h);
      noise(c, w, h, 16);
      c.fillStyle = 'rgba(40,48,58,0.20)';
      c.fillRect(0, h * 0.70, w, 10);
      c.fillStyle = 'rgba(40,48,58,0.10)';
      c.fillRect(0, h * 0.70 + 10, w, h * 0.30);
    }, 4, 2);
  }

  /* cotton weave for the bedding */
  function sheetTexture() {
    return canvasTex(256, 256, function (c, w, h) {
      c.fillStyle = '#EFEADC';
      c.fillRect(0, 0, w, h);
      c.strokeStyle = 'rgba(150,140,120,0.16)';
      c.lineWidth = 1;
      for (var i = 0; i < w; i += 4) {
        c.beginPath(); c.moveTo(i, 0); c.lineTo(i, h); c.stroke();
        c.beginPath(); c.moveTo(0, i); c.lineTo(w, i); c.stroke();
      }
      noise(c, w, h, 10);
    }, 3, 5);
  }


  /* ---- the patient ----
     A shape under a sheet is not a person, it is bedding. He is propped on the
     pillow with his head, shoulders, arms and hands above the blanket, which
     is what makes the room read as somebody in it.

     Stylised on purpose: simple forms, no facial detail. Primitives that reach
     for realism land in the uncanny valley, and a clean stylised head does not.
     The chest is a separate group so breathing moves him rather than the sheet. */
  /* r128 has no CapsuleGeometry -- it landed in r142 -- so a rounded limb is a
     cylinder with a cap on each end. Checked with typeof, because `new X ? a : b`
     evaluates the construction and throws before the ternary can pick. */
  function limb(radius, length) {
    if (typeof THREE.CapsuleGeometry === 'function') {
      return new THREE.CapsuleGeometry(radius, length - radius * 2, 6, 12);
    }
    return new THREE.CylinderGeometry(radius, radius, length, 14);
  }

  function buildPatient(skin, hair) {
    var g = new THREE.Group();

    var flesh = new THREE.MeshStandardMaterial({
      color: skin, roughness: 0.72, metalness: 0.0
    });
    var hairMat = new THREE.MeshStandardMaterial({
      color: hair, roughness: 0.92, metalness: 0.0
    });
    var gownMat = new THREE.MeshStandardMaterial({
      color: 0x6E93A8, roughness: 0.86, metalness: 0.0
    });

    function part(geo, mat, x, y, z) {
      var m = new THREE.Mesh(geo, mat);
      m.position.set(x, y, z);
      m.castShadow = true;
      m.receiveShadow = true;
      g.add(m);
      return m;
    }

    /* head, tipped back into the pillow */
    var head = part(new THREE.SphereGeometry(0.108, 26, 20), flesh, 0, 0.90, -0.80);
    head.scale.set(0.95, 1.06, 1.12);
    head.rotation.x = -0.32;

    /* jaw gives the profile a chin instead of a ball */
    var jaw = part(new THREE.SphereGeometry(0.082, 20, 16), flesh, 0, 0.862, -0.748);
    jaw.scale.set(0.92, 0.70, 1.02);
    jaw.rotation.x = -0.30;

    /* hair as a cap, thinning at the front the way a man of 54 wears it */
    var cap = part(new THREE.SphereGeometry(0.113, 24, 18,
                   0, Math.PI * 2, 0, Math.PI * 0.58), hairMat, 0, 0.906, -0.806);
    cap.scale.set(1.0, 0.95, 1.10);
    cap.rotation.x = -0.36;

    var ear1 = part(new THREE.SphereGeometry(0.026, 12, 10), flesh, -0.102, 0.895, -0.795);
    ear1.scale.set(0.5, 1, 0.8);
    var ear2 = part(new THREE.SphereGeometry(0.026, 12, 10), flesh, 0.102, 0.895, -0.795);
    ear2.scale.set(0.5, 1, 0.8);

    var neck = part(new THREE.CylinderGeometry(0.058, 0.066, 0.13, 14), flesh, 0, 0.828, -0.700);
    neck.rotation.x = Math.PI / 2 - 0.22;

    /* chest and shoulders in their own group so breathing moves the man */
    var chest = new THREE.Group();
    var torso = new THREE.Mesh(new THREE.SphereGeometry(0.20, 24, 18), gownMat);
    torso.scale.set(1.12, 0.52, 1.55);
    torso.position.set(0, 0.778, -0.42);
    torso.castShadow = true; torso.receiveShadow = true;
    chest.add(torso);

    var shoulder1 = new THREE.Mesh(new THREE.SphereGeometry(0.086, 16, 14), gownMat);
    shoulder1.position.set(-0.185, 0.792, -0.585);
    shoulder1.castShadow = true;
    chest.add(shoulder1);
    var shoulder2 = shoulder1.clone();
    shoulder2.position.x = 0.205;
    chest.add(shoulder2);
    g.add(chest);

    /* arms resting on top of the blanket, slightly out from the body */
    function arm(side) {
      var a = new THREE.Group();
      var upper = new THREE.Mesh(limb(0.052, 0.30), gownMat);
      upper.position.set(side * 0.225, 0.800, -0.40);
      upper.rotation.set(Math.PI / 2, 0, side * 0.10);   /* lie along the bed */
      upper.castShadow = true;
      a.add(upper);

      var fore = new THREE.Mesh(limb(0.046, 0.30), flesh);
      fore.position.set(side * 0.242, 0.792, -0.10);
      fore.rotation.set(Math.PI / 2, 0, side * -0.05);
      fore.castShadow = true;
      a.add(fore);

      var hand = new THREE.Mesh(new THREE.SphereGeometry(0.056, 16, 12), flesh);
      hand.position.set(side * 0.236, 0.796, 0.09);
      hand.scale.set(0.78, 0.52, 1.10);
      hand.castShadow = true;
      a.add(hand);

      g.add(a);
      return a;
    }
    arm(-1); arm(1);

    g.userData.chest = chest;
    return g;
  }

  function Room3D(canvas, ecgCanvas) {
    this.ok = false;
    if (!available()) return;

    this.clock = 0;
    this.rr = 18;
    this.frozen = false;

    var W = canvas.clientWidth || 640;
    var H = canvas.clientHeight || 360;

    this.renderer = new THREE.WebGLRenderer({
      canvas: canvas, antialias: true, alpha: false
    });
    this.renderer.setPixelRatio(Math.min(global.devicePixelRatio || 1, 2));
    this.renderer.setSize(W, H, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    /* r128 colour management. outputColorSpace does not exist here. */
    this.renderer.outputEncoding = THREE.sRGBEncoding;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x141A22);
    this.scene.fog = new THREE.Fog(0x141A22, 4.2, 13);

    this.camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 100);
    this.camera.position.set(CAM[0], CAM[1], CAM[2]);
    this.camera.lookAt(LOOK[0], LOOK[1], LOOK[2]);

    this.build(ecgCanvas);
    this.ok = true;

    var self = this;
    global.addEventListener('resize', function () { self.resize(canvas); });
  }

  Room3D.prototype.resize = function (canvas) {
    if (!this.ok) return;
    var W = canvas.clientWidth || 640;
    var H = canvas.clientHeight || 360;
    this.renderer.setSize(W, H, false);
    this.camera.aspect = W / H;
    this.camera.updateProjectionMatrix();
  };

  /* Metres throughout. */
  Room3D.prototype.build = function (ecgCanvas) {
    var S = this.scene;

    function box(w, h, d, colour, rough) {
      return new THREE.Mesh(
        new THREE.BoxGeometry(w, h, d),
        new THREE.MeshStandardMaterial({
          color: colour,
          roughness: rough === undefined ? 0.85 : rough,
          metalness: 0.05
        })
      );
    }

    /* ---- shell ---- */
    var floor = new THREE.Mesh(
      new THREE.PlaneGeometry(24, 24),
      new THREE.MeshStandardMaterial({
        map: floorTexture(), color: 0x9FB0C0,
        roughness: 0.42, metalness: 0.04
      })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    S.add(floor);

    var wall = new THREE.Mesh(
      new THREE.PlaneGeometry(24, 9),
      new THREE.MeshStandardMaterial({ map: wallTexture(), color: 0xAEBDC9, roughness: 0.95 })
    );
    wall.position.set(0, 4.5, -3.2);
    wall.receiveShadow = true;
    S.add(wall);

    /* ---- bed ---- */
    var frame = box(1.15, 0.16, 2.25, 0x39434F, 0.55);
    frame.position.set(0, 0.62, 0);
    frame.castShadow = true; frame.receiveShadow = true;
    S.add(frame);

    var i, leg;
    for (i = 0; i < 4; i++) {
      leg = box(0.07, 0.56, 0.07, 0x20242b, 0.6);
      leg.position.set(
        (i % 2 ? 1 : -1) * 0.48, 0.28, (i < 2 ? 1 : -1) * 0.98
      );
      leg.castShadow = true;
      S.add(leg);
    }

    var head = box(1.15, 0.5, 0.07, 0x39434F, 0.55);
    head.position.set(0, 0.92, -1.12);
    head.castShadow = true;
    S.add(head);

    /* ---- the form under the sheet ----
       No face, no character model. A plane draped over a few sine lobes reads
       as a person because of the silhouette and the way the light falls, not
       because of any detail. The chest lobe is what breathes. */
    var segW = 26, segL = 48;
    var sheetGeo = new THREE.PlaneGeometry(1.04, 1.34, segW, segL);
    this.baseZ = [];
    var pos = sheetGeo.attributes.position;
    for (i = 0; i < pos.count; i++) {
      var x = pos.getX(i);
      var y = pos.getY(i);          /* along the body, -1 head .. +1 feet */
      var t = (y + 1) / 2;
      var across = Math.pow(Math.cos(Math.min(1, Math.abs(x) / 0.34) * Math.PI / 2), 0.75);

      var belly = 0.20 * Math.exp(-Math.pow((t - 0.12) / 0.16, 2));
      var hips  = 0.22 * Math.exp(-Math.pow((t - 0.34) / 0.13, 2));
      var thigh = 0.20 * Math.exp(-Math.pow((t - 0.55) / 0.13, 2));
      var knees = 0.17 * Math.exp(-Math.pow((t - 0.76) / 0.085, 2));
      var feet  = 0.14 * Math.exp(-Math.pow((t - 0.965) / 0.045, 2));
      var h = (belly + hips + thigh + knees + feet) * across;

      this.baseZ.push(h);
      pos.setZ(i, h);
    }
    sheetGeo.computeVertexNormals();

    var sheet = new THREE.Mesh(
      sheetGeo,
      new THREE.MeshStandardMaterial({
        map: sheetTexture(), color: 0xD5CDBA,
        roughness: 0.92, metalness: 0, side: THREE.DoubleSide
      })
    );
    sheet.rotation.x = -Math.PI / 2;
    sheet.position.set(0, 0.705, 0.42);
    sheet.castShadow = true;
    sheet.receiveShadow = true;
    S.add(sheet);
    this.sheet = sheet;

    this.patient = buildPatient(0xA97449, 0x2B2420);
    S.add(this.patient);

    var pillow = box(0.46, 0.11, 0.28, 0xE3DBC9, 0.92);
    pillow.position.set(0, 0.742, -0.86);
    pillow.rotation.x = -0.12;
    pillow.castShadow = true; pillow.receiveShadow = true;
    S.add(pillow);

    /* ---- IV pole ---- */
    var pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.018, 0.018, 1.9, 10),
      new THREE.MeshStandardMaterial({ color: 0x9aa2ad, roughness: 0.35, metalness: 0.7 })
    );
    pole.position.set(-0.95, 0.95, -0.55);
    pole.castShadow = true;
    S.add(pole);

    var poleBase = new THREE.Mesh(
      new THREE.CylinderGeometry(0.17, 0.19, 0.03, 14),
      new THREE.MeshStandardMaterial({ color: 0x3a4049, roughness: 0.6 })
    );
    poleBase.position.set(-0.95, 0.015, -0.55);
    S.add(poleBase);

    var bag = box(0.15, 0.26, 0.05, 0xbfd8cf, 0.4);
    bag.position.set(-0.88, 1.66, -0.55);
    bag.castShadow = true;
    S.add(bag);

    /* ---- monitor on a stand ---- */
    var standPole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.022, 0.022, 1.15, 10),
      new THREE.MeshStandardMaterial({ color: 0x8e959f, roughness: 0.4, metalness: 0.6 })
    );
    standPole.position.set(1.0, 0.575, -0.7);
    standPole.castShadow = true;
    S.add(standPole);

    var standBase = new THREE.Mesh(
      new THREE.CylinderGeometry(0.19, 0.21, 0.03, 14),
      new THREE.MeshStandardMaterial({ color: 0x3a4049, roughness: 0.6 })
    );
    standBase.position.set(1.0, 0.015, -0.7);
    S.add(standBase);

    var shell = box(0.66, 0.46, 0.09, 0x23272e, 0.65);
    shell.position.set(1.0, 1.34, -0.7);
    shell.rotation.y = -0.42;
    shell.castShadow = true;
    S.add(shell);

    /* The screen IS the 2D ECG canvas. Not a second waveform. */
    this.ecgTexture = new THREE.CanvasTexture(ecgCanvas);
    this.ecgTexture.minFilter = THREE.LinearFilter;
    this.ecgTexture.magFilter = THREE.LinearFilter;
    this.ecgTexture.generateMipmaps = false;

    var screen = new THREE.Mesh(
      new THREE.PlaneGeometry(0.58, 0.38),
      new THREE.MeshBasicMaterial({ map: this.ecgTexture, toneMapped: false })
    );
    /* A child of the shell at local +Z. Parenting handles the rotation, so the
       screen cannot end up buried inside its own housing. */
    screen.position.set(0, 0, 0.047);
    shell.add(screen);
    this.screen = screen;

    /* ---- lighting ----
       The room read as grey boxes because a flat ambient did most of the work.
       Now a warm key with a visible cone does the shaping, a cool rim peels the
       body off the wall, and the monitor is a practical light in the scene. */
    S.add(new THREE.HemisphereLight(0x6E86A6, 0x1B2230, 0.34));
    S.add(new THREE.AmbientLight(0x38445C, 0.26));

    var spot = new THREE.SpotLight(0xFFE0B4, 3.4, 9, Math.PI / 6.6, 0.45, 1.5);
    spot.position.set(0.30, 2.85, 0.55);
    spot.target.position.set(0, 0.74, 0.05);
    spot.castShadow = true;
    spot.shadow.mapSize.width = 2048;
    spot.shadow.mapSize.height = 2048;
    spot.shadow.camera.near = 0.6;
    spot.shadow.camera.far = 7;
    spot.shadow.bias = -0.0016;
    spot.shadow.radius = 4;
    S.add(spot);
    S.add(spot.target);

    /* the lamp the light comes out of, so the key has a source on screen */
    var housing = new THREE.Mesh(
      new THREE.CylinderGeometry(0.19, 0.30, 0.16, 20, 1, true),
      new THREE.MeshStandardMaterial({ color: 0x2C333D, roughness: 0.5,
                                       side: THREE.DoubleSide })
    );
    housing.position.set(0.30, 2.85, 0.55);
    S.add(housing);

    var bulb = new THREE.Mesh(
      new THREE.CircleGeometry(0.19, 20),
      new THREE.MeshBasicMaterial({ color: 0xFFE4BC })
    );
    bulb.rotation.x = -Math.PI / 2;
    bulb.position.set(0.30, 2.77, 0.55);
    S.add(bulb);

    /* the visible cone of light. Cheap, and it is most of the atmosphere. */
    var cone = new THREE.Mesh(
      new THREE.ConeGeometry(1.05, 2.1, 28, 1, true),
      new THREE.MeshBasicMaterial({
        color: 0xFFD8A4, transparent: true, opacity: 0.030,
        side: THREE.DoubleSide, depthWrite: false
      })
    );
    cone.position.set(0.30, 1.78, 0.55);
    S.add(cone);

    /* cool rim, so he is not the same colour as the wall behind him */
    var rim = new THREE.DirectionalLight(0x8FD0FF, 0.95);
    rim.position.set(-2.6, 1.7, -1.9);
    S.add(rim);

    var fill = new THREE.PointLight(0xAFC6E2, 0.42, 7, 2);
    fill.position.set(-1.5, 1.5, 1.8);
    S.add(fill);

    /* the monitor lights its own corner, and the colour tracks his status */
    this.monitorLight = new THREE.PointLight(STATUS_COLOUR.stable, 2.2, 3.4, 2);
    this.monitorLight.position.set(0.78, 1.34, -0.44);
    S.add(this.monitorLight);

    this.addHotspots();
  };

  /* ---- the inspection layer ----
     Contraband Police, but a bedside: you do not pick an examination from a
     menu, you look at the man and touch the part of him you want to check.
     Each hotspot carries the id of an examination the engine already knows
     how to answer, so this is a new way into an existing system rather than a
     second system. */
  Room3D.prototype.addHotspots = function () {
    var S = this.scene;
    var self = this;
    this.hotspots = [];

    var SPOTS = [
      { id: 'eyes',       label: 'Eyes',         pos: [0, 0.90, -0.80], r: 0.15 },
      { id: 'cognition',  label: 'Speak to him', pos: [0.20, 0.99, -0.78], r: 0.12 },
      { id: 'hands',      label: 'Hands',        pos: [-0.263, 0.78, 0.03], r: 0.13 },
      { id: 'respiratory',label: 'Chest',        pos: [0, 0.83, -0.44], r: 0.20 },
      { id: 'abdominal',  label: 'Abdomen',      pos: [0, 0.80, 0.02], r: 0.20 },
      { id: 'legs',       label: 'Legs',         pos: [0, 0.78, 0.66], r: 0.24 }
    ];

    SPOTS.forEach(function (spec) {
      var mesh = new THREE.Mesh(
        new THREE.SphereGeometry(spec.r, 18, 14),
        new THREE.MeshBasicMaterial({
          color: 0x7FC4FF, transparent: true, opacity: 0.0,
          depthWrite: false, depthTest: false
        })
      );
      mesh.position.set(spec.pos[0], spec.pos[1], spec.pos[2]);
      mesh.renderOrder = 10;
      mesh.userData = { examId: spec.id, label: spec.label };
      S.add(mesh);
      self.hotspots.push(mesh);
    });

    this.ray = new THREE.Raycaster();
    this.pointer = new THREE.Vector2(-2, -2);
    this.hovered = null;
  };

  Room3D.prototype.pointerAt = function (clientX, clientY, rect) {
    this.pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  };

  Room3D.prototype.pickHotspot = function () {
    if (!this.hotspots) return null;
    this.ray.setFromCamera(this.pointer, this.camera);
    var hits = this.ray.intersectObjects(this.hotspots, false);
    return hits.length ? hits[0].object : null;
  };

  /* Only the thing under the cursor lights up. Showing every hotspot at once
     turns the patient into a menu, which is the thing this replaces. */
  Room3D.prototype.updateHover = function () {
    if (!this.hotspots) return null;
    var hit = this.pickHotspot();
    if (hit !== this.hovered) {
      if (this.hovered) this.hovered.material.opacity = 0.0;
      this.hovered = hit;
      if (hit) hit.material.opacity = 0.30;
    }
    return hit;
  };

  Room3D.prototype.markExamined = function (examId) {
    (this.hotspots || []).forEach(function (h) {
      if (h.userData.examId === examId) h.userData.done = true;
    });
  };

  Room3D.prototype.setStatus = function (status) {
    if (!this.ok) return;
    var colour = STATUS_COLOUR[status] || STATUS_COLOUR.stable;
    this.monitorLight.color.setHex(colour);
    this.monitorLight.intensity = (status === 'flatline') ? 0.45 : 2.2;
  };

  Room3D.prototype.setRespiratoryRate = function (rr) {
    if (rr && rr > 0) this.rr = rr;
  };

  /* Nothing moves during the two seconds of silence. */
  Room3D.prototype.freeze = function () { this.frozen = true; };
  Room3D.prototype.unfreeze = function () { this.frozen = false; };

  Room3D.prototype.frame = function (dtMs) {
    if (!this.ok) return;

    if (!this.frozen) {
      this.clock += Math.min(0.05, dtMs / 1000);

      /* breathing: the chest lobe rises and falls at his respiratory rate */
      var breath = Math.sin(this.clock * (this.rr / 60) * Math.PI * 2);

      /* His chest rises, not the blanket. */
      if (this.patient && this.patient.userData.chest) {
        var c = this.patient.userData.chest;
        c.scale.y = 1 + breath * 0.045;
        c.position.y = breath * 0.012;
      }

      var pos = this.sheet.geometry.attributes.position;
      for (var i = 0; i < pos.count; i++) {
        var y = pos.getY(i);
        var t = (y + 1) / 2;
        var belly = Math.exp(-Math.pow((t - 0.12) / 0.20, 2));
        pos.setZ(i, this.baseZ[i] + breath * 0.016 * belly);
      }
      pos.needsUpdate = true;
      this.sheet.geometry.computeVertexNormals();

      /* Camera drifts on a slow sine path. Never under player control.
         These numbers are the ones that matter: the constructor's position is
         overwritten on the very first frame, so setting it there and not here
         moves the camera for exactly one frame and then snaps it back. */
      var a = this.clock * 0.055;
      this.camera.position.set(
        CAM[0] + Math.sin(a) * 0.09,
        CAM[1] + Math.sin(a * 0.7) * 0.035,
        CAM[2] + Math.cos(a) * 0.06
      );
      this.camera.lookAt(LOOK[0], LOOK[1], LOOK[2]);
    }

    this.updateHover();

    /* The ECG canvas was already redrawn this frame by the 2D panel; this just
       tells the GPU to re-upload it. One 1024-ish texture per frame is cheap. */
    this.ecgTexture.needsUpdate = true;
    this.renderer.render(this.scene, this.camera);
  };

  Room3D.prototype.dispose = function () {
    if (!this.ok) return;
    this.renderer.dispose();
    this.ok = false;
  };

  global.Room3D = Room3D;
  global.Room3D.available = available;
})(window);
