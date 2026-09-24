/* The one place an assistant's answer is turned into pixels.
 *
 * Both views used to render this separately, and a safety audit found the two
 * copies had already drifted: a rule enforced in one was absent from the
 * other. So there is now one renderer, loaded by index.html and ship.html
 * alike, and MedBox.assessment is the only function allowed to draw AI output.
 *
 * It holds three lines that the server cannot hold on its own, because they
 * are properties of the layout rather than of the data:
 *
 * 1. Every assessment carries a provenance banner, unconditionally. The old
 *    interface labelled its output only when a stand-in produced it, which
 *    meant that in the configuration a jury actually sees — a real model
 *    running — the AI region was the one place on screen with nothing saying
 *    where it came from. It sat directly beneath "7 / HIGH / Emergency
 *    response" in the same panel and the same typeface, and a reader fuses
 *    those into a single clinical statement.
 *
 * 2. A sign nobody measured is marked, in the sign, in a different colour.
 *    "Crushing chest pain radiating to the left arm" and "SpO2 89%" are not
 *    the same kind of fact and must not look like it.
 *
 * 3. An assessment goes stale. Vitals stream ten times a second and the band
 *    above redraws on every frame, while the text below is however old it is.
 *    Run a contamination scenario, assess somebody at ROUTINE, and forty
 *    seconds later "no pattern in the measured parameters" is still sitting
 *    under a band that now says HIGH. The assistant is asserting something the
 *    instruments no longer record, with no bad model output involved at all.
 */
(function (root) {
  "use strict";

  var MAX_AGE_MS = 60000;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // What the crew member said is not what the box measured, and the interface
  // says so in the sign itself rather than trusting the reader to remember.
  var SOURCE_LABEL = {
    temperature: "TEMPÉRATURE",
    spo2: "SpO₂",
    pulse: "POULS",
    respiration: "RESPIRATION",
    reported_by_crew_member: "DÉCLARÉ, NON MESURÉ",
    unattributed: "SOURCE ABSENTE"
  };

  var FIT_LABEL = {
    "one measurement fits": "une mesure concorde",
    "several measurements fit": "plusieurs mesures concordent",
    "all measured parameters fit": "tous les paramètres mesurés concordent"
  };

  function blockedLabel(value) {
    var message = String(value || "");
    if (message.indexOf("proposed a treatment") >= 0) {
      return "L’assistant a proposé un traitement. MedBox l’a bloqué : la station ne prescrit pas.";
    }
    if (message.indexOf("restated the urgency") >= 0) {
      return "L’assistant a reformulé la priorité. Cette phrase a été supprimée : NEWS2 décide seul.";
    }
    if (message.indexOf("support no hypothesis") >= 0) {
      return "L’assistant a nié les signes ayant relevé NEWS2. MedBox n’affiche pas cette contradiction.";
    }
    if (message.indexOf("not allowed to") >= 0) {
      return "L’assistant a renvoyé des champs interdits par le contrat : " +
        message.split(":").slice(1).join(":").trim();
    }
    if (message.indexOf("cited no sign") >= 0) {
      return "Une hypothèse ne citait aucun signe et a été supprimée.";
    }
    if (message.indexOf("was not an assessment") >= 0) {
      return "La réponse de l’assistant ne respectait pas le format d’évaluation.";
    }
    return message;
  }

  function failureLabel(value) {
    var message = String(value || "");
    if (message.indexOf("Vitals and triage are unaffected") >= 0) {
      return "Les constantes et la priorisation restent actives. Le mode dégradé fonctionne comme prévu.";
    }
    return message || "Les constantes et la priorisation restent actives.";
  }

  function sign(s) {
    var src = s && s.source ? s.source : "unattributed";
    var measured = src !== "reported_by_crew_member" && src !== "unattributed";
    return '<li class="sign ' + (measured ? "measured" : "unmeasured") + '">' +
      '<span class="src">' + esc(SOURCE_LABEL[src] || src) + "</span>" +
      esc(s && s.text ? s.text : "") + "</li>";
  }

  /* Render one assessment. `body` is the server's response.
   *
   * `opts.flyable` is whether this view can actually fly the camera to the
   * crew member a claim came from. The 3D console can; the flat board has no
   * camera, and an affordance that does nothing when you press it is worse
   * than no affordance at all.
   *
   * Returns HTML; the caller decides where it goes. */
  function render(body, opts) {
    var b = body || {}, o = opts || {}, html = "";

    // Unconditional, and first. Not a footnote, not conditional on the
    // stand-in, not something the reader has to go looking for.
    if (b.stand_in) {
      html += '<div class="ai-provenance standin"><b>Simulateur, pas un modèle de langage.</b> ' +
        "Cette réponse vient de tools/fake_ollama.py : il relit les constantes et applique " +
        "des règles fixes. Il valide le circuit technique, mais ne réfléchit pas et ne doit " +
        "jamais être présenté comme l’assistant.</div>";
    } else {
      html += '<div class="ai-provenance"><b>Évaluation du référent médical de bord</b> (' +
        esc(b.model || "l’assistant") + "), fondée sur les mesures et sur le score NEWS2 " +
        "affiché ci-dessus, que rien ici ne modifie." +
        (b.held_reason === "assistant_down"
          ? " <b>Réponse conservée :</b> écrite il y a " + esc(String(Math.round(b.age_seconds || 0))) +
            " s. L’assistant est arrêté ; les mesures et la priorité continuent sans lui."
          : (b.cached ? " Préparée il y a " + esc(String(Math.round(b.age_seconds || 0))) + " s, avant la demande." : "")) +
        "</div>";
    }

    // What the guard took out. An operator who never sees the assistant
    // misbehave has no way to calibrate how far to trust it, so suppression is
    // reported rather than silent.
    if (b.blocked && b.blocked.length) {
      html += '<div class="ai-blocked"><b>Contenu bloqué par MedBox</b><ul>' +
        b.blocked.map(function (x) { return "<li>" + esc(blockedLabel(x)) + "</li>"; }).join("") +
        "</ul></div>";
    }

    if (b.summary) html += '<p class="sum">' + esc(b.summary) + "</p>";

    if (b.insufficient_data && !(b.hypotheses || []).length) {
      // "All in range" is the station talking, so it is said only when NEWS2
      // agrees. The server now refuses the flag under any other band; this is
      // the second lock, for a response from before that rule existed.
      html += '<div class="nothing">' +
        (b.urgency_at_assessment === "routine" ? "Les paramètres mesurés sont dans leur plage habituelle. " : "") +
        "L’assistant n’a aucune hypothèse étayée à proposer et le dit au lieu d’en inventer une. " +
        "Ce que la personne a déclaré n’est pas mesuré par MedBox.</div>";
    }

    if (b.hypotheses && b.hypotheses.length) {
      html += "<h3>Hypothèses</h3>";
      html += b.hypotheses.map(function (h) {
        // A bolded condition name over signs that are all things somebody said
        // reads as a diagnosis however the fields are named. The station says
        // so on the hypothesis itself rather than hoping the reader notices
        // that every bullet under it is amber.
        var bare = h.no_measured_support
          ? '<span class="unbacked">Aucune mesure de MedBox ne l’étaye. ' +
            'Cette hypothèse repose uniquement sur les déclarations.</span>'
          : "";
        return '<div class="hyp' + (h.no_measured_support ? " unbacked-hyp" : "") +
          '"' + (o.flyable ? ' data-fly="1"' : "") + "><b>" + esc(h.name) + "</b>" +
          '<span class="conf">' + esc(FIT_LABEL[h.fit] || h.fit || "") + "</span>" + bare + "<ul>" +
          (h.supporting_signs || []).map(sign).join("") + "</ul>" +
          (o.flyable ? '<span class="fly">cliquer pour localiser la source →</span>' : "") +
          "</div>";
      }).join("");
    }

    if (b.questions_for_patient && b.questions_for_patient.length) {
      // Each question can be answered where it is asked. The reply is sent for
      // the crew member this assessment is ABOUT, carried on the element,
      // never for whoever happens to be selected when the button is pressed.
      html += '<h3>Questions à poser</h3><ul class="asks">' +
        b.questions_for_patient.map(function (q) {
          return '<li class="ask" data-pid="' + esc(b.patient_id) + '" data-q="' + esc(q) + '">' +
            '<span class="q">' + esc(q) + "</span>" +
            '<span class="ans-row">' +
            '<button type="button" class="ans" data-a="yes">Oui</button>' +
            '<button type="button" class="ans" data-a="no">Non</button>' +
            '<button type="button" class="ans" data-a="unsure">Incertain</button>' +
            '<input class="ans-text" maxlength="200" placeholder="Ou saisir ses mots, puis Entrée"' +
            ' aria-label="Réponse de la personne, dans ses propres mots">' +
            "</span></li>";
        }).join("") + "</ul>";
    }

    if (b.information_to_gather && b.information_to_gather.length) {
      // Deliberately NOT "Suggested protocol". That heading read as an order
      // set, over an unbounded list the model filled however it liked.
      html += "<h3>Informations à recueillir</h3><ul>" +
        b.information_to_gather.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") +
        "</ul>";
    }

    return html;
  }

  /* Is what is on screen still true?
   *
   * `held` is the assessment as returned; `liveTotal` is the NEWS2 aggregate
   * showing right now. Returns null while it still holds, or the sentence to
   * put over it when it does not. */
  /* What the voice reads out of an assessment: the rebuilt summary, the
     hypothesis names and the one question. Nothing the validator removed. */
  function spoken(b) {
    if (!b || !b.ok) return "";
    // Written for the ear on the server (server/spoken.py): no numbers, the
    // pattern in plain words, "not a diagnosis", the question. This fallback
    // only exists for an older server that sent no `spoken`.
    if (b.spoken) return String(b.spoken);
    var parts = [];
    if (b.hypotheses && b.hypotheses.length) {
      parts.push("Profil observé : " + b.hypotheses.map(function (h) { return String(h.name).toLowerCase(); }).join(", ") + ".");
    }
    if (b.questions_for_patient && b.questions_for_patient.length) {
      parts.push("Question à poser : " + b.questions_for_patient[0]);
    }
    return parts.join(" ");
  }

  function staleness(held, liveTotal, nowMs) {
    if (!held) return null;
    var age = nowMs - (held.at || 0) * 1000;
    if (liveTotal != null && held.news2_at_assessment != null &&
        liveTotal !== held.news2_at_assessment) {
      return "Les mesures ont changé depuis cette évaluation. Le score NEWS2 était de " +
        held.news2_at_assessment + " ; il est maintenant de " + liveTotal +
        ". Relancez l’évaluation.";
    }
    if (age > MAX_AGE_MS) {
      return "Cette évaluation date de " + Math.round(age / 1000) +
        " secondes. Relancez-la avec les mesures actuelles.";
    }
    return null;
  }

  function failure(note) {
    return '<div class="fail"><b>Assistant indisponible</b> ' +
      esc(failureLabel(note)) + "</div>";
  }

  /* Answering the assistant's questions, for both views.
   *
   * Delegated on the container the assessment is drawn into, once, so it
   * survives every re-render. A reply is a person talking: the server files it
   * with what they reported, the next assessment reads it inside the untrusted
   * span, and NEWS2 never sees it. The assessment on screen was written before
   * the answer, so the row says to ask again rather than implying it already
   * took the answer into account.
   *
   * `onRecorded(patientId, reported)` lets the view redraw "In their own
   * words" at once. */
  function wireAnswers(container, onRecorded) {
    function send(li, reply) {
      reply = String(reply || "").trim();
      if (!li || !reply || li.classList.contains("answered") || li.classList.contains("sending")) return;
      var pid = li.getAttribute("data-pid");
      li.classList.add("sending");
      fetch("/api/patient/" + encodeURIComponent(pid) + "/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: li.getAttribute("data-q"), answer: reply })
      })
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(function (d) {
          li.classList.remove("sending");
          li.classList.add("answered");
          li.querySelector(".ans-row").innerHTML = '<span class="done">Réponse enregistrée : « ' +
            esc(reply) + " ». Relancez l’assistant pour qu’il la prenne en compte.</span>";
          if (onRecorded) onRecorded(pid, d.reported || []);
        })
        .catch(function () {
          li.classList.remove("sending");
          var row = li.querySelector(".ans-row");
          if (row && !row.querySelector(".err")) {
            row.insertAdjacentHTML("beforeend", '<span class="err">Non enregistré. Réessayez.</span>');
          }
        });
    }
    container.addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest(".ans") : null;
      if (b) send(b.closest(".ask"), b.getAttribute("data-a"));
    });
    container.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || !e.target.classList || !e.target.classList.contains("ans-text")) return;
      e.preventDefault();
      send(e.target.closest(".ask"), e.target.value);
    });
  }

  root.MedBox = root.MedBox || {};
  root.MedBox.assessment = {
    render: render,
    spoken: spoken,
    staleness: staleness,
    failure: failure,
    wireAnswers: wireAnswers,
    MAX_AGE_MS: MAX_AGE_MS
  };
})(window);
