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

  var STATUS_COLOUR = {
    stable:    0x5DCAA5,
    declining: 0xEF9F27,
    critical:  0xE24B4A,
    flatline:  0x888780
  };

  function available() {
    return typeof global.THREE !== 'undefined';
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
    this.renderer.toneMappingExposure = 1.15;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x090B0F);
    this.scene.fog = new THREE.Fog(0x090B0F, 3.4, 11);

    this.camera = new THREE.PerspectiveCamera(34, W / H, 0.1, 100);
    this.camera.position.set(1.72, 1.16, 2.22);
    this.camera.lookAt(0, 0.86, 0);

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
      new THREE.MeshStandardMaterial({ color: 0x1A2028, roughness: 0.62, metalness: 0.08 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    S.add(floor);

    var wall = new THREE.Mesh(
      new THREE.PlaneGeometry(24, 9),
      new THREE.MeshStandardMaterial({ color: 0x232B36, roughness: 0.95 })
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
    var sheetGeo = new THREE.PlaneGeometry(1.02, 2.0, segW, segL);
    this.baseZ = [];
    var pos = sheetGeo.attributes.position;
    for (i = 0; i < pos.count; i++) {
      var x = pos.getX(i);
      var y = pos.getY(i);          /* along the body, -1 head .. +1 feet */
      var t = (y + 1) / 2;
      var across = Math.pow(Math.cos(Math.min(1, Math.abs(x) / 0.34) * Math.PI / 2), 0.75);

      var chest = 0.30 * Math.exp(-Math.pow((t - 0.30) / 0.115, 2));
      var waist = 0.17 * Math.exp(-Math.pow((t - 0.48) / 0.085, 2));
      var hips  = 0.24 * Math.exp(-Math.pow((t - 0.62) / 0.085, 2));
      var knees = 0.19 * Math.exp(-Math.pow((t - 0.80) / 0.075, 2));
      var shins = 0.11 * Math.exp(-Math.pow((t - 0.91) / 0.065, 2));
      var feet  = 0.13 * Math.exp(-Math.pow((t - 0.985) / 0.030, 2));
      var h = (chest + waist + hips + knees + shins + feet) * across;

      this.baseZ.push(h);
      pos.setZ(i, h);
    }
    sheetGeo.computeVertexNormals();

    var sheet = new THREE.Mesh(
      sheetGeo,
      new THREE.MeshStandardMaterial({
        color: 0xE9E3D6, roughness: 0.88, metalness: 0,
        side: THREE.DoubleSide
      })
    );
    sheet.rotation.x = -Math.PI / 2;
    sheet.position.set(0, 0.70, 0.08);
    sheet.castShadow = true;
    sheet.receiveShadow = true;
    S.add(sheet);
    this.sheet = sheet;

    /* A suggestion of a head on the pillow. A sphere, no features. */
    var pillow = box(0.42, 0.10, 0.26, 0xF2ECDF, 0.92);
    pillow.position.set(0, 0.75, -0.92);
    pillow.castShadow = true;
    S.add(pillow);

    var headForm = new THREE.Mesh(
      new THREE.SphereGeometry(0.115, 20, 16),
      new THREE.MeshStandardMaterial({ color: 0xB08968, roughness: 0.78 })
    );
    headForm.position.set(0, 0.86, -0.90);
    headForm.scale.set(1, 0.92, 1.05);
    headForm.castShadow = true;
    S.add(headForm);

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
    S.add(new THREE.HemisphereLight(0x5B6B82, 0x0C0F14, 0.55));
    S.add(new THREE.AmbientLight(0x2A3340, 0.45));

    var spot = new THREE.SpotLight(0xFFCE94, 2.6, 9, Math.PI / 7.4, 0.5, 1.6);
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
        color: 0xFFD8A4, transparent: true, opacity: 0.052,
        side: THREE.DoubleSide, depthWrite: false
      })
    );
    cone.position.set(0.30, 1.78, 0.55);
    S.add(cone);

    /* cool rim, so he is not the same colour as the wall behind him */
    var rim = new THREE.DirectionalLight(0x7FC4FF, 1.5);
    rim.position.set(-2.6, 1.7, -1.9);
    S.add(rim);

    var fill = new THREE.PointLight(0x9FB8D8, 0.5, 7, 2);
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
      { id: 'eyes',       label: 'Eyes',    pos: [0, 0.90, -0.88], r: 0.17 },
      { id: 'cognition',  label: 'Speak to him', pos: [0.24, 0.96, -0.86], r: 0.13 },
      { id: 'hands',      label: 'Hands',   pos: [-0.44, 0.80, 0.12], r: 0.17 },
      { id: 'respiratory',label: 'Chest',   pos: [0, 0.92, -0.32], r: 0.20 },
      { id: 'abdominal',  label: 'Abdomen', pos: [0, 0.94, 0.14],  r: 0.22 },
      { id: 'legs',       label: 'Legs',    pos: [0, 0.80, 0.76],  r: 0.22 }
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
      var pos = this.sheet.geometry.attributes.position;
      for (var i = 0; i < pos.count; i++) {
        var y = pos.getY(i);
        var t = (y + 1) / 2;
        var chest = Math.exp(-Math.pow((t - 0.30) / 0.13, 2));
        pos.setZ(i, this.baseZ[i] + breath * 0.026 * chest);
      }
      pos.needsUpdate = true;
      this.sheet.geometry.computeVertexNormals();

      /* camera drifts on a slow sine path. Never under player control. */
      var a = this.clock * 0.055;
      this.camera.position.set(
        2.6 + Math.sin(a) * 0.55,
        1.85 + Math.sin(a * 0.7) * 0.11,
        3.5 + Math.cos(a) * 0.30
      );
      this.camera.lookAt(0, 0.86, 0);
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
