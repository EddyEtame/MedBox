/* The hull: a generation ship you can see into.
 *
 * Eddy, 24 Sep: "something that actually looks like a spaceship and feels
 * like people can stay in it for a long time. Solid." ESA Horizon is a long
 * hull with two decks: the bridge forward, forty cabins with their windows
 * amidships, the mess aft on the upper deck; the infirmary and the three
 * isolation rooms on the lower deck; engines and radiators at the stern,
 * greenhouse domes on the back. The side facing the camera is cut away, so
 * the decks, the rooms and the beds inside are visible, the way a doll's
 * house shows its rooms. Everything is placed from layout.js, the same
 * plan ship.js draws its overlay from. three.js is vendored; offline. */
(function (root) {
  "use strict";
  if (!root.THREE) return;
  var THREE = root.THREE;

  var renderer = null, scene = null, camera = null, canvas = null;
  var ready = false, lastW = 0, lastH = 0, t0 = 0;
  var clipNear = null, clipDeck = null, shellMats = [], zoneTiles = [], windows = null, engineGlow = null, engineLight = null, radiators = [];
  var LAY = null;

  function mat(color, opts) {
    var m = new THREE.MeshStandardMaterial({ color: color, metalness: 0.55, roughness: 0.5 });
    if (opts) Object.keys(opts).forEach(function (k) { m[k] = opts[k]; });
    return m;
  }
  function shell(color, opts) {
    // Hull skin: clipped on the camera side so the interior shows.
    var m = mat(color, opts);
    m.clippingPlanes = [clipNear, clipDeck];
    m.clipShadows = true;
    shellMats.push(m);
    return m;
  }
  function upper(m) {
    // Deck 1 furniture: removed with the roof when a lower-deck room is in view.
    m.clippingPlanes = [clipDeck];
    return m;
  }
  function boxMesh(b, material, inset) {
    inset = inset || 0;
    var g = new THREE.BoxGeometry((b.x1 - b.x0) - inset * 2, (b.y1 - b.y0) - inset * 2, (b.z1 - b.z0) - inset * 2);
    var m = new THREE.Mesh(g, material);
    m.position.set((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, (b.z0 + b.z1) / 2);
    return m;
  }

  function roundedRect(w, h, r) {
    var s = new THREE.Shape();
    s.moveTo(-w / 2 + r, -h / 2);
    s.lineTo(w / 2 - r, -h / 2); s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
    s.lineTo(w / 2, h / 2 - r); s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
    s.lineTo(-w / 2 + r, h / 2); s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
    s.lineTo(-w / 2, -h / 2 + r); s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
    return s;
  }

  function buildShell() {
    var g = new THREE.Group();
    var L = LAY.L, W = LAY.W, H = LAY.H;
    // The main hull: a rounded section extruded along x, thin walled so the
    // cut shows a wall, not a solid block.
    var section = roundedRect(W, H, 1.3);
    var hole = roundedRect(W - 0.36, H - 0.36, 1.1);
    section.holes.push(hole);
    var hullGeo = new THREE.ExtrudeGeometry(section, { depth: L, bevelEnabled: false, curveSegments: 16 });
    hullGeo.rotateY(Math.PI / 2);
    hullGeo.translate(-L / 2, 0, 0);
    var hull = new THREE.Mesh(hullGeo, shell(0x2c363e, { roughness: 0.5, side: THREE.DoubleSide }));
    g.add(hull);
    // Deck plates between the two decks and the roof, seen in the cut.
    [LAY.DECK1.floor - 0.06, LAY.DECK2.floor - 0.06].forEach(function (y) {
      var plate = new THREE.Mesh(new THREE.BoxGeometry(L - 0.4, 0.12, W - 0.4), mat(0x55636c, { roughness: 0.6 }));
      plate.position.set(0, y, 0);
      g.add(plate);
    });
    var roof = new THREE.Mesh(new THREE.BoxGeometry(L - 0.4, 0.1, W - 0.4), shell(0x2c363e, { roughness: 0.55 }));
    roof.position.set(0, H / 2 - 0.12, 0);
    g.add(roof);
    // A lighter band along the flank, and dark seams every few metres.
    var band = new THREE.Mesh(new THREE.BoxGeometry(L - 2, 0.5, W + 0.06), shell(0x5e6f7a, { metalness: 0.7, roughness: 0.35 }));
    band.position.set(0, -0.05, 0);
    g.add(band);
    var seamGeo = new THREE.BoxGeometry(0.06, H - 0.6, W + 0.08);
    var seams = new THREE.InstancedMesh(seamGeo, shell(0x1c252c, { roughness: 0.9, metalness: 0.2 }), 12);
    var d = new THREE.Object3D();
    for (var i = 0; i < 12; i++) { d.position.set(-13 + i * 2.35, 0, 0); d.updateMatrix(); seams.setMatrixAt(i, d.matrix); }
    g.add(seams);
    // The bow: a tapered nose with the bridge's forward windows.
    var nose = new THREE.Mesh(new THREE.SphereGeometry(1, 28, 18, 0, Math.PI * 2, 0, Math.PI / 2), shell(0x3d4a54, { roughness: 0.42 }));
    nose.scale.set(LAY.BOW, H / 2, W / 2);
    nose.rotation.z = -Math.PI / 2;
    nose.position.set(L / 2, 0, 0);
    g.add(nose);
    var visor = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.22, 2.6), new THREE.MeshStandardMaterial({ color: 0x0b1a20, emissive: 0xbfeee6, emissiveIntensity: 1.2 }));
    visor.position.set(L / 2 + 2.6, 0.95, 0);
    visor.rotation.z = -0.35;
    g.add(visor);
    // The stern: an engineering block, three engines, their glow and light.
    var stern = new THREE.Mesh(new THREE.BoxGeometry(3.2, H + 0.9, W + 1.2), shell(0x2f3a42, { roughness: 0.55 }));
    stern.position.set(-L / 2 - 1.2, 0, 0);
    g.add(stern);
    var bellMat = mat(0x3a4a52, { metalness: 0.8, roughness: 0.3, side: THREE.DoubleSide });
    var discMat = new THREE.MeshStandardMaterial({ color: 0x08131a, emissive: 0x9fd6ff, emissiveIntensity: 2.4 });
    [[0, 1.3], [-2.4, -0.9], [2.4, -0.9]].forEach(function (p) {
      var bell = new THREE.Mesh(new THREE.ConeGeometry(1.05, 2.6, 28, 1, true), bellMat);
      bell.rotation.z = Math.PI / 2;
      bell.position.set(-L / 2 - 4.0, p[1], p[0]);
      g.add(bell);
      var disc = new THREE.Mesh(new THREE.CircleGeometry(0.85, 28), discMat);
      disc.rotation.y = -Math.PI / 2;
      disc.position.set(-L / 2 - 5.25, p[1], p[0]);
      g.add(disc);
    });
    engineGlow = new THREE.Mesh(new THREE.ConeGeometry(2.6, 9, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: 0x6fc3ff, transparent: true, opacity: 0.14, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }));
    engineGlow.rotation.z = Math.PI / 2;
    engineGlow.position.set(-L / 2 - 9.5, 0, 0);
    g.add(engineGlow);
    engineLight = new THREE.PointLight(0x8fd0ff, 1.2, 22);
    engineLight.position.set(-L / 2 - 5.5, 0, 0);
    g.add(engineLight);
    // Radiators: four angled fins at the stern, warmer with crew fever.
    var radMat = new THREE.MeshStandardMaterial({ color: 0x2a2226, emissive: 0xff7a3a, emissiveIntensity: 0.2, roughness: 0.7, side: THREE.DoubleSide });
    [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(function (s) {
      var fin = new THREE.Mesh(new THREE.BoxGeometry(2.6, 2.2, 0.06), radMat);
      fin.position.set(-L / 2 - 1.2, s[0] * 3.2, s[1] * 3.2);
      fin.rotation.x = s[0] * s[1] * Math.PI / 4;
      g.add(fin);
      radiators.push(fin);
    });
    // Nacelles along the flanks, on pylons.
    [1, -1].forEach(function (sz) {
      var nac = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 10, 16), mat(0x46535c, { roughness: 0.4 }));
      nac.rotation.z = Math.PI / 2;
      nac.position.set(-4.5, -2.6, sz * (W / 2 + 0.6));
      g.add(nac);
      [5, -5].forEach(function (px) {
        var cap = new THREE.Mesh(new THREE.SphereGeometry(0.8, 16, 12), mat(0x46535c, { roughness: 0.4 }));
        cap.position.set(-4.5 + px, -2.6, sz * (W / 2 + 0.6));
        g.add(cap);
      });
      [-5, 0].forEach(function (px) {
        var pylon = new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.2, 0.5), mat(0x2f3a42));
        pylon.position.set(-4.5 + px, -2.0, sz * (W / 2 + 0.1));
        g.add(pylon);
      });
    });
    // Greenhouse domes on the back: food and air for the long voyage.
    var domeMat = new THREE.MeshStandardMaterial({ color: 0x1f5a4a, emissive: 0x2fb58a, emissiveIntensity: 0.35, transparent: true, opacity: 0.75, roughness: 0.2, metalness: 0.1 });
    [-3.5, 1.5].forEach(function (px) {
      var dome = new THREE.Mesh(new THREE.SphereGeometry(1.5, 28, 16, 0, Math.PI * 2, 0, Math.PI / 2), domeMat);
      dome.position.set(px, H / 2 - 0.05, 0);
      g.add(dome);
      var ring = new THREE.Mesh(new THREE.TorusGeometry(1.5, 0.08, 8, 40), mat(0x8fa8b2, { metalness: 0.8 }));
      ring.rotation.x = Math.PI / 2;
      ring.position.set(px, H / 2, 0);
      g.add(ring);
    });
    // The bridge superstructure forward, with its window band.
    var sup = new THREE.Mesh(new THREE.BoxGeometry(4.0, 1.1, 3.2), shell(0x3d4a54));
    sup.position.set(11.4, H / 2 + 0.5, 0);
    g.add(sup);
    var supGlass = new THREE.Mesh(new THREE.BoxGeometry(4.02, 0.35, 3.22), new THREE.MeshStandardMaterial({ color: 0x0b1a20, emissive: 0xbfeee6, emissiveIntensity: 1.1 }));
    supGlass.position.set(11.4, H / 2 + 0.7, 0);
    g.add(supGlass);
    // Antennae and a dish.
    var mast = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 2.4, 8), mat(0x8fa8b2));
    mast.position.set(7.5, H / 2 + 1.2, 1.0);
    g.add(mast);
    var dish = new THREE.Mesh(new THREE.SphereGeometry(0.9, 24, 12, 0, Math.PI * 2, 0, Math.PI / 3), mat(0xc9d6dc, { metalness: 0.3, roughness: 0.6, side: THREE.DoubleSide }));
    dish.position.set(-8.5, H / 2 + 0.6, -1.4);
    dish.rotation.x = -Math.PI / 3;
    g.add(dish);
    // Windows: a row per deck along both flanks, lit from inside.
    var paneGeo = new THREE.BoxGeometry(0.28, 0.16, 0.06);
    var paneMat = new THREE.MeshStandardMaterial({ color: 0x0b1a20, emissive: 0xfff1cf, emissiveIntensity: 1.25, roughness: 0.2 });
    paneMat.clippingPlanes = [clipNear];
    shellMats.push(paneMat);
    var rows = [LAY.DECK1.floor + 1.05, LAY.DECK2.floor + 1.05], count = 0, n = 0;
    for (var x = -12.8; x <= 12.8; x += 0.62) count += 4;
    windows = new THREE.InstancedMesh(paneGeo, paneMat, count);
    rows.forEach(function (y) {
      [1, -1].forEach(function (sz) {
        for (var xx = -12.8; xx <= 12.8; xx += 0.62) {
          d.position.set(xx, y, sz * (W / 2 + 0.01));
          d.rotation.set(0, 0, 0);
          d.updateMatrix();
          windows.setMatrixAt(n++, d.matrix);
        }
      });
    });
    windows.count = n;
    g.add(windows);
    // Running lights: red to port, green to starboard, white at the stern.
    [[0xff3b3b, -1], [0x3bff6a, 1]].forEach(function (p) {
      var lamp = new THREE.Mesh(new THREE.SphereGeometry(0.14, 10, 8), new THREE.MeshStandardMaterial({ color: 0x111, emissive: p[0], emissiveIntensity: 2 }));
      lamp.position.set(12.5, 0.6, p[1] * (W / 2 + 0.1));
      g.add(lamp);
    });
    return g;
  }

  function buildInterior() {
    var g = new THREE.Group();
    var wallMat = mat(0xb9c4ca, { roughness: 0.9, metalness: 0.05 });
    var bedMat = mat(0xe7edf0, { roughness: 0.8, metalness: 0.0 });
    var pillowMat = mat(0x9fd8cf, { roughness: 0.8 });
    var consoleMat = new THREE.MeshStandardMaterial({ color: 0x1d2a33, emissive: 0x7be8d3, emissiveIntensity: 0.5, roughness: 0.4 });
    var wallUp = upper(mat(0xc9d2d7, { roughness: 0.9, metalness: 0.05 }));
    var bedUp = upper(mat(0xe7edf0, { roughness: 0.8, metalness: 0.0 }));
    var consoleUp = upper(new THREE.MeshStandardMaterial({ color: 0x1d2a33, emissive: 0x7be8d3, emissiveIntensity: 0.5, roughness: 0.4 }));
    var tableUp = upper(mat(0x9fb0b8, { roughness: 0.7 }));
    var chairUp = upper(mat(0x2b3940));
    // Cabins on deck 1: a partition per cabin and a bed against the hull.
    for (var i = 0; i < LAY.CREW; i++) {
      var c = LAY.cabinBox(i);
      var wall = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.5, c.z1 - c.z0), wallUp);
      wall.position.set(c.x0, LAY.DECK1.floor + 0.75, (c.z0 + c.z1) / 2);
      g.add(wall);
      var bed = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.18, 1.1), bedUp);
      bed.position.set(c.x, LAY.DECK1.floor + 0.12, (c.z0 + c.z1) / 2);
      g.add(bed);
      var inner = new THREE.Mesh(new THREE.BoxGeometry(c.x1 - c.x0, 1.5, 0.05), wallUp);
      inner.position.set(c.x, LAY.DECK1.floor + 0.75, c.side > 0 ? c.z0 : c.z1);
      g.add(inner);
    }
    // Bridge: consoles in an arc and the captain's chair.
    for (var k = -2; k <= 2; k++) {
      var con = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.9, 0.5), consoleUp);
      con.position.set(LAY.bridge.x1 - 0.9 - Math.abs(k) * 0.25, LAY.DECK1.floor + 0.45, k * 0.95);
      g.add(con);
    }
    var chair = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.9, 0.6), chairUp);
    chair.position.set(LAY.bridge.x0 + 1.2, LAY.DECK1.floor + 0.45, 0);
    g.add(chair);
    // Mess: two long tables.
    [-1.3, 1.3].forEach(function (z) {
      var table = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.08, 0.8), tableUp);
      table.position.set((LAY.mess.x0 + LAY.mess.x1) / 2, LAY.DECK1.floor + 0.72, z);
      g.add(table);
    });
    // Deck 2: the infirmary, eight beds around a console, and a white light.
    var infFloor = new THREE.Mesh(new THREE.BoxGeometry(LAY.infirmary.x1 - LAY.infirmary.x0, 0.04, LAY.infirmary.z1 - LAY.infirmary.z0),
      new THREE.MeshStandardMaterial({ color: 0xdde6ea, emissive: 0xffffff, emissiveIntensity: 0.12, roughness: 0.9 }));
    infFloor.position.set(LAY.infirmary.cx, LAY.DECK2.floor + 0.02, LAY.infirmary.cz);
    g.add(infFloor);
    var core = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.6, 1.0, 20), consoleMat);
    core.position.set(0, LAY.DECK2.floor + 0.5, 0);
    g.add(core);
    for (var s = 0; s < 8; s++) {
      var p = LAY.infirmarySlot(s);
      var ib = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.22, 1.0), bedMat);
      ib.position.set(p.x, LAY.DECK2.floor + 0.14, p.z);
      ib.rotation.y = -Math.atan2(p.z, p.x);
      g.add(ib);
    }
    var infLight = new THREE.PointLight(0xffffff, 1.1, 9);
    infLight.position.set(0, LAY.DECK2.ceil - 0.2, 0);
    g.add(infLight);
    [LAY.infirmary.x0, LAY.infirmary.x1].forEach(function (x) {
      var w = new THREE.Mesh(new THREE.BoxGeometry(0.06, LAY.DECK2.ceil - LAY.DECK2.floor, LAY.infirmary.z1 - LAY.infirmary.z0), wallMat);
      w.position.set(x, (LAY.DECK2.floor + LAY.DECK2.ceil) / 2, 0);
      g.add(w);
    });
    // Deck 2: the three isolation rooms, four beds each, a tinted floor and a lamp.
    for (var zi = 0; zi < LAY.ZONES; zi++) {
      var zb = LAY.zoneBox(zi);
      var tile = new THREE.Mesh(new THREE.BoxGeometry(zb.x1 - zb.x0 - 0.1, 0.04, zb.z1 - zb.z0 - 0.1),
        new THREE.MeshStandardMaterial({ color: 0x9fb0b8, emissive: 0x2fb7a6, emissiveIntensity: 0.15, roughness: 0.9 }));
      tile.position.set(zb.cx, LAY.DECK2.floor + 0.02, zb.cz);
      g.add(tile);
      zoneTiles.push(tile);
      [zb.x0, zb.x1].forEach(function (x) {
        var w = new THREE.Mesh(new THREE.BoxGeometry(0.06, LAY.DECK2.ceil - LAY.DECK2.floor, zb.z1 - zb.z0), wallMat);
        w.position.set(x, (LAY.DECK2.floor + LAY.DECK2.ceil) / 2, zb.cz);
        g.add(w);
      });
      for (var b = 0; b < LAY.BERTHS; b++) {
        var bb = LAY.bedBox(zi, b);
        var bed2 = boxMesh(bb, bedMat, 0.02);
        g.add(bed2);
        var pillow = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.1, 0.32), pillowMat);
        pillow.position.set(bb.cx, bb.y1 + 0.05, bb.cz + (bb.cz > 0 ? 0.6 : -0.6));
        g.add(pillow);
      }
      var lamp = new THREE.PointLight(0x7be8d3, 0.55, 7);
      lamp.position.set(zb.cx, LAY.DECK2.ceil - 0.2, zb.cz);
      g.add(lamp);
    }
    // Stores forward on deck 2: crates.
    for (var q = 0; q < 6; q++) {
      var crate = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 0.9), mat(0x6b7a56, { roughness: 0.8 }));
      crate.position.set(LAY.stores.x0 + 0.8 + (q % 3) * 1.6, LAY.DECK2.floor + 0.45, q < 3 ? -1.8 : 1.8);
      g.add(crate);
    }
    return g;
  }

  function buildStars() {
    var N = 1800, pos = new Float32Array(N * 3);
    for (var i = 0; i < N; i++) {
      var th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1), r = 80 + Math.random() * 50;
      pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
      pos[i * 3 + 1] = r * Math.cos(ph) * 0.7;
      pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
    }
    var geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    return new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xcfe8f0, size: 0.22, sizeAttenuation: true, transparent: true, opacity: 0.85 }));
  }

  function init(target) {
    if (ready || !target || !root.MedBox || !root.MedBox.layout) return false;
    LAY = root.MedBox.layout;
    canvas = target;
    try {
      renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
    } catch (e) {
      return false;
    }
    renderer.setClearColor(0x03080b, 1);
    renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, 1.25));   // the processor also runs the model
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.localClippingEnabled = true;
    clipNear = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0.9);   // keeps z <= 0.9: the far side stays
    clipDeck = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1000);  // keeps y <= c: lowered onto deck 1 for a lower-deck view
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(50, 1, 0.1, 400);
    scene.add(new THREE.AmbientLight(0x8fb4c2, 0.32));
    var sun = new THREE.DirectionalLight(0xfff1d6, 1.25);
    sun.position.set(18, 14, 16);
    scene.add(sun);
    var fill = new THREE.DirectionalLight(0x6fa7c0, 0.4);
    fill.position.set(-14, -8, -12);
    scene.add(fill);
    // A failure here must not take the overlay down with it: the ship page
    // works without the hull, so the hull is allowed to fail alone.
    try {
      scene.add(buildShell());
      scene.add(buildInterior());
      scene.add(buildStars());
    } catch (e) {
      if (root.console) console.error("hull: " + e.message);
      return false;
    }
    ready = true;
    t0 = performance.now();
    return true;
  }

  /* render({eye, target, fov, aspect, heat, breath, sealed, view, viewZone, glowZone, zoneNames}) */
  function render(f) {
    if (!ready) return;
    var w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    if (w !== lastW || h !== lastH) { renderer.setSize(w, h, false); lastW = w; lastH = h; }
    camera.fov = f.fov * 180 / Math.PI;
    camera.aspect = f.aspect;
    camera.updateProjectionMatrix();
    camera.position.set(f.eye[0], f.eye[1], f.eye[2]);
    camera.lookAt(f.target[0], f.target[1], f.target[2]);
    // The cut follows the camera: whichever flank faces it is opened.
    if (f.eye[2] >= 0) clipNear.set(new THREE.Vector3(0, 0, -1), 0.9); else clipNear.set(new THREE.Vector3(0, 0, 1), 0.9);
    // A lower-deck room in view: the deck above it comes off, like a doll's house.
    // Eased, so the deck lifts off as the camera arrives instead of vanishing
    // while it is still far away; 8 is above the mast, nothing is cut.
    var wantDeck = (f.view === "zone" || f.view === "medbay") ? LAY.DECK1.floor + 0.05 : 8.0;
    clipDeck.constant += (wantDeck - clipDeck.constant) * 0.16;
    var t = (performance.now() - t0) / 1000;
    for (var z = 0; z < zoneTiles.length; z++) {
      var m = zoneTiles[z].material, name = f.zoneNames && f.zoneNames[z];
      var sealed = f.sealed && f.sealed[z], glow = f.glowZone && name === f.glowZone, inView = f.view === "zone" && f.viewZone === z;
      if (glow) { m.emissive.setHex(0xf0c459); m.emissiveIntensity = 0.5 + 0.35 * Math.sin(t * 4); }
      else if (sealed) { m.emissive.setHex(0xff9a3c); m.emissiveIntensity = 0.55; }
      else if (inView) { m.emissive.setHex(0x7be8d3); m.emissiveIntensity = 0.45; }
      else { m.emissive.setHex(0x2fb7a6); m.emissiveIntensity = 0.15; }
    }
    for (var i = 0; i < radiators.length; i++) radiators[i].material.emissiveIntensity = 0.2 + (f.heat || 0) * 0.9;
    if (engineGlow) engineGlow.material.opacity = 0.12 + 0.05 * (f.breath || 0);
    if (engineLight) engineLight.intensity = 1.1 + 0.3 * (f.breath || 0);
    if (windows) windows.material.emissiveIntensity = 1.15 + 0.2 * (f.breath || 0);
    renderer.render(scene, camera);
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.hull = { init: init, render: render, ready: function () { return ready; } };
})(window);
