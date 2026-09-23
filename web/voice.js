/* Playing what the station says.
 *
 * The server decides WHAT to say, in Python, from measurements. This file only
 * plays it. That split is the point: nothing here can invent a line, so the
 * rule "the station speaks from measurements, never for the model" is true of
 * the code and not just of the intention.
 *
 * Operational alerts are files that already exist under /static/speech/,
 * rendered once at build time. So there is no model response to synthesise,
 * no network and nothing to wait for — playing an alert is a disk read. The
 * one longer exception is the fixed French consent notice: it prefers a
 * bundled consent_fr.wav and may fall back to an installed, explicitly local
 * French browser voice. Its text is deterministic and remains visible when no
 * such voice exists.
 *
 * Three things this has to get right, none of them obvious:
 *
 * 1. Never overlap. Two announcements at once is worse than neither, because
 *    the one you needed is the one you cannot make out. Everything goes
 *    through one queue.
 * 2. Drop rather than back up. If the ship deteriorates faster than the
 *    station can talk — which is exactly what the contamination scenario
 *    does — a queue that keeps everything ends up narrating something that
 *    stopped being true a minute ago. So the queue is short and the oldest
 *    go, because in an emergency the newest line is the true one.
 * 3. Start silent. A browser will not play audio before the person has
 *    interacted with the page, and a console that appears broken until you
 *    click it is worse than one that is quiet until you ask. So sound is off
 *    until it is switched on, and switching it on is itself the interaction
 *    that unlocks playback.
 */
(function (root) {
  "use strict";

  var BASE = "/static/speech/";
  // Short. See note 2 above: in a deteriorating ship, old news is wrong news.
  var MAX_QUEUE = 3;
  // The pause between a name and its phrase. A ship's announcement is a PA
  // system, not a smooth sentence, and the gap after a name is what a PA
  // sounds like. It is also what makes 40 names x 20 phrases into 40 + 20.
  var GAP_MS = 140;

  var on = false;
  var queue = [];
  var playing = false;
  var cache = {};
  var missing = {};
  var consentPlaying = false;
  var consentAudio = null;
  var consentSerial = 0;

  function clip(stem) {
    if (!cache[stem]) {
      var a = new Audio(BASE + stem + ".wav");
      a.preload = "auto";
      // A clip nobody rendered must not stall the queue for ever. Note it,
      // skip it, carry on: silence in one line beats silence in all of them.
      a.addEventListener("error", function () { missing[stem] = true; });
      cache[stem] = a;
    }
    return cache[stem];
  }

  function playOne(stem) {
    return new Promise(function (resolve) {
      if (missing[stem]) { resolve(); return; }
      var a = clip(stem);
      var done = false;
      function finish() { if (!done) { done = true; resolve(); } }
      a.addEventListener("ended", finish, { once: true });
      a.addEventListener("error", finish, { once: true });
      // A clip that never fires `ended` — a decode failure, a tab throttled in
      // the background — would wedge the queue permanently. Cap the wait.
      setTimeout(finish, 6000);
      a.currentTime = 0;
      var p = a.play();
      if (p && p.catch) p.catch(finish);
    });
  }

  function pump() {
    if (playing || consentPlaying || !queue.length || !on) return;
    playing = true;
    var item = queue.shift();
    var stems = [];
    if (item.name) stems.push(nameStem(item.name));
    stems.push(item.phrase);
    stems.reduce(function (chain, stem, i) {
      return chain
        .then(function () {
          return i === 0 ? null : new Promise(function (r) { setTimeout(r, GAP_MS); });
        })
        .then(function () { return playOne(stem); });
    }, Promise.resolve()).then(function () {
      playing = false;
      pump();
    });
  }

  /* Must match server/speech.py name_stem() exactly. A mismatch here is a
     silent 404 per crew member, so tests/test_speech.py checks both. */
  function nameStem(name) {
    return "name_" + String(name).toLowerCase()
      .replace(/[^a-z0-9]/g, "_").replace(/^_+|_+$/g, "");
  }

  function say(items) {
    if (!on || !items || !items.length) return;
    for (var i = 0; i < items.length; i++) queue.push(items[i]);
    while (queue.length > MAX_QUEUE) queue.shift();
    pump();
  }

  function setOn(v) {
    on = !!v;
    if (!on) { queue.length = 0; }
    try { localStorage.setItem("medbox.voice", on ? "1" : "0"); } catch (e) {}
    return on;
  }

  function restore() {
    // Default off, deliberately. A console that starts talking at somebody who
    // did not ask for it gets muted, and then the channel is gone when it
    // matters.
    try { return localStorage.getItem("medbox.voice") === "1"; } catch (e) { return false; }
  }

  /* Consent is a fixed safety notice, never text produced by the LLM. Prefer
     a pre-rendered French clip when one is bundled. If it is absent, use only
     a French voice explicitly reported by the browser as local; a cloud voice
     would break the offline promise. The full notice is always visible in the
     microphone panel, so missing text-to-speech never blocks consent. */
  function localFrenchSpeech(text, serial) {
    return new Promise(function (resolve) {
      if (!root.speechSynthesis || !root.SpeechSynthesisUtterance) {
        resolve(false);
        return;
      }
      var finished = false;
      function done(value) {
        if (finished) return;
        finished = true;
        resolve(value);
      }
      function choose() {
        var voices = root.speechSynthesis.getVoices ? root.speechSynthesis.getVoices() : [];
        if (!voices.length) return null;
        for (var i = 0; i < voices.length; i++) {
          if (/^fr([-_]|$)/i.test(voices[i].lang || "") && voices[i].localService !== false) {
            return voices[i];
          }
        }
        return false;
      }
      function speak(voice) {
        if (serial !== consentSerial || !voice) { done(false); return; }
        var utterance = new root.SpeechSynthesisUtterance(text);
        utterance.lang = voice.lang || "fr-FR";
        utterance.voice = voice;
        utterance.rate = 0.96;
        utterance.onend = function () { done(true); };
        utterance.onerror = function () { done(false); };
        root.speechSynthesis.speak(utterance);
        setTimeout(function () { done(false); }, 45000);
      }

      var selected = choose();
      if (selected !== null) { speak(selected); return; }
      // Chromium sometimes fills the voice list asynchronously.
      function ready() {
        clearTimeout(wait);
        root.speechSynthesis.removeEventListener("voiceschanged", ready);
        speak(choose());
      }
      var wait = setTimeout(function () {
        root.speechSynthesis.removeEventListener("voiceschanged", ready);
        speak(choose());
      }, 800);
      root.speechSynthesis.addEventListener("voiceschanged", ready);
    });
  }

  function playConsentAsset(text, serial) {
    var url = BASE + "consent_fr.wav";
    return fetch(url, { method: "HEAD", cache: "no-store" }).then(function (response) {
      if (serial !== consentSerial) return false;
      if (!response.ok) throw new Error("missing consent clip");
      return new Promise(function (resolve) {
        var audio = new Audio(url);
        var finished = false;
        consentAudio = audio;
        function done(ok) {
          if (finished) return;
          finished = true;
          consentAudio = null;
          resolve(ok);
        }
        audio.addEventListener("ended", function () { done(true); }, { once: true });
        audio.addEventListener("error", function () { done(false); }, { once: true });
        var promise = audio.play();
        if (promise && promise.catch) promise.catch(function () { done(false); });
        setTimeout(function () { done(false); }, 45000);
      });
    }).then(function (played) {
      return played ? true : localFrenchSpeech(text, serial);
    }).catch(function () {
      missing.consent_fr = true;
      return localFrenchSpeech(text, serial);
    });
  }

  function waitForOperationalLine(serial) {
    return new Promise(function (resolve) {
      function check() {
        if (serial !== consentSerial || !playing) { resolve(); return; }
        setTimeout(check, 80);
      }
      check();
    });
  }

  function speakConsentNotice(text) {
    var serial = ++consentSerial;
    consentPlaying = true;
    return waitForOperationalLine(serial).then(function () {
      return playConsentAsset(text, serial);
    }).then(function (spoken) {
      if (serial !== consentSerial) return false;
      consentPlaying = false;
      pump();
      return spoken;
    }, function () {
      if (serial !== consentSerial) return false;
      consentPlaying = false;
      pump();
      return false;
    });
  }

  /* Speak a short deterministic/local response after a wake-word command.
     It uses only a voice the browser reports as local and is optional: the
     same sentence is always visible in the listening panel. */
  function speakText(text) {
    if (!on || !String(text || "").trim()) return Promise.resolve(false);
    var serial = ++consentSerial;
    consentPlaying = true;
    return waitForOperationalLine(serial).then(function () {
      return localFrenchSpeech(String(text), serial);
    }).then(function (spoken) {
      if (serial !== consentSerial) return false;
      consentPlaying = false;
      pump();
      return spoken;
    }, function () {
      if (serial !== consentSerial) return false;
      consentPlaying = false;
      pump();
      return false;
    });
  }

  function cancelConsentSpeech() {
    consentSerial += 1;
    consentPlaying = false;
    if (consentAudio) {
      try { consentAudio.pause(); } catch (e) {}
      consentAudio = null;
    }
    if (root.speechSynthesis) root.speechSynthesis.cancel();
    pump();
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.voice = {
    say: say,
    setOn: setOn,
    isOn: function () { return on; },
    isSpeaking: function () { return playing || consentPlaying; },
    restore: restore,
    speakConsentNotice: speakConsentNotice,
    speakText: speakText,
    cancelConsentSpeech: cancelConsentSpeech,
    nameStem: nameStem,
    missing: function () { return Object.keys(missing); }
  };
})(window);
