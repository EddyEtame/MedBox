/* The crew dashboard: everyone's week, how the crew is doing, what to do
 * together, and the referent's messages, which ping and are read out loud.
 * Same feed as the board (the WebSocket), same guards (voice.js is optional). */
(function (root) {
  "use strict";
  function el(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  var state = { members: {}, seen: {}, zones: {} };
  var URGENCY = { routine: "routine", low: "faible", medium: "moyenne", high: "haute" };

  /* A loud, short ping from the browser itself: nothing to download, and it
     is heard even when the voice is off. Needs one gesture on the page. */
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
    } catch (e) { /* no audio: the badge and the flash still show */ }
    document.body.classList.add("alert");
    setTimeout(function () { document.body.classList.remove("alert"); }, 1200);
  }

  function fmt(v, d) { return v == null ? "–" : Number(v).toFixed(d == null ? 0 : d); }

  function renderMessages(list) {
    var ul = el("msgList");
    if (!list.length) { ul.innerHTML = '<li class="hint">Aucun message pour l’instant.</li>'; el("unread").hidden = true; return; }
    var unread = 0;
    ul.innerHTML = list.map(function (m) {
      if (!m.read_at) unread++;
      var when = new Date(m.at * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
      return '<li class="msg' + (m.read_at ? "" : " unread") + '" data-id="' + m.id + '">' +
        '<div class="msg-h"><span class="when">' + when + '</span>' +
        '<button class="btn small read" data-id="' + m.id + '">' + (m.read_at ? "Relire" : "Lire") + "</button></div>" +
        '<div class="msg-t">' + esc(m.text) + "</div></li>";
    }).join("");
    el("unread").textContent = String(unread);
    el("unread").hidden = unread === 0;
  }

  function readMessage(id) {
    fetch("/api/messages/" + id + "/read", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (m) {
        // Opened by a person: the referent says it. The click is the gesture.
        if (MedBox.voice) { MedBox.voice.setOn(true, false); MedBox.voice.speakText(m.spoken || m.text, "fr"); }
        paintVoice();
        openCard(m);
        load();
      })
      .catch(function () {});
  }

  /* Explanation mode: who the message is about, their numbers today against
     their own baseline, and the ship with them lit and their isolation zone
     glowing. Eddy, 24 Sep: "pull up a card about the person, show the 3D
     view, glow the room where my man's gonna be quarantined". */
  function nextZone(member) {
    if (member && member.isolation && member.isolation.zone) return member.isolation.zone;
    var names = Object.keys(state.zones || {});
    for (var i = 0; i < names.length; i++) {
      var z = state.zones[names[i]];
      if ((Number(z.occupied) || 0) < (Number(z.capacity) || 1)) return names[i];
    }
    return names[0] || "A";
  }
  function initials(name) { return String(name || "?").split(/\s+/).map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase(); }
  function openCard(m) {
    var member = state.members[m.patient_id];
    if (!member) return;
    closeCard();
    var zone = nextZone(member);
    var u = UNITS_ROWS(member);
    var back = document.createElement("div");
    back.className = "card-back"; back.id = "cardBack";
    back.innerHTML = '<div class="card" role="dialog" aria-label="Fiche de ' + esc(member.name) + '">' +
      '<button class="x" id="cardClose" aria-label="Fermer">×</button>' +
      '<div class="card-h"><div class="avatar">' + esc(initials(member.name)) + "</div>" +
      "<div><h2>" + esc(member.name) + "</h2><div class=\"hint\">" + esc(member.role) + (member.port ? " · port " + member.port : "") + "</div></div></div>" +
      '<p class="card-msg">' + esc(m.text) + "</p>" +
      '<table class="week card-vitals"><tbody>' + u + "</tbody></table>" +
      '<div class="card-ship"><iframe src="/ship?embed=1&focus=' + encodeURIComponent(member.id) + "&glow=" + encodeURIComponent(zone) + '" title="Vaisseau"></iframe></div>' +
      '<p class="hint">Zone ' + esc(zone) + " en surbrillance : c’est là que " + esc(member.name) + " sera isolé.</p>" +
      "</div>";
    document.body.appendChild(back);
    el("cardClose").addEventListener("click", closeCard);
    back.addEventListener("click", function (e) { if (e.target === back) closeCard(); });
  }
  function closeCard() { var b = el("cardBack"); if (b) b.remove(); }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeCard(); });
  function UNITS_ROWS(member) {
    var units = { temperature: ["Température", "°C", 1], spo2: ["SpO₂", "%", 1], pulse: ["Pouls", "/min", 0], respiration: ["Respiration", "/min", 0], systolic_bp: ["Tension", "mmHg", 0] };
    return Object.keys(units).map(function (k) {
      var u = units[k], now = (member.vitals || {})[k], base = (member.baseline || {})[k];
      return "<tr><th>" + u[0] + "</th><td>" + (now == null ? "–" : fmt(now, u[2]) + " " + u[1]) + "</td><td class=\"hint\">habituel " + (base == null ? "–" : fmt(base, u[2])) + "</td></tr>";
    }).join("");
  }

  function renderChampion(c) {
    var box = el("champion");
    if (!c) { box.innerHTML = '<p class="hint">Personne n’est dans sa plage habituelle toute la semaine.</p>'; return; }
    var link = c.port ? ("http://" + location.hostname + ":" + c.port + "/") : ("/me/" + c.id);
    box.innerHTML = '<div class="champ"><div class="avatar">' + esc(initials(c.name)) + "</div><div><b><a href=\"" + link + "\" title=\"Son espace personnel\">" + esc(c.name) + "</a></b> <span class=\"hint\">" + esc(c.role) + "</span>" +
      "<p>" + esc(c.why) + "</p><p>Ce que " + esc(c.name) + " fait, à suivre :</p><ul>" +
      c.habits.map(function (h) { return "<li>" + esc(h) + "</li>"; }).join("") + "</ul></div></div>";
  }

  function renderMembers(members) {
    var body = el("members").querySelector("tbody");
    body.innerHTML = members.map(function (m) {
      var w = m.week && m.week.vitals ? m.week.vitals : {};
      var u = m.today.urgency || "routine";
      var iso = m.isolation ? (m.isolation.confirmed ? " · isolé" + (m.isolation.zone ? " " + m.isolation.zone : "") : " · isolement décidé") : "";
      var link = m.port ? ("http://" + location.hostname + ":" + m.port + "/") : ("/me/" + m.id);
      return "<tr class=\"u-" + u + "\">" +
        "<td><b>" + esc(m.name) + "</b><br><span class=\"hint\">" + esc(m.role) + "</span></td>" +
        "<td><span class=\"band " + u + "\">" + (m.today.total == null ? "–" : m.today.total + " · " + URGENCY[u]) + "</span>" + esc(iso) + "</td>" +
        "<td>" + (w.temperature ? fmt(w.temperature.avg, 1) + " <span class=\"hint\">(" + fmt(w.temperature.min, 1) + "–" + fmt(w.temperature.max, 1) + ")</span>" : "–") + "</td>" +
        "<td>" + (w.spo2 ? fmt(w.spo2.avg, 1) + " %" : "–") + "</td>" +
        "<td>" + (w.pulse ? fmt(w.pulse.avg) : "–") + "</td>" +
        "<td>" + (w.respiration ? fmt(w.respiration.avg) : "–") + "</td>" +
        "<td>" + (w.systolic_bp ? fmt(w.systolic_bp.avg) : "–") + "</td>" +
        "<td><a class=\"btn small\" href=\"" + link + "\">" + (m.port ? "Port " + m.port : "Ouvrir") + "</a></td></tr>";
    }).join("");
  }

  function renderActivities(list) {
    el("activities").innerHTML = list.map(function (a) {
      return "<li><b>" + esc(a.title) + "</b> <span class=\"hint\">" + esc(a.when || "") + "</span><br>" + esc(a.why) + "</li>";
    }).join("");
  }

  function load() {
    fetch("/api/crew/week", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      el("shipName").textContent = d.ship || "ESA Horizon";
      el("crewTotal").textContent = d.summary.total;
      el("crewFit").textContent = d.summary.fit;
      el("crewImpaired").textContent = d.summary.impaired;
      el("crewIsolated").innerHTML = d.summary.isolated +
        (d.summary.proposed ? ' <small class="hint" title="Isolements décidés par le référent, à confirmer par une personne">+' + d.summary.proposed + " à confirmer</small>" : "");
      var s = d.summary;
      el("crewSummary").textContent = s.impaired === 0
        ? "Tout l’équipage est dans sa plage habituelle. Rien à signaler."
        : s.impaired + (s.impaired > 1 ? " membres" : " membre") + " à surveiller, " +
          (s.isolated ? s.isolated + " en isolement" : "aucun isolement confirmé") +
          (s.proposed ? ", " + s.proposed + (s.proposed > 1 ? " décisions" : " décision") + " à accuser" : "") + ".";
      state.members = {};
      d.members.forEach(function (m) { state.members[m.id] = m; });
      state.zones = d.zones || {};
      renderMembers(d.members);
      renderChampion(d.champion);
      renderActivities(d.activities || []);
      renderMessages(d.messages || []);
      (d.messages || []).forEach(function (m) { state.seen[m.id] = true; });
    }).catch(function () { el("crewSummary").textContent = "La station ne répond pas."; });
  }

  /* Live: messages ping the moment they are written; the board frame keeps
     today's column fresh without reloading everything. */
  function connect() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(proto + "//" + location.host + "/ws");
    ws.onmessage = function (ev) {
      var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "board" && m.ears && MedBox.mic) MedBox.mic.setAvailable(m.ears.available, m.ears.error);
      if (m.type === "message" && m.message && m.message.recipient === "crew") {
        if (!state.seen[m.message.id]) { state.seen[m.message.id] = true; ping(); load(); }
      } else if (m.type === "message_read") {
        load();
      } else if (m.type === "state" && m.spoken) {
        if (!MedBox.voice) return;
        var now = Date.now();
        if (!state.lastStateSaid || now - state.lastStateSaid > 5000) { state.lastStateSaid = now; MedBox.voice.speakText(m.spoken, "fr"); }
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

  // No member is selected on this page: a spoken question goes to the
  // referent as a question about the crew.
  if (MedBox.mic) MedBox.mic.attach(function () { return null; }, function () {});
  el("msgList").addEventListener("click", function (e) {
    var b = e.target.closest("button.read");
    if (b) readMessage(b.dataset.id);
  });
  (function wireVoice() {
    var btn = el("voiceBtn");
    if (!MedBox.voice) { if (btn) btn.hidden = true; return; }
    btn.addEventListener("click", function () { MedBox.voice.setOn(!MedBox.voice.isOn(), true); paintVoice(); ping(); });
    MedBox.voice.setOn(MedBox.voice.restore());
    paintVoice();
  })();
  root.MedBox = root.MedBox || {};
  load();
  setInterval(load, 30000);
  connect();
})(window);
