/* MedBox console — the 2D view.
   Connects to /ws, renders the crew board, and asks the slow track for an
   assessment only when the operator presses the button. Nothing here ever
   waits on the AI to draw a vital sign. */

(function () {
  "use strict";

  var el = function (id) { return document.getElementById(id); };
  var state = { board: [], selected: null, quarantine: null, aiUp: false };

  /* ---------- websocket, with automatic reconnect ---------- */
  var ws = null, retry = 0;

  function connect() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws");

    ws.onopen = function () {
      retry = 0;
      setChip("linkChip", true, "Screen link");
    };
    ws.onclose = function () {
      setChip("linkChip", false, "Screen link lost");
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
    };
  }

  function setChip(id, up, text) {
    var c = el(id);
    if (!c) return;
    c.className = "chip " + (up ? "up" : "down");
    c.innerHTML = '<i class="led"></i>' + text;
  }

  /* ---------- board ---------- */
  function onBoard(msg) {
    state.board = msg.board || [];
    state.quarantine = msg.quarantine;
    state.aiUp = !!(msg.ai && msg.ai.available);

    el("ship").textContent = msg.ship || "";
    state.standIn = !!(msg.ai && msg.ai.stand_in);
    // The board and the 3D console must never disagree about what is
    // answering. Both say "stand-in" the moment it is one.
    var aiChip = el("aiChip");
    if (state.aiUp && state.standIn) {
      aiChip.className = "chip standin";
      aiChip.innerHTML = '<i class="led"></i>Stand-in, not a model';
    } else {
      setChip("aiChip", state.aiUp, state.aiUp ? "AI narration" : "AI offline — triage unaffected");
    }
    el("scenarioChip").textContent = msg.scenario ? ("Running: " + msg.scenario) : "No scenario running";

    var impaired = 0;
    state.board.forEach(function (r) {
      if (r.triage.urgency !== "routine") impaired++;
    });
    var isolated = state.quarantine ? state.quarantine.assignments.length : 0;
    el("crewTotal").textContent = state.board.length;
    el("crewImpaired").textContent = impaired;
    el("crewIsolated").textContent = isolated;

    renderRows();
    renderZones();
    if (state.selected) renderDetail();
  }

  var isolatedSet = function () {
    var s = {};
    if (state.quarantine) {
      state.quarantine.assignments.forEach(function (a) { s[a.patient_id] = a.zone; });
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
    host.innerHTML = html;
  }

  function renderZones() {
    if (!state.quarantine) return;
    var zones = state.quarantine.zones;
    el("zones").innerHTML = Object.keys(zones).map(function (z) {
      var d = zones[z], pct = Math.round((d.occupied / d.capacity) * 100);
      return '<div class="zone' + (d.sealed ? ' sealed' : '') + '">' +
        '<span class="zn">' + z + '</span>' +
        '<span class="zbar"><span class="zfill" style="width:' + pct + '%"></span></span>' +
        '<span class="zc">' + d.occupied + '/' + d.capacity + '</span></div>';
    }).join("");
  }

  /* ---------- patient detail ---------- */
  function renderDetail() {
    var row = null;
    for (var i = 0; i < state.board.length; i++) {
      if (state.board[i].patient.id === state.selected) { row = state.board[i]; break; }
    }
    if (!row) return;
    var p = row.patient, t = row.triage;

    el("detailName").textContent = p.name;
    el("detailRole").textContent = p.id + " · " + p.role;
    el("aiBtn").disabled = false;

    var cells = [
      ["Temperature", num(p.temperature, 1) + " °C", "temperature"],
      ["SpO₂", num(p.spo2, 0) + " %", "spo2"],
      ["Pulse", num(p.pulse, 0) + " /min", "pulse"],
      ["Respiration", num(p.respiration, 0) + " /min", "respiration"]
    ];
    el("vitals").innerHTML = cells.map(function (c) {
      var score = 0, reason = "";
      t.params.forEach(function (q) {
        if (q.name === c[2]) { score = q.score; reason = q.reason; }
      });
      return '<div class="vcell s' + score + '"><span class="k">' + c[0] + '</span>' +
        '<div class="v">' + c[1] + '</div><div class="r">' + esc(reason) + '</div></div>';
    }).join("");

    el("why").innerHTML =
      "NEWS2 aggregate " + t.total + " → " + t.urgency.toUpperCase() + "<br>" +
      esc(t.response) + "<br>measured: " + t.measured.join(", ");
  }

  /* ---------- the slow track, on demand only ---------- */
  function askAI() {
    if (!state.selected) return;
    var out = el("aiOut");
    out.innerHTML = '<p class="sum">Thinking…</p>';
    el("aiBtn").disabled = true;

    fetch("/api/assess/" + encodeURIComponent(state.selected), { method: "POST" })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        el("aiBtn").disabled = false;
        if (!res.ok) {
          out.innerHTML = '<div class="fail"><b>Assistant unavailable</b>' +
            esc(res.body.note || "") + "</div>";
          return;
        }
        var b = res.body;
        var html = "";
        if (b.stand_in) {
          html += '<div class="standin-note"><b>Stand-in, not a language model</b>' +
            'This came from tools/fake_ollama.py, which reads the vitals back and ' +
            'applies fixed rules. It proves the path works. It is not the assistant ' +
            'thinking, and must never be presented as such.</div>';
        }
        html += '<p class="sum">' + esc(b.summary || "") + "</p>";
        if (b.hypotheses && b.hypotheses.length) {
          html += "<h3>Hypotheses</h3>";
          html += b.hypotheses.map(function (h) {
            return '<div class="hyp"><b>' + esc(h.name) + '</b>' +
              '<span class="conf">' + esc(h.confidence) + ' confidence</span>' +
              "<ul>" + (h.supporting_signs || []).map(function (s) {
                return "<li>" + esc(s) + "</li>";
              }).join("") + "</ul></div>";
          }).join("");
        }
        if (b.questions_for_patient && b.questions_for_patient.length) {
          html += "<h3>Ask the patient</h3><ul>" +
            b.questions_for_patient.map(function (q) { return "<li>" + esc(q) + "</li>"; }).join("") +
            "</ul>";
        }
        if (b.suggested_protocol && b.suggested_protocol.length) {
          html += "<h3>Suggested protocol</h3><ul>" +
            b.suggested_protocol.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") +
            "</ul>";
        }
        out.innerHTML = html;
      })
      .catch(function () {
        el("aiBtn").disabled = false;
        out.innerHTML = '<div class="fail"><b>Assistant unreachable</b>' +
          "Vitals and triage are unaffected.</div>";
      });
  }

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* ---------- wiring ---------- */
  function select(id) {
    state.selected = id;
    el("aiOut").innerHTML = "";
    el("sayInput").value = "";
    el("sayInput").disabled = false;
    el("sayBtn").disabled = false;
    renderReported([]);
    loadReported();
    renderRows();
    renderDetail();
  }

  /* --------------------------------------------- what the crew member said */
  function renderReported(list) {
    var box = el("pSaid");
    if (!list || !list.length) {
      box.innerHTML = '<p class="none">Nothing reported yet.</p>';
      return;
    }
    box.innerHTML = list.map(function (r) {
      var who = r.source === "voice" ? "heard" : "typed";
      if (r.source === "voice" && r.confidence != null) {
        who = 'heard · <span class="heard">' + Math.round(r.confidence * 100) + '% sure</span>';
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

  el("rows").addEventListener("click", function (e) {
    var row = e.target.closest(".row");
    if (row) select(row.dataset.id);
  });
  el("rows").addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var row = e.target.closest(".row");
    if (row) { e.preventDefault(); select(row.dataset.id); }
  });
  el("aiBtn").addEventListener("click", askAI);
  el("sayForm").addEventListener("submit", sayIt);

  el("runBtn").addEventListener("click", function () {
    var name = el("scenarioPick").value;
    if (name) fetch("/api/scenario/" + encodeURIComponent(name), { method: "POST" });
  });
  el("stopBtn").addEventListener("click", function () {
    fetch("/api/scenario/stop", { method: "POST" });
    el("aiOut").innerHTML = "";
  });

  fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
    el("scenarioPick").innerHTML = (s.scenarios || []).map(function (n) {
      return '<option value="' + esc(n) + '">' + esc(n) + "</option>";
    }).join("");
  }).catch(function () {});

  connect();
})();
