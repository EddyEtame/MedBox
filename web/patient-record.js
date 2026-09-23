/* Shared patient record. Independent of the telemetry and AI availability. */
(function () {
  "use strict";
  var selected = null, generation = 0, busy = false;
  var host = document.createElement("section");
  host.className = "patient-record";
  host.hidden = true;
  document.getElementById("aiOut").parentNode.appendChild(host);
  var css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "/static/patient-record.css";
  document.head.appendChild(css);
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c];
    });
  }
  function date(t) { return new Date(t * 1000).toLocaleString(); }
  function chart(rows, key, title, changes) {
    var points = rows.filter(function (r) { return Number.isFinite(r[key]); });
    if (!points.length) return "<p>" + title + " : aucune mesure</p>";
    var values = points.map(function (r) { return r[key]; });
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    var start = rows[0].at, end = rows[rows.length - 1].at;
    function x(t) { return 10 + 280 * (t - start) / Math.max(1, end - start); }
    function y(v) { return 65 - 50 * (v - lo) / Math.max(0.1, hi - lo); }
    var path = points.map(function (r) { return x(r.at) + "," + y(r[key]); }).join(" ");
    var change = changes.find(function (c) { return c.at >= start && c.at <= end; });
    var marker = change ? '<line x1="' + x(change.at) + '" x2="' + x(change.at) +
      '" y1="5" y2="70" stroke="#fbbf24" stroke-dasharray="3 3"/>' : "";
    return '<figure><figcaption>' + title + ' · ' + lo.toFixed(1) + '–' + hi.toFixed(1) +
      '</figcaption><svg viewBox="0 0 300 75" role="img" aria-label="' + title +
      '"><polyline fill="none" stroke="currentColor" stroke-width="2" points="' + path + '"/>' +
      marker + '</svg><small>' + date(start) + ' → ' + date(end) + '</small></figure>';
  }
  function render(d, sessions) {
    var rows = (d.history || []).slice().reverse(), changes = d.triage_history || [];
    var html = '<h3>Historique des mesures</h3><p>Dernières mesures, jusqu’à 10 minutes. ' +
      'Trait jaune : dernier changement de niveau dans la période.</p>';
    [["temperature","Température (°C)"],["spo2","SpO₂ (%)"],["pulse","Pouls (/min)"],
      ["respiration","Respiration (/min)"]].forEach(function (v) { html += chart(rows,v[0],v[1],changes); });
    if (changes.length) html += '<p>Dernier niveau enregistré : ' + esc(changes[0].urgency) +
      ' · ' + date(changes[0].at) + '</p>';
    html += '<h3>Réponses enregistrées</h3><p>Déclarations du patient, non mesurées.</p>';
    html += (d.answers || []).map(function (a) { return '<p><b>' + esc(a.question) + '</b><br>' +
      esc(a.answer) + '<br><small>' + date(a.at) + '</small></p>'; }).join("") || '<p>Aucune réponse.</p>';
    html += '<h3>Contacts en quarantaine</h3>';
    html += (d.contacts || []).map(function (c) { return '<p>Zone ' + esc(c.zone) + ' : ' +
      esc(c.patient_a) + ' / ' + esc(c.patient_b) + '<br>' + date(c.since) + ' → ' +
      (c.until == null ? 'en cours' : date(c.until)) + '</p>'; }).join("") || '<p>Aucun contact enregistré.</p>';
    html += '<h3>Journal des scénarios</h3>';
    html += (sessions.sessions || []).map(function (s) {
      return '<details><summary>' + esc(s.name) + ' · ' + date(s.since) + '</summary><p>Fin : ' +
        (s.until == null ? 'non enregistrée ou scénario actif' : date(s.until)) + '</p>' +
        s.events.map(function (e) {
          var detail = {};
          try { detail = JSON.parse(e.detail); } catch (ignore) {}
          var label = e.kind === 'afflict' ? 'Évolution simulée : ' + (detail.patients || []).join(', ') :
            e.kind === 'scenario_stop' ? 'Scénario arrêté' :
            detail.reason === 'released' ? 'Sortie de quarantaine : ' + e.patient_id :
            'Quarantaine : ' + e.patient_id + (detail.zone ? ' · zone ' + detail.zone : ' · en attente de place');
          return '<p>' + esc(label) + '<br><small>' + date(e.at) + '</small></p>';
        }).join('') + '</details>';
    }).join('') || '<p>Aucun scénario enregistré.</p>';
    host.innerHTML = html;
  }
  function refresh() {
    if (!selected || busy) return;
    var id = selected, token = generation;
    busy = true;
    Promise.all([fetch('/api/patient/' + encodeURIComponent(id)), fetch('/api/sessions')])
      .then(function (responses) { return Promise.all(responses.map(function (r) {
        if (!r.ok) throw new Error('Historique indisponible'); return r.json();
      })); })
      .then(function (data) { if (token === generation) render(data[0], data[1]); })
      .catch(function () { if (token === generation) host.textContent = 'Historique indisponible. Nouvelle tentative automatique.'; })
      .finally(function () { busy = false; });
  }
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.matches('.patient-answer')) return;
    event.preventDefault();
    var status = form.querySelector('.answer-status');
    var choice = event.submitter ? event.submitter.value : 'text';
    var answer = choice === 'text' ? form.elements.answer.value.trim() : choice;
    if (!answer) { status.textContent = 'Écris une réponse avant d’enregistrer.'; return; }
    var controls = form.querySelectorAll('button, input');
    controls.forEach(function (c) { c.disabled = true; });
    status.textContent = 'Enregistrement…';
    fetch('/api/patient/' + encodeURIComponent(form.dataset.patient) + '/answer', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({question:form.querySelector('.answer-question').textContent, answer:answer})
    }).then(function (r) { if (!r.ok) throw new Error('save'); return r.json(); })
      .then(function () {
        status.textContent = 'Réponse enregistrée. Relance Ask the assistant pour en tenir compte.';
        if (selected === form.dataset.patient) refresh();
      }).catch(function () {
        status.textContent = 'Échec de l’enregistrement. Réessaie.';
        controls.forEach(function (c) { c.disabled = false; });
      });
  });
  window.MedBox = window.MedBox || {};
  window.MedBox.patientRecord = {select:function (id) {
    selected = id; generation++; host.hidden = !id;
    host.textContent = id ? 'Chargement de l’historique…' : ''; refresh();
  }};
  setInterval(refresh, 5000);
})();
