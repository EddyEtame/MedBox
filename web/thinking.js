/* The referent thinks out loud.
 *
 * While an assessment or an answer is on its way, the page shows the steps
 * the station is taking, in order, with the seconds ticking, and the voice
 * says « un instant » once when the answer is not immediate. Eddy, 24 Sep:
 * "if thinking is taking a while, add things that show thinking is going
 * on — pulling data, analysing all possibilities…". The steps are honest
 * about what happens: the facts are read, compared to the baseline, the
 * isolation registers are checked, then the model phrases the answer. */
(function (root) {
  "use strict";

  var STEPS = [
    [0, "Je relève les constantes"],
    [1600, "Je compare à la ligne de base"],
    [3600, "Je vérifie l’isolement et les contacts"],
    [5800, "J’examine toutes les possibilités"],
    [8200, "Je formule ma réponse"],
    [12000, "Je relis avant de répondre"],
    [18000, "Le modèle est lent sur ce processeur, je continue"]
  ];
  var SELF = {
    "Je relève les constantes": "Je relève vos constantes",
    "Je compare à la ligne de base": "Je compare à votre ligne de base",
    "Je vérifie l’isolement et les contacts": "Je vérifie votre isolement et vos contacts"
  };
  var SAY = "Un instant, je regarde les constantes.";
  var SAY_SELF = "Un instant, je regarde vos constantes.";

  function injectStyles() {
    if (document.getElementById("medboxThinkingStyles")) return;
    var style = document.createElement("style");
    style.id = "medboxThinkingStyles";
    style.textContent =
      ".thinking{display:block;padding:8px 10px;border-left:3px solid rgba(123,232,211,.6);background:rgba(123,232,211,.06);" +
      "border-radius:0 8px 8px 0;font:13px/1.45 system-ui,sans-serif;color:inherit}" +
      ".thinking__now{display:flex;align-items:center;gap:8px}" +
      ".thinking__dot{width:9px;height:9px;border-radius:50%;background:#7be8d3;flex:none;animation:thinkingPulse 1.1s ease-in-out infinite}" +
      ".thinking__label{font-weight:600}" +
      ".thinking__t{margin-left:auto;opacity:.55;font-variant-numeric:tabular-nums;font-size:12px}" +
      ".thinking__done{list-style:none;margin:6px 0 0;padding:0;opacity:.6;font-size:12px}" +
      ".thinking__done li{margin:2px 0;padding-left:16px;position:relative}" +
      ".thinking__done li::before{content:'✓';position:absolute;left:0;color:#7be8d3}" +
      "@keyframes thinkingPulse{0%,100%{transform:scale(.7);opacity:.5}50%{transform:scale(1.15);opacity:1}}" +
      "@media (prefers-reduced-motion:reduce){.thinking__dot{animation:none}}";
    document.head.appendChild(style);
  }

  /* start(out, {self, say, lang, speakAfter, speak}) -> {stop(), elapsed()}
     `out` is emptied and receives the live steps; the caller overwrites it
     with the answer when it arrives and calls stop(). */
  function start(out, opts) {
    opts = opts || {};
    injectStyles();
    var timers = [], startedAt = Date.now(), stopped = false;
    var box = document.createElement("div");
    box.className = "thinking";
    box.setAttribute("role", "status");
    box.setAttribute("aria-live", "polite");
    box.innerHTML = '<div class="thinking__now"><i class="thinking__dot"></i><span class="thinking__label"></span>' +
      '<span class="thinking__t">0 s</span></div><ul class="thinking__done"></ul>';
    out.innerHTML = "";
    out.appendChild(box);
    var label = box.querySelector(".thinking__label");
    var doneUl = box.querySelector(".thinking__done");
    var clockEl = box.querySelector(".thinking__t");

    function wording(text) { return opts.self && SELF[text] ? SELF[text] : text; }
    function show(i) {
      if (stopped) return;
      if (i > 0) {
        var li = document.createElement("li");
        li.textContent = wording(STEPS[i - 1][1]);
        doneUl.appendChild(li);
      }
      label.textContent = wording(STEPS[i][1]) + "…";
    }
    STEPS.forEach(function (s, i) { timers.push(setTimeout(function () { show(i); }, s[0])); });
    var clock = setInterval(function () {
      if (!stopped) clockEl.textContent = Math.round((Date.now() - startedAt) / 1000) + " s";
    }, 1000);
    if (opts.speak !== false) {
      timers.push(setTimeout(function () {
        if (stopped) return;
        var text = opts.self ? SAY_SELF : SAY;
        if (typeof opts.say === "function") opts.say(text);
        else if (root.MedBox && MedBox.voice) MedBox.voice.speakText(text, opts.lang || "fr");
      }, opts.speakAfter || 700));
    }
    return {
      stop: function () { stopped = true; timers.forEach(clearTimeout); clearInterval(clock); },
      elapsed: function () { return Date.now() - startedAt; }
    };
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.thinking = { start: start, STEPS: STEPS };
})(window);
