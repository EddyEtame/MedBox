/* MedBox's local, consent-gated listening loop.
 *
 * One click is still required: browsers do not let a page take a microphone
 * silently. After that click, MedBox explains the session in French and hears
 * only a clear consent decision. Consent audio and its transcript are thrown
 * away. Once accepted, an energy VAD cuts the live stream into utterances and
 * the local Whisper endpoint listens for the wake word "MedBox". Ambient
 * speech without the wake word is discarded; an explicit command is kept as
 * reported speech only when a crew member is selected.
 *
 * No Web Speech recognition API is used. In Chrome that can send audio to a
 * vendor service. Audio here travels only to this same-origin local server,
 * where its temporary file is deleted in a finally block.
 */
(function (root) {
  "use strict";

  var MAX_UTTERANCE_MS = 12000;
  var IDLE_SEGMENT_MS = 3500;
  var END_SILENCE_MS = 850;
  var WAKE_WINDOW_MS = 9000;
  var MAX_PENDING = 3;
  var MIN_BLOB_BYTES = 900;
  var MIN_CONSENT_CONFIDENCE = 0.55;

  var stream = null;
  var rec = null;
  var audioContext = null;
  var analyser = null;
  var source = null;
  var vadTimer = 0;
  var armGeneration = 0;
  var arming = false;
  var running = false;
  var available = false;
  var consented = false;
  var paused = false;
  var hasSpeech = false;
  var loudFrames = 0;
  var segmentStartedAt = 0;
  var speechStartedAt = 0;
  var lastLoudAt = 0;
  var noiseFloor = 0.006;
  var wakeUntil = 0;
  var pending = [];
  var uploading = false;
  var sessionId = null;
  var getPatient = function () { return null; };
  var onReported = null;
  var ui = {};

  var STATES = {
    OFF: ["ARRÊTÉ", "off"],
    ARMING: ["ACTIVATION", "arming"],
    CONSENT: ["CONSENTEMENT", "consent"],
    LISTENING: ["À L’ÉCOUTE", "listening"],
    SPEECH: ["PAROLE DÉTECTÉE", "speech"],
    TRANSCRIBING: ["TRANSCRIPTION", "transcribing"],
    WAKE: ["MEDBOX ACTIVÉ", "wake"],
    PAUSED: ["EN PAUSE", "paused"],
    ERROR: ["ERREUR", "error"]
  };

  var CONSENT_TEXT = "Je suis MedBox, assistant local hors ligne de surveillance. " +
    "Je ne remplace pas un médecin : diagnostics, médicaments et isolement demandent " +
    "une validation médicale. Avec votre accord, le microphone reste actif durant " +
    "cette session pour détecter « MedBox ». L’audio et la réponse de consentement " +
    "ne sont pas conservés ; seuls votre décision et l’heure sont journalisées " +
    "localement. Après « MedBox », une demande peut être inscrite comme propos " +
    "rapporté dans le dossier sélectionné. Vous pouvez suspendre l’écoute ou retirer " +
    "votre accord à tout moment. Pour accepter, dites clairement « J’accepte », " +
    "« oui », « I accept » ou « yes ».";

  function el(id) { return document.getElementById(id); }

  function supported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
              root.MediaRecorder && (root.AudioContext || root.webkitAudioContext));
  }

  function injectStyles() {
    if (el("medboxMicStyles")) return;
    var style = document.createElement("style");
    style.id = "medboxMicStyles";
    style.textContent =
      ".medbox-listener{position:fixed;right:18px;bottom:18px;z-index:1200;width:min(390px,calc(100vw - 36px));" +
      "padding:14px;border:1px solid rgba(123,232,211,.34);border-radius:14px;background:rgba(5,15,23,.96);" +
      "box-shadow:0 18px 55px rgba(0,0,0,.42);color:#eafbf8;font:13px/1.45 system-ui,sans-serif}" +
      ".medbox-listener__top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}" +
      ".medbox-listener__title{font-weight:800;letter-spacing:.08em;text-transform:uppercase}" +
      ".medbox-listener__state{padding:4px 8px;border-radius:999px;background:#23313b;color:#c9d6dc;font-size:11px;font-weight:800}" +
      ".medbox-listener__state[data-state=listening],.medbox-listener__state[data-state=wake]{background:#0e4c40;color:#8fffe7}" +
      ".medbox-listener__state[data-state=speech],.medbox-listener__state[data-state=transcribing]{background:#3b3266;color:#d9d0ff}" +
      ".medbox-listener__state[data-state=error]{background:#5b2029;color:#ffd4da}" +
      ".medbox-listener__notice{max-height:170px;overflow:auto;margin:8px 0;padding:10px;border-left:3px solid #57dfc4;background:#0d2029;color:#dce9ec}" +
      ".medbox-listener__status{min-height:38px;margin:8px 0;color:#cfe2e6}" +
      ".medbox-listener__status.bad{color:#ff9eaa}" +
      ".medbox-listener__actions{display:flex;flex-wrap:wrap;gap:8px}.medbox-listener .btn{margin:0}" +
      ".medbox-listener button[hidden]{display:none!important}";
    document.head.appendChild(style);
  }

  function ensureDock(btn) {
    var dock = el("micDock");
    if (dock) return dock;
    injectStyles();
    dock = document.createElement("section");
    dock.id = "micDock";
    dock.className = "medbox-listener";
    dock.setAttribute("aria-label", "Écoute locale MedBox");
    dock.innerHTML =
      '<div class="medbox-listener__top"><span class="medbox-listener__title">Écoute locale</span>' +
      '<span id="micState" class="medbox-listener__state" data-state="off">ARRÊTÉ</span></div>' +
      '<p id="micConsentNotice" class="medbox-listener__notice">' + CONSENT_TEXT + '</p>' +
      '<p id="micStatus" class="medbox-listener__status" role="status" aria-live="polite">' +
      'Activez le microphone pour commencer.</p>' +
      '<div id="micActions" class="medbox-listener__actions"></div>';
    document.body.appendChild(dock);
    var actions = el("micActions");
    actions.appendChild(btn);

    var pause = document.createElement("button");
    pause.type = "button";
    pause.id = "micPauseBtn";
    pause.className = "btn";
    pause.textContent = "Mettre en pause";
    pause.hidden = true;
    actions.appendChild(pause);

    var revoke = document.createElement("button");
    revoke.type = "button";
    revoke.id = "micRevokeBtn";
    revoke.className = "btn";
    revoke.textContent = "Retirer mon accord";
    revoke.hidden = true;
    actions.appendChild(revoke);

    ui = {
      dock: dock,
      state: el("micState"),
      status: el("micStatus"),
      notice: el("micConsentNotice"),
      main: btn,
      pause: pause,
      revoke: revoke
    };
    return dock;
  }

  function transition(code, message, bad) {
    var state = STATES[code] || STATES.OFF;
    if (ui.state) {
      ui.state.textContent = state[0];
      ui.state.dataset.state = state[1];
    }
    if (ui.status) {
      ui.status.textContent = message || "";
      ui.status.classList.toggle("bad", !!bad);
    }
    var legacy = el("micOut");
    if (legacy) {
      legacy.textContent = message || "";
      legacy.classList.toggle("bad", !!bad);
    }
  }

  function setButtons() {
    if (!ui.main) return;
    ui.main.textContent = arming ? "Activation…" : (paused ? "Reprendre l’écoute" :
      (running ? "Écoute active" : "Activer MedBox"));
    ui.main.disabled = !available || arming || (running && !paused);
    if (ui.pause) ui.pause.hidden = !running;
    if (ui.revoke) ui.revoke.hidden = !consented && !running && !paused;
    if (ui.notice) ui.notice.hidden = consented;
  }

  function mimeType() {
    var tries = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (var i = 0; i < tries.length; i++) {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(tries[i])) return tries[i];
    }
    return "";
  }

  function stopTracks() {
    if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
    stream = null;
  }

  function startAuditSession() {
    if (sessionId) return Promise.resolve(sessionId);
    return fetch("/api/voice/sessions", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ languages: ["fr", "en"], client: "local-web" })
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok || !body.session_id) throw new Error(body.detail || "session failed");
        sessionId = body.session_id;
        return sessionId;
      });
    });
  }

  function auditConsent(decision, language) {
    if (!sessionId) return Promise.reject(new Error("missing listening session"));
    return fetch("/api/voice/sessions/" + encodeURIComponent(sessionId) + "/consent", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: decision,
        method: "voice",
        language: language || "und"
      })
    }).then(function (response) {
      if (!response.ok) throw new Error("consent audit failed");
    });
  }

  function endAuditSession() {
    var ending = sessionId;
    sessionId = null;
    if (!ending) return Promise.resolve();
    return fetch("/api/voice/sessions/" + encodeURIComponent(ending) + "/end", {
      method: "POST",
      cache: "no-store",
      keepalive: true
    }).catch(function () {});
  }

  function clearAudioGraph() {
    if (vadTimer) { clearTimeout(vadTimer); vadTimer = 0; }
    try { if (source) source.disconnect(); } catch (ignore) {}
    source = null;
    analyser = null;
    if (audioContext) {
      try { audioContext.close(); } catch (ignore2) {}
    }
    audioContext = null;
  }

  function stopCapture() {
    running = false;
    arming = false;
    armGeneration += 1;
    wakeUntil = 0;
    hasSpeech = false;
    loudFrames = 0;
    if (rec && rec.state !== "inactive") {
      rec._medboxKeep = false;
      try { rec.stop(); } catch (ignore) {}
    }
    rec = null;
    clearAudioGraph();
    stopTracks();
    if (root.MedBox && MedBox.voice && MedBox.voice.cancelConsentSpeech) {
      MedBox.voice.cancelConsentSpeech();
    }
  }

  function resetSpeechFlags() {
    hasSpeech = false;
    loudFrames = 0;
    speechStartedAt = 0;
    lastLoudAt = 0;
  }

  function startSegmentRecorder() {
    if (!running || !stream || rec) return;
    var chunks = [];
    var type = mimeType();
    var current;
    try {
      current = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
    } catch (err) {
      transition("ERROR", "Impossible de démarrer l’enregistrement local.", true);
      stopCapture();
      setButtons();
      return;
    }
    rec = current;
    current._medboxKeep = false;
    current.addEventListener("dataavailable", function (event) {
      if (event.data && event.data.size) chunks.push(event.data);
    });
    current.addEventListener("stop", function () {
      var keep = !!current._medboxKeep;
      var blob = keep ? new Blob(chunks, { type: current.mimeType || "audio/webm" }) : null;
      chunks.length = 0;
      if (rec === current) rec = null;
      resetSpeechFlags();
      if (running) startSegmentRecorder();
      if (blob && blob.size >= MIN_BLOB_BYTES) enqueue(blob);
      blob = null;
    });
    segmentStartedAt = Date.now();
    current.start(250);
  }

  function finishSegment(keep) {
    var current = rec;
    if (!current || current.state === "inactive") return;
    current._medboxKeep = !!(keep && hasSpeech);
    if (current._medboxKeep) transition("TRANSCRIBING", "Transcription locale en cours…");
    try { current.stop(); } catch (ignore) {}
  }

  function rmsLevel() {
    var size = analyser.fftSize || 1024;
    if (analyser.getFloatTimeDomainData) {
      var floats = new Float32Array(size);
      analyser.getFloatTimeDomainData(floats);
      var sum = 0;
      for (var i = 0; i < floats.length; i++) sum += floats[i] * floats[i];
      return Math.sqrt(sum / floats.length);
    }
    var bytes = new Uint8Array(size);
    analyser.getByteTimeDomainData(bytes);
    var total = 0;
    for (var j = 0; j < bytes.length; j++) {
      var sample = (bytes[j] - 128) / 128;
      total += sample * sample;
    }
    return Math.sqrt(total / bytes.length);
  }

  function vadTick() {
    vadTimer = 0;
    if (!running || !analyser) return;
    if (root.MedBox && MedBox.voice && MedBox.voice.isSpeaking && MedBox.voice.isSpeaking()) {
      if (rec) finishSegment(false);
      vadTimer = setTimeout(vadTick, 80);
      return;
    }

    var now = Date.now();
    var rms = rmsLevel();
    var threshold = Math.max(0.016, Math.min(0.075, noiseFloor * 3.2));
    var loud = rms > threshold;
    if (!hasSpeech && !loud) noiseFloor = noiseFloor * 0.97 + rms * 0.03;
    if (loud) loudFrames += 1; else loudFrames = Math.max(0, loudFrames - 1);

    if (!hasSpeech && loudFrames >= 2) {
      hasSpeech = true;
      speechStartedAt = now;
      lastLoudAt = now;
      transition("SPEECH", "Parole détectée — traitement local uniquement.");
    } else if (hasSpeech && loud) {
      lastLoudAt = now;
    }

    if (hasSpeech && ((now - lastLoudAt) >= END_SILENCE_MS ||
                      (now - speechStartedAt) >= MAX_UTTERANCE_MS)) {
      finishSegment(true);
    } else if (!hasSpeech && rec && (now - segmentStartedAt) >= IDLE_SEGMENT_MS) {
      finishSegment(false);
    }
    vadTimer = setTimeout(vadTick, 60);
  }

  function startAudioGraph(s) {
    var AudioCtor = root.AudioContext || root.webkitAudioContext;
    audioContext = new AudioCtor();
    source = audioContext.createMediaStreamSource(s);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.15;
    source.connect(analyser);
    if (audioContext.state === "suspended" && audioContext.resume) audioContext.resume();
  }

  function beginListening() {
    if (!stream) return;
    arming = false;
    running = true;
    paused = false;
    noiseFloor = 0.006;
    resetSpeechFlags();
    startSegmentRecorder();
    vadTimer = setTimeout(vadTick, 60);
    transition(consented ? "LISTENING" : "CONSENT", consented
      ? "À l’écoute. Dites « MedBox », puis votre demande."
      : "J’attends votre réponse : « J’accepte », « oui », « I accept » ou « yes ».");
    setButtons();
  }

  function arm() {
    if (!available || !supported() || arming || running) return;
    if (paused) paused = false;
    arming = true;
    var generation = ++armGeneration;
    transition("ARMING", "Autorisez le microphone dans le navigateur…");
    if (ui.notice) ui.notice.hidden = consented;
    setButtons();
    navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false
    }).then(function (s) {
      if (generation !== armGeneration) {
        s.getTracks().forEach(function (track) { track.stop(); });
        return;
      }
      stream = s;
      stream.getTracks().forEach(function (track) {
        track.addEventListener("ended", function () {
          if (!running && !arming) return;
          stopCapture();
          transition("ERROR", "Le microphone a été débranché ou retiré.", true);
          setButtons();
        });
      });
      startAudioGraph(s);
      startAuditSession().then(function () {
        if (generation !== armGeneration || !stream) {
          endAuditSession();
          return;
        }
        if (consented) { beginListening(); return; }
        transition("CONSENT", "MedBox présente les conditions d’écoute…");
        var spoken = root.MedBox && MedBox.voice && MedBox.voice.speakConsentNotice
          ? MedBox.voice.speakConsentNotice(CONSENT_TEXT)
          : Promise.resolve(false);
        Promise.resolve(spoken).then(function () {
          if (generation === armGeneration && stream) beginListening();
        });
      }).catch(function () {
        if (generation !== armGeneration) return;
        stopCapture();
        transition("ERROR", "La session de consentement locale n’a pas pu être ouverte.", true);
        setButtons();
      });
    }).catch(function (err) {
      stopCapture();
      var refused = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      transition("ERROR", refused
        ? "Accès refusé. Cliquez sur l’icône du microphone du navigateur pour l’autoriser."
        : "Aucun microphone utilisable n’a été trouvé.", true);
      setButtons();
    });
  }

  function normalize(text) {
    return String(text || "").toLowerCase()
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .replace(/[’']/g, " ").replace(/[^a-z0-9]+/g, " ").trim();
  }

  function consentDecision(text) {
    var value = normalize(text);
    var negative = /(^| )(non|no|je refuse|i refuse|je n accepte pas|i do not accept|i don t accept)( |$)/;
    if (negative.test(value)) return "reject";
    // Consent must be the whole answer, not one tempting word buried in a
    // sentence such as "je n'ai pas dit oui". Allow the natural pairings but
    // nothing else; uncertainty keeps the gate closed.
    var positive = {
      "j accepte": true,
      "oui": true,
      "oui j accepte": true,
      "j accepte oui": true,
      "i accept": true,
      "yes": true,
      "yes i accept": true,
      "i accept yes": true
    };
    return positive[value] === true ? "accept" : "unknown";
  }

  function hasWakeWord(text) {
    return /(^|\s)med[\s-]*box(?=\s|[,.!?:;]|$)/i.test(String(text || ""));
  }

  function withoutWakeWord(text) {
    return String(text || "")
      .replace(/(^|\s)med[\s-]*box(?=\s|[,.!?:;]|$)[\s,.!?:;-]*/i, " ")
      .trim();
  }

  function postAudio(blob) {
    return fetch("/api/voice/transcribe", {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": blob.type || "audio/webm",
        "X-MedBox-Purpose": consented ? "wake" : "consent"
      },
      body: blob
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        return { ok: response.ok, status: response.status, body: body };
      });
    });
  }

  function recordCommand(text, confidence, generation) {
    if (generation !== armGeneration) return Promise.resolve();
    var patientId = getPatient ? getPatient() : null;
    wakeUntil = 0;
    return fetch("/api/assistant/command", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, patient_id: patientId, confidence: confidence })
    }).then(function (response) {
      return response.json().then(function (body) { return { ok: response.ok, body: body }; });
    }).then(function (result) {
      if (!result.ok) throw new Error(result.body.detail || result.body.error || "record failed");
      if (generation !== armGeneration) return;
      var reply = result.body.reply || ("Commande entendue : « " + text + " »");
      // How the words were understood, when it was not the allow-list: the
      // model within the station's own actions, or a phrase learned before.
      var how = result.body.resolved_by;
      if (how === "model" || how === "learned") {
        reply += " (compris comme : " + (result.body.understood_as || "") +
          (how === "learned" ? ", formulation déjà apprise" : ", formulation apprise à l’instant") + ")";
      }
      transition("LISTENING", reply);
      if (onReported) onReported(result.body.reported || []);
      root.dispatchEvent(new CustomEvent("medbox-command", { detail: result.body }));
      if (root.MedBox && MedBox.voice && MedBox.voice.speakText) {
        MedBox.voice.speakText(reply);
      }
      if (result.body.action === "pause") setTimeout(pause, 250);
    });
  }

  function handleTranscript(heard, generation) {
    if (generation !== armGeneration) return Promise.resolve();
    var text = heard && heard.text ? String(heard.text).trim() : "";
    if (!text) return Promise.resolve();
    if (!consented) {
      if (typeof heard.confidence !== "number" || heard.confidence < MIN_CONSENT_CONFIDENCE) {
        transition("CONSENT", "Réponse incertaine. Répétez clairement une phrase de consentement.");
        return Promise.resolve();
      }
      var decision = consentDecision(text);
      text = "";
      if (decision === "accept") {
        return auditConsent("accepted", heard.language).then(function () {
          if (generation !== armGeneration) return;
          consented = true;
          paused = false;
          transition("LISTENING", "Consentement reçu. Dites « MedBox », puis votre demande.");
          setButtons();
        }).catch(function () {
          if (generation !== armGeneration) return;
          stopCapture();
          transition("ERROR", "Le consentement n’a pas pu être enregistré localement.", true);
          setButtons();
        });
      } else if (decision === "reject") {
        return auditConsent("refused", heard.language).catch(function () {}).then(function () {
          if (generation !== armGeneration) return;
          stopCapture();
          consented = false;
          endAuditSession();
          transition("OFF", "Consentement non accordé. Le microphone MedBox est fermé.");
          setButtons();
        });
      } else {
        transition("CONSENT", "Réponse non reconnue. Dites clairement « J’accepte », « oui », « I accept » ou « yes ».");
      }
      return Promise.resolve();
    }

    var now = Date.now();
    if (wakeUntil && now > wakeUntil) wakeUntil = 0;
    if (hasWakeWord(text)) {
      var command = withoutWakeWord(text);
      if (!command) {
        wakeUntil = now + WAKE_WINDOW_MS;
        transition("WAKE", "Je vous écoute. Formulez votre demande maintenant.");
        return Promise.resolve();
      }
      return recordCommand(command, heard.confidence, generation);
    }
    if (wakeUntil > now) return recordCommand(text, heard.confidence, generation);
    transition("LISTENING", "À l’écoute. Dites « MedBox », puis votre demande.");
    return Promise.resolve();
  }

  function processBlob(blob, generation) {
    if (generation !== armGeneration) return Promise.resolve();
    transition("TRANSCRIBING", consented
      ? "Vérification locale du mot d’appel…"
      : "Vérification locale du consentement…");
    return postAudio(blob).then(function (result) {
      blob = null;
      if (generation !== armGeneration) return;
      if (!result.ok) {
        if (result.status === 503) {
          transition(consented ? "LISTENING" : "CONSENT", consented
            ? "Rien de net n’a été entendu. Dites « MedBox » pour m’appeler."
            : "Je n’ai pas compris. Répétez une phrase de consentement.");
          return;
        }
        throw new Error(result.body.detail || result.body.error || "transcription failed");
      }
      return handleTranscript(result.body.heard || {}, generation);
    }).catch(function () {
      blob = null;
      if (generation !== armGeneration) return;
      transition("ERROR", "La transcription locale a échoué. Les mesures continuent normalement.", true);
    });
  }

  function drain() {
    if (uploading || !pending.length) return;
    uploading = true;
    var item = pending.shift();
    processBlob(item.blob, item.generation).then(function () {
      item = null;
      uploading = false;
      drain();
    }, function () {
      item = null;
      uploading = false;
      drain();
    });
  }

  function enqueue(blob) {
    while (pending.length >= MAX_PENDING) pending.shift();
    pending.push({ blob: blob, generation: armGeneration });
    drain();
  }

  function pause() {
    if (!running) return;
    stopCapture();
    pending.length = 0;
    paused = true;
    transition("PAUSED", "Écoute suspendue. Cliquez sur « Reprendre l’écoute » pour réactiver le microphone.");
    setButtons();
  }

  function revoke() {
    var audit = consented ? auditConsent("revoked", "fr").catch(function () {}) : Promise.resolve();
    stopCapture();
    pending.length = 0;
    consented = false;
    paused = false;
    audit.then(endAuditSession);
    transition("OFF", "Consentement retiré. MedBox n’accède plus au microphone. Vous pouvez aussi retirer l’autorisation dans le navigateur.");
    setButtons();
  }

  function attach(getPatientFn, onReportedFn) {
    var btn = el("micBtn");
    if (!btn || !supported()) return;
    getPatient = typeof getPatientFn === "function" ? getPatientFn : getPatient;
    onReported = typeof onReportedFn === "function" ? onReportedFn : null;
    ensureDock(btn);
    btn.setAttribute("aria-label", "Activer l’écoute locale MedBox");
    btn.addEventListener("click", arm);
    ui.pause.addEventListener("click", pause);
    ui.revoke.addEventListener("click", revoke);
    root.addEventListener("beforeunload", function () {
      stopCapture();
      endAuditSession();
    });
    transition("OFF", "Activez le microphone pour commencer. Le navigateur demandera votre autorisation.");
    setButtons();
  }

  function setAvailable(ok, why) {
    var btn = el("micBtn");
    if (!btn || !supported()) return;
    available = !!ok;
    btn.hidden = !ok;
    btn.disabled = !ok || arming || (running && !paused);
    btn.title = ok ? "Activer l’écoute locale continue"
                   : (why || "Aucun modèle vocal local sur cette machine");
    var dock = ensureDock(btn);
    dock.hidden = !ok;
    if (!ok && (running || arming)) {
      stopCapture();
      transition("ERROR", why || "Le modèle vocal local n’est plus disponible.", true);
    }
    setButtons();
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.mic = {
    attach: attach,
    setAvailable: setAvailable,
    supported: supported,
    pause: pause,
    revoke: revoke,
    consentDecision: consentDecision,
    hasWakeWord: hasWakeWord,
    state: function () {
      return { available: available, arming: arming, running: running, consented: consented, paused: paused };
    }
  };
})(window);
