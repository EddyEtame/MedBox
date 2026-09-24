/* The Ship — MedBox 3D console.
 *
 * Raw WebGL, no library. The brief makes offline mode mandatory, so nothing may
 * be fetched from a CDN at runtime; writing the renderer means the repo is the
 * whole dependency and every shader is ours to tune.
 *
 * Every motion in this scene carries information. Nothing here is decorative:
 *
 *   ring rotation    the habitation torus spins for artificial gravity
 *   inward drift     a crew member's NEWS2 score pulls them toward the medbay
 *                    at the hub, so triage order is a physical fact of the
 *                    scene rather than a list you have to read
 *   hull colour      aggregate thermal load across the crew
 *   global pulse     the mean respiration rate of the crew — the ship breathes
 *                    with the people inside it, and it breathes faster when
 *                    they are in trouble
 *   sealed arc       a quarantine zone closed
 *
 * The data is identical to the flat board at /board. The two views read the
 * same WebSocket and share the same palette so they can never disagree.
 */
(function () {
  "use strict";

  var canvas = document.getElementById("gl");
  var gl = canvas.getContext("webgl2", { antialias: true, alpha: false })
        || canvas.getContext("webgl", { antialias: true, alpha: false });

  if (!gl) {
    document.getElementById("fallback").hidden = false;
    return;
  }

  // The context can be taken away at any moment: a driver reset, a sleep and
  // resume, a projector plugged in mid-demo. Nothing listened for it, so the
  // ship became a silent black void with the HUD still floating over it. Say
  // what happened and offer the board, which needs no GPU at all.
  canvas.addEventListener("webglcontextlost", function (e) {
    e.preventDefault();
    var fb = document.getElementById("fallback");
    fb.querySelector("h2").textContent = "La vue 3D a perdu son contexte graphique";
    fb.querySelector("p").textContent = "Le pilote graphique a redémarré. Les mesures " +
      "restent actives sur le tableau. Rechargez la page pour relancer la vue 3D.";
    fb.hidden = false;
  });

  /* ----------------------------------------------------------- tiny mat4 */
  function mat4() { return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]); }

  function perspective(out, fovy, aspect, near, far) {
    var f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    out[0]=f/aspect; out[1]=0; out[2]=0;  out[3]=0;
    out[4]=0; out[5]=f; out[6]=0; out[7]=0;
    out[8]=0; out[9]=0; out[10]=(far+near)*nf; out[11]=-1;
    out[12]=0; out[13]=0; out[14]=2*far*near*nf; out[15]=0;
    return out;
  }

  function lookAt(out, eye, center, up) {
    var z0=eye[0]-center[0], z1=eye[1]-center[1], z2=eye[2]-center[2];
    var len = Math.hypot(z0,z1,z2) || 1; z0/=len; z1/=len; z2/=len;
    var x0=up[1]*z2-up[2]*z1, x1=up[2]*z0-up[0]*z2, x2=up[0]*z1-up[1]*z0;
    len = Math.hypot(x0,x1,x2) || 1; x0/=len; x1/=len; x2/=len;
    var y0=z1*x2-z2*x1, y1=z2*x0-z0*x2, y2=z0*x1-z1*x0;
    out[0]=x0; out[1]=y0; out[2]=z0; out[3]=0;
    out[4]=x1; out[5]=y1; out[6]=z1; out[7]=0;
    out[8]=x2; out[9]=y2; out[10]=z2; out[11]=0;
    out[12]=-(x0*eye[0]+x1*eye[1]+x2*eye[2]);
    out[13]=-(y0*eye[0]+y1*eye[1]+y2*eye[2]);
    out[14]=-(z0*eye[0]+z1*eye[1]+z2*eye[2]);
    out[15]=1;
    return out;
  }

  function multiply(out, a, b) {
    for (var c = 0; c < 4; c++) {
      var b0=b[c*4], b1=b[c*4+1], b2=b[c*4+2], b3=b[c*4+3];
      out[c*4]   = b0*a[0] + b1*a[4] + b2*a[8]  + b3*a[12];
      out[c*4+1] = b0*a[1] + b1*a[5] + b2*a[9]  + b3*a[13];
      out[c*4+2] = b0*a[2] + b1*a[6] + b2*a[10] + b3*a[14];
      out[c*4+3] = b0*a[3] + b1*a[7] + b2*a[11] + b3*a[15];
    }
    return out;
  }

  /* --------------------------------------------------------------- shaders */
  function compile(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error("shader:", gl.getShaderInfoLog(s), src);
      return null;
    }
    return s;
  }

  function program(vsrc, fsrc) {
    var vs = compile(gl.VERTEX_SHADER, vsrc), fs = compile(gl.FRAGMENT_SHADER, fsrc);
    if (!vs || !fs) return null;
    var p = gl.createProgram();
    gl.attachShader(p, vs); gl.attachShader(p, fs); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      console.error("link:", gl.getProgramInfoLog(p));
      return null;
    }
    return p;
  }

  /* Lines: the ring lattice, the spokes, the sealed arcs. Depth-faded so the
     far side of the torus recedes instead of tangling with the near side. */
  var lineProg = program(
    "attribute vec3 aPos; attribute float aGlow;" +
    "uniform mat4 uVP; uniform float uTime, uSpin, uBreath;" +
    "varying float vGlow, vDepth;" +
    "void main(){" +
    "  float c = cos(uSpin), s = sin(uSpin);" +
    "  vec3 p = vec3(aPos.x*c - aPos.z*s, aPos.y, aPos.x*s + aPos.z*c);" +
    "  p *= 1.0 + uBreath*0.012;" +
    "  vec4 clip = uVP * vec4(p,1.0);" +
    "  vDepth = clamp(1.0 - (clip.w - 6.0)/26.0, 0.12, 1.0);" +
    "  vGlow = aGlow;" +
    "  gl_Position = clip;" +
    "}",
    "precision mediump float;" +
    "uniform vec3 uColdColor, uHotColor; uniform float uHeat;" +
    "varying float vGlow, vDepth;" +
    "void main(){" +
    "  vec3 c = mix(uColdColor, uHotColor, uHeat);" +
    "  gl_FragColor = vec4(c * (0.35 + vGlow), vDepth * (0.30 + vGlow*0.65));" +
    "}"
  );

  /* Stars: plain points with a little twinkle, so the ring has something to
     move against and the eye can read the camera orbiting. */
  var starProg = program(
    "attribute vec3 aPos; attribute float aSeed;" +
    "uniform mat4 uVP; uniform float uTime;" +
    "varying float vA;" +
    "void main(){" +
    "  gl_Position = uVP * vec4(aPos,1.0);" +
    "  gl_PointSize = 1.0 + aSeed*1.7;" +
    "  vA = 0.25 + 0.45*abs(sin(uTime*0.35 + aSeed*31.0));" +
    "}",
    "precision mediump float; varying float vA;" +
    "void main(){ gl_FragColor = vec4(0.72,0.84,0.90, vA); }"
  );

  /* Crew: camera-facing quads with a soft radial core. Additive, so a cluster
     of sick crew at the hub genuinely blooms. */
  var nodeProg = program(
    "attribute vec2 aCorner;" +
    "uniform mat4 uVP; uniform vec3 uCenter, uRight, uUp; uniform float uSize;" +
    "varying vec2 vUV;" +
    "void main(){" +
    "  vUV = aCorner;" +
    "  vec3 p = uCenter + uRight*aCorner.x*uSize + uUp*aCorner.y*uSize;" +
    "  gl_Position = uVP * vec4(p,1.0);" +
    "}",
    "precision mediump float;" +
    "uniform vec3 uColor; uniform float uIntensity, uRing;" +
    "varying vec2 vUV;" +
    "void main(){" +
    "  float d = length(vUV);" +
    "  if (d > 1.0) discard;" +
    "  float core = smoothstep(0.30, 0.0, d);" +
    "  float halo = smoothstep(1.0, 0.26, d) * 0.40;" +
    "  float sel  = uRing * smoothstep(0.045, 0.0, abs(d - 0.56));" +
    "  float a = (core + halo) * uIntensity + sel;" +
    "  gl_FragColor = vec4(uColor * (core*1.5 + halo + sel*1.4), a);" +
    "}"
  );

  if (!lineProg || !starProg || !nodeProg) {
    document.getElementById("fallback").hidden = false;
    return;
  }

  /* ------------------------------------------------------------- geometry */
  var RING_R = 6.0, HUB_R = 1.50, DECK_Y = 0.85, CREW = 40;
  var DOCK_R = HUB_R + 0.45;   // where inbound critical crew come to rest
  var FOV = 0.86;

  function buildRing() {
    var v = [], SEG = 120;
    // Two deck rails, top and bottom of the torus cross-section.
    [-DECK_Y, DECK_Y].forEach(function (y) {
      for (var i = 0; i < SEG; i++) {
        var a0 = i / SEG * Math.PI * 2, a1 = (i + 1) / SEG * Math.PI * 2;
        v.push(Math.cos(a0)*RING_R, y, Math.sin(a0)*RING_R, 0.30);
        v.push(Math.cos(a1)*RING_R, y, Math.sin(a1)*RING_R, 0.30);
      }
    });
    // Struts between the rails: these are what make the rotation readable.
    for (var s = 0; s < 48; s++) {
      var a = s / 48 * Math.PI * 2, x = Math.cos(a)*RING_R, z = Math.sin(a)*RING_R;
      var bright = (s % 4 === 0) ? 0.55 : 0.16;
      v.push(x, -DECK_Y, z, bright, x, DECK_Y, z, bright);
    }
    // Spokes from hub to ring — the route a patient travels to the medbay.
    for (var k = 0; k < 6; k++) {
      var b = k / 6 * Math.PI * 2;
      v.push(Math.cos(b)*HUB_R, 0, Math.sin(b)*HUB_R, 0.5,
             Math.cos(b)*RING_R, 0, Math.sin(b)*RING_R, 0.12);
    }
    // The hub itself: the medbay.
    for (var h = 0; h < 40; h++) {
      var h0 = h/40*Math.PI*2, h1 = (h+1)/40*Math.PI*2;
      v.push(Math.cos(h0)*HUB_R, 0, Math.sin(h0)*HUB_R, 0.85);
      v.push(Math.cos(h1)*HUB_R, 0, Math.sin(h1)*HUB_R, 0.85);
    }
    return new Float32Array(v);
  }

  /* The medbay. Despun core at the centre of the ring: a lit deck, a spine
     running through it, and eight berths on its rim. Critical crew converge
     onto that rim, so the scene shows them arriving somewhere real. */
  function buildHub() {
    var v = [], i, a0, a1, SEG = 56;
    function circle(r, y, glow) {
      for (var k = 0; k < SEG; k++) {
        a0 = k / SEG * Math.PI * 2; a1 = (k + 1) / SEG * Math.PI * 2;
        v.push(Math.cos(a0)*r, y, Math.sin(a0)*r, glow);
        v.push(Math.cos(a1)*r, y, Math.sin(a1)*r, glow);
      }
    }
    circle(HUB_R,        0,     0.70);
    circle(HUB_R * 0.42, 0,     0.45);
    circle(HUB_R * 0.86,  0.30, 0.22);
    circle(HUB_R * 0.86, -0.30, 0.22);
    circle(DOCK_R,       0,     0.75);   // the berth rim crew dock against

    v.push(0, -0.62, 0, 0.35,  0, 0.62, 0, 0.35);
    for (i = 0; i < 4; i++) {
      var a = i / 4 * Math.PI * 2 + Math.PI/4, cx = Math.cos(a), cz = Math.sin(a);
      v.push(cx*HUB_R*0.86,  0.30, cz*HUB_R*0.86, 0.22,  cx*HUB_R*0.86, -0.30, cz*HUB_R*0.86, 0.22);
    }
    // Sixteen berths on the dock rim, so an arriving crew member lands in a
    // slot rather than hovering near the middle of the scene.
    for (i = 0; i < 16; i++) {
      var b = i / 16 * Math.PI * 2, bx = Math.cos(b), bz = Math.sin(b);
      v.push(bx*(DOCK_R-0.16), 0, bz*(DOCK_R-0.16), 0.30,  bx*(DOCK_R+0.16), 0, bz*(DOCK_R+0.16), 0.75);
    }
    return new Float32Array(v);
  }

  function buildSealArc(zoneIndex, zones) {
    // A bulkhead drawn across this zone's arc of the ring.
    var v = [], span = Math.PI*2/zones, a0 = zoneIndex*span, SEG = 46;
    var TOP = DECK_Y*1.18, BOT = -DECK_Y*1.18;
    for (var i = 0; i < SEG; i++) {
      var t0 = a0 + (i/SEG)*span, t1 = a0 + ((i+1)/SEG)*span;
      for (var yy = -1; yy <= 1; yy += 2) {
        var y = yy * TOP;
        v.push(Math.cos(t0)*RING_R, y, Math.sin(t0)*RING_R, 1.0);
        v.push(Math.cos(t1)*RING_R, y, Math.sin(t1)*RING_R, 1.0);
      }
      // Dense shutter slats, so a sealed zone reads as closed, not outlined.
      v.push(Math.cos(t0)*RING_R, BOT, Math.sin(t0)*RING_R, 0.42);
      v.push(Math.cos(t0)*RING_R, TOP, Math.sin(t0)*RING_R, 0.42);
    }
    // End caps: the two bulkhead doors that bound the sealed section.
    [a0, a0 + span].forEach(function (t) {
      var cx = Math.cos(t), cz = Math.sin(t);
      for (var j = 0; j < 5; j++) {
        var r0 = RING_R - 0.85 + j * 0.2125;
        v.push(cx*r0, BOT*1.25, cz*r0, 1.0,  cx*r0, TOP*1.25, cz*r0, 1.0);
      }
      v.push(cx*(RING_R-0.85), TOP*1.25, cz*(RING_R-0.85), 1.0,  cx*RING_R, TOP*1.25, cz*RING_R, 1.0);
      v.push(cx*(RING_R-0.85), BOT*1.25, cz*(RING_R-0.85), 1.0,  cx*RING_R, BOT*1.25, cz*RING_R, 1.0);
    });
    return new Float32Array(v);
  }

  function buildStars() {
    var v = [], N = 900;
    for (var i = 0; i < N; i++) {
      // Rejection-sample a shell so stars sit far behind the ring.
      var th = Math.random()*Math.PI*2, ph = Math.acos(2*Math.random()-1), r = 42 + Math.random()*26;
      v.push(r*Math.sin(ph)*Math.cos(th), r*Math.cos(ph)*0.65, r*Math.sin(ph)*Math.sin(th), Math.random());
    }
    return new Float32Array(v);
  }

  function buffer(data) {
    var b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return b;
  }

  var ringData = buildRing(), ringBuf = buffer(ringData);
  var starData = buildStars(), starBuf = buffer(starData);
  var quadBuf  = buffer(new Float32Array([-1,-1, 1,-1, -1,1, 1,1]));
  var hubData = buildHub();
  var hubBuf = buffer(hubData);

  var ZONES = 3;
  var sealBufs = [], sealCounts = [];
  for (var z = 0; z < ZONES; z++) {
    var d = buildSealArc(z, ZONES);
    sealBufs.push(buffer(d));
    sealCounts.push(d.length / 4);
  }

  /* ---------------------------------------------------------------- state */
  var URGENCY = {
    routine: [0.29, 0.42, 0.47],
    low:     [0.50, 0.78, 0.84],
    medium:  [0.94, 0.77, 0.35],
    high:    [1.00, 0.36, 0.43]
  };
  var GLOW = { routine: 0.30, low: 0.56, medium: 0.78, high: 0.94 };

  var state = {
    board: [], byId: {}, quarantine: null, selected: null,
    heat: 0, breathHz: 0.25, aiUp: false, standIn: false, sealed: {},
    // The assessment currently on screen, as the server stamped it. Kept so
    // the panel can tell when the readings it describes are no longer the
    // readings above it.
    held: null
  };
  // Rendered positions, eased toward their target so crew glide rather than snap.
  var nodes = {};

  /* Distance that just contains the ring for the current viewport shape.
     A phone held upright needs to sit much further back than a projector,
     so the framing is computed rather than guessed at one aspect ratio. */
  function fitDist(aspect, pitch) {
    // A phone cannot hold a 12-unit-wide ring and still have it mean
    // anything, so portrait crops the rim slightly rather than shrinking
    // the ship into a logo. The ring reads as continuing past the edge.
    var t = Math.tan(FOV / 2), m = aspect < 0.85 ? 0.82 : 1.10;
    var near = RING_R * Math.cos(pitch);          // near edge, toward camera
    var halfV = RING_R * Math.sin(pitch) + DECK_Y * 1.4;
    var needV = halfV * m / t + near;
    var needH = RING_R * m / (t * Math.max(0.2, aspect)) + near;
    return Math.max(9, Math.min(36, Math.max(needV, needH)));
  }
  function fitPitch(aspect) {
    // Portrait has height to spare and no width, so tilt toward plan view.
    // Tilting toward plan view on a tall screen makes the ring rounder, so
    // it uses the height a phone actually has.
    return aspect < 0.85 ? 1.00 : 0.46;
  }

  var cam = {
    yaw: 0.72, pitch: 0.46, dist: 14.0,
    tYaw: 0.72, tPitch: 0.46, tDist: 14.0,
    target: [0, 0, 0], tTarget: [0, 0, 0], flying: 0, userZoom: 0
  };

  /* ------------------------------------------------------------ data feed */
  function el(id) { return document.getElementById(id); }

  function setChip(id, up, text) {
    var c = el(id);
    c.className = "chip " + (up ? "up" : "down");
    c.innerHTML = '<i class="led"></i>' + text;
  }

  var ws = null, retry = 0;

  /* A frozen ship must not look like a calm one. Same watchdog as app.js:
     stamped at the end of a repaint, and after two seconds without one the
     link chip goes red and the HUD dims. The ring keeps turning either way,
     which is exactly why the numbers on it need saying are old. */
  var lastPainted = 0;
  setInterval(function () {
    if (!ws || ws.readyState !== 1 || !lastPainted) return;
    var gap = Date.now() - lastPainted;
    var stale = gap > 2000;
    document.body.classList.toggle("stale-feed", stale);
    if (stale) setChip("linkChip", false, "aucune mise à jour depuis " + Math.round(gap / 1000) + " s");
    else if (el("linkChip").className !== "chip up") setChip("linkChip", true, "liaison");
  }, 500);

  function connect() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws");
    ws.onopen = function () { retry = 0; setChip("linkChip", true, "liaison"); };
    ws.onclose = function () {
      setChip("linkChip", false, "liaison perdue");
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 400 * retry);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
    ws.onmessage = function (ev) {
      var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "board") onBoard(m);
      // Someone reported a symptom, possibly from another screen. If it is
      // the crew member on show, their words appear without a refresh.
      else if (m.type === "symptom" && m.reported &&
               m.reported.patient_id === state.selected) loadReported();
      else if (m.type === "quarantine" && state.selected && MedBox.patientTools)
        MedBox.patientTools.refresh(state.selected);
      // Something the station could not do, e.g. a scenario step it skipped.
      // The command line's output stays until the next command, which is
      // long enough to be read.
      else if (m.type === "event" && m.kind === "warning") say(String(m.text || ""), true);
    };
  }

  function onBoard(m) {
    state.board = m.board || [];
    state.quarantine = m.quarantine;
    state.aiUp = !!(m.ai && m.ai.available);

    state.byId = {};
    var fit = 0, imp = 0, respSum = 0, respN = 0, heatSum = 0, heatN = 0;

    state.board.forEach(function (r, i) {
      var p = r.patient;
      state.byId[p.id] = r;
      if (r.triage.urgency === "routine") fit++; else imp++;
      if (p.respiration != null) { respSum += p.respiration; respN++; }
      if (p.temperature != null) {
        // Map 36.5-39.5 C onto 0-1 so the hull reads crew thermal load.
        heatSum += Math.max(0, Math.min(1, (p.temperature - 36.5) / 3.0)); heatN++;
      }
      if (!nodes[p.id]) {
        // Home berth: evenly spaced around the ring, alternating deck level.
        var idx = parseInt(p.id.replace(/\D/g, ""), 10) || (i + 1);
        var ang = (idx - 1) / CREW * Math.PI * 2;
        nodes[p.id] = {
          ang: ang, home: ang, deck: (idx % 2 ? 1 : -1) * 0.34,
          r: RING_R, tr: RING_R, col: URGENCY.routine.slice(),
          tcol: URGENCY.routine.slice(), size: 0.15, tsize: 0.15,
          glow: GLOW.routine, tglow: GLOW.routine
        };
      }
      var n = nodes[p.id];
      // THE SPATIAL TRIAGE: NEWS2 pulls the patient off the ring toward the hub.
      // Saturate at 7, the NEWS2 threshold for an emergency response. So
      // "docked at the medbay" is not a look, it is a clinical statement:
      // that crew member scores 7 or more and needs a team now.
      var sev = Math.max(0, Math.min(1, r.triage.total / 7));
      n.tr = RING_R - (RING_R - DOCK_R) * sev;
      n.tcol = URGENCY[r.triage.urgency] || URGENCY.routine;
      n.tglow = GLOW[r.triage.urgency] || GLOW.routine;
      n.tsize = 0.13 + sev * 0.13;
    });

    state.heat = heatN ? heatSum / heatN : 0;
    var meanResp = respN ? respSum / respN : 15;
    state.breathHz = meanResp / 60;

    state.sealed = {};
    if (state.quarantine) {
      var zk = Object.keys(state.quarantine.zones);
      zk.forEach(function (z, i) {
        if (i < ZONES) state.sealed[i] = state.quarantine.zones[z].sealed;
      });
    }

    el("gFit").textContent = fit;
    el("gImp").textContent = imp;
    el("gIso").textContent = state.quarantine ? state.quarantine.assignments.filter(function (a) {
      return a.confirmed;
    }).length : 0;
    el("gResp").textContent = meanResp.toFixed(0) + " /min";
    el("gRespHz").textContent = "· rythme du bord";
    el("shipSub").textContent = "anneau d’habitation · " + state.board.length + " membres";
    state.standIn = !!(m.ai && m.ai.stand_in);
    // The frame carries what to say, decided server-side from measurements.
    // Usually an empty list.
    // Guarded: these two scripts are the slow track, and a slow track that
    // is missing must never stop a measurement reaching the screen. Without
    // the check, one absent file throws here ten times a second and every
    // number below this line stops updating.
    if (m.say && m.say.length && MedBox.voice) MedBox.voice.say(m.say);
    if (m.ears && MedBox.mic) MedBox.mic.setAvailable(m.ears.available, m.ears.error);
    // Never let a stand-in read as the assistant. The chip says which it is
    // before a single assessment has been shown.
    var aiChip = el("aiChip");
    if (m.ai && m.ai.warming) {
      aiChip.className = "chip";
      aiChip.innerHTML = '<i class="led"></i>préchauffage';
    } else if (state.aiUp && state.standIn) {
      aiChip.className = "chip standin";
      aiChip.innerHTML = '<i class="led"></i>secours, pas un modèle';
    } else {
      setChip("aiChip", state.aiUp, state.aiUp ? "assistant prêt" : "assistant indisponible");
    }
    el("scChip").textContent = m.scenario ? ("SIMULÉ · " + m.scenario) : "aucun scénario";
    if (m.scenario_meta && m.scenario_meta.simulation) {
      var sim = m.scenario_meta.simulation;
      el("simChip").textContent = "SIMULÉ · " +
        (sim.represented_duration || "TEMPS ACCÉLÉRÉ") + " / " +
        (sim.demo_duration || "DÉMO") + " · HORS LIGNE";
    } else {
      el("simChip").textContent = "SIMULÉ · LIGNE SAINE · HORS LIGNE";
    }

    /* Hidden at zero, loud at one. The bulkheads already show which
       zones are closed; nothing on this view showed a crew member the
       ship has no berth for, which is the one number that means the
       quarantine plan has run out. Same rule on the flat board. */
    var waiting = state.quarantine ? (state.quarantine.awaiting_bed || 0) : 0;
    var bedChip = el("bedChip");
    bedChip.hidden = !waiting;
    if (waiting) {
      bedChip.textContent = waiting +
        (waiting === 1 ? " membre en attente d’une place" : " membres en attente d’une place");
    }

    var quarantine = state.quarantine || { zones: {}, candidates: 0 };
    el("candidateCount").textContent = (quarantine.candidates || 0) + " à confirmer";
    el("zoneRail").innerHTML = Object.keys(quarantine.zones || {}).map(function (zoneName) {
      var zone = quarantine.zones[zoneName];
      var capacity = Math.max(1, Number(zone.capacity) || 1);
      var occupied = Math.max(0, Number(zone.occupied) || 0);
      var percent = Math.min(100, occupied / capacity * 100);
      return '<div class="zone-row ' + (zone.sealed ? "sealed" : "open") + '">' +
        '<span class="zone-name">' + esc(zoneName) + '</span>' +
        '<span class="zone-cap" aria-label="' + occupied + ' places occupées sur ' + capacity + '">' +
          '<i style="width:' + percent.toFixed(1) + '%"></i></span>' +
        '<span class="zone-state">' + occupied + '/' + capacity + ' · ' +
          (zone.sealed ? "scellée" : "ouverte") + '</span></div>';
    }).join("");

    var duration = m.scenario_meta && Number(m.scenario_meta.duration_seconds);
    var elapsed = m.scenario_elapsed == null ? 0 : Math.max(0, Number(m.scenario_elapsed) || 0);
    var percentDone = duration > 0 ? Math.min(100, elapsed / duration * 100) : 0;
    // Once the last step is behind us the clock stops: "03:02 / 01:30" read
    // as a scenario that had overrun, when it had simply finished.
    var over = duration > 0 && elapsed >= duration;
    el("timelineLabel").textContent = m.scenario
      ? m.scenario + (over ? " · terminé, surveillance continue" : "")
      : "Surveillance nominale";
    el("timelineClock").textContent = m.scenario
      ? formatClock(Math.min(elapsed, duration)) + " / " + formatClock(duration)
      : "ligne saine personnelle";
    el("timelineFill").style.width = percentDone.toFixed(1) + "%";

    if (state.selected) renderPanel();
    lastPainted = Date.now();
  }

  /* --------------------------------------------------------------- render */
  var dpr = 1, W = 1, H = 1;
  function placeRail() {
    // Under the header, wherever the header ends: it wraps to two or three
    // lines with the window, and a fixed top left the rail on the chips.
    var rail = el("zoneRail") && el("zoneRail").parentElement, top = document.querySelector(".hud.top");
    if (rail && top) rail.style.top = Math.round(top.getBoundingClientRect().bottom + 8) + "px";
  }

  function resize() {
    placeRail();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(1, Math.round(canvas.clientWidth * dpr));
    H = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  }

  var proj = mat4(), view = mat4(), vp = mat4();
  var eye = [0,0,0], right = [0,0,0], upv = [0,0,0];
  var breathCtx = el("breath").getContext("2d");
  var breathHist = new Array(66).fill(0);

  function drawLines(buf, count, heat, breath, spin) {
    gl.useProgram(lineProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    var aPos = gl.getAttribLocation(lineProg, "aPos");
    var aGlow = gl.getAttribLocation(lineProg, "aGlow");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(aGlow);
    gl.vertexAttribPointer(aGlow, 1, gl.FLOAT, false, 16, 12);
    gl.uniformMatrix4fv(gl.getUniformLocation(lineProg, "uVP"), false, vp);
    gl.uniform1f(gl.getUniformLocation(lineProg, "uSpin"), spin);
    gl.uniform1f(gl.getUniformLocation(lineProg, "uBreath"), breath);
    gl.uniform1f(gl.getUniformLocation(lineProg, "uHeat"), heat);
    var cold = arguments[5] || [0.31, 0.72, 0.80];
    var hot  = arguments[6] || [1.0, 0.48, 0.22];
    gl.uniform3f(gl.getUniformLocation(lineProg, "uColdColor"), cold[0], cold[1], cold[2]);
    gl.uniform3f(gl.getUniformLocation(lineProg, "uHotColor"), hot[0], hot[1], hot[2]);
    gl.drawArrays(gl.LINES, 0, count);
  }

  var last = 0, spin = 0, breathPhase = 0;

  function frame(ts) {
    var dt = last ? Math.min(0.05, (ts - last) / 1000) : 0.016;
    last = ts;
    resize();

    // Ring spins for artificial gravity; it speeds up very slightly with heat
    // so a ship in trouble reads as working harder.
    spin += dt * (0.055 + state.heat * 0.03);
    breathPhase += dt * state.breathHz * Math.PI * 2;
    var breath = Math.sin(breathPhase);

    // Camera easing, including flights to a selected crew member.
    cam.yaw   += (cam.tYaw   - cam.yaw)   * Math.min(1, dt * 4.5);
    cam.pitch += (cam.tPitch - cam.pitch) * Math.min(1, dt * 4.5);
    // Re-frame on resize and rotation, unless the operator has taken the
    // zoom themselves or we are flying to a crew member.
    if (!cam.userZoom && !cam.flying) {
      var asp = W / H;
      cam.tPitch = fitPitch(asp);
      cam.tDist = fitDist(asp, cam.tPitch);
      // The HUD sits along the top on a phone, so bias the ship down into
      // the space the operator can actually see.
      cam.tTarget[1] = asp < 0.85 ? 1.7 : 0;
    }
    cam.dist  += (cam.tDist  - cam.dist)  * Math.min(1, dt * 3.2);
    for (var i = 0; i < 3; i++) {
      cam.target[i] += (cam.tTarget[i] - cam.target[i]) * Math.min(1, dt * 3.0);
    }
    if (!dragging && !cam.flying) cam.tYaw += dt * 0.035;   // slow idle drift

    var cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
    eye[0] = cam.target[0] + Math.cos(cam.yaw) * cp * cam.dist;
    eye[1] = cam.target[1] + sp * cam.dist;
    eye[2] = cam.target[2] + Math.sin(cam.yaw) * cp * cam.dist;

    perspective(proj, FOV, W / H, 0.1, 200);
    lookAt(view, eye, cam.target, [0, 1, 0]);
    multiply(vp, proj, view);

    // Camera basis for billboarding.
    right[0] = view[0]; right[1] = view[4]; right[2] = view[8];
    upv[0]   = view[1]; upv[1]   = view[5]; upv[2]   = view[9];

    gl.viewport(0, 0, W, H);
    gl.clearColor(0.012, 0.031, 0.043, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.DEPTH_TEST);

    // stars
    gl.useProgram(starProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, starBuf);
    var sPos = gl.getAttribLocation(starProg, "aPos");
    var sSeed = gl.getAttribLocation(starProg, "aSeed");
    gl.enableVertexAttribArray(sPos);
    gl.vertexAttribPointer(sPos, 3, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(sSeed);
    gl.vertexAttribPointer(sSeed, 1, gl.FLOAT, false, 16, 12);
    gl.uniformMatrix4fv(gl.getUniformLocation(starProg, "uVP"), false, vp);
    gl.uniform1f(gl.getUniformLocation(starProg, "uTime"), ts / 1000);
    gl.drawArrays(gl.POINTS, 0, starData.length / 4);

    // habitation ring: spins for artificial gravity, warms with crew fever
    drawLines(ringBuf, ringData.length / 4, state.heat, breath, spin);

    // the medbay is despun, so it holds still while the ring turns around it
    drawLines(hubBuf, hubData.length / 4, state.heat * 0.5, breath, 0,
              [0.40, 0.66, 0.74], [0.95, 0.66, 0.46]);

    // sealed quarantine arcs, in their own amber so they read as bulkheads
    // shut rather than as more of the ring running hot
    for (var z = 0; z < ZONES; z++) {
      if (!state.sealed[z]) continue;
      drawLines(sealBufs[z], sealCounts[z], 1.0, breath, spin,
                [1.0, 0.64, 0.26], [1.0, 0.64, 0.26]);
    }

    // crew
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);   // additive: clustering blooms
    gl.useProgram(nodeProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuf);
    var aCorner = gl.getAttribLocation(nodeProg, "aCorner");
    gl.enableVertexAttribArray(aCorner);
    gl.vertexAttribPointer(aCorner, 2, gl.FLOAT, false, 0, 0);
    var uVP = gl.getUniformLocation(nodeProg, "uVP");
    var uCenter = gl.getUniformLocation(nodeProg, "uCenter");
    var uRight = gl.getUniformLocation(nodeProg, "uRight");
    var uUp = gl.getUniformLocation(nodeProg, "uUp");
    var uSize = gl.getUniformLocation(nodeProg, "uSize");
    var uColor = gl.getUniformLocation(nodeProg, "uColor");
    var uIntensity = gl.getUniformLocation(nodeProg, "uIntensity");
    var uRing = gl.getUniformLocation(nodeProg, "uRing");
    gl.uniformMatrix4fv(uVP, false, vp);
    gl.uniform3fv(uRight, right);
    gl.uniform3fv(uUp, upv);

    var ids = Object.keys(nodes);
    for (var k = 0; k < ids.length; k++) {
      var n = nodes[ids[k]];
      n.r += (n.tr - n.r) * Math.min(1, dt * 1.6);       // glide, never snap
      n.size += (n.tsize - n.size) * Math.min(1, dt * 4);
      n.glow += (n.tglow - n.glow) * Math.min(1, dt * 3);
      for (var c = 0; c < 3; c++) n.col[c] += (n.tcol[c] - n.col[c]) * Math.min(1, dt * 3);

      var a = n.ang + spin;
      var px = Math.cos(a) * n.r, pz = Math.sin(a) * n.r;
      var py = n.deck * (n.r / RING_R);   // converge to the hub plane on the way in
      n.sx = px; n.sy = py; n.sz = pz;

      var sel = (state.selected === ids[k]) ? 1 : 0;
      // With someone selected, the rest of the crew fall back so the ring
      // marks one person rather than a neighbourhood.
      var focus = (!state.selected || sel) ? 1 : 0.28;
      // The ship breathes: every crew glow swells with the mean respiration rate.
      var pulse = 1 + breath * 0.16 + sel * 0.25;
      gl.uniform3f(uCenter, px, py, pz);
      gl.uniform1f(uSize, n.size * (1 + breath * 0.06) * 3.1);
      gl.uniform3fv(uColor, n.col);
      gl.uniform1f(uIntensity, n.glow * pulse * focus);
      gl.uniform1f(uRing, sel);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }

    drawBreath(breath);
    requestAnimationFrame(frame);
  }

  function drawBreath(breath) {
    breathHist.push(breath);
    if (breathHist.length > 66) breathHist.shift();
    var c = breathCtx, w = 132, h = 22;
    c.clearRect(0, 0, w, h);
    c.beginPath();
    for (var i = 0; i < breathHist.length; i++) {
      var x = (i / (breathHist.length - 1)) * w, y = h / 2 - breathHist[i] * (h / 2 - 3);
      if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
    }
    var hot = state.heat > 0.28;
    c.strokeStyle = hot ? "#f0c459" : "#4fd8e2";
    c.lineWidth = 1.4;
    c.stroke();
  }

  /* -------------------------------------------------------------- picking */
  function project(x, y, z) {
    var cx = vp[0]*x + vp[4]*y + vp[8]*z + vp[12];
    var cy = vp[1]*x + vp[5]*y + vp[9]*z + vp[13];
    var cw = vp[3]*x + vp[7]*y + vp[11]*z + vp[15];
    if (cw <= 0) return null;
    return { x: (cx/cw*0.5+0.5)*canvas.clientWidth, y: (0.5-cy/cw*0.5)*canvas.clientHeight };
  }

  function pick(mx, my) {
    var best = null, bestD = 34;   // generous radius: these are small targets
    Object.keys(nodes).forEach(function (id) {
      var n = nodes[id];
      if (n.sx === undefined) return;
      var s = project(n.sx, n.sy, n.sz);
      if (!s) return;
      var d = Math.hypot(s.x - mx, s.y - my);
      if (d < bestD) { bestD = d; best = id; }
    });
    return best;
  }

  /* ------------------------------------------------------- camera control */
  var dragging = false, lastX = 0, lastY = 0, moved = 0;

  canvas.addEventListener("pointerdown", function (e) {
    dragging = true; moved = 0; lastX = e.clientX; lastY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    var dx = e.clientX - lastX, dy = e.clientY - lastY;
    moved += Math.abs(dx) + Math.abs(dy);
    lastX = e.clientX; lastY = e.clientY;
    cam.tYaw -= dx * 0.006;
    cam.tPitch = Math.max(-1.35, Math.min(1.35, cam.tPitch + dy * 0.005));
    cam.flying = 0;
  });
  canvas.addEventListener("pointerup", function (e) {
    dragging = false;
    try { canvas.releasePointerCapture(e.pointerId); } catch (err) {}
    if (moved < 6) {
      var rect = canvas.getBoundingClientRect();
      var id = pick(e.clientX - rect.left, e.clientY - rect.top);
      if (id) selectCrew(id); else closePanel();
    }
  });
  canvas.addEventListener("wheel", function (e) {
    e.preventDefault();
    cam.userZoom = 1;
    cam.tDist = Math.max(4.5, Math.min(38, cam.tDist + e.deltaY * 0.012));
  }, { passive: false });

  function flyTo(id) {
    var n = nodes[id];
    if (!n) return;
    cam.flying = 1;
    cam.tTarget = [n.sx, n.sy, n.sz];
    cam.tDist = 6.2;
    cam.tYaw = Math.atan2(n.sz, n.sx) + 0.9;
    cam.tPitch = 0.34;
  }

  function resetCam() {
    cam.flying = 0;
    cam.userZoom = 0;
    cam.tTarget = [0, 0, 0];
    var asp = W / H;
    cam.tPitch = fitPitch(asp);
    cam.tDist = fitDist(asp, cam.tPitch);
  }

  /* ---------------------------------------------------------------- panel */
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }
  function num(v, d) { return v == null ? "—" : Number(v).toFixed(d || 0); }

  function selectCrew(id) {
    state.selected = id;
    state.held = null;
    el("aiOut").innerHTML = "";
    el("aiStale").hidden = true;
    el("sayInput").value = "";
    renderReported([]);
    loadReported();
    el("panel").hidden = false;
    document.body.classList.add("has-panel");
    flyTo(id);
    renderPanel();
    if (MedBox.patientTools) MedBox.patientTools.select(id);
  }

  function closePanel() {
    state.selected = null;
    el("panel").hidden = true;
    document.body.classList.remove("has-panel");
    resetCam();
  }

  function renderPanel() {
    var row = state.byId[state.selected];
    if (!row) return;
    var p = row.patient, t = row.triage;
    checkHeld(row);

    el("pPid").textContent = p.id;
    el("pName").textContent = p.name;
    el("pRole").textContent = p.role;

    el("pNews").innerHTML =
      '<div class="agg"><span class="n">' + t.total + '</span>' +
      '<span class="band" style="color:' + bandColor(t.urgency) + '">' + esc(t.urgency) + '</span></div>' +
      '<p class="resp">' + esc(t.response) + '</p>' +
      '<p class="src">' + esc(t.score_label || "Dépistage partiel dérivé de NEWS2") +
      ' · mesuré : ' + t.measured.join(", ") + '</p>';

    var cells = [
      ["Temp", num(p.temperature,1) + " °C", "temperature"],
      ["SpO₂", num(p.spo2,0) + " %", "spo2"],
      ["Pouls", num(p.pulse,0), "pulse"],
      ["Resp.", num(p.respiration,0), "respiration"],
      ["Tension", num(p.systolic_bp,0), "systolic_bp"],
      ["Conscience", "", "consciousness"],
      ["Oxygène", "", "oxygen"]
    ];
    el("pVit").innerHTML = cells.map(function (c) {
      var score = 0, reason = "", measured = true;
      t.params.forEach(function (q) { if (q.name === c[2]) { score = q.score; reason = q.reason; measured = q.measured; } });
      var shown = c[1] || reason;
      return '<div class="vc s' + score + (measured ? "" : " assumed") + '"><span class="k">' + c[0] + '</span>' +
             '<div class="v">' + esc(shown) + '</div><div class="r">' + (c[1] ? esc(reason) : (measured ? "observé" : "supposé")) + '</div></div>';
    }).join("");
  }

  /* --------------------------------------------- what the crew member said */
  function renderReported(list) {
    var box = el("pSaid");
    if (!list || !list.length) {
      box.innerHTML = '<p class="none">Aucune déclaration enregistrée.</p>';
      return;
    }
    box.innerHTML = list.map(function (r) {
      var who = r.source === "voice" ? "entendu" :
                r.source === "answer" ? "réponse" : "saisi";
      // A transcript is a guess about what was said. Show the confidence so an
      // operator can see when the box may simply have misheard.
      if (r.source === "voice" && r.confidence != null) {
        who = 'entendu · <span class="heard">confiance ' + Math.round(r.confidence * 100) + '%</span>';
      }
      return '<div class="quote ' + (r.source === "voice" ? "voice" : "") + '">' +
             "<p>&ldquo;" + esc(r.text) + "&rdquo;</p>" +
             '<span class="who">' + who + "</span></div>";
    }).join("");
  }

  function loadReported() {
    var id = state.selected;
    if (!id) return;
    fetch("/api/patient/" + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (d) { if (state.selected === id) renderReported(d.reported || []); })
      .catch(function () { /* the board is unaffected either way */ });
  }

  function sayIt(e) {
    e.preventDefault();
    var input = el("sayInput"), text = input.value.trim();
    if (!text || !state.selected) return;
    input.value = "";
    fetch("/api/patient/" + encodeURIComponent(state.selected) + "/symptom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, source: "typed" })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderReported(d.reported || []); })
      .catch(function () { input.value = text; });
  }

  /* ------------------------------------------------------- the guide */
  function renderGuide(m) {
    var withAI = m.capabilities.filter(function (c) { return c.needs_ai; });
    var without = m.capabilities.filter(function (c) { return !c.needs_ai; });

    function item(c) {
      return '<div class="gitem ' + (c.needs_ai ? "ai" : "") + '">' +
        "<b>" + esc(c.title) + "</b><p>" + esc(c.does) + "</p>" +
        '<span class="how">' + esc(c.how) + "</span></div>";
    }

    var html =
      '<div class="gsec"><h3>Fonctionne sans l’assistant</h3>' +
      without.map(item).join("") + "</div>" +
      '<div class="gsec"><h3>Demande l’assistant</h3>' +
      withAI.map(item).join("") + "</div>" +
      '<div class="gsec"><h3>Ce qu’il ne fera jamais</h3>' +
      m.refusals.map(function (r) {
        return '<div class="gno"><b>' + esc(r.never) + "</b><p>" + esc(r.why) + "</p></div>";
      }).join("") + "</div>" +
      '<div class="gsec"><h3>À taper, ou à dire après « MedBox »</h3><div class="keys">' +
      m.shortcuts.map(function (k) {
        return "<kbd" + (k.needs_ai ? ' class="ai"' : "") + ">" + esc(k.phrase) + "</kbd>" +
               "<span>" + esc(k.does) + "</span>";
      }).join("") + "</div></div>" +
      '<div class="gsec" id="guideLearned"><h3>Ce que MedBox a appris</h3>' +
      '<p class="guide-lead">Chargement…</p></div>';

    el("guideBody").innerHTML = html;
    el("guideLead").textContent = m.ai_available
      ? (m.stand_in
          ? "Un substitut répond, pas un modèle. Tout ce qui suit appartient à la station et reste vrai dans les deux cas."
          : "L’essentiel fonctionne avec ou sans l’assistant. Ce qui est en cyan a besoin de lui.")
      : "L’assistant ne répond pas. Les fonctions déterministes de la première liste restent actives.";
    renderLearned();
  }

  /* What the station learned from every request: phrasings it did not know,
     understood once (by the model, within the station's own actions) or taught
     by an operator, and deterministic ever since. Shown to the jury as is. */
  function renderLearned() {
    var box = el("guideLearned");
    if (!box) return;
    fetch("/api/assistant/learned").then(function (r) { return r.json(); }).then(function (d) {
      var s = d.stats || {}, phrases = d.phrases || [];
      var html = "<p class=\"guide-lead\">" + esc(String(s.requests || 0)) + " demande(s) reçue(s) · " +
        esc(String(phrases.length)) + " formulation(s) apprise(s)</p>";
      if (!phrases.length) {
        html += '<p class="guide-lead">Dites « MedBox » puis une demande dans vos mots : ' +
          "si elle correspond à une action de la station, elle sera apprise ici.</p>";
      }
      var HOW = { operator: "appris d’un opérateur", lexicon: "reconnu par le vocabulaire de la station",
                  model: "arbitré par le modèle entre lectures plausibles, puis retenu" };
      html += phrases.slice(0, 12).map(function (p) {
        return '<div class="gitem"><b>« ' + esc(p.example) + " »</b><p>compris comme : " + esc(p.label_fr) +
          '</p><span class="how">' + esc(HOW[p.source] || p.source) + " · utilisé " + esc(String(p.uses)) +
          ' fois · <a href="#" class="forget" data-text="' + esc(p.example) + '">oublier</a></span></div>';
      }).join("");
      box.innerHTML = '<h3>Ce que MedBox a appris</h3>' + html;
      box.querySelectorAll(".forget").forEach(function (a) {
        a.addEventListener("click", function (e) {
          e.preventDefault();
          fetch("/api/assistant/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: a.getAttribute("data-text"), intent: "forget" }) })
            .then(renderLearned).catch(function () {});
        });
      });
    }).catch(function () {
      box.innerHTML = '<h3>Ce que MedBox a appris</h3><p class="guide-lead">Indisponible.</p>';
    });
  }

  function openGuide() {
    el("guide").hidden = false;
    document.body.classList.add("has-guide");
    el("introOut").innerHTML = "";
    fetch("/api/assistant/help")
      .then(function (r) { return r.json(); })
      .then(renderGuide)
      .catch(function () {
        el("guideBody").innerHTML =
          '<p class="guide-lead">La station ne répond pas. Rechargez la page.</p>';
      });
  }

  function closeGuide() {
    el("guide").hidden = true;
    document.body.classList.remove("has-guide");
  }

  function introduce() {
    var out = el("introOut"), btn = el("introBtn");
    out.innerHTML = '<p class="sum">Asking…</p>';
    btn.disabled = true;
    fetch("/api/assistant/introduce", { method: "POST" })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (!res.ok) {
          out.innerHTML = '<div class="fail"><b>L’assistant ne peut pas répondre</b>' +
            esc(res.body.note || "") + "</div>";
          return;
        }
        var html = "";
        if (res.body.stand_in) {
          html += '<div class="standin-note"><b>Stand-in, not a language model</b>' +
            "Ce texte ne vient pas de l’assistant. La liste ci-dessus appartient à la station." +
            "</div>";
        }
        var introduction = res.body.text || "";
        out.innerHTML = html + '<p class="sum">' + esc(introduction) + "</p>";
        // Guarded on the same line, the shape the freeze-guard test reads.
        if (introduction && MedBox.voice) MedBox.voice.speakText(introduction);
      })
      .catch(function () {
        btn.disabled = false;
        out.innerHTML = '<div class="fail"><b>Assistant indisponible</b>' +
          "Les fonctions déterministes ci-dessus restent actives.</div>";
      });
  }

  /* ---------------------------------------------------------- commands */
  /* A phrase is a phrase whether it was typed or heard, so speech will
     arrive through this same function rather than a parallel one. Six of the
     eight commands do not touch the assistant, which is the point: an
     operator should not have to learn which of their tools stop working when
     the model does. */
  function say(text, bad) {
    var out = el("cmdOut");
    out.textContent = text || "";
    out.className = "cmd-out" + (bad ? " bad" : "");
  }

  function ordered() {
    // The board arrives sorted by NEWS2 descending, worst first.
    return state.board.map(function (r) { return r.patient.id; });
  }

  function describe(id) {
    var row = state.byId[id];
    if (!row) return id;
    return row.patient.name + " · NEWS2 " + row.triage.total + " " + row.triage.urgency;
  }

  function runCommand(raw, spoken) {
    var text = String(raw || "").trim();
    if (!text) return;
    var word = text.split(/\s+/)[0].toLowerCase().normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z]/g, "");
    var rest = text.slice(word.length).trim();
    var ids = ordered();

    if (word === "aide" || word === "help") { openGuide(); say("Aide ouverte."); return; }

    if (word === "prioritaire" || word === "pire" || word === "worst") {
      if (!ids.length) return say("Aucun membre n’est encore affiché.", true);
      selectCrew(ids[0]);
      return say("Prioritaire : " + describe(ids[0]));
    }

    if (word === "suivant" || word === "next") {
      if (!ids.length) return say("Aucun membre n’est encore affiché.", true);
      var at = ids.indexOf(state.selected);
      var nxt = ids[(at + 1) % ids.length];
      selectCrew(nxt);
      return say(describe(nxt));
    }

    if (word === "pourquoi" || word === "why") {
      if (!state.selected) return say("Sélectionnez un membre ou saisissez « prioritaire ».", true);
      var t = state.byId[state.selected].triage;
      var parts = (t.params || []).filter(function (q) { return q.score > 0; })
        .map(function (q) { return q.name + " +" + q.score + " (" + q.reason + ")"; });
      return say(parts.length
        ? "NEWS2 " + t.total + " = " + parts.join(", ")
        : "NEWS2 0. Chaque paramètre mesuré est dans sa plage habituelle.");
    }

    if (word === "isoles" || word === "isolated") {
      var q = state.quarantine;
      if (!q) return say("Aucune donnée d’isolement disponible.", true);
      var zones = Object.keys(q.zones).map(function (z) {
        return z + " " + q.zones[z].occupied + "/" + q.zones[z].capacity +
               (q.zones[z].sealed ? " scellée" : " ouverte");
      });
      var confirmed = q.assignments.filter(function (a) { return a.confirmed; }).length;
      return say(confirmed + " isolement(s) confirmé(s) · " + zones.join(" · ") +
                 (q.candidates ? " · " + q.candidates + " à confirmer" : "") +
                 (q.awaiting_bed ? " · " + q.awaiting_bed + " en attente d’une place" : ""));
    }

    if (word === "declare" || word === "said") {
      if (!state.selected) return say("Sélectionnez un membre ou saisissez « prioritaire ».", true);
      if (!rest) return say("Précisez ses mots : déclaré j’ai mal à la tête", true);
      fetch("/api/patient/" + encodeURIComponent(state.selected) + "/symptom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(spoken
          ? { text: rest, source: "voice", confidence: spoken }
          : { text: rest, source: "typed" })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) { renderReported(d.reported || []); say("Déclaration enregistrée : « " + rest + " »"); })
        .catch(function () { say("La déclaration n’a pas pu être enregistrée.", true); });
      return;
    }

    if (word === "evaluer" || word === "demander" || word === "assess" || word === "ask") {
      if (!state.selected) return say("Sélectionnez un membre ou saisissez « prioritaire ».", true);
      if (!state.aiUp) {
        return say("L’assistant ne répond pas. La surveillance continue ; essayez « pourquoi ».", true);
      }
      askAI();
      return say("Évaluation locale de " + state.byId[state.selected].patient.name + "…");
    }

    say("Commande « " + word + " » inconnue. Ouvrez Aide pour la liste.", true);
  }

  /* The text mode. The station writes the facts, the model phrases two
     sentences under a shape, the validator rebuilds them; when the model is
     dead the station answers with the facts itself and says so. */
  function askQuestion(text) {
    text = String(text || "").trim();
    if (!text) return;
    say("Question posée… l’assistant répond en quelques secondes.");
    fetch("/api/assistant/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, patient_id: state.selected })
    })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        var b = res.body || {};
        if (!res.ok) return say(b.detail || "Question refusée.", true);
        var note = b.held_reason ? " (l’assistant est arrêté : réponse de la station)" : "";
        var blocked = b.blocked && b.blocked.length ? " — " + b.blocked.join(" ") : "";
        say(b.answer + note + blocked, !!blocked);
        if (MedBox.voice) MedBox.voice.speakText(b.answer);
      })
      .catch(function () { say("L’assistant n’a pas répondu. La surveillance continue.", true); });
  }

  function bandColor(u) {
    return { routine:"#4a6b78", low:"#7fc6d6", medium:"#f0c459", high:"#ff5c6e" }[u] || "#4a6b78";
  }

  /* ------------------------------------------------------------ slow track */
  function askAI() {
    if (!state.selected) return;
    // Pinned now: see app.js. A late answer for someone the operator has left
    // is dropped, not drawn under the person they are looking at, and not
    // flown to either.
    var id = state.selected;
    var out = el("aiOut"), btn = el("aiBtn");
    out.innerHTML = '<p class="sum">Analyse locale en cours…</p>';
    btn.disabled = true;

    fetch("/api/assess/" + encodeURIComponent(id), { method: "POST" })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (state.selected !== id) return;
        if (!res.ok) {
          state.held = null;
          out.innerHTML = MedBox.assessment.failure(res.body.note);
          return;
        }
        // Hold on to it so the panel can notice when the readings it was
        // written against stop being the readings on screen.
        state.held = res.body;
        out.innerHTML = MedBox.assessment.render(res.body, { flyable: true });
        if (MedBox.assessment.spoken && MedBox.voice) MedBox.voice.speakText(MedBox.assessment.spoken(res.body));
      })
      .catch(function () {
        btn.disabled = false;
        if (state.selected !== id) return;
        state.held = null;
        out.innerHTML = MedBox.assessment.failure("Les mesures et la priorité restent actives.");
      });
  }

  /* An assessment describes a moment. The band above it describes now.
   *
   * Called on every board frame, because the gap between those two is exactly
   * what the demo is designed to open up: assess someone at ROUTINE, let the
   * scenario afflict them, and the text below goes quietly false while nothing
   * on screen changes. */
  function checkHeld(liveRow) {
    var out = el("aiOut");
    if (!state.held || !out.innerHTML) return;
    if (state.held.patient_id !== state.selected) return;
    var live = liveRow && liveRow.triage ? liveRow.triage.total : null;
    var msg = MedBox.assessment.staleness(state.held, live, Date.now());
    out.classList.toggle("stale", !!msg);
    var banner = el("aiStale");
    if (banner) {
      banner.hidden = !msg;
      if (msg) banner.textContent = msg;
    }
  }

  /* --------------------------------------------------------------- wiring */
  el("aiBtn").addEventListener("click", askAI);
  // Replies to the assistant's questions. Not guarded: the assessment
  // panel cannot exist without assessment.js, see CLAUDE.md.
  MedBox.assessment.wireAnswers(el("aiOut"), function (pid, list) {
    if (state.selected === pid) renderReported(list);
  });
  el("sayForm").addEventListener("submit", sayIt);
  (function wireVoice() {
    var btn = el("voiceBtn");
    // Same rule as the frame path. This block runs at load, so without the
    // check an absent voice.js throws here and everything wired below it —
    // the microphone, the guide button, the command bar — never gets wired.
    if (!MedBox.voice) { if (btn) btn.hidden = true; return; }
    function paint() {
      var on = MedBox.voice.isOn();
      btn.textContent = on ? "Son activé" : "Son coupé";
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("primary", on);
    }
    // Pressing the button is itself the gesture a browser needs before it will
    // play anything, so switching sound on and unlocking playback are the same
    // action rather than two the operator has to discover separately.
    btn.addEventListener("click", function () { MedBox.voice.setOn(!MedBox.voice.isOn()); paint(); });
    MedBox.voice.setOn(MedBox.voice.restore());
    paint();
  })();
  if (MedBox.mic) MedBox.mic.attach(function () { return state.selected; }, renderReported);
  window.addEventListener("medbox-command", function (event) {
    var detail = event.detail || {};
    if (detail.action === "open_help") openGuide();
    if (detail.patient_id && (detail.action === "select" || detail.action === "show_why" ||
        detail.action === "assess")) {
      selectCrew(detail.patient_id);
    }
    if (detail.action === "assess" && detail.patient_id) askAI();
  });
  if (MedBox.patientTools) {
    MedBox.patientTools.attach(function () { return state.selected; }, renderPanel);
  }

  function formatClock(seconds) {
    seconds = Math.max(0, Math.round(Number(seconds) || 0));
    var minutes = Math.floor(seconds / 60);
    return String(minutes).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  }
  el("helpBtn").addEventListener("click", openGuide);
  el("cmdForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var input = el("cmdInput"), text = input.value;
    input.value = "";
    if (state.askMode || /^\?/.test(text.trim())) askQuestion(text.replace(/^\s*\?\s*/, ""));
    else runCommand(text, 0);
  });
  el("cmdMode").addEventListener("click", function () {
    state.askMode = !state.askMode;
    el("cmdMode").textContent = state.askMode ? "Question" : "Commande";
    el("cmdMode").classList.toggle("ask", state.askMode);
    el("cmdInput").placeholder = state.askMode
      ? "Question à l’assistant — exemple : pourquoi ce score ?"
      : "Commande locale — exemple : worst";
    el("cmdInput").focus();
  });
  el("guideClose").addEventListener("click", closeGuide);
  el("introBtn").addEventListener("click", introduce);
  el("closeBtn").addEventListener("click", closePanel);
  el("aiOut").addEventListener("click", function (e) {
    if (e.target.closest(".hyp") && state.selected) flyTo(state.selected);
  });
  el("runBtn").addEventListener("click", function () {
    var n = el("scenarioPick").value;
    if (n) fetch("/api/scenario/" + encodeURIComponent(n), { method: "POST" });
  });
  el("stopBtn").addEventListener("click", function () {
    fetch("/api/scenario/stop", { method: "POST" });
    el("aiOut").innerHTML = "";
  });
  // Rehearsal equals the live run: the replay is a function of elapsed
  // simulation time, so stopping and starting again gives the same curves.
  el("replayBtn").addEventListener("click", function () {
    var n = el("scenarioPick").value;
    el("aiOut").innerHTML = "";
    fetch("/api/scenario/stop", { method: "POST" }).then(function () {
      if (n) return fetch("/api/scenario/" + encodeURIComponent(n), { method: "POST" });
    });
  });
  window.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""));
    if (e.key === "/" && !typing) { e.preventDefault(); el("cmdInput").focus(); return; }
    if (e.key !== "Escape") return;
    if (typing) { e.target.blur(); return; }
    if (!el("guide").hidden) closeGuide(); else closePanel();
  });
  window.addEventListener("resize", resize);

  fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
    // French names from the catalogue, the demo first and selected. The file
    // names were shown before, so the picker opened on "baisse-thermique",
    // whichever sorted first, and the demo had to be hunted for.
    var list = s.scenario_catalog || (s.scenarios || []).map(function (n) { return { stem: n, name: n }; });
    el("scenarioPick").innerHTML = list.map(function (sc) {
      return '<option value="' + esc(sc.stem) + '"' + (sc.demo ? ' selected' : '') + '>' +
        esc(sc.name) + "</option>";
    }).join("");
  }).catch(function () {});

  connect();
  requestAnimationFrame(frame);
})();
