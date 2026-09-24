/* One person's page. The referent knows who it is talking to: it greets by
 * name, says where they stand, reads their assessment in the second person,
 * answers their questions, and its messages to them ping and are spoken. */
(function (root) {
  "use strict";
  function el(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  var pid = decodeURIComponent((location.pathname.match(/\/me\/([^\/]+)/) || [])[1] || "");
  var state = { me: null, seen: {}, introduced: false };
  var URGENCY = { routine: "routine", low: "faible", medium: "moyenne", high: "haute" };
  var UNITS = { temperature: ["Température", "°C", 1], spo2: ["SpO₂", "%", 1], pulse: ["Pouls", "/min", 0], respiration: ["Respiration", "/min", 0], systolic_bp: ["Tension", "mmHg", 0] };

  var audioCtx = null;
  function ping() {
    try {
      audioCtx = audioCtx || new (root.AudioContext || root.webkitAudioContext)();
      var now = audioCtx.currentTime;
      [880, 1320, 880].forEach(function (freq, i) {
        var osc = audioCtx.createOscillator(), gain = audioCtx.createGain();
        osc.type = "square"; osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, now + i * 0.22);
        gain.gain.exponentialRampToValueAtTime(0.9, now + i * 0.22 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.22 + 0.2);
        osc.connect(gain); gain.connect(audioCtx.destination);
        osc.start(now + i * 0.22); osc.stop(now + i * 0.22 + 0.21);
      });
    } catch (e) {}
    document.body.classList.add("alert");
    setTimeout(function () { document.body.classList.remove("alert"); }, 1200);
  }
  function fmt(v, d) { return v == null ? "–" : Number(v).toFixed(d); }

  function renderToday(me) {
    var rows = Object.keys(UNITS).map(function (k) {
      var u = UNITS[k], now = me.vitals[k], base = me.baseline[k];
      return "<tr><th>" + u[0] + "</th><td>" + (now == null ? "–" : fmt(now, u[2]) + " " + u[1]) + "</td>" +
        "<td class=\"hint\">habituel " + (base == null ? "–" : fmt(base, u[2])) + "</td></tr>";
    });
    el("today").querySelector("tbody").innerHTML = rows.join("");
    var t = me.today;
    el("meToday").textContent = t.total == null ? "–" : t.total + " · " + URGENCY[t.urgency || "routine"];
    el("meWeek").textContent = me.week_ok ? "stable" : "écarts";
  }
  function renderWeek(week) {
    el("week").querySelector("tbody").innerHTML = (week.daily || []).map(function (d) {
      return "<tr><td>" + esc(d.day.slice(5)) + "</td><td>" + fmt(d.temperature, 1) + "</td><td>" + fmt(d.spo2, 1) +
        "</td><td>" + fmt(d.pulse, 0) + "</td><td>" + fmt(d.respiration, 0) + "</td><td>" + fmt(d.systolic_bp, 0) + "</td></tr>";
    }).join("") || '<tr><td colspan="6" class="hint">Pas encore d’historique.</td></tr>';
  }
  function renderMessages(list) {
    var ul = el("msgList");
    if (!list.length) { ul.innerHTML = '<li class="hint">Aucun message.</li>'; el("unread").hidden = true; return; }
    var unread = 0;
    ul.innerHTML = list.map(function (m) {
      if (!m.read_at) unread++;
      var when = new Date(m.at * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
      return '<li class="msg' + (m.read_at ? "" : " unread") + '"><div class="msg-h"><span class="when">' + when + "</span>" +
        '<button class="btn small read" data-id="' + m.id + '">' + (m.read_at ? "Relire" : "Lire") + "</button></div>" +
        '<div class="msg-t">' + esc(m.text) + "</div></li>";
    }).join("");
    el("unread").textContent = String(unread);
    el("unread").hidden = unread === 0;
  }
  function renderActivities(list) {
    el("activities").innerHTML = list.map(function (a) { return "<li><b>" + esc(a.title) + "</b><br>" + esc(a.why) + "</li>"; }).join("");
  }

  function speak(text, lang) { if (MedBox.voice) { MedBox.voice.setOn(true, false); MedBox.voice.speakText(text, lang || "fr"); } paintVoice(); }

  function load() {
    return fetch("/api/me/" + encodeURIComponent(pid), { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (me) {
      state.me = me;
      document.title = me.name + " · MedBox";
      el("meName").textContent = me.name;
      el("meRole").textContent = me.role + (me.port ? " · port " + me.port : "");
      el("introText").textContent = me.intro.text;
      renderToday(me); renderWeek(me.week); renderMessages(me.messages || []); renderActivities(me.activities || []);
      (me.messages || []).forEach(function (m) { state.seen[m.id] = true; });
    }).catch(function () { el("introText").textContent = "La station ne répond pas."; });
  }

  function askAI() {
    var out = el("aiOut");
    out.innerHTML = "<p class=\"hint\">Le référent relit vos mesures…</p>";
    fetch("/api/assess/" + encodeURIComponent(pid) + "?me=1", { method: "POST" })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        if (!res.ok) { out.innerHTML = MedBox.assessment.failure(res.body.note || "Le référent ne répond pas ; vos mesures restent suivies."); return; }
        out.innerHTML = MedBox.assessment.render(res.body);
        if (res.body.spoken) speak(res.body.spoken, "fr");
      })
      .catch(function () { out.innerHTML = MedBox.assessment.failure("Le référent ne répond pas ; vos mesures restent suivies."); });
  }

  el("listenBtn").addEventListener("click", function () {
    if (state.me) speak(state.me.intro.spoken, "fr");
  });
  el("aiBtn").addEventListener("click", askAI);
  el("askForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var input = el("askInput"), text = input.value.trim(), out = el("askOut");
    if (!text) return;
    input.value = "";
    out.textContent = "Question posée…";
    fetch("/api/assistant/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, patient_id: pid, self: true }) })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        var b = res.body || {};
        if (!res.ok) { out.textContent = b.detail || "Question refusée."; return; }
        out.textContent = b.answer + (b.held_reason ? " (le référent est arrêté : réponse de la station)" : "");
        speak(b.spoken || b.answer, b.lang || "fr");
      })
      .catch(function () { out.textContent = "Le référent n’a pas répondu."; });
  });
  el("msgList").addEventListener("click", function (e) {
    var b = e.target.closest("button.read");
    if (!b) return;
    fetch("/api/messages/" + b.dataset.id + "/read", { method: "POST" }).then(function (r) { return r.json(); })
      .then(function (m) { speak(m.spoken || m.text, "fr"); load(); }).catch(function () {});
  });

  function connect() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(proto + "//" + location.host + "/ws");
    ws.onmessage = function (ev) {
      var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "message" && m.message && m.message.recipient === pid) {
        if (!state.seen[m.message.id]) { state.seen[m.message.id] = true; ping(); load(); }
      } else if (m.type === "board" && state.me) {
        var row = (m.board || []).filter(function (r) { return r.patient && r.patient.id === pid; })[0];
        if (row) { state.me.vitals = row.patient; state.me.today = row.triage; renderToday(state.me); }
      }
    };
    ws.onclose = function () { setTimeout(connect, 1500); };
  }

  function paintVoice() {
    var btn = el("voiceBtn");
    if (!MedBox.voice) { if (btn) btn.hidden = true; return; }
    var on = MedBox.voice.isOn();
    btn.textContent = on ? "Son activé" : "Son coupé";
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.classList.toggle("primary", on);
  }
  (function wireVoice() {
    var btn = el("voiceBtn");
    if (!MedBox.voice) { if (btn) btn.hidden = true; return; }
    btn.addEventListener("click", function () { MedBox.voice.setOn(!MedBox.voice.isOn(), true); paintVoice(); });
    MedBox.voice.setOn(MedBox.voice.restore());
    paintVoice();
  })();
  if (MedBox.mic) MedBox.mic.attach(function () { return pid; }, function () {});
  root.MedBox = root.MedBox || {};
  load();
  setInterval(load, 30000);
  connect();
})(window);
