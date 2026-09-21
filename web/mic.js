/* Hold to speak: recording a crew member's words in the browser.
 *
 * Explicitly NOT the Web Speech API. In Chrome that ships the audio to Google,
 * which would quietly undo the one claim this whole project is built on. The
 * recording goes to this machine's own server, is transcribed by a model on
 * this machine's disk, and never leaves. That is worth the extra code.
 *
 * Hold to record rather than click-to-start, click-to-stop. Somebody holding a
 * console over a patient should never have to wonder whether it is still
 * listening, and a button that is only recording while your finger is on it
 * cannot be left on by accident.
 *
 * What comes back is a guess, and the interface treats it as one. It is filed
 * as a reported symptom with source "voice" and the transcriber's confidence
 * attached, which the panel renders as "heard · N% sure". An operator acting
 * on a misheard symptom needs to be able to see that it was misheard.
 */
(function (root) {
  "use strict";

  // Plenty for a sentence, and short enough that a button left held by a
  // pocket cannot fill a disk.
  var MAX_MS = 15000;

  var rec = null, chunks = [], stream = null, startedAt = 0;

  function el(id) { return document.getElementById(id); }

  function show(msg, bad) {
    var out = el("micOut");
    if (!out) return;
    out.textContent = msg || "";
    out.classList.toggle("bad", !!bad);
  }

  function supported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
              root.MediaRecorder);
  }

  /* Which container this browser will actually give us. Chrome and Firefox
     disagree, and an unsupported mimeType makes the constructor throw, so ask
     rather than assume. PyAV decodes all of these. */
  function mimeType() {
    var tries = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (var i = 0; i < tries.length; i++) {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(tries[i])) return tries[i];
    }
    return "";
  }

  function stopTracks() {
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
  }

  function start(patientId, onDone) {
    if (rec || !supported()) return;
    show("Listening…");
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (s) {
      stream = s;
      chunks = [];
      var type = mimeType();
      rec = type ? new MediaRecorder(s, { mimeType: type }) : new MediaRecorder(s);
      rec.addEventListener("dataavailable", function (e) {
        if (e.data && e.data.size) chunks.push(e.data);
      });
      rec.addEventListener("stop", function () {
        var held = Date.now() - startedAt;
        var blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        rec = null;
        stopTracks();
        // A tap rather than a hold. Say so instead of sending a click.
        if (held < 400 || blob.size < 1200) { show("Hold the button while they speak."); return; }
        send(patientId, blob, onDone);
      });
      startedAt = Date.now();
      rec.start();
      setTimeout(function () { if (rec) stop(); }, MAX_MS);
    }).catch(function (err) {
      stopTracks();
      show(err && err.name === "NotAllowedError"
        ? "The microphone was refused. Type it instead."
        : "No microphone here. Type it instead.", true);
    });
  }

  function stop() {
    if (rec && rec.state !== "inactive") rec.stop();
  }

  function send(patientId, blob, onDone) {
    show("Transcribing…");
    fetch("/api/patient/" + encodeURIComponent(patientId) + "/listen", {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob
    })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        if (!res.ok) { show(res.body.detail || res.body.error || "Nothing was transcribed.", true); return; }
        var heard = res.body.heard || {};
        // Echo what was heard, because the operator has to be able to catch a
        // misheard symptom before it becomes part of the record.
        show("Heard: “" + (heard.text || "") + "”");
        if (onDone) onDone(res.body.reported || []);
      })
      .catch(function () { show("The station did not answer. Type it instead.", true); });
  }

  /* Wire the button for a view. `getPatient` returns the selected id, and
     `onReported` is handed the refreshed list. */
  function attach(getPatient, onReported) {
    var btn = el("micBtn");
    if (!btn || !supported()) return;
    // Deliberately does NOT reveal the button. Whether this browser can
    // record and whether this machine can transcribe are different
    // questions, and only setAvailable knows the second one.

    function begin(e) {
      e.preventDefault();
      var pid = getPatient();
      if (!pid) return;
      btn.classList.add("recording");
      btn.textContent = "Listening…";
      start(pid, onReported);
    }
    function end() {
      btn.classList.remove("recording");
      btn.textContent = "Hold to speak";
      stop();
    }

    btn.addEventListener("mousedown", begin);
    btn.addEventListener("touchstart", begin, { passive: false });
    ["mouseup", "mouseleave", "touchend", "touchcancel"].forEach(function (ev) {
      btn.addEventListener(ev, end);
    });
    // Keyboard: space or enter held. Without this the feature is unreachable
    // for anyone not using a mouse.
    btn.addEventListener("keydown", function (e) {
      if ((e.key === " " || e.key === "Enter") && !e.repeat) begin(e);
    });
    btn.addEventListener("keyup", function (e) {
      if (e.key === " " || e.key === "Enter") end();
    });
  }

  /* Called on every frame. The server says whether this machine can transcribe
     at all; a button that appears and then fails is worse than no button. */
  function setAvailable(ok, why) {
    var btn = el("micBtn");
    if (!btn || !supported()) return;
    /* Hidden, not merely disabled. attach() used to reveal the button the
       moment the BROWSER could record, and this function then greyed it out
       — so a machine with no speech model showed a dead button in the middle
       of the patient panel, with the reason buried in a tooltip nobody hovers
       during a consultation. The markup ships it hidden and it stays hidden
       until the station says it can listen. */
    btn.hidden = !ok;
    btn.disabled = !ok;
    btn.title = ok ? "Hold to record what they said"
                   : (why || "No speech model on this machine");
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.mic = { attach: attach, setAvailable: setAvailable, supported: supported };
})(window);
