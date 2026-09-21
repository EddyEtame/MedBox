/* Playing what the station says.
 *
 * The server decides WHAT to say, in Python, from measurements. This file only
 * plays it. That split is the point: nothing here can invent a line, so the
 * rule "the station speaks from measurements, never for the model" is true of
 * the code and not just of the intention.
 *
 * Every clip is a file that already exists under /static/speech/, rendered
 * once at build time. So there is no engine here, no synthesis, no network and
 * nothing to wait for — playing a line is a disk read.
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
    if (playing || !queue.length || !on) return;
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

  root.MedBox = root.MedBox || {};
  root.MedBox.voice = {
    say: say,
    setOn: setOn,
    isOn: function () { return on; },
    restore: restore,
    nameStem: nameStem,
    missing: function () { return Object.keys(missing); }
  };
})(window);
