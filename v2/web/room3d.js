/* The room.
 *
 * The monitor used to be a strip of DOM above this canvas, and the room was
 * whatever space was left underneath. That is backwards: the room IS the game
 * now, and the only place his vitals exist is the screen on the arm at the
 * head of the bed, which you read by looking at it.
 *
 * Every piece of geometry is a primitive built here. No models, no textures,
 * no downloaded assets -- the surfaces are canvases painted in code at load.
 * The only image in the scene is the monitor face, handed in as a canvas by
 * monitor.js and wrapped in a CanvasTexture.
 *
 * Pinned to three.js r128, which is the legacy API: THREE is a global from the
 * UMD build, lights are in pre-r155 intensity units, and colour management is
 * the old outputEncoding path. Using a modern API here gives a black screen.
 *
 * This whole layer is disposable. Room3D.available() is false if three.js did
 * not load, in which case app.js adds .noroom and the round plays on with the
 * conversation at full width.
 */
(function (global) {
  'use strict';

  /* The shot. One definition, used by the constructor and by the drift --
     having the value in two places is how it ended up pinned two metres away
     while three separate edits moved the other copy.

     Framed from the foot of the bed, off to his left, so that the face and the
     monitor are both in shot and neither is in the centre. */
  var CAM = [1.50, 1.62, 1.47];
  var LOOK = [0.40, 1.02, -0.74];

  var STATUS_COLOUR = {
    stable:    0x4FE39B,
    declining: 0xFFA62E,
    critical:  0xFF4257,
    flatline:  0x7E91A4
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

  function noise(ctx, w, h, amount) {
    var img, d, i, n;
    try {
      img = ctx.getImageData(0, 0, w, h);
    } catch (e) {
      return;                       /* headless stub, or a tainted canvas */
    }
    d = img.data;
    for (i = 0; i < d.length; i += 4) {
      n = (Math.sin(i * 12.9898) * 43758.5453) % 1;
      n = (n < 0 ? -n : n) * amount - amount / 2;
      d[i] += n; d[i + 1] += n; d[i + 2] += n;
    }
    ctx.putImageData(img, 0, 0);
  }

  /* hospital vinyl: big sheet goods, soft speckle, welded seams */
  function floorTexture() {
    return canvasTex(512, 512, function (c, w, h) {
      c.fillStyle = '#8E9AA0';
      c.fillRect(0, 0, w, h);
      noise(c, w, h, 30);
      c.strokeStyle = 'rgba(30,38,46,0.34)';
      c.lineWidth = 2;
      c.beginPath(); c.moveTo(0, 0); c.lineTo(0, h); c.stroke();
      c.beginPath(); c.moveTo(0, 0); c.lineTo(w, 0); c.stroke();
    }, 7, 7);
  }

  /* wall: wipe-clean paint over a vinyl dado, with a bump rail */
  function wallTexture() {
    return canvasTex(512, 512, function (c, w, h) {
      c.fillStyle = '#C9CFC8';
      c.fillRect(0, 0, w, h);
      noise(c, w, h, 12);
      c.fillStyle = '#8FA3A8';                     /* dado below the rail */
      c.fillRect(0, h * 0.62, w, h * 0.38);
      c.fillStyle = '#54636B';                     /* the rail itself */
      c.fillRect(0, h * 0.60, w, h * 0.026);
      c.fillStyle = 'rgba(255,255,255,0.07)';
      c.fillRect(0, h * 0.60, w, 3);
    }, 3, 1);
  }

  /* The blanket gets its OWN texture, darker than the sheets.
     Everything on this bed used to be a pale grey-blue lit by a strong exam
     light, so the blanket, the mattress, the backrest and the pillow all blew
     out to the same white and the draping was invisible -- the bed read as a
     flat board with a man on it. A cellular blanket is a different colour from
     the linen in real life too. */
  function blanketTexture() {
    return canvasTex(256, 256, function (c, w, h) {
      c.fillStyle = '#6E8E92';
      c.fillRect(0, 0, w, h);
      /* the open cellular weave */
      c.strokeStyle = 'rgba(38,56,60,0.34)';
      c.lineWidth = 2;
      for (var i = 0; i < w; i += 12) {
        c.beginPath(); c.moveTo(i, 0); c.lineTo(i, h); c.stroke();
        c.beginPath(); c.moveTo(0, i); c.lineTo(w, i); c.stroke();
      }
      c.strokeStyle = 'rgba(255,255,255,0.10)';
      c.lineWidth = 1;
      for (var j = 6; j < w; j += 12) {
        c.beginPath(); c.moveTo(j, 0); c.lineTo(j, h); c.stroke();
        c.beginPath(); c.moveTo(0, j); c.lineTo(w, j); c.stroke();
      }
      noise(c, w, h, 14);
    }, 3, 4);
  }

  /* cotton weave for the bedding */
  function sheetTexture() {
    return canvasTex(256, 256, function (c, w, h) {
      c.fillStyle = '#EEF1F2';
      c.fillRect(0, 0, w, h);
      c.strokeStyle = 'rgba(140,152,160,0.18)';
      c.lineWidth = 1;
      for (var i = 0; i < w; i += 4) {
        c.beginPath(); c.moveTo(i, 0); c.lineTo(i, h); c.stroke();
        c.beginPath(); c.moveTo(0, i); c.lineTo(w, i); c.stroke();
      }
      noise(c, w, h, 9);
    }, 3, 4);
  }

  /* the privacy curtain: heavy vertical folds, mesh panel at the top */
  function curtainTexture() {
    return canvasTex(256, 512, function (c, w, h) {
      c.fillStyle = '#7FA9A2';
      c.fillRect(0, 0, w, h);
      for (var x = 0; x < w; x += 16) {
        var g = c.createLinearGradient(x, 0, x + 16, 0);
        g.addColorStop(0, 'rgba(0,0,0,0.26)');
        g.addColorStop(0.5, 'rgba(255,255,255,0.13)');
        g.addColorStop(1, 'rgba(0,0,0,0.26)');
        c.fillStyle = g;
        c.fillRect(x, 0, 16, h);
      }
      c.fillStyle = 'rgba(230,238,236,0.45)';      /* the mesh top */
      c.fillRect(0, 0, w, h * 0.12);
      noise(c, w, h, 10);
    }, 1, 1);
  }

  /* suspended ceiling: mineral tile in a T-bar grid */
  function ceilingTexture() {
    return canvasTex(256, 256, function (c, w, h) {
      c.fillStyle = '#E4E6E2';
      c.fillRect(0, 0, w, h);
      noise(c, w, h, 16);
      c.strokeStyle = 'rgba(120,128,132,0.55)';
      c.lineWidth = 4;
      c.strokeRect(0, 0, w, h);
    }, 8, 8);
  }

  /* what is outside at night: a dark city, a few windows still warm */
  function nightTexture() {
    return canvasTex(256, 256, function (c, w, h) {
      var g = c.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, '#16233A');
      g.addColorStop(0.62, '#243B52');
      g.addColorStop(1, '#0E1622');
      c.fillStyle = g;
      c.fillRect(0, 0, w, h);
      c.fillStyle = '#0A0F18';
      c.fillRect(0, h * 0.63, w, h * 0.37);        /* the block opposite */
      c.fillStyle = 'rgba(255,214,150,0.85)';
      for (var i = 0; i < 26; i++) {
        var x = (i * 71) % (w - 12) + 4;
        var y = h * 0.66 + ((i * 37) % Math.floor(h * 0.3));
        if ((i * 13) % 3 === 0) c.fillRect(x, y, 5, 7);
      }
    }, 1, 1);
  }

  /* ---- limbs ----
     r128 has no CapsuleGeometry -- it landed in r142 -- so a rounded limb is a
     cylinder with a ball at each joint. Checked with typeof, because
     `new X ? a : b` evaluates the construction and throws before the ternary
     can pick. */
  function limbGeo(radius, length) {
    if (typeof THREE.CapsuleGeometry === 'function') {
      return new THREE.CapsuleGeometry(radius, Math.max(0.01, length - radius * 2), 6, 12);
    }
    return new THREE.CylinderGeometry(radius, radius, length, 14);
  }

  /* A limb between two points in space. Placing bones by their endpoints
     rather than by a position and two Euler angles is the difference between
     an arm that lies on the blanket and an arm that points at the ceiling. */
  function bone(a, b, r, mat) {
    var va = new THREE.Vector3(a[0], a[1], a[2]);
    var vb = new THREE.Vector3(b[0], b[1], b[2]);
    var dir = new THREE.Vector3().subVectors(vb, va);
    var len = dir.length();
    var m = new THREE.Mesh(limbGeo(r, len), mat);
    m.position.copy(va).add(vb).multiplyScalar(0.5);
    m.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0), dir.clone().normalize()
    );
    m.castShadow = true;
    return m;
  }

  function ball(r, mat, x, y, z, sx, sy, sz) {
    var m = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 16), mat);
    m.position.set(x, y, z);
    if (sx !== undefined) m.scale.set(sx, sy, sz);
    m.castShadow = true;
    return m;
  }

  /* ---- the patient ----
     He is propped against a raised backrest at about thirty degrees, which is
     how anyone awake enough to be answering questions is actually sat, and his
     head, shoulders, arms and hands are above the blanket.

     He has a face, and it points up the bed at you. The previous build gave him
     a bare sphere with a hair cap on it, and from the only camera angle the
     game ever uses you saw the back of his head -- which read exactly like a
     man lying face down in his pillow.

     Stylised on purpose: clean forms, no pores, no wrinkles. Primitives that
     reach for realism land in the uncanny valley; a clean stylised head does
     not. */

  /* The line of his body, hips to crown, all on one incline.
     NECK_BASE to NECK_TOP is a neck, not a torso: these used to be 28cm
     apart, which drew a bare flesh-coloured column from his chin to his
     waist. With the gown hidden under the blanket behind it, the only
     reasonable reading of the result was that he had no clothes on. */
  var HIP       = [0, 0.84, -0.18];
  var NECK_BASE = [0, 1.05, -0.70];
  var NECK_TOP  = [0, 1.13, -0.80];
  var HEAD      = [0, 1.23, -0.88];

  /* Where the blanket stops: pulled up to mid-chest, so all you see of him
     above it is the top of his chest, his shoulders and his head. */
  var BLANKET_EDGE_Z = -0.62;

  function buildPatient() {
    var g = new THREE.Group();

    var flesh = new THREE.MeshStandardMaterial({ color: 0x8E5A34, roughness: 0.62, metalness: 0 });
    var hairMat = new THREE.MeshStandardMaterial({ color: 0x2C2320, roughness: 0.92, metalness: 0 });
    var gownMat = new THREE.MeshStandardMaterial({ color: 0x4C7A8E, roughness: 0.88, metalness: 0 });
    var white = new THREE.MeshStandardMaterial({ color: 0xF6F3EC, roughness: 0.5 });
    var iris  = new THREE.MeshStandardMaterial({ color: 0x3B2A1E, roughness: 0.35 });
    var dark  = new THREE.MeshStandardMaterial({ color: 0x2A1B14, roughness: 0.8 });

    g.userData.mats = { flesh: flesh, hair: hairMat, gown: gownMat };

    /* --- torso, in its own group so breathing moves the man, not the bed --- */
    var chest = new THREE.Group();

    /* The gown: the part of him the blanket does NOT cover, so it has to be
       unmistakably clothing. It sits high and forward of the blanket edge. */
    /* A man lying on his back is a broad, shallow shape: his chest stands
       maybe seven centimetres off the mattress. These spheres were 27cm deep
       and stacked, which domed his front into a bump and made him look
       pregnant. Local Z is the depth axis here, because the mesh is tipped
       back along the backrest, so Z is the number that has to stay small. */
    /* The torso has to END before the blanket does.
       It is an ellipsoid tipped back along the backrest, so it reaches further
       down the bed than its numbers suggest: at the old length its foot end
       came out past the blanket edge and mounded up there, which is the belly
       that kept looking wrong. It now stops short of BLANKET_EDGE_Z and the
       blanket takes over. There is no separate waist sphere any more -- it sat
       entirely under the blanket and did nothing but risk poking through. */
    /* ONE trunk, not a torso plus an upper chest plus two shoulder balls.
       Built as separate lumps they never quite met, so from the bedside he
       read as a pile of parts rather than a body -- and the overlaps mounded
       up at the seams. A single wide, flat ellipsoid carries the shoulders in
       its own width, and the arms and neck are sunk deep enough into it that
       there is no join to see. */
    /* A cylinder from the waist to the shoulders, laid along the backrest.
       An ellipsoid tapers at both ends, so its shoulders were always narrower
       than its middle; a cylinder keeps one width the whole way up and reads
       as a chest under a blanket rather than as an egg. */
    var trunk = bone([0, 0.84, -0.30], [0, 1.05, -0.76], 0.198, gownMat);
    trunk.receiveShadow = true;
    chest.add(trunk);
    /* the shoulder caps, same radius, so the top is round not cut off */
    chest.add(ball(0.198, gownMat, 0, 1.05, -0.76, 1.0, 0.72, 0.80));

    /* The neckline, sunk into the trunk so it is a collar and not a ring
       floating in front of him. A torus here read as a hoop. */
    var collarMat = new THREE.MeshStandardMaterial({ color: 0x33606F, roughness: 0.9 });
    var collar = ball(0.086, collarMat, 0, 1.085, -0.780, 1.02, 0.40, 0.58);
    chest.add(collar);

    g.add(chest);

    g.add(bone([0, 1.06, -0.74], NECK_TOP, 0.054, flesh));   /* a neck, not a trunk */

    /* --- the head ---
       Built facing local +Z, then turned as a unit: tipped back onto the
       pillow and turned a little toward you, because he is talking to you. */
    var head = new THREE.Group();
    head.position.set(HEAD[0], HEAD[1], HEAD[2]);
    head.rotation.set(-0.46, 0.24, 0);

    var skull = ball(0.108, flesh, 0, 0, 0, 0.96, 1.05, 1.06);
    head.add(skull);

    var jaw = ball(0.086, flesh, 0, -0.045, 0.030, 0.94, 0.74, 0.96);
    head.add(jaw);

    var chin = ball(0.040, flesh, 0, -0.072, 0.058, 1.0, 0.72, 0.9);
    head.add(chin);

    /* brow, nose, mouth: the three shapes that make a sphere into a face */
    var brow = new THREE.Mesh(new THREE.BoxGeometry(0.128, 0.020, 0.030), flesh);
    brow.position.set(0, 0.034, 0.090);
    head.add(brow);

    var nose = new THREE.Mesh(new THREE.ConeGeometry(0.026, 0.072, 12), flesh);
    nose.position.set(0, -0.005, 0.104);
    nose.rotation.x = Math.PI / 2;          /* point it out of the face */
    head.add(nose);

    var mouth = new THREE.Mesh(new THREE.BoxGeometry(0.048, 0.010, 0.014), dark);
    mouth.position.set(0, -0.052, 0.093);
    head.add(mouth);

    /* open eyes. He is awake and being interviewed -- closed eyes read as a
       corpse, which is the wrong information to give the player for free. */
    [-1, 1].forEach(function (s) {
      var socket = ball(0.024, white, s * 0.040, 0.012, 0.089, 1, 0.78, 0.6);
      head.add(socket);
      var pupil = ball(0.011, iris, s * 0.040, 0.010, 0.104, 1, 1, 0.5);
      head.add(pupil);
      var lid = new THREE.Mesh(new THREE.BoxGeometry(0.038, 0.009, 0.020), flesh);
      lid.position.set(s * 0.040, 0.026, 0.092);
      head.add(lid);
      var ear = ball(0.026, flesh, s * 0.104, -0.006, -0.012, 0.42, 1.0, 0.76);
      head.add(ear);
    });

    /* Hair: a cap over the crown and the BACK only.
       A full hemisphere centred on the skull covers the forehead, and from the
       one camera angle this game has that turned his whole head into a dark
       blob with no face in it -- the exact complaint this rebuild started
       from. So it is pushed back and tilted off the brow. */
    var cap = new THREE.Mesh(
      new THREE.SphereGeometry(0.110, 24, 18, 0, Math.PI * 2, 0, Math.PI * 0.50),
      hairMat
    );
    cap.position.set(0, 0.010, -0.030);
    cap.rotation.x = 0.62;
    cap.scale.set(1.02, 0.90, 1.04);
    cap.castShadow = true;
    head.add(cap);

    /* the beard, hidden unless the case wants it: on the jaw, and nowhere
       near the eyes */
    var beard = new THREE.Mesh(new THREE.SphereGeometry(0.086, 18, 14), hairMat);
    beard.scale.set(0.96, 0.62, 0.74);
    beard.position.set(0, -0.062, 0.030);
    beard.visible = false;
    head.add(beard);

    /* Long hair.
       This was one sphere tucked behind the skull, which from the only camera
       angle the game has was almost entirely buried inside the head -- so
       "she has long hair" was invisible and every patient looked identical.
       The camera sees the face and the TOP of the head, so the hair has to be
       on the sides and the crown to read at all. */
    var longHair = new THREE.Group();
    /* Someone lying on their back has their hair fanned out on the pillow
       AROUND the head, not hanging beside the face. Hanging side locks read
       from this camera as a pair of floppy ears, which is exactly what they
       looked like. One wide, flat fan behind the head instead. */
    longHair.add(ball(0.150, hairMat, 0, -0.030, -0.130, 1.22, 0.52, 0.95));
    var crown = new THREE.Mesh(
      new THREE.SphereGeometry(0.118, 22, 16, 0, Math.PI * 2, 0, Math.PI * 0.58),
      hairMat
    );
    crown.position.set(0, 0.008, -0.026);
    crown.rotation.x = 0.55;
    crown.scale.set(1.06, 1.0, 1.08);
    longHair.add(crown);
    longHair.visible = false;
    head.add(longHair);

    g.add(head);
    g.userData.head = head;
    g.userData.beard = beard;
    g.userData.longHair = longHair;
    g.userData.cap = cap;

    /* --- arms, resting on top of the blanket --- */
    /* Arms rest ON the blanket, so they have to clear its surface: the lobes
       are tall now, and at the old height his hands were buried in it. The
       upper arm is gown, because a hospital gown has sleeves. */
    /* Arms lie ALONG him, close in, following the slope of the blanket they
       rest on. Splayed out wide at the shoulder they read as a doll's. The
       shoulder end is sunk well inside the trunk so there is no join. */
    [-1, 1].forEach(function (s) {
      var shoulder = [s * 0.185, 1.020, -0.760];
      var elbow    = [s * 0.245, 0.935, -0.400];
      var wrist    = [s * 0.240, 0.975, -0.080];
      g.add(bone(shoulder, elbow, 0.055, gownMat));
      g.add(bone(elbow, wrist, 0.045, flesh));
      g.add(ball(0.049, flesh, s * 0.238, 0.978, -0.020, 0.78, 0.58, 1.05));
    });

    g.userData.chest = chest;
    return g;
  }

  function Room3D(canvas, screenCanvas) {
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
    this.renderer.toneMappingExposure = 0.94;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0B1016);
    this.scene.fog = new THREE.Fog(0x0B1016, 4.2, 13);

    /* 47 rather than 41: the room panel is nearly square, so the horizontal
       field is much narrower than the number suggests, and at 41 the monitor's
       column of numbers fell off the right-hand edge. */
    this.camera = new THREE.PerspectiveCamera(47, W / H, 0.1, 100);
    this.camera.position.set(CAM[0], CAM[1], CAM[2]);
    this.camera.lookAt(LOOK[0], LOOK[1], LOOK[2]);

    this.build(screenCanvas);
    this.ok = true;

    var self = this;
    this._onResize = function () { self.resize(canvas); };
    global.addEventListener('resize', this._onResize);
  }

  Room3D.prototype.resize = function (canvas) {
    if (!this.ok) return;
    var W = canvas.clientWidth || 640;
    var H = canvas.clientHeight || 360;
    this.renderer.setSize(W, H, false);
    this.camera.aspect = W / H;
    this.camera.updateProjectionMatrix();
  };

  /* Metres throughout. The head of the bed is at -Z, the foot at +Z. */
  Room3D.prototype.build = function (screenCanvas) {
    var S = this.scene;
    var i;

    function box(w, h, d, colour, rough, metal) {
      return new THREE.Mesh(
        new THREE.BoxGeometry(w, h, d),
        new THREE.MeshStandardMaterial({
          color: colour,
          roughness: rough === undefined ? 0.85 : rough,
          metalness: metal === undefined ? 0.05 : metal
        })
      );
    }
    function place(m, x, y, z, cast, receive) {
      m.position.set(x, y, z);
      m.castShadow = cast !== false;
      m.receiveShadow = receive !== false;
      S.add(m);
      return m;
    }
    var steel = new THREE.MeshStandardMaterial({ color: 0xA9B2BC, roughness: 0.3, metalness: 0.75 });

    /* ---- shell: floor, three walls, ceiling ---- */
    var floor = new THREE.Mesh(
      new THREE.PlaneGeometry(16, 16),
      new THREE.MeshStandardMaterial({ map: floorTexture(), color: 0x6A757C, roughness: 0.34, metalness: 0.06 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    S.add(floor);

    var wallMat = new THREE.MeshStandardMaterial({ map: wallTexture(), color: 0x939E9E, roughness: 0.95 });

    var headWall = new THREE.Mesh(new THREE.PlaneGeometry(9, 3.1), wallMat);
    place(headWall, 0, 1.55, -2.05, false, true);

    var leftWall = new THREE.Mesh(new THREE.PlaneGeometry(7, 3.1), wallMat);
    leftWall.rotation.y = Math.PI / 2;
    place(leftWall, -2.6, 1.55, 1.0, false, true);

    var rightWall = new THREE.Mesh(new THREE.PlaneGeometry(7, 3.1), wallMat);
    rightWall.rotation.y = -Math.PI / 2;
    place(rightWall, 2.9, 1.55, 1.0, false, true);

    var ceiling = new THREE.Mesh(
      new THREE.PlaneGeometry(9, 7),
      new THREE.MeshStandardMaterial({ map: ceilingTexture(), color: 0xD6DAD6, roughness: 1 })
    );
    ceiling.rotation.x = Math.PI / 2;
    place(ceiling, 0, 3.1, 0.6, false, false);

    /* skirting, so the floor and wall do not just abut */
    place(box(9, 0.09, 0.03, 0x5C6970, 0.6), 0, 0.045, -2.03, false, true);

    /* ---- the headwall service panel: the strip every ward bed has ---- */
    var panel = box(2.1, 0.30, 0.07, 0xEDEFEA, 0.6);
    place(panel, 0, 1.36, -2.0);
    for (i = 0; i < 4; i++) {
      var outlet = box(0.09, 0.11, 0.03, i < 2 ? 0x3C7F5E : 0xFFFFFF, 0.5);
      place(outlet, -0.62 + i * 0.30, 1.36, -1.955, false, false);
    }
    for (i = 0; i < 3; i++) {
      place(box(0.11, 0.11, 0.02, 0xD8D3C4, 0.6), 0.42 + i * 0.17, 1.36, -1.955, false, false);
    }
    /* the little strip light under the panel, always on */
    var strip = new THREE.Mesh(
      new THREE.BoxGeometry(1.9, 0.03, 0.05),
      new THREE.MeshBasicMaterial({ color: 0xFFE9C4 })
    );
    place(strip, 0, 1.19, -1.98, false, false);

    /* ---- window on the far wall, with blinds and a night outside ---- */
    var glass = new THREE.Mesh(
      new THREE.PlaneGeometry(1.5, 1.05),
      new THREE.MeshBasicMaterial({ map: nightTexture() })
    );
    place(glass, -1.55, 1.68, -2.02, false, false);
    place(box(1.62, 0.06, 0.07, 0xE8EAE5, 0.7), -1.55, 2.23, -2.0, false, false);
    place(box(1.62, 0.06, 0.07, 0xE8EAE5, 0.7), -1.55, 1.13, -2.0, false, false);
    place(box(0.06, 1.17, 0.07, 0xE8EAE5, 0.7), -2.33, 1.68, -2.0, false, false);
    place(box(0.06, 1.17, 0.07, 0xE8EAE5, 0.7), -0.77, 1.68, -2.0, false, false);
    for (i = 0; i < 7; i++) {          /* venetian slats, tilted half open */
      var slat = box(1.48, 0.035, 0.035, 0xDDE2DE, 0.8);
      slat.rotation.x = 0.55;
      place(slat, -1.55, 2.14 - i * 0.075, -1.985, false, false);
    }

    /* ---- privacy curtain on a ceiling rail, pulled back ---- */
    place(box(0.035, 0.035, 3.2, 0xB9C0C6, 0.4, 0.5), -1.95, 2.72, -0.35, false, false);
    var curtain = new THREE.Mesh(
      new THREE.PlaneGeometry(1.5, 2.0, 12, 1),
      new THREE.MeshStandardMaterial({
        map: curtainTexture(), color: 0xBFD6D0,
        roughness: 0.95, side: THREE.DoubleSide
      })
    );
    /* ripple the panel so it hangs in folds rather than as a flat board */
    var cpos = curtain.geometry.attributes.position;
    for (i = 0; i < cpos.count; i++) {
      cpos.setZ(i, Math.sin(cpos.getX(i) * 9.0) * 0.055);
    }
    curtain.geometry.computeVertexNormals();
    curtain.rotation.y = Math.PI / 2;
    place(curtain, -1.95, 1.70, 0.30, true, true);

    /* ---- the door, on the far side ---- */
    place(box(0.95, 2.08, 0.06, 0xD9D2C2, 0.8), 2.86, 1.04, -0.10, false, true);
    place(box(1.06, 2.16, 0.03, 0x8C949A, 0.7), 2.88, 1.08, -0.10, false, false);
    place(box(0.05, 0.05, 0.14, 0xC6CDD4, 0.3, 0.8), 2.82, 1.02, 0.26, false, false);

    /* ---- the bed ---- */
    place(box(1.06, 0.15, 2.10, 0x5A6772, 0.55), 0, 0.615, -0.05);
    for (i = 0; i < 4; i++) {
      place(box(0.07, 0.52, 0.07, 0x262B32, 0.6),
            (i % 2 ? 1 : -1) * 0.44, 0.27, (i < 2 ? 1 : -1) * 0.88, true, false);
      var castor = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.055, 0.045, 12), steel);
      castor.rotation.z = Math.PI / 2;
      place(castor, (i % 2 ? 1 : -1) * 0.44, 0.05, (i < 2 ? 1 : -1) * 0.88, true, false);
    }

    /* the flat part of the mattress, and the raised backrest he leans on */
    var mattressMat = new THREE.MeshStandardMaterial({
      map: sheetTexture(), color: 0xA3AFB6, roughness: 0.92
    });
    var mattress = new THREE.Mesh(new THREE.BoxGeometry(1.02, 0.14, 1.36), mattressMat);
    place(mattress, 0, 0.70, 0.32);

    var backrest = new THREE.Mesh(new THREE.BoxGeometry(1.02, 0.14, 0.80), mattressMat);
    backrest.rotation.x = 0.50;
    place(backrest, 0, 0.88, -0.68);

    /* headboard and footboard */
    place(box(1.12, 0.46, 0.06, 0x6E7A85, 0.55), 0, 1.02, -1.14);
    place(box(1.12, 0.34, 0.06, 0x6E7A85, 0.55), 0, 0.88, 1.04);

    /* Side rails. The far one is up, because he is a fall risk; the near one
       is down, because that is what you do before you walk up to a patient --
       and because up it drew a bright metal bar straight across his chest
       from the only camera angle this game has. */
    function rail(s, y) {
      place(box(0.035, 0.035, 0.94, 0x94A0A8, 0.35, 0.6), s * 0.53, y, -0.22, true, false);
      place(box(0.035, 0.035, 0.94, 0x94A0A8, 0.35, 0.6), s * 0.53, y - 0.16, -0.22, true, false);
      for (var k = 0; k < 4; k++) {
        place(box(0.025, 0.17, 0.025, 0x94A0A8, 0.35, 0.6),
              s * 0.53, y - 0.08, -0.62 + k * 0.26, true, false);
      }
    }
    rail(-1, 0.99);
    rail(1, 0.60);

    /* ---- the blanket, draped over him from the chest down ----
       A plane over a few sine lobes reads as a body because of the silhouette
       and the way the light falls, not because of any detail. */
    /* BLANKET_LEN is the plane's length along the body, and `bodyT` is the
       only correct way to turn a vertex into "how far down him are we".
       Two bugs lived here, both inherited from v1 and both invisible until
       the drape was strong enough to see:

       1. The plane is rotated -90 degrees about X, which maps local +Y to
          world -Z. -Y is therefore the FOOT of the bed, not the head -- so
          every lobe was mirrored and his belly was rendering past his ankles.
       2. getY returns real local units, here -0.76..+0.76, not -1..+1. The
          old `(y + 1) / 2` squashed the whole body into t = 0.12..0.88 and
          slid it down the bed. */
    var BLANKET_LEN = 1.62;
    function bodyT(y) { return 0.5 - y / BLANKET_LEN; }   /* 0 chest .. 1 feet */
    /* Its centre follows from where the top edge has to land, rather than
       being a number picked to look right and then fought with. */
    var BLANKET_Z = BLANKET_EDGE_Z + BLANKET_LEN / 2;

    var segW = 24, segL = 44;
    var sheetGeo = new THREE.PlaneGeometry(1.02, BLANKET_LEN, segW, segL);
    var pos = sheetGeo.attributes.position;
    for (i = 0; i < pos.count; i++) {
      var x = pos.getX(i);
      var t = bodyT(pos.getY(i));
      var across = Math.pow(Math.cos(Math.min(1, Math.abs(x) / 0.40) * Math.PI / 2), 0.7);

      /* Below the chest he IS the blanket -- there is no leg geometry, because
         a limb under a draped plane clips through it. So the lobes have to do
         the whole job, and the previous amplitudes were too shy to read as a
         person: from the camera he was a flat sheet with a torso on it. The
         knees are the tell-tale, so they are the tallest thing here. */
      var gut   = 0.20 * Math.exp(-Math.pow((t - 0.08) / 0.15, 2));
      var hips  = 0.25 * Math.exp(-Math.pow((t - 0.30) / 0.13, 2));
      var thigh = 0.23 * Math.exp(-Math.pow((t - 0.52) / 0.13, 2));
      var knees = 0.27 * Math.exp(-Math.pow((t - 0.74) / 0.085, 2));
      var shin  = 0.14 * Math.exp(-Math.pow((t - 0.88) / 0.07, 2));
      var feet  = 0.18 * Math.exp(-Math.pow((t - 0.975) / 0.04, 2));

      /* the gap between his legs, so it is two of them and not one mound */
      var split = 1 - 0.22 * Math.exp(-Math.pow(x / 0.075, 2)) * Math.min(1, Math.max(0, (t - 0.42) / 0.12));

      pos.setZ(i, (gut + hips + thigh + knees + shin + feet) * across * split);
    }
    sheetGeo.computeVertexNormals();

    var sheet = new THREE.Mesh(
      sheetGeo,
      new THREE.MeshStandardMaterial({
        map: blanketTexture(), color: 0xFFFFFF,   /* let the texture set it */
        roughness: 0.97, metalness: 0, side: THREE.DoubleSide
      })
    );
    sheet.rotation.x = -Math.PI / 2;
    place(sheet, 0, 0.775, BLANKET_Z);
    this.sheet = sheet;

    /* The turned-back top sheet: a white cuff along the blanket's edge. It is
       what makes the blanket look folded over him rather than laid on him. */
    var cuff = new THREE.Mesh(
      new THREE.BoxGeometry(1.03, 0.055, 0.20),
      new THREE.MeshStandardMaterial({ map: sheetTexture(), color: 0xF0F3F4, roughness: 0.93 })
    );
    cuff.rotation.x = -0.20;
    place(cuff, 0, 0.905, BLANKET_EDGE_Z + 0.03);

    this.patient = buildPatient();
    S.add(this.patient);

    var pillow = box(0.52, 0.12, 0.34, 0xF4F6F4, 0.95);
    pillow.rotation.x = 0.44;
    place(pillow, 0, 1.08, -0.92);

    /* ---- IV pole, bag, and a line that actually reaches his arm ---- */
    var pole = new THREE.Mesh(new THREE.CylinderGeometry(0.017, 0.017, 1.95, 10), steel);
    place(pole, -0.92, 0.97, -0.62, true, false);
    var poleBase = new THREE.Mesh(
      new THREE.CylinderGeometry(0.19, 0.20, 0.03, 16),
      new THREE.MeshStandardMaterial({ color: 0x3C444D, roughness: 0.6 })
    );
    place(poleBase, -0.92, 0.015, -0.62, false, true);
    place(box(0.03, 0.03, 0.24, 0xB9C0C6, 0.4, 0.6), -0.92, 1.88, -0.62, false, false);

    var bagMat = new THREE.MeshStandardMaterial({
      color: 0xD8ECE4, roughness: 0.25, metalness: 0,
      transparent: true, opacity: 0.88
    });
    var bag = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.28, 0.05), bagMat);
    place(bag, -0.92, 1.70, -0.55);
    place(box(0.05, 0.09, 0.035, 0xEFF6F2, 0.3), -0.92, 1.52, -0.55, false, false);

    var line = bone([-0.92, 1.48, -0.55], [-0.240, 0.978, -0.020], 0.007,
                    new THREE.MeshStandardMaterial({ color: 0xE6EEF0, roughness: 0.4 }));
    S.add(line);

    /* ---- bedside cabinet, jug, cup ---- */
    place(box(0.44, 0.62, 0.42, 0xC9BFA8, 0.8), -0.95, 0.31, 0.42);
    place(box(0.40, 0.03, 0.38, 0xB3A78E, 0.7), -0.95, 0.615, 0.42, false, false);
    place(box(0.40, 0.02, 0.36, 0x8E8570, 0.7), -0.95, 0.44, 0.44, false, false);
    var jug = new THREE.Mesh(new THREE.CylinderGeometry(0.058, 0.05, 0.16, 14),
                             new THREE.MeshStandardMaterial({ color: 0xE9E4D6, roughness: 0.4 }));
    place(jug, -1.02, 0.70, 0.40);
    var cup = new THREE.Mesh(new THREE.CylinderGeometry(0.032, 0.026, 0.075, 12),
                             new THREE.MeshStandardMaterial({ color: 0xF2EFE6, roughness: 0.5 }));
    place(cup, -0.86, 0.66, 0.50);

    /* ---- overbed table, swung right out of the way ----
       It used to sit at (1.05, _, 0.62), which is between this camera and the
       bed: a white slab across the bottom third of every frame. */
    place(box(0.60, 0.025, 0.35, 0xA8977A, 0.6), -1.28, 0.86, 1.12);
    place(box(0.05, 0.56, 0.05, 0x7C858E, 0.4, 0.6), -1.28, 0.58, 1.12, true, false);
    place(box(0.32, 0.02, 0.28, 0x3A424A, 0.6), -1.28, 0.29, 1.12, false, true);

    /* ---- the monitor, on an arm off the headwall ----
       Swung out over his left so it is square to the camera and close enough
       to read. This is the only place the vitals exist now. */
    place(box(0.07, 0.07, 0.30, 0xAEB6BE, 0.35, 0.7), 1.22, 1.62, -1.90, true, false);
    var arm = bone([1.22, 1.62, -1.78], [1.10, 1.54, -0.76], 0.028, steel);
    S.add(arm);

    var shell = box(0.74, 0.50, 0.10, 0x232A33, 0.55);
    shell.rotation.y = 0.20;
    place(shell, 1.08, 1.50, -0.66);

    /* The screen IS the monitor canvas. Not a second waveform. */
    this.screenTexture = new THREE.CanvasTexture(screenCanvas);
    this.screenTexture.minFilter = THREE.LinearFilter;
    this.screenTexture.magFilter = THREE.LinearFilter;
    this.screenTexture.generateMipmaps = false;

    var screen = new THREE.Mesh(
      new THREE.PlaneGeometry(0.665, 0.415),
      new THREE.MeshBasicMaterial({ map: this.screenTexture, toneMapped: false })
    );
    /* A child of the shell at local +Z. Parenting handles the rotation, so the
       screen cannot end up buried inside its own housing. */
    screen.position.set(0, 0.015, 0.052);
    shell.add(screen);
    this.screen = screen;

    /* a couple of hardware buttons under the glass */
    for (i = 0; i < 4; i++) {
      var btn = new THREE.Mesh(
        new THREE.BoxGeometry(0.035, 0.016, 0.012),
        new THREE.MeshStandardMaterial({ color: 0x4A535E, roughness: 0.6 })
      );
      btn.position.set(-0.22 + i * 0.095, -0.225, 0.052);
      shell.add(btn);
    }

    /* ---- a wall clock, and a sanitiser dispenser: cheap, and they read ---- */
    var clockFace = new THREE.Mesh(
      new THREE.CircleGeometry(0.13, 24),
      new THREE.MeshStandardMaterial({ color: 0xF4F2EA, roughness: 0.6 })
    );
    place(clockFace, -0.55, 2.28, -1.99, false, false);
    place(box(0.012, 0.085, 0.012, 0x2A3038, 0.7), -0.55, 2.32, -1.975, false, false);
    place(box(0.06, 0.012, 0.012, 0x2A3038, 0.7), -0.52, 2.28, -1.975, false, false);
    place(box(0.13, 0.20, 0.08, 0xE8EAE5, 0.7), 2.10, 1.42, -1.98, false, false);

    /* ---- lighting ----
       A ward at night: the overhead panels are dimmed, the headwall strip is
       on, the monitor lights its own corner, and a little cold comes in the
       window. Enough ambient that nothing falls to pure black, not so much
       that the shadows die. */

    S.add(new THREE.HemisphereLight(0x9FB6C8, 0x3A3835, 0.26));
    S.add(new THREE.AmbientLight(0xE8E6DE, 0.13));

    /* two recessed ceiling panels, dimmed for the night */
    [-0.9, 1.0].forEach(function (z) {
      var panelGeo = new THREE.Mesh(
        new THREE.BoxGeometry(1.15, 0.04, 0.58),
        new THREE.MeshBasicMaterial({ color: 0xCFC4AC })
      );
      panelGeo.position.set(-0.1, 3.06, z);
      S.add(panelGeo);
      var pl = new THREE.PointLight(0xFFF0D8, 0.20, 7.0, 2);
      pl.position.set(-0.1, 2.95, z);
      S.add(pl);
    });

    /* the key: the exam light over the bed. Carrying most of the exposure on
       one warm source is what gives the room a lit side and a dark side --
       the previous build spread the same total across eight lights and got a
       flat white box with no shadows in it. */
    var spot = new THREE.SpotLight(0xFFD9A4, 2.4, 9, Math.PI / 6.0, 0.55, 1.4);
    spot.position.set(0.45, 2.80, -0.30);
    spot.target.position.set(0, 0.92, -0.62);
    spot.castShadow = true;
    spot.shadow.mapSize.width = 2048;
    spot.shadow.mapSize.height = 2048;
    spot.shadow.camera.near = 0.6;
    spot.shadow.camera.far = 7;
    spot.shadow.bias = -0.0016;
    spot.shadow.radius = 4;
    S.add(spot);
    S.add(spot.target);

    var housing = new THREE.Mesh(
      new THREE.CylinderGeometry(0.17, 0.27, 0.15, 20, 1, true),
      new THREE.MeshStandardMaterial({ color: 0x3E444C, roughness: 0.55, side: THREE.DoubleSide })
    );
    place(housing, 0.45, 2.80, -0.30, false, false);
    var bulb = new THREE.Mesh(new THREE.CircleGeometry(0.17, 20),
                              new THREE.MeshBasicMaterial({ color: 0xFFF1D6 }));
    bulb.rotation.x = -Math.PI / 2;
    place(bulb, 0.45, 2.72, -0.30, false, false);

    var cone = new THREE.Mesh(
      new THREE.ConeGeometry(0.92, 2.0, 26, 1, true),
      new THREE.MeshBasicMaterial({
        color: 0xFFE3B8, transparent: true, opacity: 0.030,
        side: THREE.DoubleSide, depthWrite: false
      })
    );
    place(cone, 0.45, 1.78, -0.30, false, false);

    /* the headwall strip washes the wall behind him */
    var wash = new THREE.PointLight(0xFFD2A0, 0.42, 3.4, 2);
    wash.position.set(0, 1.24, -1.80);
    S.add(wash);

    /* cold from the window, so the shade side is not all brown */
    var moon = new THREE.DirectionalLight(0x8FAAD0, 0.20);
    moon.position.set(-3.4, 2.6, -2.6);
    S.add(moon);

    /* the corridor, through the door */
    var corridor = new THREE.PointLight(0xFFE6BE, 0.18, 5.0, 2);
    corridor.position.set(2.55, 1.9, 0.30);
    S.add(corridor);

    /* the monitor lights its own corner, and the colour tracks his status */
    this.monitorLight = new THREE.PointLight(STATUS_COLOUR.stable, 1.2, 2.6, 2);
    this.monitorLight.position.set(0.94, 1.48, -0.44);
    S.add(this.monitorLight);

    this.addHotspots();
  };

  /* ---- the inspection layer ----
     You do not pick an examination from a menu, you look at the man and touch
     the part of him you want to check. Each hotspot carries the id of an
     examination the engine already knows how to answer, so this is a new way
     into an existing system rather than a second system. */
  Room3D.prototype.addHotspots = function () {
    var S = this.scene;
    var self = this;
    this.hotspots = [];

    /* These sit on the body, so they move when the body does. Left behind at
       the old heights they pointed at the inside of the mattress. */
    var SPOTS = [
      { id: 'eyes',        label: 'Look at his eyes',    pos: [0.02, 1.24, -0.82], r: 0.13 },
      { id: 'cognition',   label: 'Speak to him',        pos: [0.21, 1.32, -0.90], r: 0.12 },
      { id: 'hands',       label: 'His hands',           pos: [-0.243, 0.975, -0.05], r: 0.14 },
      { id: 'respiratory', label: 'Listen to his chest', pos: [0, 1.04, -0.70], r: 0.18 },
      { id: 'abdominal',   label: 'Feel his abdomen',    pos: [0, 1.00, -0.18], r: 0.20 },
      { id: 'legs',        label: 'His legs',            pos: [0, 1.02, 0.52], r: 0.24 }
    ];

    SPOTS.forEach(function (spec) {
      var mesh = new THREE.Mesh(
        new THREE.SphereGeometry(spec.r, 18, 14),
        new THREE.MeshBasicMaterial({
          color: 0x8FD8FF, transparent: true, opacity: 0.0,
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
      if (this.hovered) this.hovered.material.opacity = this.hovered.userData.done ? 0.10 : 0.0;
      this.hovered = hit;
      if (hit) hit.material.opacity = hit.userData.done ? 0.14 : 0.30;
    }
    return hit;
  };

  Room3D.prototype.markExamined = function (examId) {
    (this.hotspots || []).forEach(function (h) {
      if (h.userData.examId === examId) h.userData.done = true;
    });
  };

  /* A new patient in the same bed: forget what was examined on the last one. */
  Room3D.prototype.resetExams = function () {
    (this.hotspots || []).forEach(function (h) {
      h.userData.done = false;
      h.material.opacity = 0;
    });
    this.hovered = null;
  };

  /* Each case is a different person: five bodies, not one body in five
     colours. `build` is girth and `frame` is shoulder width; height is left
     alone because the chest group sits at the origin, so scaling Y would sink
     him into the mattress rather than making him shorter. */
  Room3D.prototype.setPatientLook = function (look) {
    if (!this.ok || !this.patient || !look) return;
    var u = this.patient.userData;
    if (!u || !u.mats) return;

    if (look.skin) u.mats.flesh.color.setHex(look.skin);
    if (look.hair) u.mats.hair.color.setHex(look.hair);
    if (look.gown) u.mats.gown.color.setHex(look.gown);
    if (u.beard) u.beard.visible = !!look.beard;
    if (u.longHair) u.longHair.visible = !!look.longHair;
    if (u.cap) {
      /* the short cap is the man's hair: off when she has long hair, and
         shrunk back off the forehead when he is going bald */
      u.cap.visible = !look.longHair;
      var thin = look.thin ? 0.80 : 1.0;
      u.cap.scale.set(1.02 * thin, 0.90 * thin, 1.04 * thin);
    }

    /* Both fold into X, and nothing else.
       The chest group is unrotated and sits at the origin, so its Z runs along
       the BED, not through his chest -- scaling it by "build" made him longer
       rather than broader. Y is no use either: its children sit at y ~ 1.0, so
       scaling Y lifts him off the mattress. Width is the one axis that is both
       safe and visible, so build and frame multiply together into it. */
    var width = (look.frame || 1) * (look.build || 1);
    if (u.chest) u.chest.scale.set(width, 1, 1);
    if (u.head) u.head.scale.setScalar(look.head || 1);
  };

  Room3D.prototype.setStatus = function (status) {
    if (!this.ok) return;
    var colour = STATUS_COLOUR[status] || STATUS_COLOUR.stable;
    this.monitorLight.color.setHex(colour);
    this.monitorLight.intensity = (status === 'flatline') ? 0.35 : 1.3;
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

      /* Nothing on the bed moves: not the blanket, not his chest. The only
         thing alive in the frame is the trace on the monitor, which is where
         you are supposed to be looking anyway.

         The blanket does not move. It is laid over him once at build time and
         left alone -- animating its vertices meant re-uploading the geometry
         and recomputing every normal on it each frame, and the wobble read as
         the bedding crawling rather than as him breathing. His chest above it
         still rises, which is the part you are meant to notice.

         Camera drifts on a slow sine path. Never under player control.
         These numbers are the ones that matter: the constructor's position is
         overwritten on the very first frame, so setting it there and not here
         moves the camera for exactly one frame and then snaps it back. */
      var a = this.clock * 0.05;
      this.camera.position.set(
        CAM[0] + Math.sin(a) * 0.075,
        CAM[1] + Math.sin(a * 0.7) * 0.030,
        CAM[2] + Math.cos(a) * 0.050
      );
      this.camera.lookAt(LOOK[0], LOOK[1], LOOK[2]);
    }

    this.updateHover();

    /* The monitor canvas was already redrawn this frame by monitor.js; this
       just tells the GPU to re-upload it. One texture per frame is cheap. */
    this.screenTexture.needsUpdate = true;
    this.renderer.render(this.scene, this.camera);
  };

  Room3D.prototype.dispose = function () {
    if (!this.ok) return;
    if (this._onResize) global.removeEventListener('resize', this._onResize);
    this.renderer.dispose();
    this.ok = false;
  };

  global.Room3D = Room3D;
  global.Room3D.available = available;
})(window);
