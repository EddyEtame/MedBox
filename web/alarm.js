/* The alarm: a sound and a flash when the ship goes to a high crisis, on
 * top of the referent's voice, not instead of it.
 *
 * Eddy, 25 Sep: "in a high crisis situation there should be alarms that
 * ring, not just the AI talking; the AI will talk but the alarms ring at
 * the same time." A member at priority « haute » (NEWS2 seven or more)
 * rings a two-tone siren for three seconds and the page flashes red; a
 * member at « moyenne » gets a double beep. Synthesised here with WebAudio,
 * no file to load, so it cannot be missing. The browser only lets audio
 * start after a gesture: the context is opened on the first click or key,
 * and until then the flash still shows. */
(function (root) {
  "use strict";
  var ctx = null, lastRing = {}, flashTimer = null;

  function context() {
    if (ctx) return ctx;
    var AC = root.AudioContext || root.webkitAudioContext;
    if (!AC) return null;
    try { ctx = new AC(); } catch (e) { return null; }
    return ctx;
  }
  function unlock() {
    var c = context();
    if (c && c.state === "suspended") c.resume().catch(function () {});
  }
  ["pointerdown", "keydown", "touchstart"].forEach(function (ev) {
    root.addEventListener(ev, unlock, { passive: true });
  });

  function tone(c, at, freq, dur, gain, type) {
    var o = c.createOscillator(), g = c.createGain();
    o.type = type || "square";
    o.frequency.setValueAtTime(freq, at);
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(gain, at + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    o.connect(g); g.connect(c.destination);
    o.start(at); o.stop(at + dur + 0.05);
  }

  // High: a siren, two tones alternating for three seconds.
  function siren(c) {
    var t = c.currentTime + 0.02;
    for (var i = 0; i < 6; i++) tone(c, t + i * 0.5, i % 2 ? 660 : 880, 0.48, 0.12, "square");
  }
  // Medium: two short beeps.
  function beeps(c) {
    var t = c.currentTime + 0.02;
    tone(c, t, 740, 0.16, 0.1, "triangle");
    tone(c, t + 0.24, 740, 0.16, 0.1, "triangle");
  }

  function injectStyles() {
    if (document.getElementById("medboxAlarmStyles")) return;
    var style = document.createElement("style");
    style.id = "medboxAlarmStyles";
    style.textContent =
      "@keyframes medboxAlarmFlash{0%,100%{box-shadow:inset 0 0 0 0 rgba(255,74,74,0)}50%{box-shadow:inset 0 0 0 14px rgba(255,74,74,.55)}}" +
      "body.alarm-high::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:9998;animation:medboxAlarmFlash .5s ease-in-out 6}" +
      "body.alarm-medium::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:9998;box-shadow:inset 0 0 0 8px rgba(240,196,89,.45);animation:medboxAlarmFlash .6s ease-in-out 2}" +
      ".alarm-banner{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:9999;padding:9px 18px;border-radius:100px;" +
      "font:700 13px/1 ui-monospace,Consolas,monospace;letter-spacing:.12em;text-transform:uppercase;color:#1a0505;background:#ff4a4a;" +
      "box-shadow:0 8px 30px rgba(255,74,74,.45);animation:medboxAlarmBanner .5s ease-in-out infinite alternate}" +
      ".alarm-banner.medium{background:#f0c459;color:#241a02;box-shadow:0 8px 30px rgba(240,196,89,.4)}" +
      "@keyframes medboxAlarmBanner{from{opacity:.75}to{opacity:1}}" +
      "@media (prefers-reduced-motion:reduce){body.alarm-high::after,body.alarm-medium::after,.alarm-banner{animation:none}}";
    document.head.appendChild(style);
  }

  function flash(level, text) {
    injectStyles();
    var body = document.body;
    body.classList.remove("alarm-high", "alarm-medium");
    void body.offsetWidth;   // restart the animation
    body.classList.add(level === "high" ? "alarm-high" : "alarm-medium");
    var banner = document.getElementById("medboxAlarmBanner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "medboxAlarmBanner";
      banner.setAttribute("role", "alert");
      body.appendChild(banner);
    }
    banner.className = "alarm-banner" + (level === "high" ? "" : " medium");
    banner.textContent = text || (level === "high" ? "Alerte haute à bord" : "Alerte à bord");
    banner.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(function () {
      banner.hidden = true;
      body.classList.remove("alarm-high", "alarm-medium");
    }, level === "high" ? 6000 : 3000);
  }

  /* ring(level, key, text): level "high" or "medium"; key (a member id)
     keeps one member from ringing more than once every twenty seconds. */
  function ring(level, key, text) {
    if (level !== "high" && level !== "medium") return false;
    var now = Date.now(), k = String(key || level);
    if (lastRing[k] && now - lastRing[k] < 20000) return false;
    lastRing[k] = now;
    flash(level, text);
    var c = context();
    if (!c) return true;
    if (c.state === "suspended") c.resume().catch(function () {});
    try { if (level === "high") siren(c); else beeps(c); } catch (e) {}
    return true;
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.alarm = { ring: ring, unlock: unlock };
})(window);
