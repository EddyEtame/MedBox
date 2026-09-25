/* The ship's plan: one source of truth for where things are.
 *
 * ESA Horizon is a generation ship, not a station: a long hull people live
 * in for decades. Axes: x runs bow (+) to stern (-), y is up, z is
 * starboard (+). Units are the ones the 3D view has always used.
 *
 * Two decks. Deck 1 (upper): the bridge forward, forty cabins along both
 * sides amidships, the mess and the gym aft. Deck 2 (lower): the infirmary
 * amidships, the three isolation rooms A, B, C around it, four beds each,
 * stores forward. ship.js places the crew glow, the beds and the seals from
 * this file; hull.js builds the walls, floors and beds from the same
 * numbers, so the overlay and the hull never disagree. */
(function (root) {
  "use strict";

  // Six aboard, one room each (Eddy, 25 Sep: « there's just supposed to be
  // six, and we're supposed to see each and everybody's room »): three a
  // side on the upper deck, wide enough for a bed, a desk and a name.
  var L = 30, W = 7, H = 5, BOW = 5, ZONES = 3, BERTHS = 4, CREW = 6;
  var DECK1 = { floor: 0.2, ceil: 2.3 };
  var DECK2 = { floor: -2.3, ceil: -0.2 };
  var CABIN_PITCH = 5.6, CABIN_X0 = -6.9, CABIN_DEPTH = 2.2, HULL_Z = W / 2;

  function cabinBox(i) {
    var side = i % 2 ? 1 : -1, col = Math.floor(i / 2);
    var x = CABIN_X0 + col * CABIN_PITCH;
    var zOut = side * (HULL_Z - 0.2), zIn = side * (HULL_Z - 0.2 - CABIN_DEPTH);
    return { x0: x - CABIN_PITCH / 2, x1: x + CABIN_PITCH / 2, y0: DECK1.floor, y1: DECK1.ceil,
             z0: Math.min(zOut, zIn), z1: Math.max(zOut, zIn), side: side, x: x };
  }
  function cabin(i) {
    if (i >= CREW) return dorm(i);
    var b = cabinBox(i);
    return { x: b.x, y: DECK1.floor + 0.75, z: (b.z0 + b.z1) / 2 };
  }
  // Beyond the rooms (a crew of forty again): bunks in the mess, in rows.
  function dorm(i) {
    var k = i - CREW;
    return { x: -13.0 + (k % 6) * 0.6, y: DECK1.floor + 0.75, z: -2.4 + (Math.floor(k / 6) % 8) * 0.65 };
  }

  // Isolation rooms on deck 2: A forward of the infirmary, B and C aft.
  var ZONE_X = [[3.0, 7.6], [-7.1, -2.5], [-11.7, -7.1]];
  function zoneBox(zi) {
    var xs = ZONE_X[zi] || ZONE_X[0];
    return { x0: xs[0], x1: xs[1], y0: DECK2.floor, y1: DECK2.ceil, z0: -2.9, z1: 2.9,
             cx: (xs[0] + xs[1]) / 2, cy: DECK2.floor + 0.9, cz: 0 };
  }
  function bedBox(zi, slot) {
    var z = zoneBox(zi);
    var col = slot % 2, row = Math.floor(slot / 2);          // two columns along x, two rows along z
    var cx = z.x0 + 1.25 + col * 2.1, cz = row ? 1.55 : -1.55;
    return { x0: cx - 0.45, x1: cx + 0.45, y0: DECK2.floor, y1: DECK2.floor + 0.32, z0: cz - 0.9, z1: cz + 0.9, cx: cx, cz: cz };
  }
  function berth(zi, slot) {
    var b = bedBox(zi, slot);
    return { x: b.cx, y: DECK2.floor + 0.7, z: b.cz };
  }

  var infirmary = { x0: -2.2, x1: 2.2, y0: DECK2.floor, y1: DECK2.ceil, z0: -2.9, z1: 2.9, cx: 0, cy: DECK2.floor + 0.9, cz: 0 };
  function infirmarySlot(k) {
    var a = (k % 8) / 8 * Math.PI * 2, r = 1.55;
    return { x: Math.cos(a) * r, y: DECK2.floor + 0.7, z: Math.sin(a) * r };
  }

  var bridge = { x0: 9.6, x1: 13.6, y0: DECK1.floor, y1: DECK1.ceil, z0: -2.6, z1: 2.6 };
  var mess = { x0: -13.4, x1: -9.6, y0: DECK1.floor, y1: DECK1.ceil, z0: -3.0, z1: 3.0 };
  var stores = { x0: 8.2, x1: 13.4, y0: DECK2.floor, y1: DECK2.ceil, z0: -2.9, z1: 2.9 };

  /* Line segments (x, y, z, glow) for the technical overlay: the plan the
     station draws over the hull. */
  function seg(v, a, b, g) { v.push(a[0], a[1], a[2], g, b[0], b[1], b[2], g); }
  function rect(v, x0, x1, y, z0, z1, g) {
    seg(v, [x0, y, z0], [x1, y, z0], g); seg(v, [x1, y, z0], [x1, y, z1], g);
    seg(v, [x1, y, z1], [x0, y, z1], g); seg(v, [x0, y, z1], [x0, y, z0], g);
  }
  function box(v, b, g) {
    rect(v, b.x0, b.x1, b.y0, b.z0, b.z1, g);
    rect(v, b.x0, b.x1, b.y1, b.z0, b.z1, g);
    [[b.x0, b.z0], [b.x1, b.z0], [b.x1, b.z1], [b.x0, b.z1]].forEach(function (c) {
      seg(v, [c[0], b.y0, c[1]], [c[0], b.y1, c[1]], g);
    });
  }
  function plan() {
    var v = [];
    // Deck outlines and the two corridors.
    rect(v, -14, 14, DECK1.floor, -3.3, 3.3, 0.32);
    rect(v, -14, 14, DECK2.floor, -3.3, 3.3, 0.32);
    seg(v, [-13.4, DECK1.floor + 0.01, 0], [13.6, DECK1.floor + 0.01, 0], 0.16);
    seg(v, [-11.7, DECK2.floor + 0.01, 0], [13.4, DECK2.floor + 0.01, 0], 0.16);
    // Cabins: partitions and beds on deck 1, both sides.
    for (var i = 0; i < CREW; i++) {
      var c = cabinBox(i);
      seg(v, [c.x0, DECK1.floor, c.z0], [c.x0, DECK1.floor, c.z1], 0.22);
      seg(v, [c.x0, DECK1.floor, c.side > 0 ? c.z0 : c.z1], [c.x0, DECK1.floor + 1.2, c.side > 0 ? c.z0 : c.z1], 0.14);
      var bz = (c.z0 + c.z1) / 2;
      rect(v, c.x - 0.3, c.x + 0.3, DECK1.floor + 0.02, bz - 0.55, bz + 0.55, 0.30);
    }
    seg(v, [CABIN_X0 - CABIN_PITCH / 2, DECK1.floor, 1.7], [CABIN_X0 + 19 * CABIN_PITCH + CABIN_PITCH / 2, DECK1.floor, 1.7], 0.22);
    seg(v, [CABIN_X0 - CABIN_PITCH / 2, DECK1.floor, -1.7], [CABIN_X0 + 19 * CABIN_PITCH + CABIN_PITCH / 2, DECK1.floor, -1.7], 0.22);
    box(v, bridge, 0.3);
    box(v, mess, 0.24);
    box(v, stores, 0.2);
    // Infirmary: its room and eight beds around the console.
    box(v, infirmary, 0.5);
    for (var k = 0; k < 8; k++) {
      var s = infirmarySlot(k);
      rect(v, s.x - 0.32, s.x + 0.32, DECK2.floor + 0.02, s.z - 0.5, s.z + 0.5, 0.55);
    }
    return new Float32Array(v);
  }
  function zoneLines(zi, glow) { var v = []; box(v, zoneBox(zi), glow); return new Float32Array(v); }
  function bedLines(zi, glow) {
    var v = [];
    for (var s = 0; s < BERTHS; s++) box(v, bedBox(zi, s), glow);
    return new Float32Array(v);
  }

  /* Where the camera goes for each view: the near side is +z, the cut side. */
  function cameraFor(kind, arg) {
    if (kind === "zone") { var z = zoneBox(arg); return { target: [z.cx, z.cy - 0.3, z.cz], dist: 8.2, yaw: 1.25, pitch: 0.62 }; }
    if (kind === "medbay") return { target: [infirmary.cx, infirmary.cy - 0.3, infirmary.cz], dist: 8.0, yaw: 1.3, pitch: 0.66 };
    if (kind === "member") return { target: arg, dist: 5.6, yaw: 1.30, pitch: 0.34 };
    return { target: [-2.5, -0.3, 0], dist: 28, yaw: 1.02, pitch: 0.30 };
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.layout = {
    L: L, W: W, H: H, BOW: BOW, ZONES: ZONES, BERTHS: BERTHS, CREW: CREW, DECK1: DECK1, DECK2: DECK2, HULL_Z: HULL_Z,
    cabin: cabin, cabinBox: cabinBox, zoneBox: zoneBox, bedBox: bedBox, berth: berth,
    infirmary: infirmary, infirmarySlot: infirmarySlot, bridge: bridge, mess: mess, stores: stores,
    plan: plan, zoneLines: zoneLines, bedLines: bedLines, cameraFor: cameraFor
  };
})(window);
