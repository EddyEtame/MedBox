/* The hull: a spaceship you can see.
 *
 * Eddy, 24 Sep: "the space ship view should look like an actual space ship
 * view". This layer draws the ship itself with three.js (vendored, offline)
 * on a canvas under the technical overlay that ship.js keeps drawing: the
 * habitation ring as a real torus with windows, six spokes, the despun
 * medbay core, a spine with a command module forward and three engines
 * aft, solar arrays and radiators. Same units and axes as ship.js: the
 * ring lies in the y = 0 plane at radius 6 and spins around y; the camera
 * is the one ship.js computes, handed over every frame, so the crew glow
 * and the berths stay exactly where the hull is. */
(function (root) {
  "use strict";
  if (!root.THREE) return;
  var THREE = root.THREE;

  var RING_R = 6.0, TUBE = 0.95, HUB_R = 1.5, ZONES = 3;
  var renderer = null, scene = null, camera = null, canvas = null;
  var spinning = null, zoneBands = [], windows = null, radiators = [], engineGlow = null, engineLight = null;
  var ready = false, lastW = 0, lastH = 0, t0 = 0;

  function mat(color, opts) {
    var m = new THREE.MeshStandardMaterial({ color: color, metalness: 0.55, roughness: 0.45 });
    if (opts) Object.keys(opts).forEach(function (k) { m[k] = opts[k]; });
    return m;
  }

  function buildRing() {
    var g = new THREE.Group();
    // The torus: the crew live in here. Slightly translucent so the
    // technical overlay (berths, bulkheads, the crew glow) reads through.
    var hull = new THREE.Mesh(new THREE.TorusGeometry(RING_R, TUBE, 22, 180),
      mat(0x1c2a33, { transparent: true, opacity: 0.5, roughness: 0.55 }));
    hull.rotation.x = Math.PI / 2;
    g.add(hull);
    // Two outer rails, the structure ship.js draws as lines, made solid.
    [0.55, -0.55].forEach(function (y) {
      var rail = new THREE.Mesh(new THREE.TorusGeometry(RING_R + TUBE * 0.62, 0.07, 8, 180), mat(0x5d7c88, { metalness: 0.8, roughness: 0.3 }));
      rail.rotation.x = Math.PI / 2;
      rail.position.y = y;
      g.add(rail);
    });
    // Windows: a belt of small lit panes on the outer wall.
    var paneGeo = new THREE.BoxGeometry(0.13, 0.07, 0.04);
    var paneMat = new THREE.MeshStandardMaterial({ color: 0x0b1a20, emissive: 0x9ff0e0, emissiveIntensity: 1.3, roughness: 0.2 });
    windows = new THREE.InstancedMesh(paneGeo, paneMat, 160);
    var dummy = new THREE.Object3D();
    for (var i = 0; i < 160; i++) {
      var a = i / 160 * Math.PI * 2, r = RING_R + TUBE * 0.98;
      dummy.position.set(Math.cos(a) * r, (i % 2 ? 0.18 : -0.18), Math.sin(a) * r);
      dummy.rotation.set(0, -a, 0);
      dummy.updateMatrix();
      windows.setMatrixAt(i, dummy.matrix);
    }
    g.add(windows);
    // Zone bands: three thin arcs on the outer wall, one per isolation zone.
    for (var z = 0; z < ZONES; z++) {
      var span = Math.PI * 2 / ZONES;
      var band = new THREE.Mesh(new THREE.TorusGeometry(RING_R, TUBE + 0.02, 18, 70, span),
        new THREE.MeshStandardMaterial({ color: 0x0e2a30, emissive: 0x2fb7a6, emissiveIntensity: 0.18, transparent: true, opacity: 0.22, roughness: 0.6 }));
      band.rotation.x = Math.PI / 2;
      band.rotation.z = -z * span;
      zoneBands.push(band);
      g.add(band);
    }
    // Six spokes from the ring to the core bearing.
    for (var s = 0; s < 6; s++) {
      var b = s / 6 * Math.PI * 2, len = RING_R - HUB_R - 0.2;
      var spoke = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.11, len, 10), mat(0x4a5f6a, { metalness: 0.75, roughness: 0.35 }));
      spoke.position.set(Math.cos(b) * (HUB_R + len / 2), 0, Math.sin(b) * (HUB_R + len / 2));
      spoke.rotation.z = Math.PI / 2;
      spoke.rotation.y = -b;
      g.add(spoke);
    }
    return g;
  }

  function buildCore() {
    var g = new THREE.Group();
    // The despun medbay core with its docking rim.
    var core = new THREE.Mesh(new THREE.CylinderGeometry(HUB_R, HUB_R, 1.7, 40), mat(0x33474f, { roughness: 0.4 }));
    g.add(core);
    var rim = new THREE.Mesh(new THREE.TorusGeometry(HUB_R + 0.42, 0.14, 10, 80), mat(0x7be8d3, { emissive: 0x1e6b62, emissiveIntensity: 0.6, metalness: 0.6 }));
    rim.rotation.x = Math.PI / 2;
    g.add(rim);
    var lamp = new THREE.PointLight(0x7be8d3, 0.7, 14);
    g.add(lamp);
    // The spine: a truss along the ship's axis.
    var spine = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 17, 14), mat(0x2b3940, { metalness: 0.7, roughness: 0.4 }));
    spine.position.y = -0.8;
    g.add(spine);
    for (var r = -8; r <= 6; r += 1.4) {
      var rib = new THREE.Mesh(new THREE.TorusGeometry(0.46, 0.05, 6, 24), mat(0x5d7c88, { metalness: 0.8, roughness: 0.3 }));
      rib.rotation.x = Math.PI / 2;
      rib.position.y = r;
      g.add(rib);
    }
    // Forward: the command module, a capsule with lit ports and a dish.
    var cmd = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.95, 1.7, 28), mat(0x3a4d56, { roughness: 0.35 }));
    cmd.position.y = 7.3;
    g.add(cmd);
    var nose = new THREE.Mesh(new THREE.ConeGeometry(0.75, 1.2, 28), mat(0x46606a, { roughness: 0.3, metalness: 0.7 }));
    nose.position.y = 8.75;
    g.add(nose);
    var ports = new THREE.Mesh(new THREE.TorusGeometry(0.86, 0.06, 6, 40), new THREE.MeshStandardMaterial({ color: 0x0b1a20, emissive: 0xbfeee6, emissiveIntensity: 1.2 }));
    ports.rotation.x = Math.PI / 2;
    ports.position.y = 7.6;
    g.add(ports);
    var dish = new THREE.Mesh(new THREE.SphereGeometry(0.7, 24, 12, 0, Math.PI * 2, 0, Math.PI / 3), mat(0xc9d6dc, { metalness: 0.3, roughness: 0.6, side: THREE.DoubleSide }));
    dish.position.set(1.3, 6.6, 0);
    dish.rotation.z = -Math.PI / 2.4;
    g.add(dish);
    // Aft: three engines around the spine, lit from inside.
    var glowMat = new THREE.MeshStandardMaterial({ color: 0x08131a, emissive: 0x9fd6ff, emissiveIntensity: 2.2 });
    for (var e = 0; e < 3; e++) {
      var ea = e / 3 * Math.PI * 2 + Math.PI / 6, ex = Math.cos(ea) * 0.95, ez = Math.sin(ea) * 0.95;
      var bell = new THREE.Mesh(new THREE.ConeGeometry(0.55, 1.6, 26, 1, true), mat(0x3a4a52, { metalness: 0.8, roughness: 0.3, side: THREE.DoubleSide }));
      bell.position.set(ex, -9.6, ez);
      bell.rotation.x = Math.PI;
      g.add(bell);
      var disc = new THREE.Mesh(new THREE.CircleGeometry(0.42, 24), glowMat);
      disc.position.set(ex, -10.35, ez);
      disc.rotation.x = Math.PI / 2;
      g.add(disc);
    }
    engineGlow = new THREE.Mesh(new THREE.ConeGeometry(1.1, 5.5, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: 0x6fc3ff, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }));
    engineGlow.position.y = -13.2;
    g.add(engineGlow);
    engineLight = new THREE.PointLight(0x8fd0ff, 1.1, 16);
    engineLight.position.y = -10.4;
    g.add(engineLight);
    // Solar arrays forward of the ring, radiators aft.
    var panelMat = new THREE.MeshStandardMaterial({ color: 0x0f1b46, emissive: 0x0a1a44, emissiveIntensity: 0.3, metalness: 0.4, roughness: 0.4, side: THREE.DoubleSide });
    [1, -1].forEach(function (sx) {
      var truss = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 2.4, 8), mat(0x5d7c88));
      truss.rotation.z = Math.PI / 2;
      truss.position.set(sx * 1.5, 5.6, 0);
      g.add(truss);
      var panel = new THREE.Mesh(new THREE.BoxGeometry(5.2, 0.04, 1.9), panelMat);
      panel.position.set(sx * 5.3, 5.6, 0);
      g.add(panel);
      for (var k = 1; k < 5; k++) {
        var line = new THREE.Mesh(new THREE.BoxGeometry(0.025, 0.05, 1.9), mat(0x8fa8b2, { metalness: 0.9 }));
        line.position.set(sx * (2.7 + k * 1.04), 5.6, 0);
        g.add(line);
      }
      var radMat = new THREE.MeshStandardMaterial({ color: 0x3b3238, emissive: 0xff7a3a, emissiveIntensity: 0.18, roughness: 0.7, side: THREE.DoubleSide });
      var rad = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.6, 3.6), radMat);
      rad.position.set(0, -7.6, sx * 2.4);
      g.add(rad);
      radiators.push(rad);
    });
    return g;
  }

  function buildStars() {
    var N = 1600, pos = new Float32Array(N * 3);
    for (var i = 0; i < N; i++) {
      var th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1), r = 60 + Math.random() * 40;
      pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
      pos[i * 3 + 1] = r * Math.cos(ph) * 0.7;
      pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
    }
    var geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    return new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xcfe8f0, size: 0.16, sizeAttenuation: true, transparent: true, opacity: 0.85 }));
  }

  function init(target) {
    if (ready || !target) return false;
    canvas = target;
    try {
      renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
    } catch (e) {
      return false;
    }
    renderer.setClearColor(0x03080b, 1);
    renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(50, 1, 0.1, 260);
    scene.add(new THREE.AmbientLight(0x8fb4c2, 0.28));
    var sun = new THREE.DirectionalLight(0xfff1d6, 1.35);
    sun.position.set(14, 10, 8);
    scene.add(sun);
    var fill = new THREE.DirectionalLight(0x6fa7c0, 0.35);
    fill.position.set(-10, -6, -8);
    scene.add(fill);
    spinning = buildRing();
    scene.add(spinning);
    scene.add(buildCore());
    scene.add(buildStars());
    ready = true;
    t0 = performance.now();
    return true;
  }

  /* render({eye, target, fov, aspect, spin, heat, breath, sealed, view, viewZone, glowZone, zoneNames}) */
  function render(f) {
    if (!ready) return;
    var w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    if (w !== lastW || h !== lastH) { renderer.setSize(w, h, false); lastW = w; lastH = h; }
    camera.fov = f.fov * 180 / Math.PI;
    camera.aspect = f.aspect;
    camera.updateProjectionMatrix();
    camera.position.set(f.eye[0], f.eye[1], f.eye[2]);
    camera.lookAt(f.target[0], f.target[1], f.target[2]);
    spinning.rotation.y = -f.spin;
    var t = (performance.now() - t0) / 1000;
    // The zone in view is lit; a sealed zone is amber; the card's zone pulses.
    for (var z = 0; z < ZONES; z++) {
      var band = zoneBands[z], m = band.material;
      var name = f.zoneNames && f.zoneNames[z];
      var sealed = f.sealed && f.sealed[z];
      var glow = f.glowZone && name === f.glowZone;
      var inView = f.view === "zone" && f.viewZone === z;
      if (glow) { m.emissive.setHex(0xf0c459); m.emissiveIntensity = 0.7 + 0.5 * Math.sin(t * 4); m.opacity = 0.42; }
      else if (sealed) { m.emissive.setHex(0xff9a3c); m.emissiveIntensity = 0.75; m.opacity = 0.4; }
      else if (inView) { m.emissive.setHex(0x7be8d3); m.emissiveIntensity = 0.55; m.opacity = 0.3; }
      else { m.emissive.setHex(0x2fb7a6); m.emissiveIntensity = 0.18; m.opacity = 0.22; }
    }
    // Radiators run hotter with crew fever; engines breathe with the ship.
    for (var i = 0; i < radiators.length; i++) radiators[i].material.emissiveIntensity = 0.18 + (f.heat || 0) * 0.9;
    if (engineGlow) engineGlow.material.opacity = 0.14 + 0.05 * (f.breath || 0);
    if (engineLight) engineLight.intensity = 1.0 + 0.25 * (f.breath || 0);
    if (windows) windows.material.emissiveIntensity = 1.4 + 0.25 * (f.breath || 0);
    renderer.render(scene, camera);
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.hull = { init: init, render: render, ready: function () { return ready; } };
})(window);
