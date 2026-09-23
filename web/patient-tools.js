/* Patient-level simulation controls, isolation confirmation and local reports.
 *
 * Every simulated input is a delta from the persisted healthy reference. The
 * browser never calculates a replacement vital and never sends a number to
 * the LLM. Medical reports are stored locally and are not model context.
 */
(function (root) {
  "use strict";

  var selected = null;
  var getPatient = function () { return null; };
  var onChanged = function () {};
  var busy = false;
  var activeProtocol = null;

  var PRESETS = {
    pseudo_flu: {
      changes: { temperature: 1.4, pulse: 24, respiration: 5 },
      duration: 32,
      reason: "Simulation : signes pseudo-grippaux déclarés"
    },
    respiratory: {
      changes: { temperature: 0.8, spo2: -4.5, pulse: 22, respiration: 9 },
      duration: 30,
      reason: "Simulation : gêne respiratoire progressive"
    },
    effort: {
      changes: { temperature: 0.4, pulse: 34, respiration: 8 },
      duration: 22,
      reason: "Simulation : récupération après effort prolongé"
    },
    cold: {
      changes: { temperature: -1.8, pulse: -10, respiration: -2 },
      duration: 30,
      reason: "Simulation : exposition environnementale froide"
    },
    baseline: {
      changes: { temperature: 0, spo2: 0, pulse: 0, respiration: 0 },
      duration: 25,
      reason: "Simulation : retour progressif à la ligne saine personnelle"
    }
  };

  function el(id) { return document.getElementById(id); }

  function status(id, text, bad) {
    var node = el(id);
    if (!node) return;
    node.textContent = text || "";
    node.classList.toggle("bad", !!bad);
  }

  function request(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) throw new Error(body.detail || body.error || "Échec de la requête");
        return body;
      });
    });
  }

  function applyChanges(changes, duration, reason, exposureConfirmed) {
    var patientId = getPatient();
    if (!patientId || busy) return Promise.resolve();
    busy = true;
    status("simStatus", "Application de la trajectoire simulée…");
    return request("/api/patient/" + encodeURIComponent(patientId) + "/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        changes: changes,
        over_seconds: duration,
        reason: reason,
        exposure_confirmed: exposureConfirmed === true
      })
    }).then(function () {
      status("simStatus", "Changements enregistrés dans la piste d’audit.");
      return refresh(patientId);
    }).then(onChanged).catch(function (error) {
      status("simStatus", error.message, true);
    }).then(function () { busy = false; });
  }

  function submitPreset(event) {
    event.preventDefault();
    var preset = PRESETS[el("simPreset").value];
    if (preset) applyChanges(preset.changes, preset.duration, preset.reason, false);
  }

  function value(id) {
    var input = el(id);
    if (!input || input.value.trim() === "") return null;
    return Number(input.value.replace(",", "."));
  }

  function submitManual(event) {
    event.preventDefault();
    var changes = {};
    [
      ["temperature", "simTemperature"],
      ["spo2", "simSpo2"],
      ["pulse", "simPulse"],
      ["respiration", "simRespiration"],
      ["systolic_bp", "simSystolic"]
    ].forEach(function (entry) {
      var number = value(entry[1]);
      if (number !== null && Number.isFinite(number)) changes[entry[0]] = number;
    });
    if (!Object.keys(changes).length) {
      status("simStatus", "Saisissez au moins un écart.", true);
      return;
    }
    applyChanges(
      changes,
      value("simDuration") || 25,
      (el("simReason").value || "Exercice manuel de simulation").trim(),
      !!(el("simExposure") && el("simExposure").checked)
    );
  }

  /* ACVPU and oxygen: the two NEWS2 inputs a person enters. Sent for the
     selected crew member, recorded with the time, never a measurement. */
  function submitObservations(event) {
    event.preventDefault();
    var pid = getPatient ? getPatient() : null;
    if (!pid) { status("obsStatus", "Sélectionnez d’abord un membre.", true); return; }
    var level = el("obsConsciousness") ? el("obsConsciousness").value : "";
    var oxygenSel = el("obsOxygen") ? el("obsOxygen").value : "";
    var body = {
      consciousness: level || null,
      on_oxygen: oxygenSel === "" ? null : oxygenSel === "yes"
    };
    fetch("/api/patient/" + encodeURIComponent(pid) + "/observations", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.j.detail || "refusé");
        status("obsStatus", "Observation enregistrée. Le score intègre ces deux paramètres.");
        if (onChanged) onChanged();
      })
      .catch(function (err) { status("obsStatus", "Non enregistré : " + err.message, true); });
  }

  function bytes(value) {
    if (value < 1024) return value + " o";
    if (value < 1024 * 1024) return Math.round(value / 1024) + " Ko";
    return (value / (1024 * 1024)).toFixed(1) + " Mo";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>\"]/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[character];
    });
  }

  var GATE_LABELS = {
    depistage_absent: "dépistage de sécurité absent",
    depistage_incomplet: "dépistage de sécurité incomplet",
    depistage_non_confirme: "vérifications non confirmées",
    validation_humaine_absente: "validation médicale humaine absente",
    validation_humaine_refusee: "validation humaine refusée",
    validation_humaine_hors_perimetre: "validation donnée pour une autre carte",
    validation_humaine_obsolete: "validation humaine expirée",
    role_humain_non_autorise: "qualité du validateur non autorisée",
    drapeau_rouge_present: "signe d’alerte présent",
    allergie_signalee: "allergie pertinente signalée",
    contre_indication_signalee: "contre-indication pertinente signalée",
    inventaire_perime_ou_obsolete: "inventaire simulé obsolète",
    stock_simule_insuffisant: "stock simulé insuffisant",
    aucune_option_medicamenteuse_dans_ce_protocole: "aucune option médicamenteuse dans cette carte"
  };

  function renderProtocol(result) {
    activeProtocol = result || null;
    var box = el("protocolResult");
    var validation = el("protocolValidation");
    if (!box || !validation) return;
    if (!result || !result.card) {
      box.innerHTML = '<p class="protocol-empty">Aucune carte locale ne correspond aux observations actuelles.</p>';
      validation.hidden = true;
      return;
    }
    var card = result.card;
    var html = '<article class="protocol-card"><div class="protocol-card__head"><b>' +
      escapeHtml(card.id) + '</b><span>SIMULATION · NON DIAGNOSTIC</span></div>' +
      '<h4>' + escapeHtml(card.title_fr) + '</h4><p>' + escapeHtml(card.classification_fr) + '</p>';
    if (card.actions_fr && card.actions_fr.length) {
      html += '<h5>Actions autorisées</h5><ul>' + card.actions_fr.map(function (item) {
        return '<li>' + escapeHtml(item) + '</li>';
      }).join("") + '</ul>';
    }
    if (card.red_flags_fr && card.red_flags_fr.length) {
      html += '<h5>Signes d’alerte</h5><ul class="red-flags">' + card.red_flags_fr.map(function (item) {
        return '<li>' + escapeHtml(item) + '</li>';
      }).join("") + '</ul>';
    }
    if (result.medication_options && result.medication_options.length) {
      html += '<h5>Option ouverte après validation humaine</h5>' + result.medication_options.map(function (option) {
        return '<div class="med-option"><b>' + escapeHtml(option.name_fr) + '</b><span>' +
          escapeHtml(option.status_fr) + '</span><strong>' +
          escapeHtml(option.inventory.location_label) + '</strong><small>Stock simulé · ' +
          escapeHtml(option.inventory.quantity) + ' ' + escapeHtml(option.inventory.unit) +
          ' · lot ' + escapeHtml(option.inventory.lot) + '</small></div>';
      }).join("");
    } else {
      var reasons = (result.medication_gate && result.medication_gate.reasons || []).map(function (reason) {
        return GATE_LABELS[reason] || String(reason).replace(/_/g, " ");
      });
      html += '<p class="protocol-gate"><b>Option médicamenteuse masquée.</b> ' +
        escapeHtml(reasons.join(" · ") || "Validation non disponible") + '.</p>';
    }
    if (card.sources && card.sources.length) {
      html += '<div class="protocol-sources">Sources : ' + card.sources.map(function (source) {
        return '<a href="' + escapeHtml(source.url) + '" target="_blank" rel="noopener">' +
          escapeHtml(source.title) + '</a>';
      }).join(" · ") + '</div>';
    }
    box.innerHTML = html + '</article>';
    var gateReasons = result.medication_gate && result.medication_gate.reasons || [];
    validation.hidden = gateReasons.indexOf("aucune_option_medicamenteuse_dans_ce_protocole") >= 0 ||
      !!(result.medication_options && result.medication_options.length);
  }

  function evaluateProtocol(payload) {
    var patientId = getPatient();
    if (!patientId || busy) return Promise.resolve();
    busy = true;
    status("protocolStatus", "Évaluation de la carte locale…");
    return request("/api/patient/" + encodeURIComponent(patientId) + "/protocol", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    }).then(function (result) {
      renderProtocol(result);
      status("protocolStatus", "Résultat local déterministe · aucune donnée transmise au LLM.");
    }).catch(function (error) {
      renderProtocol(null);
      status("protocolStatus", error.message, true);
    }).then(function () { busy = false; });
  }

  function initialProtocolEvaluation() {
    return evaluateProtocol({ observation: (el("protocolObservation").value || "").trim() });
  }

  function validateProtocol(event) {
    event.preventDefault();
    if (!activeProtocol || !activeProtocol.card) return;
    var blockedItems = ["MED-PARACETAMOL-DEMO-01", "SRO-DEMO-01"];
    return evaluateProtocol({
      observation: (el("protocolObservation").value || "").trim(),
      screening: {
        patient_identity_confirmed: el("protocolIdentity").checked,
        age_years: Number(el("protocolAge").value),
        allergies_reviewed: el("protocolAllergiesReviewed").checked,
        allergic_item_ids: el("protocolAllergyPresent").checked ? blockedItems : [],
        current_medications_reviewed: el("protocolMedsReviewed").checked,
        contraindications_reviewed: el("protocolContraReviewed").checked,
        contraindicated_item_ids: el("protocolContraPresent").checked ? blockedItems : [],
        red_flags_reviewed: el("protocolFlagsReviewed").checked,
        red_flags: el("protocolFlagPresent").checked ? ["signe signalé par le validateur"] : [],
        pregnancy_status: el("protocolPregnancy").value
      },
      human_validation: {
        validated: el("protocolAttest").checked,
        protocol_id: activeProtocol.card.id,
        role: el("protocolRole").value,
        validator_id: (el("protocolValidator").value || "").trim(),
        validated_at: new Date().toISOString()
      }
    });
  }

  function renderDocuments(list) {
    var box = el("documentList");
    if (!box) return;
    box.textContent = "";
    if (!list || !list.length) {
      var empty = document.createElement("p");
      empty.className = "said-rule";
      empty.textContent = "Aucun rapport local associé.";
      box.appendChild(empty);
      return;
    }
    list.forEach(function (doc) {
      var link = document.createElement("a");
      link.className = "document-item";
      link.href = "/api/documents/" + encodeURIComponent(doc.id);
      link.target = "_blank";
      link.rel = "noopener";
      var name = document.createElement("span");
      name.textContent = doc.original_name;
      var size = document.createElement("span");
      size.textContent = bytes(doc.size_bytes);
      link.appendChild(name);
      link.appendChild(size);
      box.appendChild(link);
    });
  }

  function drawTrends(history, baseline) {
    var canvas = el("vitalTrend");
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext("2d");
    var rows = (history || []).slice().reverse().slice(-90);
    var series = [
      ["temperature", "TEMP", "#ffb257", 1],
      ["spo2", "SpO₂", "#69dce3", 0],
      ["pulse", "POULS", "#ff7184", 0],
      ["respiration", "RESP", "#a895ff", 0]
    ];
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#06131d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (rows.length < 2) {
      ctx.fillStyle = "#75939a";
      ctx.font = "12px system-ui";
      ctx.fillText("La courbe apparaît après quelques observations enregistrées.", 12, 24);
      return;
    }
    var left = 70, right = canvas.width - 10;
    var rowHeight = canvas.height / series.length;
    series.forEach(function (definition, index) {
      var key = definition[0], label = definition[1], color = definition[2], digits = definition[3];
      var values = rows.map(function (row) { return Number(row[key]); })
        .filter(function (number) { return Number.isFinite(number); });
      if (!values.length) return;
      var reference = baseline && Number(baseline[key]);
      if (Number.isFinite(reference)) values.push(reference);
      var min = Math.min.apply(Math, values), max = Math.max.apply(Math, values);
      var pad = Math.max((max - min) * 0.18, key === "temperature" ? 0.12 : 0.8);
      min -= pad; max += pad;
      var top = index * rowHeight + 7, bottom = (index + 1) * rowHeight - 7;
      function y(value) { return bottom - ((value - min) / (max - min || 1)) * (bottom - top); }
      ctx.strokeStyle = "rgba(122,160,168,.14)";
      ctx.beginPath(); ctx.moveTo(left, bottom); ctx.lineTo(right, bottom); ctx.stroke();
      if (Number.isFinite(reference)) {
        ctx.setLineDash([3, 4]);
        ctx.strokeStyle = "rgba(170,205,208,.33)";
        ctx.beginPath(); ctx.moveTo(left, y(reference)); ctx.lineTo(right, y(reference)); ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      var plotted = 0;
      rows.forEach(function (row, point) {
        var value = Number(row[key]);
        if (!Number.isFinite(value)) return;
        var x = left + (point / Math.max(1, rows.length - 1)) * (right - left);
        if (!plotted) ctx.moveTo(x, y(value)); else ctx.lineTo(x, y(value));
        plotted += 1;
      });
      ctx.stroke();
      var latest = Number(rows[rows.length - 1][key]);
      ctx.fillStyle = color;
      ctx.font = "700 10px system-ui";
      ctx.fillText(label, 8, top + 9);
      ctx.fillStyle = "#d8ecee";
      ctx.font = "10px ui-monospace, monospace";
      ctx.fillText(Number.isFinite(latest) ? latest.toFixed(digits) : "—", 8, top + 22);
    });
  }

  function uploadDocument() {
    var patientId = getPatient();
    var input = el("documentInput");
    var file = input && input.files ? input.files[0] : null;
    if (!patientId || !file || busy) {
      status("documentStatus", "Choisissez un rapport à ajouter.", true);
      return;
    }
    if (file.size > 12 * 1024 * 1024) {
      status("documentStatus", "Le rapport dépasse 12 Mo.", true);
      return;
    }
    busy = true;
    status("documentStatus", "Copie locale et calcul de l’empreinte…");
    fetch("/api/patient/" + encodeURIComponent(patientId) + "/documents", {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-MedBox-Filename": encodeURIComponent(file.name)
      },
      body: file
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error(body.detail || "Ajout impossible");
        return body;
      });
    }).then(function () {
      input.value = "";
      status("documentStatus", "Rapport ajouté localement. Il n’est pas transmis au LLM.");
      return refresh(patientId);
    }).catch(function (error) {
      status("documentStatus", error.message, true);
    }).then(function () { busy = false; });
  }

  function isolationAction(path, body) {
    var patientId = getPatient();
    if (!patientId || busy) return;
    busy = true;
    request("/api/quarantine/" + encodeURIComponent(patientId) + "/" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }).then(function () {
      status("simStatus", path === "confirm"
        ? "Isolement confirmé par l’opérateur."
        : "Sortie du registre enregistrée.");
      return refresh(patientId);
    }).then(onChanged).catch(function (error) {
      status("simStatus", error.message, true);
    }).then(function () { busy = false; });
  }

  function renderIsolation(entry) {
    var box = el("isolationActions");
    if (!box) return;
    box.textContent = "";
    box.hidden = !entry;
    if (!entry) return;
    var copy = document.createElement("p");
    copy.textContent = entry.requires_confirmation
      ? "Candidat à l’isolement — confirmation humaine requise. " + entry.reason
      : (entry.zone
        ? "Isolement confirmé · zone " + entry.zone + ". " + entry.reason
        : "Isolement confirmé · en attente d’une place. " + entry.reason);
    box.appendChild(copy);
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn";
    if (entry.requires_confirmation) {
      button.textContent = "Confirmer l’isolement";
      button.addEventListener("click", function () { isolationAction("confirm"); });
    } else {
      button.textContent = "Lever manuellement";
      button.addEventListener("click", function () {
        isolationAction("release", { reason: "Levée manuelle par l’opérateur" });
      });
    }
    box.appendChild(button);
  }

  function refresh(patientId) {
    selected = patientId || getPatient();
    if (!selected) return Promise.resolve();
    return request("/api/patient/" + encodeURIComponent(selected), { cache: "no-store" })
      .then(function (record) {
        if (selected !== getPatient()) return;
        renderDocuments(record.documents || []);
        renderIsolation(record.isolation || null);
        drawTrends(record.history || [], record.patient && record.patient.baseline);
      }).catch(function (error) {
        status("documentStatus", error.message, true);
      });
  }

  function select(patientId) {
    selected = patientId;
    var input = el("documentInput");
    var upload = el("documentUploadBtn");
    if (input) input.disabled = !patientId;
    if (upload) upload.disabled = !patientId;
    status("simStatus", "");
    status("documentStatus", "");
    status("protocolStatus", "");
    activeProtocol = null;
    if (el("protocolResult")) el("protocolResult").textContent = "";
    if (el("protocolValidation")) el("protocolValidation").hidden = true;
    return refresh(patientId);
  }

  function attach(getPatientFn, changedFn) {
    getPatient = typeof getPatientFn === "function" ? getPatientFn : getPatient;
    onChanged = typeof changedFn === "function" ? changedFn : onChanged;
    if (el("simPresetForm")) el("simPresetForm").addEventListener("submit", submitPreset);
    if (el("simManualForm")) el("simManualForm").addEventListener("submit", submitManual);
    if (el("obsForm")) el("obsForm").addEventListener("submit", submitObservations);
    if (el("documentUploadBtn")) el("documentUploadBtn").addEventListener("click", uploadDocument);
    if (el("protocolEvaluateBtn")) el("protocolEvaluateBtn").addEventListener("click", initialProtocolEvaluation);
    if (el("protocolValidationForm")) el("protocolValidationForm").addEventListener("submit", validateProtocol);
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.patientTools = { attach: attach, select: select, refresh: refresh };
})(window);
