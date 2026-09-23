/* MedBox console — the 2D view.
   Connects to /ws, renders the crew board, and asks the slow track for an
   assessment only when the operator presses the button. Nothing here ever
   waits on the AI to draw a vital sign. */

(function () {
  "use strict";

  var el = function (id) { return document.getElementById(id); };
  // `held` is the assessment currently on screen, as the server stamped it,
  // so the detail pane can tell when the readings it describes have moved on.
  var state = { board: [], selected: null, quarantine: null, aiUp: false, held: null, asking: false };

  /* ---------- websocket, with automatic reconnect ---------- */
  var ws = null, retry = 0;

  function connect() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws");

    ws.onopen = function () {
      retry = 0;
      setChip("linkChip", true, "Liaison écran");
    };
    ws.onclose = function () {
      setChip("linkChip", false, "Liaison écran perdue");
      // Back off, but never give up: the server may just be restarting.
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 400 * retry);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
    ws.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "board") onBoard(msg);
      // A symptom reported from the other view, or another screen entirely.
      else if (msg.type === "symptom" && msg.reported &&
               msg.reported.patient_id === state.selected) loadReported();
      else if (msg.type === "quarantine" && state.selected && MedBox.patientTools)
        MedBox.patientTools.refresh(state.selected);
      // Something the station could not do, e.g. a scenario step it skipped.
      // Held for fifteen seconds, because the chip it lands in is rewritten
      // on every frame and would otherwise show it for a tenth of a second.
      else if (msg.type === "event" && msg.kind === "warning")
        state.warning = { text: String(msg.text || ""), until: Date.now() + 15000 };
    };
  }

  function setChip(id, up, text) {
    var c = el(id);
    if (!c) return;
    c.className = "chip " + (up ? "up" : "down");
    c.innerHTML = '<i class="led"></i>' + text;
  }

  /* ---------- a frozen board must not look like a calm one ---------- */
  /* Stamped at the END of a repaint, not when a frame arrives: a frame that
     arrives and then throws half way through rendering leaves the board just as
     frozen. Either way, after two seconds the link chip stops saying all is
     well and the numbers dim, so nobody reads a stale SpO2 as a current one.
     Before this, a stalled server kept a green "Screen link" over the last
     numbers it had sent, for as long as anyone cared to look. */
  var lastPainted = 0;
  setInterval(function () {
    if (!ws || ws.readyState !== 1 || !lastPainted) return;  // onclose says it
    var gap = Date.now() - lastPainted;
    var stale = gap > 2000;
    document.body.classList.toggle("stale-feed", stale);
    if (stale) setChip("linkChip", false, "Aucune mise à jour depuis " + Math.round(gap / 1000) + " s");
    else if (el("linkChip").className !== "chip up") setChip("linkChip", true, "Liaison écran");
  }, 500);

  /* ---------- board ---------- */
  function onBoard(msg) {
    state.board = msg.board || [];
    state.quarantine = msg.quarantine;
    state.aiUp = !!(msg.ai && msg.ai.available);

    el("ship").textContent = msg.ship || "";
    state.standIn = !!(msg.ai && msg.ai.stand_in);
    // Guarded for the same reason the 3D view guards it: this is the slow
    // track, and an absent script must not stop a reading reaching the board.
    if (msg.ears && MedBox.mic) MedBox.mic.setAvailable(msg.ears.available, msg.ears.error);
    // The board and the 3D console must never disagree about what is
    // answering. Both say "stand-in" the moment it is one.
    var aiChip = el("aiChip");
    if (msg.ai && msg.ai.warming) {
      aiChip.className = "chip";
      aiChip.innerHTML = '<i class="led"></i>Assistant en préchauffage';
    } else if (state.aiUp && state.standIn) {
      aiChip.className = "chip standin";
      aiChip.innerHTML = '<i class="led"></i>Simulation de secours, pas un modèle';
    } else {
      setChip("aiChip", state.aiUp,
        state.aiUp ? "Assistant local prêt" : "Assistant indisponible — surveillance active");
    }
    var warning = state.warning && Date.now() < state.warning.until ? state.warning.text : "";
    var scChip = el("scenarioChip");
    scChip.textContent = warning ||
      (msg.scenario ? ("SIMULÉ · " + msg.scenario +
        (msg.scenario_meta && msg.scenario_meta.simulation
          ? " · " + (msg.scenario_meta.simulation.represented_duration || "temps accéléré")
          : "")) : "Aucun scénario");
    scChip.classList.toggle("down", !!warning);

    var impaired = 0;
    state.board.forEach(function (r) {
      if (r.triage.urgency !== "routine") impaired++;
    });
    var isolated = state.quarantine ? state.quarantine.assignments.filter(function (a) {
      return a.confirmed;
    }).length : 0;
    el("crewTotal").textContent = state.board.length;
    el("crewImpaired").textContent = impaired;
    el("crewIsolated").textContent = isolated;

    renderRows();
    renderZones();
    if (state.selected) renderDetail();
    lastPainted = Date.now();
  }

  var isolatedSet = function () {
    var s = {};
    if (state.quarantine) {
      state.quarantine.assignments.forEach(function (a) {
        if (a.confirmed && a.zone) s[a.patient_id] = a.zone;
      });
    }
    return s;
  };

  function vitalClass(params, name) {
    for (var i = 0; i < params.length; i++) {
      if (params[i].name === name && params[i].measured) {
        if (params[i].score >= 3) return "vit worst";
        if (params[i].score >= 1) return "vit bad";
      }
    }
    return "vit";
  }

  function num(v, digits) {
    return (v === null || v === undefined) ? "—" : Number(v).toFixed(digits || 0);
  }

  function renderRows() {
    var host = el("rows"), iso = isolatedSet();
    if (!state.board.length) { el("empty").hidden = false; host.innerHTML = ""; return; }
    el("empty").hidden = true;

    var html = state.board.map(function (r) {
      var p = r.patient, t = r.triage;
      var zone = iso[p.id];
      return '<div class="row u-' + t.urgency + (state.selected === p.id ? ' sel' : '') +
        '" data-id="' + p.id + '" role="button" tabindex="0">' +
        '<span class="pid">' + p.id + '</span>' +
        '<span class="who"><b>' + esc(p.name) + '</b><span>' + esc(p.role) +
          (zone ? ' · <span class="iso">ZONE ' + zone + '</span>' : '') + '</span></span>' +
        '<span class="' + vitalClass(t.params, "temperature") + '">' + num(p.temperature, 1) + '</span>' +
        '<span class="' + vitalClass(t.params, "spo2") + '">' + num(p.spo2, 0) + '</span>' +
        '<span class="' + vitalClass(t.params, "pulse") + '">' + num(p.pulse, 0) + '</span>' +
        '<span class="' + vitalClass(t.params, "respiration") + '">' + num(p.respiration, 0) + '</span>' +
        '<span class="badge b-' + t.urgency + '">' + t.urgency + ' ' + t.total + '</span>' +
        '</div>';
    }).join("");
    // The rows are rebuilt ten times a second, which takes keyboard focus with
    // them: Tab to a row and it was gone 100 ms later. Put it back on the row
    // with the same id.
    var active = document.activeElement;
    var focused = active && host.contains(active) ? active.getAttribute("data-id") : null;
    host.innerHTML = html;
    if (focused) {
      var again = host.querySelector('[data-id="' + focused + '"]');
      if (again) again.focus();
    }
  }

  function renderZones() {
    if (!state.quarantine) return;
    var zones = state.quarantine.zones;
    var html = Object.keys(zones).map(function (z) {
      var d = zones[z], pct = Math.round((d.occupied / d.capacity) * 100);
      return '<div class="zone' + (d.sealed ? ' sealed' : '') + '">' +
        '<span class="zn">' + z + '</span>' +
        '<span class="zbar"><span class="zfill" style="width:' + pct + '%"></span></span>' +
        '<span class="zc">' + d.occupied + '/' + d.capacity + '</span></div>';
    }).join("");

    /* A crew member with nowhere to go is the most important fact this panel
       can carry, and until now it was reachable only by typing `isolated` on
       the other view: the server counted them, nothing drew them. Rendered
       only when it is non-zero, because a permanent "0 awaiting a bed" row
       teaches an operator to stop reading this line. */
    var waiting = state.quarantine.awaiting_bed || 0;
    if (waiting) {
      html += '<div class="zone overflow"><span class="zn">!</span>' +
        '<span class="zover">' + waiting +
        (waiting === 1 ? " membre en attente d’une place" : " membres en attente d’une place") +
        '</span><span class="zc">zones complètes</span></div>';
    }
    var candidates = state.quarantine.candidates || 0;
    if (candidates) {
      html += '<div class="zone candidate"><span class="zn">?</span>' +
        '<span class="zover">' + candidates +
        (candidates === 1 ? " recommandation à confirmer" : " recommandations à confirmer") +
        '</span><span class="zc">décision humaine</span></div>';
    }
    el("zones").innerHTML = html;
  }

  /* ---------- patient detail ---------- */
  function renderDetail() {
    var row = null;
    for (var i = 0; i < state.board.length; i++) {
      if (state.board[i].patient.id === state.selected) { row = state.board[i]; break; }
    }
    if (!row) return;
    checkHeld(row);
    var p = row.patient, t = row.triage;

    el("detailName").textContent = p.name;
    el("detailRole").textContent = p.id + " · " + p.role;
    // Not simply re-enabled: this runs every frame, so the button came back
    // 100 ms after a press and a second request could overlap the first.
    el("aiBtn").disabled = state.asking;

    var cells = [
      ["Température", num(p.temperature, 1) + " °C", "temperature"],
      ["SpO₂", num(p.spo2, 0) + " %", "spo2"],
      ["Pouls", num(p.pulse, 0) + " /min", "pulse"],
      ["Respiration", num(p.respiration, 0) + " /min", "respiration"],
      ["Tension syst.", num(p.systolic_bp, 0) + " mmHg", "systolic_bp"],
      ["Conscience", "", "consciousness"],
      ["Oxygène", "", "oxygen"]
    ];
    el("vitals").innerHTML = cells.map(function (c) {
      var score = 0, reason = "", measured = true;
      t.params.forEach(function (q) {
        if (q.name === c[2]) { score = q.score; reason = q.reason; measured = q.measured; }
      });
      // The two observed parameters show their reason as the value: "alerte
      // (observé)" or "vigilance supposée" is the whole information.
      var shown = c[1] || reason;
      return '<div class="vcell s' + score + (measured ? "" : " assumed") + '"><span class="k">' + c[0] + '</span>' +
        '<div class="v">' + esc(shown) + '</div><div class="r">' + (c[1] ? esc(reason) : (measured ? "observé" : "supposé")) + '</div></div>';
    }).join("");

    el("why").innerHTML =
      esc(t.score_label || "Dépistage partiel dérivé de NEWS2") + " : " + t.total +
      " → " + t.urgency.toUpperCase() + "<br>" + esc(t.response) +
      "<br>Mesuré : " + t.measured.join(", ") +
      (t.missing_news2 && t.missing_news2.length
        ? "<br>Non disponible : " + t.missing_news2.join(", ") : "");
  }

  /* ---------- the slow track, on demand only ---------- */
  function askAI() {
    if (!state.selected) return;
    // Pinned now. The answer takes seconds, the operator may have moved on by
    // the time it lands, and drawn under whoever is selected then it read as
    // that person's assessment: one crew member's hypotheses under another's
    // name, band and vitals, with no stale warning.
    var id = state.selected;
    var out = el("aiOut");
    out.innerHTML = '<p class="sum">Analyse locale en cours…</p>';
    state.asking = true;
    el("aiBtn").disabled = true;

    fetch("/api/assess/" + encodeURIComponent(id), { method: "POST" })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        state.asking = false;
        el("aiBtn").disabled = false;
        if (state.selected !== id) return;
        if (!res.ok) {
          state.held = null;
          out.innerHTML = MedBox.assessment.failure(res.body.note);
          return;
        }
        state.held = res.body;
        out.innerHTML = MedBox.assessment.render(res.body);
      })
      .catch(function () {
        state.asking = false;
        el("aiBtn").disabled = false;
        if (state.selected !== id) return;
        state.held = null;
        out.innerHTML = MedBox.assessment.failure("Les mesures et la priorité restent actives.");
      });
  }

  /* The band beside this text updates on every frame. The text does not. */
  function checkHeld(row) {
    var out = el("aiOut");
    if (!state.held || !out.innerHTML) return;
    if (state.held.patient_id !== state.selected) return;
    var live = row && row.triage ? row.triage.total : null;
    var msg = MedBox.assessment.staleness(state.held, live, Date.now());
    out.classList.toggle("stale", !!msg);
    var banner = el("aiStale");
    if (banner) {
      banner.hidden = !msg;
      if (msg) banner.textContent = msg;
    }
  }

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* ---------- wiring ---------- */
  function select(id) {
    state.selected = id;
    state.held = null;
    el("aiOut").innerHTML = "";
    el("aiStale").hidden = true;
    el("sayInput").value = "";
    el("sayInput").disabled = false;
    el("sayBtn").disabled = false;
    renderReported([]);
    loadReported();
    renderRows();
    renderDetail();
    if (MedBox.patientTools) MedBox.patientTools.select(id);
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

  // pointerdown, not click. A click needs the same element under the pointer
  // when the button goes down and when it comes up, and the rows are rebuilt
  // ten times a second: a rebuild in between swallowed the click, so a row
  // pressed in front of the jury sometimes simply did not open.
  el("rows").addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    var row = e.target.closest(".row");
    if (row) select(row.dataset.id);
  });
  el("rows").addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var row = e.target.closest(".row");
    if (row) { e.preventDefault(); select(row.dataset.id); }
  });
  if (MedBox.mic) MedBox.mic.attach(function () { return state.selected; }, renderReported);
  window.addEventListener("medbox-command", function (event) {
    var detail = event.detail || {};
    if (detail.patient_id && (detail.action === "select" || detail.action === "show_why" ||
        detail.action === "assess")) {
      select(detail.patient_id);
    }
    if (detail.action === "assess" && detail.patient_id) askAI();
  });
  if (MedBox.patientTools) {
    MedBox.patientTools.attach(function () { return state.selected; }, renderDetail);
  }
  el("aiBtn").addEventListener("click", askAI);
  // Replies to the assistant's questions. Not guarded: the assessment
  // panel cannot exist without assessment.js, see CLAUDE.md.
  MedBox.assessment.wireAnswers(el("aiOut"), function (pid, list) {
    if (state.selected === pid) renderReported(list);
  });
  el("sayForm").addEventListener("submit", sayIt);

  el("runBtn").addEventListener("click", function () {
    var name = el("scenarioPick").value;
    if (name) fetch("/api/scenario/" + encodeURIComponent(name), { method: "POST" });
  });
  el("stopBtn").addEventListener("click", function () {
    fetch("/api/scenario/stop", { method: "POST" });
    el("aiOut").innerHTML = "";
  });
  el("replayBtn").addEventListener("click", function () {
    var n = el("scenarioPick").value;
    el("aiOut").innerHTML = "";
    fetch("/api/scenario/stop", { method: "POST" }).then(function () {
      if (n) return fetch("/api/scenario/" + encodeURIComponent(n), { method: "POST" });
    });
  });

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
})();
