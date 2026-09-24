/* The hull: a generation ship you can see into.
 *
 * Eddy, 24 Sep: "something that actually looks like a spaceship and feels
 * like people can stay in it for a long time. Solid." Then, at one in the
 * morning: "ameliorate the 3D to baffled bar, right now it's poor." So this
 * is no longer grey blocks under a flat light. ESA Horizon is a long hull
 * with two decks: the bridge forward, forty cabins with their windows
 * amidships, the mess aft on the upper deck; the infirmary and the three
 * isolation rooms on the lower deck; engines and radiators at the stern,
 * greenhouse domes on the back, pink with grow light. The side facing the
 * camera is cut away, so the decks, the rooms and the beds inside are
 * visible, the way a doll's house shows its rooms. A warm sun from the
 * front right casts shadows, a cool rim light from behind draws the
 * silhouette, panel lines and grime are painted on the skin, engines and
 * lamps glow, a planet and a nebula give the void a depth, running lights
 * blink, stars drift. Everything is placed from layout.js, the same plan
 * ship.js draws its overlay from. three.js is vendored; offline.
 *
 * Cost, measured on the defence laptop (Iris Xe, 1366x768, pixel ratio
 * 1.25): the whole thing renders while the language model runs on the CPU,
 * so textures are small canvases made once, the shadow map is 1024 and
 * there are eight point lights, no post-processing; the glow is sprites. */
(function (root) {
  "use strict";
  if (!root.THREE) return;
  var THREE = root.THREE;

  var renderer = null, scene = null, camera = null, canvas = null;
  var ready = false, lastW = 0, lastH = 0, t0 = 0;
  var clipNear = null, clipDeck = null, shellMats = [], zoneTiles = [], zoneDoors = [], windows = null;
  var engineGlow = null, engineLight = null, engineDiscs = [], engineSprites = [], radiators = [];
  var navLamps = [], growLights = [], growSprites = [], stars = [], planetGroup = null, cutStrips = [];
  var LAY = null, panelTex = null, plateTex = null, glowTex = null, dish = null, padRing = null;

  /* ---------- painted surfaces: small canvases, made once ---------- */

  function canvasTexture(size, paint) {
    var c = document.createElement("canvas");
    c.width = size; c.height = size;
    var ctx = c.getContext("2d");
    paint(ctx, size);
    var t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 4;
    // Painted colours are sRGB. Left as linear, the renderer lifts every
    // dark: the night sky came out a washed grey-blue (seen 25 Sep, 01:20).
    t.encoding = THREE.sRGBEncoding;
    return t;
  }

  // Hull plating: panels of uneven size, a dark seam around each, a few
  // rivets, streaks of grime that run aft. Doubles as the bump map.
  function paintPanels(ctx, S) {
    ctx.fillStyle = "#b9c4cc";
    ctx.fillRect(0, 0, S, S);
    var y = 0, rnd = mulberry(7);
    while (y < S) {
      var h = 18 + Math.floor(rnd() * 30), x = 0;
      while (x < S) {
        var w = 24 + Math.floor(rnd() * 46);
        var shade = 168 + Math.floor(rnd() * 34), kind = rnd();
        if (kind < 0.05) ctx.fillStyle = "#c9803a";                                  // an accent panel, ESA orange
        else if (kind < 0.14) ctx.fillStyle = "rgb(" + (shade - 70) + "," + (shade - 60) + "," + (shade - 52) + ")";  // a dark panel
        else ctx.fillStyle = "rgb(" + shade + "," + (shade + 8) + "," + (shade + 14) + ")";
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = "rgba(20,30,36,0.55)";
        ctx.lineWidth = 1.2;
        ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
        if (rnd() < 0.5) {
          ctx.fillStyle = "rgba(40,50,58,0.5)";
          ctx.fillRect(x + 3, y + 3, 2, 2);
          ctx.fillRect(x + w - 6, y + h - 6, 2, 2);
        }
        x += w;
      }
      y += h;
    }
    // grime streaks, thin and long
    for (var i = 0; i < 26; i++) {
      var gx = rnd() * S, gy = rnd() * S, gl = 30 + rnd() * 90;
      var grad = ctx.createLinearGradient(gx, gy, gx - gl, gy);
      grad.addColorStop(0, "rgba(30,38,44,0.35)");
      grad.addColorStop(1, "rgba(30,38,44,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(gx - gl, gy, gl, 1 + rnd() * 2);
    }
  }

  // Deck plates: dark metal grating with a fine grid and worn tread lines.
  function paintPlates(ctx, S) {
    ctx.fillStyle = "#3a4650";
    ctx.fillRect(0, 0, S, S);
    ctx.strokeStyle = "rgba(15,22,27,0.8)";
    ctx.lineWidth = 2;
    for (var i = 0; i <= S; i += 32) {
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, S); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(S, i); ctx.stroke();
    }
    ctx.strokeStyle = "rgba(160,180,190,0.16)";
    ctx.lineWidth = 1;
    for (var j = 8; j < S; j += 32) {
      ctx.beginPath(); ctx.moveTo(0, j); ctx.lineTo(S, j); ctx.stroke();
    }
  }

  // A soft round glow for sprites.
  function paintGlow(ctx, S) {
    var g = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.25, "rgba(255,255,255,0.55)");
    g.addColorStop(0.6, "rgba(255,255,255,0.12)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, S, S);
  }

  // The nebula behind everything: deep indigo to teal, a few soft clouds.
  function paintNebula(ctx, S) {
    var g = ctx.createLinearGradient(0, 0, 0, S);
    g.addColorStop(0, "#02040a");
    g.addColorStop(0.45, "#050d1a");
    g.addColorStop(0.7, "#071923");
    g.addColorStop(1, "#010306");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, S, S);
    var rnd = mulberry(3);
    for (var i = 0; i < 14; i++) {
      var x = rnd() * S, y = S * (0.3 + rnd() * 0.5), r = S * (0.08 + rnd() * 0.18);
      var c = ctx.createRadialGradient(x, y, 0, x, y, r);
      var hue = rnd() < 0.5 ? "70,140,170" : "120,90,170";
      c.addColorStop(0, "rgba(" + hue + ",0.11)");
      c.addColorStop(1, "rgba(" + hue + ",0)");
      ctx.fillStyle = c;
      ctx.fillRect(x - r, y - r, r * 2, r * 2);
    }
  }

  // A banded planet, ochre and dust, for scale and warmth.
  function paintPlanet(ctx, S) {
    var rnd = mulberry(11), y = 0;
    while (y < S) {
      var h = 6 + rnd() * 22;
      var t = rnd();
      var r = Math.floor(110 + t * 70), gch = Math.floor(70 + t * 45), b = Math.floor(40 + t * 28);
      ctx.fillStyle = "rgb(" + r + "," + gch + "," + b + ")";
      ctx.fillRect(0, y, S, h + 1);
      y += h;
    }
    ctx.fillStyle = "rgba(255,240,220,0.08)";
    for (var i = 0; i < 40; i++) ctx.fillRect(rnd() * S, rnd() * S, rnd() * 60, 2);
  }

  // The name on the flank, the registry, a roundel: paint on the skin.
  function paintName(ctx, S) {
    ctx.clearRect(0, 0, S, S);
    ctx.fillStyle = "#e9f2f6";
    ctx.font = "bold 92px 'Segoe UI', Arial, sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillText("ESA HORIZON", 22, S * 0.36);
    ctx.fillStyle = "#7be8d3";
    ctx.fillRect(22, S * 0.55, 470, 8);
    ctx.fillStyle = "#b8c7cf";
    ctx.font = "600 38px 'Consolas', 'Courier New', monospace";
    ctx.fillText("GS-40 · 2080 · VAISSEAU-MONDE", 24, S * 0.74);
    ctx.strokeStyle = "#7be8d3";
    ctx.lineWidth = 6;
    ctx.beginPath(); ctx.arc(S - 70, S * 0.36, 34, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(S - 70, S * 0.36, 12, 0, Math.PI * 2); ctx.fillStyle = "#7be8d3"; ctx.fill();
  }
  // Hazard chevrons near the engines.
  function paintChevrons(ctx, S) {
    ctx.clearRect(0, 0, S, S);
    ctx.fillStyle = "#1a1c1e";
    ctx.fillRect(0, S * 0.3, S, S * 0.4);
    ctx.fillStyle = "#f0c040";
    for (var x = -S; x < S * 2; x += 56) {
      ctx.beginPath();
      ctx.moveTo(x, S * 0.7); ctx.lineTo(x + 28, S * 0.7); ctx.lineTo(x + 28 + S * 0.4, S * 0.3); ctx.lineTo(x + S * 0.4, S * 0.3);
      ctx.closePath(); ctx.fill();
    }
  }
  function decal(tex, w, h, x, y, side) {
    var m = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 });
    m.clippingPlanes = [clipNear];
    shellMats.push(m);
    var plane = new THREE.Mesh(new THREE.PlaneGeometry(w, h), m);
    plane.position.set(x, y, side * (LAY.W / 2 + 0.025));
    plane.rotation.y = side > 0 ? 0 : Math.PI;
    return plane;
  }

  function mulberry(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ---------- materials ---------- */

  function mat(color, opts) {
    var m = new THREE.MeshStandardMaterial({ color: color, metalness: 0.5, roughness: 0.55 });
    if (opts) Object.keys(opts).forEach(function (k) { m[k] = opts[k]; });
    return m;
  }
  function plated(color, repeatX, repeatY, opts) {
    // Hull skin with the painted panels and their relief.
    var t = panelTex.clone(); t.needsUpdate = true; t.repeat.set(repeatX, repeatY);
    var m = mat(color, { map: t, bumpMap: t, bumpScale: 0.012, metalness: 0.6, roughness: 0.5 });
    if (opts) Object.keys(opts).forEach(function (k) { m[k] = opts[k]; });
    return m;
  }
  function shell(m) {
    // Hull skin: clipped on the camera side so the interior shows.
    m.clippingPlanes = [clipNear, clipDeck];
    m.clipShadows = true;
    shellMats.push(m);
    return m;
  }
  function upper(m) {
    // Deck 1 furniture: removed with the roof when a lower-deck room is in view.
    m.clippingPlanes = [clipDeck];
    m.clipShadows = true;
    return m;
  }
  function glowing(color, intensity) {
    return new THREE.MeshStandardMaterial({ color: 0x0a1418, emissive: color, emissiveIntensity: intensity, roughness: 0.3, metalness: 0.1 });
  }
  function sprite(color, size, opacity) {
    var s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: color, transparent: true, opacity: opacity, blending: THREE.AdditiveBlending, depthWrite: false }));
    s.scale.set(size, size, 1);
    return s;
  }
  function lit(mesh, cast, receive) {
    mesh.castShadow = !!cast;
    mesh.receiveShadow = !!receive;
    return mesh;
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

  /* ---------- the ship ---------- */

  function buildShell() {
    var g = new THREE.Group();
    var L = LAY.L, W = LAY.W, H = LAY.H;
    var d = new THREE.Object3D();
    // The main hull: a rounded section extruded along x, thin walled so the
    // cut shows a wall, not a solid block. Painted plating outside, a
    // darker lining inside (DoubleSide shows the inner face in the cut).
    var section = roundedRect(W, H, 1.3);
    var hole = roundedRect(W - 0.36, H - 0.36, 1.1);
    section.holes.push(hole);
    var hullGeo = new THREE.ExtrudeGeometry(section, { depth: L, bevelEnabled: false, curveSegments: 20 });
    hullGeo.rotateY(Math.PI / 2);
    hullGeo.translate(-L / 2, 0, 0);
    var hull = lit(new THREE.Mesh(hullGeo, shell(plated(0xaab6bf, 6, 2, { side: THREE.DoubleSide }))), true, true);
    g.add(hull);
    // The cut face: the hull's wall, seen edge-on where the flank is opened,
    // so the cut reads as a thick skin sliced, not a hollow shell.
    [H / 2 - 0.1, -H / 2 + 0.1].forEach(function (y) {
      var strip = new THREE.Mesh(new THREE.BoxGeometry(L, 0.2, 0.05), mat(0xdfe7ec, { metalness: 0.35, roughness: 0.5 }));
      strip.position.set(0, y, 0.9);
      g.add(strip);
      cutStrips.push(strip);
    });
    // Deck plates between the two decks and the roof, seen in the cut:
    // grating, worn.
    var plate1 = plateTex.clone(); plate1.needsUpdate = true; plate1.repeat.set(14, 4);
    var plateMat = mat(0x8a98a2, { map: plate1, bumpMap: plate1, bumpScale: 0.01, metalness: 0.65, roughness: 0.55 });
    [LAY.DECK1.floor - 0.06, LAY.DECK2.floor - 0.06].forEach(function (y, idx) {
      var plate = lit(new THREE.Mesh(new THREE.BoxGeometry(L - 0.4, 0.12, W - 0.4), idx === 0 ? upper(plateMat.clone()) : plateMat), true, true);
      plate.position.set(0, y, 0);
      g.add(plate);
    });
    var roof = lit(new THREE.Mesh(new THREE.BoxGeometry(L - 0.4, 0.1, W - 0.4), shell(plated(0x93a1aa, 8, 2))), true, true);
    roof.position.set(0, H / 2 - 0.12, 0);
    g.add(roof);
    // A darker band along the flank with the ship's name colour, and ribs.
    var band = lit(new THREE.Mesh(new THREE.BoxGeometry(L - 2, 0.5, W + 0.06), shell(mat(0x3b4a55, { metalness: 0.75, roughness: 0.35 }))), true, true);
    band.position.set(0, -0.05, 0);
    g.add(band);
    var stripe = new THREE.Mesh(new THREE.BoxGeometry(L - 4, 0.12, W + 0.08), shell(glowing(0x7be8d3, 0.9)));
    stripe.position.set(-1, 0.55, 0);
    g.add(stripe);
    var seamGeo = new THREE.BoxGeometry(0.12, H - 0.5, W + 0.1);
    var seams = new THREE.InstancedMesh(seamGeo, shell(mat(0x27323a, { roughness: 0.8, metalness: 0.4 })), 12);
    for (var i = 0; i < 12; i++) { d.position.set(-13 + i * 2.35, 0, 0); d.rotation.set(0, 0, 0); d.updateMatrix(); seams.setMatrixAt(i, d.matrix); }
    seams.castShadow = true;
    g.add(seams);
    // The bow: a tapered nose with the bridge's forward windows.
    var nose = lit(new THREE.Mesh(new THREE.SphereGeometry(1, 32, 20, 0, Math.PI * 2, 0, Math.PI / 2), shell(plated(0xb4bfc7, 3, 2))), true, true);
    nose.scale.set(LAY.BOW, H / 2, W / 2);
    nose.rotation.z = -Math.PI / 2;
    nose.position.set(L / 2, 0, 0);
    g.add(nose);
    var visor = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.22, 2.6), glowing(0xbfeee6, 1.6));
    visor.position.set(L / 2 + 2.6, 0.95, 0);
    visor.rotation.z = -0.35;
    g.add(visor);
    // The stern: an engineering block, three engines, their glow and light.
    var stern = lit(new THREE.Mesh(new THREE.BoxGeometry(3.2, H + 0.9, W + 1.2), shell(plated(0x8b98a1, 2, 3))), true, true);
    stern.position.set(-L / 2 - 1.2, 0, 0);
    g.add(stern);
    var bellMat = mat(0x2d353b, { metalness: 0.9, roughness: 0.32, side: THREE.DoubleSide });
    var bellRing = mat(0x141a1e, { metalness: 0.95, roughness: 0.25 });
    [[0, 1.3], [-2.4, -0.9], [2.4, -0.9]].forEach(function (p) {
      var bell = lit(new THREE.Mesh(new THREE.ConeGeometry(1.05, 2.6, 32, 1, true), bellMat), true, false);
      bell.rotation.z = -Math.PI / 2;   // the mouth aft, the throat at the stern block
      bell.position.set(-L / 2 - 4.0, p[1], p[0]);
      g.add(bell);
      var throat = new THREE.Mesh(new THREE.ConeGeometry(0.8, 2.2, 24, 1, true),
        new THREE.MeshBasicMaterial({ color: 0x4fb0ff, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }));
      throat.rotation.z = -Math.PI / 2;
      throat.position.set(-L / 2 - 4.1, p[1], p[0]);
      g.add(throat);
      [0.7, 1.4, 2.1].forEach(function (dd) {
        var rr = 1.05 * dd / 2.6;
        var ring = new THREE.Mesh(new THREE.TorusGeometry(rr + 0.03, 0.045, 6, 32), bellRing);
        ring.rotation.y = Math.PI / 2;
        ring.position.set(-L / 2 - 2.7 - dd, p[1], p[0]);
        g.add(ring);
      });
      var lip = new THREE.Mesh(new THREE.TorusGeometry(1.05, 0.09, 8, 40), bellRing);
      lip.rotation.y = Math.PI / 2;
      lip.position.set(-L / 2 - 5.3, p[1], p[0]);
      g.add(lip);
      var disc = new THREE.Mesh(new THREE.CircleGeometry(0.88, 32), glowing(0x9fd6ff, 3.2));
      disc.rotation.y = -Math.PI / 2;
      disc.position.set(-L / 2 - 5.2, p[1], p[0]);
      g.add(disc);
      engineDiscs.push(disc);
      var halo = sprite(0x8fd0ff, 3.4, 0.55);
      halo.position.set(-L / 2 - 5.6, p[1], p[0]);
      g.add(halo);
      engineSprites.push(halo);
    });
    engineGlow = new THREE.Mesh(new THREE.ConeGeometry(2.8, 11, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: 0x6fc3ff, transparent: true, opacity: 0.12, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }));
    engineGlow.rotation.z = Math.PI / 2;
    engineGlow.position.set(-L / 2 - 10.5, 0, 0);
    g.add(engineGlow);
    var plume = sprite(0x6fc3ff, 9, 0.35);
    plume.position.set(-L / 2 - 7.5, 0, 0);
    g.add(plume);
    engineSprites.push(plume);
    engineLight = new THREE.PointLight(0x8fd0ff, 1.6, 26, 2);
    engineLight.position.set(-L / 2 - 5.5, 0, 0);
    g.add(engineLight);
    // Radiators: four angled fins at the stern, warmer with crew fever, on
    // struts, with the coolant line drawn on them.
    var radMat = new THREE.MeshStandardMaterial({ color: 0x140d0e, emissive: 0xff5a1e, emissiveIntensity: 0.55, roughness: 0.75, metalness: 0.4, side: THREE.DoubleSide });
    [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(function (s) {
      var fin = lit(new THREE.Mesh(new THREE.BoxGeometry(2.8, 2.4, 0.08), radMat), true, false);
      fin.position.set(-L / 2 - 1.2, s[0] * 3.3, s[1] * 3.3);
      fin.rotation.x = s[0] * s[1] * Math.PI / 4;
      g.add(fin);
      radiators.push(fin);
      var strut = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 2.2, 8), bellRing);
      strut.position.set(-L / 2 - 1.2, s[0] * 2.1, s[1] * 2.1);
      strut.rotation.x = -s[0] * s[1] * Math.PI / 4;
      g.add(strut);
    });
    // Nacelles along the flanks, on pylons, banded.
    [1, -1].forEach(function (sz) {
      var nacMat = plated(0x9aa8b1, 4, 1);
      var nac = lit(new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 10, 24), nacMat), true, true);
      nac.rotation.z = Math.PI / 2;
      nac.position.set(-4.5, -2.6, sz * (W / 2 + 0.6));
      g.add(nac);
      [5, -5].forEach(function (px) {
        var cap = lit(new THREE.Mesh(new THREE.SphereGeometry(0.8, 20, 14), mat(0x5b6a74, { metalness: 0.7, roughness: 0.4 })), true, false);
        cap.position.set(-4.5 + px, -2.6, sz * (W / 2 + 0.6));
        g.add(cap);
      });
      [-5, 0].forEach(function (px) {
        var pylon = lit(new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.2, 0.5), mat(0x3b4a55, { metalness: 0.7 })), true, true);
        pylon.position.set(-4.5 + px, -2.0, sz * (W / 2 + 0.1));
        g.add(pylon);
      });
      var ringMat = mat(0x27323a, { metalness: 0.85, roughness: 0.3 });
      [-3, -1, 1, 3].forEach(function (px) {
        var ring = new THREE.Mesh(new THREE.TorusGeometry(0.84, 0.05, 6, 30), ringMat);
        ring.rotation.y = Math.PI / 2;
        ring.position.set(-4.5 + px, -2.6, sz * (W / 2 + 0.6));
        g.add(ring);
      });
    });
    // Greenhouse domes on the back: food and air for the long voyage. Glass
    // over foliage, a grow lamp inside: the pink an orbital farm has.
    var domeMat = new THREE.MeshStandardMaterial({ color: 0x7fd6c4, emissive: 0x2a8a72, emissiveIntensity: 0.18, transparent: true, opacity: 0.32, roughness: 0.08, metalness: 0.15, side: THREE.DoubleSide, depthWrite: false });
    var leafMat = mat(0x2f7a3c, { roughness: 0.9, metalness: 0.0 });
    var leafMat2 = mat(0x4fa34a, { roughness: 0.9, metalness: 0.0 });
    var rnd = mulberry(5);
    [-3.5, 1.5].forEach(function (px) {
      var dome = new THREE.Mesh(new THREE.SphereGeometry(1.5, 32, 18, 0, Math.PI * 2, 0, Math.PI / 2), domeMat);
      dome.position.set(px, H / 2 - 0.05, 0);
      g.add(dome);
      var ring = lit(new THREE.Mesh(new THREE.TorusGeometry(1.5, 0.09, 8, 48), mat(0x8fa8b2, { metalness: 0.85, roughness: 0.3 })), true, false);
      ring.rotation.x = Math.PI / 2;
      ring.position.set(px, H / 2, 0);
      g.add(ring);
      for (var k = 0; k < 14; k++) {
        var a = rnd() * Math.PI * 2, r = rnd() * 1.05;
        var leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(0.16 + rnd() * 0.22, 0), k % 2 ? leafMat : leafMat2);
        leaf.position.set(px + Math.cos(a) * r, H / 2 + 0.08 + rnd() * 0.5, Math.sin(a) * r);
        leaf.rotation.set(rnd() * 3, rnd() * 3, 0);
        g.add(leaf);
      }
      var grow = new THREE.PointLight(0xff4fd0, 2.4, 7, 2);
      grow.position.set(px, H / 2 + 1.0, 0);
      g.add(grow);
      growLights.push(grow);
      var pink = sprite(0xff6ad4, 4.2, 0.45);
      pink.position.set(px, H / 2 + 0.7, 0);
      g.add(pink);
      growSprites.push(pink);
    });
    // The bridge superstructure forward, with its window band.
    var sup = lit(new THREE.Mesh(new THREE.BoxGeometry(4.0, 1.1, 3.2), shell(plated(0xa9b5bd, 2, 1))), true, true);
    sup.position.set(11.4, H / 2 + 0.5, 0);
    g.add(sup);
    var supGlass = new THREE.Mesh(new THREE.BoxGeometry(4.02, 0.35, 3.22), glowing(0xbfeee6, 1.4));
    supGlass.position.set(11.4, H / 2 + 0.7, 0);
    g.add(supGlass);
    // Antennae and a dish.
    var mast = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 2.4, 8), mat(0xc4d0d6, { metalness: 0.8 }));
    mast.position.set(7.5, H / 2 + 1.2, 1.0);
    g.add(mast);
    dish = lit(new THREE.Mesh(new THREE.SphereGeometry(0.9, 24, 12, 0, Math.PI * 2, 0, Math.PI / 3), mat(0xd6e0e5, { metalness: 0.35, roughness: 0.55, side: THREE.DoubleSide })), true, false);
    dish.position.set(-8.5, H / 2 + 0.6, -1.4);
    dish.rotation.x = -Math.PI / 3;
    g.add(dish);
    // Markings on both flanks: the name forward, chevrons at the stern.
    var nameTex = canvasTexture(512, paintName); nameTex.wrapS = nameTex.wrapT = THREE.ClampToEdgeWrapping;
    var chevTex = canvasTexture(256, paintChevrons); chevTex.wrapS = chevTex.wrapT = THREE.ClampToEdgeWrapping;
    [1, -1].forEach(function (side) {
      g.add(decal(nameTex, 5.6, 1.4, 8.2, 0.95, side));
      g.add(decal(chevTex, 1.6, 0.5, -12.6, 0.95, side));
    });
    // A shuttle on its dorsal pad, a ring of light around it: something
    // the size of a person's world, next to the size of the ship's.
    var padMat = upper(mat(0x27323a, { metalness: 0.7, roughness: 0.5 }));
    var pad = lit(new THREE.Mesh(new THREE.BoxGeometry(2.8, 0.06, 1.8), padMat), false, true);
    pad.position.set(-6.8, H / 2 - 0.04, 1.7);
    g.add(pad);
    padRing = new THREE.Mesh(new THREE.TorusGeometry(1.15, 0.03, 6, 48), upper(glowing(0x7be8d3, 1.2)));
    padRing.rotation.x = Math.PI / 2;
    padRing.position.set(-6.8, H / 2 + 0.0, 1.7);
    g.add(padRing);
    var shuttleMat = upper(plated(0xd6dee3, 1, 1));
    var shuttle = lit(new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.42, 0.8), shuttleMat), true, true);
    shuttle.position.set(-6.8, H / 2 + 0.36, 1.7);
    g.add(shuttle);
    var shuttleNose = lit(new THREE.Mesh(new THREE.SphereGeometry(0.4, 16, 12), shuttleMat), true, false);
    shuttleNose.scale.set(1.3, 0.55, 1.0);
    shuttleNose.position.set(-5.95, H / 2 + 0.36, 1.7);
    g.add(shuttleNose);
    var cockpit = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.14, 0.5), upper(glowing(0xbfeee6, 1.4)));
    cockpit.position.set(-6.1, H / 2 + 0.5, 1.7);
    g.add(cockpit);
    [0.55, -0.55].forEach(function (dz) {
      var pod = lit(new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 1.3, 12), upper(mat(0x46535c, { metalness: 0.7, roughness: 0.4 }))), true, false);
      pod.rotation.z = Math.PI / 2;
      pod.position.set(-7.0, H / 2 + 0.28, 1.7 + dz);
      g.add(pod);
    });
    // Windows: a row per deck along both flanks, lit from inside, warm.
    var paneGeo = new THREE.BoxGeometry(0.3, 0.17, 0.06);
    var paneMat = glowing(0xfff1cf, 1.4);
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
    // Running lights: red to port, green to starboard, white strobes at the
    // mast and the stern. They blink, as they do on anything that flies.
    [[0xff3b3b, -1, 12.5, 0.6], [0x3bff6a, 1, 12.5, 0.6], [0xffffff, 0, 7.5, H / 2 + 2.45], [0xffffff, 0, -L / 2 - 2.9, H / 2 + 0.55]].forEach(function (p, idx) {
      var lamp = new THREE.Mesh(new THREE.SphereGeometry(0.13, 10, 8), glowing(p[0], 2.5));
      lamp.position.set(p[2], p[3], p[1] * (W / 2 + 0.1));
      g.add(lamp);
      var halo = sprite(p[0], 1.1, 0.7);
      halo.position.copy(lamp.position);
      g.add(halo);
      navLamps.push({ mesh: lamp, halo: halo, phase: idx * 0.9, strobe: p[0] === 0xffffff });
    });
    return g;
  }

  function buildInterior() {
    var g = new THREE.Group();
    var wallMat = mat(0xe3e9ec, { roughness: 0.85, metalness: 0.05 });
    var frameMat = mat(0x2b3940, { roughness: 0.6, metalness: 0.5 });
    var mattressMat = mat(0xeef2f4, { roughness: 0.9, metalness: 0.0 });
    var blanketMat = mat(0x4f8fb0, { roughness: 0.95, metalness: 0.0 });
    var pillowMat = mat(0xf6f8f9, { roughness: 0.9, metalness: 0.0 });
    var consoleMat = new THREE.MeshStandardMaterial({ color: 0x1d2a33, emissive: 0x37c9ff, emissiveIntensity: 0.9, roughness: 0.35, metalness: 0.3 });
    var stripMat = glowing(0xdff4ff, 1.3);
    var wallUp = upper(wallMat.clone());
    var frameUp = upper(frameMat.clone()), mattressUp = upper(mattressMat.clone()), blanketUp = upper(blanketMat.clone()), pillowUp = upper(pillowMat.clone());
    var consoleUp = upper(consoleMat.clone());
    var stripUp = upper(stripMat.clone());
    var tableUp = upper(mat(0x9fb0b8, { roughness: 0.6, metalness: 0.4 }));
    var chairUp = upper(mat(0x2b3940));

    // Every repeated piece is one instanced mesh, one draw call: sixty
    // beds and forty cabins as separate meshes cost the processor more
    // than the pixels did (measured 25 Sep: 16 ms a frame, mostly draw
    // calls, while the model also wants that processor).
    var beds = { up: [], down: [] };
    function bedAt(x, y, z, rotY, up) { (up ? beds.up : beds.down).push([x, y, z, rotY]); }
    function instancedBoxes(w, h, d, material, list, cast) {
      if (!list.length) return null;
      var im = new THREE.InstancedMesh(new THREE.BoxGeometry(w, h, d), material, list.length);
      var o = new THREE.Object3D();
      for (var i = 0; i < list.length; i++) {
        o.position.set(list[i][0], list[i][1], list[i][2]); o.rotation.set(0, list[i][3] || 0, 0); o.updateMatrix(); im.setMatrixAt(i, o.matrix);
      }
      im.castShadow = !!cast; im.receiveShadow = true;
      g.add(im);
      return im;
    }
    function buildBeds(list, frame, mattress, blanket, pillow) {
      instancedBoxes(0.66, 0.1, 1.16, frame, list.map(function (b) { return [b[0], b[1] + 0.05, b[2], b[3]]; }), true);
      instancedBoxes(0.6, 0.12, 1.1, mattress, list.map(function (b) { return [b[0], b[1] + 0.16, b[2], b[3]]; }), true);
      instancedBoxes(0.58, 0.05, 0.62, blanket, list.map(function (b) { return [b[0] + Math.cos(b[3]) * -0.2, b[1] + 0.245, b[2] + Math.sin(b[3]) * -0.2, b[3]]; }), false);
      instancedBoxes(0.46, 0.07, 0.26, pillow, list.map(function (b) { return [b[0] + Math.cos(b[3]) * 0.38, b[1] + 0.255, b[2] + Math.sin(b[3]) * 0.38, b[3]]; }), false);
    }

    // People. Not forty (the overlay carries every member as a light); a
    // watch on the bridge, a table in the mess, two on duty in the
    // infirmary, one in the stores: enough that the ship is inhabited.
    var suitA = mat(0x6f8797, { roughness: 0.7, metalness: 0.1 }), suitB = mat(0x3f6f8f, { roughness: 0.7, metalness: 0.1 });
    var medic = mat(0xe4ecf0, { roughness: 0.8, metalness: 0.0 }), skin = mat(0xd9b08c, { roughness: 0.8, metalness: 0.0 });
    var suitAUp = upper(suitA.clone()), suitBUp = upper(suitB.clone()), skinUp = upper(skin.clone());
    function person(x, floorY, z, suit, seated, up, facing) {
      var h = seated ? 0.42 : 0.62;
      var body = lit(new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.13, h, 10), suit), true, false);
      body.position.set(x, floorY + h / 2 + (seated ? 0.3 : 0), z);
      body.rotation.y = facing || 0;
      g.add(body);
      var head = new THREE.Mesh(new THREE.SphereGeometry(0.1, 12, 10), up ? skinUp : skin);
      head.position.set(x, floorY + h + (seated ? 0.3 : 0) + 0.1, z);
      g.add(head);
    }
    for (var w = -1; w <= 1; w++) person(LAY.bridge.x1 - 1.55 - Math.abs(w) * 0.25, LAY.DECK1.floor, w * 0.95, w ? suitAUp : suitBUp, false, true);
    [[-0.8, -1.3 + 0.55], [0.8, -1.3 - 0.55], [-0.6, 1.3 + 0.55], [0.7, 1.3 - 0.55]].forEach(function (q, idx) {
      person((LAY.mess.x0 + LAY.mess.x1) / 2 + q[0], LAY.DECK1.floor, q[1], idx % 2 ? suitAUp : suitBUp, true, true);
    });
    person(0.95, LAY.DECK2.floor, 0.9, medic, false, false);
    person(-0.9, LAY.DECK2.floor, -0.7, medic, false, false);
    person(LAY.stores.x0 + 2.4, LAY.DECK2.floor, 0.2, suitA, false, false);
    // Corridor light strips along each deck's centre line: the decks read
    // as lit corridors, not as slabs.
    var strip1 = new THREE.Mesh(new THREE.BoxGeometry(LAY.L - 3, 0.04, 0.12), stripUp);
    strip1.position.set(-1, LAY.DECK1.ceil - 0.05, 0);
    g.add(strip1);
    var strip2 = new THREE.Mesh(new THREE.BoxGeometry(LAY.L - 3, 0.04, 0.12), stripMat);
    strip2.position.set(-1, LAY.DECK2.ceil - 0.05, 0);
    g.add(strip2);
    // Cabins on deck 1: a partition per cabin with a doorway, a bed against
    // the hull, a locker.
    var lockerMat = upper(mat(0x6f8391, { metalness: 0.6, roughness: 0.5 }));
    var walls = [], parts = [], lintels = [], lockers = [], c0 = LAY.cabinBox(0), span0 = c0.x1 - c0.x0, depth0 = c0.z1 - c0.z0;
    for (var i = 0; i < LAY.CREW; i++) {
      var c = LAY.cabinBox(i);
      walls.push([c.x0, LAY.DECK1.floor + 0.75, (c.z0 + c.z1) / 2, 0]);
      bedAt(c.x, LAY.DECK1.floor, (c.z0 + c.z1) / 2 + (c.side > 0 ? 0.15 : -0.15), 0, true);
      var span = c.x1 - c.x0;
      var innerZ = c.side > 0 ? c.z0 : c.z1;
      parts.push([c.x0 + span * 0.275, LAY.DECK1.floor + 0.75, innerZ, 0]);
      lintels.push([c.x1 - span * 0.225, LAY.DECK1.floor + 1.35, innerZ, 0]);
      lockers.push([c.x1 - 0.2, LAY.DECK1.floor + 0.55, c.side > 0 ? c.z1 - 0.22 : c.z0 + 0.22, 0]);
    }
    instancedBoxes(0.05, 1.5, depth0, wallUp, walls, true);
    instancedBoxes(span0 * 0.55, 1.5, 0.05, wallUp, parts, true);
    instancedBoxes(span0 * 0.45, 0.3, 0.05, wallUp, lintels, false);
    instancedBoxes(0.28, 1.1, 0.34, lockerMat, lockers, false);
    // Bridge: consoles in an arc with lit screens, a holo table, the
    // captain's chair.
    for (var k = -2; k <= 2; k++) {
      var con = lit(new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.9, 0.5), upper(mat(0x2b3940, { metalness: 0.6 }))), true, true);
      con.position.set(LAY.bridge.x1 - 0.9 - Math.abs(k) * 0.25, LAY.DECK1.floor + 0.45, k * 0.95);
      g.add(con);
      var screen = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.5, 0.42), consoleUp);
      screen.position.set(LAY.bridge.x1 - 0.55 - Math.abs(k) * 0.25, LAY.DECK1.floor + 0.95, k * 0.95);
      screen.rotation.z = -0.25;
      g.add(screen);
    }
    var holo = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.65, 0.14, 24), consoleUp);
    holo.position.set(LAY.bridge.x0 + 2.2, LAY.DECK1.floor + 0.07, 0);
    g.add(holo);
    var holoCone = new THREE.Mesh(new THREE.ConeGeometry(0.5, 0.9, 20, 1, true), upper(new THREE.MeshBasicMaterial({ color: 0x37c9ff, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false })));
    holoCone.position.set(LAY.bridge.x0 + 2.2, LAY.DECK1.floor + 0.6, 0);
    holoCone.rotation.x = Math.PI;
    g.add(holoCone);
    var chair = lit(new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.9, 0.6), chairUp), true, true);
    chair.position.set(LAY.bridge.x0 + 1.2, LAY.DECK1.floor + 0.45, 0);
    g.add(chair);
    var bridgeLight = new THREE.PointLight(0x8fd0ff, 0.8, 7, 2);
    bridgeLight.position.set((LAY.bridge.x0 + LAY.bridge.x1) / 2, LAY.DECK1.ceil - 0.2, 0);
    g.add(bridgeLight);
    // Mess: two long tables and benches, a warm lamp.
    [-1.3, 1.3].forEach(function (z) {
      var table = lit(new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.08, 0.8), tableUp), true, true);
      table.position.set((LAY.mess.x0 + LAY.mess.x1) / 2, LAY.DECK1.floor + 0.72, z);
      g.add(table);
      [0.55, -0.55].forEach(function (dz) {
        var bench = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.06, 0.3), chairUp);
        bench.position.set((LAY.mess.x0 + LAY.mess.x1) / 2, LAY.DECK1.floor + 0.42, z + dz);
        g.add(bench);
      });
    });
    var messLight = new THREE.PointLight(0xffd9a8, 0.7, 6, 2);
    messLight.position.set((LAY.mess.x0 + LAY.mess.x1) / 2, LAY.DECK1.ceil - 0.2, 0);
    g.add(messLight);
    // Deck 2: the infirmary, eight beds around a console, a ring light.
    var infFloor = lit(new THREE.Mesh(new THREE.BoxGeometry(LAY.infirmary.x1 - LAY.infirmary.x0, 0.04, LAY.infirmary.z1 - LAY.infirmary.z0),
      new THREE.MeshStandardMaterial({ color: 0xe6edf0, emissive: 0xffffff, emissiveIntensity: 0.1, roughness: 0.85 })), false, true);
    infFloor.position.set(LAY.infirmary.cx, LAY.DECK2.floor + 0.02, LAY.infirmary.cz);
    g.add(infFloor);
    var core = lit(new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.6, 1.0, 24), consoleMat), true, true);
    core.position.set(0, LAY.DECK2.floor + 0.5, 0);
    g.add(core);
    var ringLight = new THREE.Mesh(new THREE.TorusGeometry(1.6, 0.05, 8, 48), glowing(0xdff4ff, 1.4));
    ringLight.rotation.x = Math.PI / 2;
    ringLight.position.set(0, LAY.DECK2.ceil - 0.08, 0);
    g.add(ringLight);
    for (var s = 0; s < 8; s++) {
      var p = LAY.infirmarySlot(s);
      bedAt(p.x, LAY.DECK2.floor, p.z, -Math.atan2(p.z, p.x), false);
    }
    var infLight = new THREE.PointLight(0xffffff, 1.3, 9, 2);
    infLight.position.set(0, LAY.DECK2.ceil - 0.2, 0);
    g.add(infLight);
    [LAY.infirmary.x0, LAY.infirmary.x1].forEach(function (x) {
      var w = lit(new THREE.Mesh(new THREE.BoxGeometry(0.06, LAY.DECK2.ceil - LAY.DECK2.floor, LAY.infirmary.z1 - LAY.infirmary.z0), wallMat), true, true);
      w.position.set(x, (LAY.DECK2.floor + LAY.DECK2.ceil) / 2, 0);
      g.add(w);
    });
    // Deck 2: the three isolation rooms, four beds each, a tinted floor, a
    // lamp, and a door frame that turns amber when the room is sealed.
    for (var zi = 0; zi < LAY.ZONES; zi++) {
      var zb = LAY.zoneBox(zi);
      var tile = lit(new THREE.Mesh(new THREE.BoxGeometry(zb.x1 - zb.x0 - 0.1, 0.04, zb.z1 - zb.z0 - 0.1),
        new THREE.MeshStandardMaterial({ color: 0xaebcc4, emissive: 0x2fb7a6, emissiveIntensity: 0.15, roughness: 0.85 })), false, true);
      tile.position.set(zb.cx, LAY.DECK2.floor + 0.02, zb.cz);
      g.add(tile);
      zoneTiles.push(tile);
      [zb.x0, zb.x1].forEach(function (x) {
        var w = lit(new THREE.Mesh(new THREE.BoxGeometry(0.06, LAY.DECK2.ceil - LAY.DECK2.floor, zb.z1 - zb.z0), wallMat), true, true);
        w.position.set(x, (LAY.DECK2.floor + LAY.DECK2.ceil) / 2, zb.cz);
        g.add(w);
      });
      for (var b = 0; b < LAY.BERTHS; b++) {
        var bb = LAY.bedBox(zi, b);
        bedAt(bb.cx, LAY.DECK2.floor, bb.cz, bb.cz > 0 ? Math.PI / 2 : -Math.PI / 2, false);
      }
      var door = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.06, 0.06), glowing(0x7be8d3, 0.8));
      door.position.set(zb.cx, LAY.DECK2.ceil - 0.06, zb.cz > 0 ? zb.z0 : zb.z1);
      g.add(door);
      zoneDoors.push(door);
      var lamp = new THREE.PointLight(0x7be8d3, 0.7, 7, 2);
      lamp.position.set(zb.cx, LAY.DECK2.ceil - 0.2, zb.cz);
      g.add(lamp);
    }
    // Stores forward on deck 2: crates, strapped.
    var crateTex = panelTex.clone(); crateTex.needsUpdate = true; crateTex.repeat.set(0.5, 0.5);
    var crateMat = mat(0x7d8a5e, { map: crateTex, roughness: 0.8, metalness: 0.2 });
    var strapMat = mat(0x2b3940, { roughness: 0.7 });
    for (var q = 0; q < 6; q++) {
      var crate = lit(new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 0.9), crateMat), true, true);
      crate.position.set(LAY.stores.x0 + 0.8 + (q % 3) * 1.6, LAY.DECK2.floor + 0.45, q < 3 ? -1.8 : 1.8);
      g.add(crate);
      var strap = new THREE.Mesh(new THREE.BoxGeometry(0.92, 0.92, 0.12), strapMat);
      strap.position.copy(crate.position);
      g.add(strap);
    }
    buildBeds(beds.up, frameUp, mattressUp, blanketUp, pillowUp);
    buildBeds(beds.down, frameMat, mattressMat, blanketMat, pillowMat);
    return g;
  }

  /* ---------- the void ---------- */

  function buildStars() {
    var g = new THREE.Group();
    var rnd = mulberry(23);
    // Two layers: a far dust of small stars and a nearer field of brighter
    // ones, warm and cool, each with its own size, drawn as soft discs.
    [[2600, 120, 0.9, 0.55], [500, 90, 2.2, 0.95]].forEach(function (layer) {
      var N = layer[0], pos = new Float32Array(N * 3), col = new Float32Array(N * 3);
      for (var i = 0; i < N; i++) {
        var th = rnd() * Math.PI * 2, ph = Math.acos(2 * rnd() - 1), r = layer[1] + rnd() * 60;
        pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
        pos[i * 3 + 1] = r * Math.cos(ph) * 0.8;
        pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
        var warm = rnd();
        var v = 0.55 + rnd() * 0.45;
        col[i * 3] = v * (warm < 0.3 ? 1.0 : 0.85);
        col[i * 3 + 1] = v * (warm < 0.3 ? 0.9 : 0.93);
        col[i * 3 + 2] = v * (warm < 0.3 ? 0.75 : 1.0);
      }
      var geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
      var pts = new THREE.Points(geo, new THREE.PointsMaterial({ size: layer[2], map: glowTex, vertexColors: true, sizeAttenuation: true, transparent: true, opacity: layer[3], depthWrite: false, blending: THREE.AdditiveBlending }));
      g.add(pts);
      stars.push(pts);
    });
    // The nebula, far behind, and a planet with its atmosphere, lit by the
    // same sun as the ship.
    var nebula = new THREE.Mesh(new THREE.SphereGeometry(300, 32, 20), new THREE.MeshBasicMaterial({ map: canvasTexture(512, paintNebula), side: THREE.BackSide, depthWrite: false }));
    g.add(nebula);
    planetGroup = new THREE.Group();
    var planetTex = canvasTexture(256, paintPlanet);
    planetTex.wrapS = planetTex.wrapT = THREE.ClampToEdgeWrapping;
    var planet = new THREE.Mesh(new THREE.SphereGeometry(44, 48, 32), new THREE.MeshStandardMaterial({ map: planetTex, roughness: 1.0, metalness: 0.0 }));
    planetGroup.add(planet);
    var atmo = new THREE.Mesh(new THREE.SphereGeometry(45.6, 48, 32), new THREE.MeshBasicMaterial({ color: 0xff8a4c, transparent: true, opacity: 0.09, blending: THREE.AdditiveBlending, side: THREE.BackSide, depthWrite: false }));
    planetGroup.add(atmo);
    var limb = sprite(0xffa060, 110, 0.16);
    planetGroup.add(limb);
    planetGroup.position.set(-135, -85, -215);
    g.add(planetGroup);
    // The sun itself, a glow where the key light comes from.
    var sun = sprite(0xfff0d0, 60, 0.85);
    sun.position.set(150, 105, 130);
    g.add(sun);
    return g;
  }

  /* ---------- life ---------- */

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
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.physicallyCorrectLights = false;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.localClippingEnabled = true;
    clipNear = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0.9);   // keeps z <= 0.9: the far side stays
    clipDeck = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1000);  // keeps y <= c: lowered onto deck 1 for a lower-deck view
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(50, 1, 0.1, 700);
    panelTex = canvasTexture(512, paintPanels);
    plateTex = canvasTexture(256, paintPlates);
    glowTex = canvasTexture(128, paintGlow);
    glowTex.wrapS = glowTex.wrapT = THREE.ClampToEdgeWrapping;
    // Light: a warm sun from the front right that casts shadows, a cool rim
    // from behind and below that draws the silhouette against the void, and
    // a hemisphere so the shadowed side keeps its colour.
    scene.add(new THREE.HemisphereLight(0x6fa3c7, 0x0b1a22, 0.55));
    var sun = new THREE.DirectionalLight(0xffe0b8, 1.9);
    sun.position.set(30, 22, 26);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.camera.near = 1;
    sun.shadow.camera.far = 120;
    sun.shadow.camera.left = -24; sun.shadow.camera.right = 24;
    sun.shadow.camera.top = 16; sun.shadow.camera.bottom = -16;
    sun.shadow.bias = -0.0015;
    sun.shadow.normalBias = 0.02;
    scene.add(sun);
    var rim = new THREE.DirectionalLight(0x63c8ff, 1.1);
    rim.position.set(-18, -6, -24);
    scene.add(rim);
    // What the metal reflects: the same night, the same sun, the same cool
    // rim, baked once into an environment map. Without it every metal is a
    // matte grey; with it the nacelles, the bells and the band catch light.
    try {
      var pmrem = new THREE.PMREMGenerator(renderer);
      var envScene = new THREE.Scene();
      envScene.add(new THREE.Mesh(new THREE.SphereGeometry(60, 32, 16), new THREE.MeshBasicMaterial({ side: THREE.BackSide, map: canvasTexture(256, paintNebula) })));
      var sunBall = new THREE.Mesh(new THREE.SphereGeometry(7, 16, 8), new THREE.MeshBasicMaterial({ color: 0xffe6c0 }));
      sunBall.position.set(30, 22, 26);
      envScene.add(sunBall);
      var rimBall = new THREE.Mesh(new THREE.SphereGeometry(6, 16, 8), new THREE.MeshBasicMaterial({ color: 0x63c8ff }));
      rimBall.position.set(-18, -6, -24);
      envScene.add(rimBall);
      scene.environment = pmrem.fromScene(envScene, 0.04).texture;
      pmrem.dispose();
    } catch (e) {
      if (root.console) console.warn("hull: no environment map: " + e.message);
    }
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
    for (var cs = 0; cs < cutStrips.length; cs++) cutStrips[cs].position.z = f.eye[2] >= 0 ? 0.9 : -0.9;
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
      var dm = zoneDoors[z] && zoneDoors[z].material;
      if (dm) { dm.emissive.setHex(sealed ? 0xff9a3c : 0x7be8d3); dm.emissiveIntensity = sealed ? 1.6 + 0.5 * Math.sin(t * 5) : 0.8; }
    }
    var heat = f.heat || 0, breath = f.breath || 0;
    for (var i = 0; i < radiators.length; i++) radiators[i].material.emissiveIntensity = 0.55 + heat * 1.3 + 0.05 * Math.sin(t * 7 + i);
    var flicker = 0.9 + 0.1 * Math.sin(t * 13) * Math.sin(t * 5.3);
    if (engineGlow) engineGlow.material.opacity = (0.12 + 0.05 * breath) * flicker;
    if (engineLight) engineLight.intensity = (1.5 + 0.4 * breath) * flicker;
    for (var e = 0; e < engineSprites.length; e++) engineSprites[e].material.opacity = (e === engineSprites.length - 1 ? 0.32 : 0.55) * flicker + 0.08 * breath;
    for (var k = 0; k < engineDiscs.length; k++) engineDiscs[k].material.emissiveIntensity = 3.0 * flicker + 0.6 * breath;
    if (windows) windows.material.emissiveIntensity = 1.3 + 0.2 * breath;
    for (var gl = 0; gl < growLights.length; gl++) {
      var pulse = 0.85 + 0.15 * Math.sin(t * 0.8 + gl);
      growLights[gl].intensity = 2.4 * pulse;
      growSprites[gl].material.opacity = 0.45 * pulse;
    }
    for (var n = 0; n < navLamps.length; n++) {
      var lamp = navLamps[n], on;
      if (lamp.strobe) on = ((t + lamp.phase) % 1.6) < 0.08;
      else on = ((t + lamp.phase) % 1.2) < 0.7;
      lamp.mesh.material.emissiveIntensity = on ? 3.0 : 0.25;
      lamp.halo.material.opacity = on ? 0.75 : 0.0;
    }
    if (dish) dish.rotation.y = t * 0.12;
    if (padRing) padRing.material.emissiveIntensity = 0.9 + 0.5 * Math.sin(t * 1.5);
    for (var s = 0; s < stars.length; s++) stars[s].rotation.y = t * 0.0035 * (s + 1);
    if (planetGroup) planetGroup.rotation.y = t * 0.004;
    renderer.render(scene, camera);
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.hull = { init: init, render: render, ready: function () { return ready; } };
})(window);
