"""A stand-in for Ollama that speaks its HTTP API without a model.

This exists for three reasons, and none of them is "pretend we have an AI":

1. The AI integration can be tested in CI, on a laptop, or on a machine that
   has never pulled a model. Without this, every test of the slow track needs
   four gigabytes of weights.
2. The second developer can work on the interface without installing Ollama.
3. If the model will not load ten minutes before the defence, the demo still
   has a path that exercises the real client, the real schema and the real
   rendering, and we say out loud on stage that it is a stand-in.

It is deliberately honest, and it says so in the one place that cannot be
forged: `/api/version` answers "stand-in", which the client probes before it
ever asks for an assessment. The flag the interface renders comes from that
probe, NOT from these responses — an honesty label emitted by the thing being
labelled is worth nothing. It does not
pretend to reason. It reads the vitals out of the prompt and states what the
instruments recorded, which is the one thing a language model is NOT needed
for and therefore the one thing a stand-in can do without lying.

Run it:
    python tools/fake_ollama.py --port 11434

Then start MedBox normally. The client cannot tell the difference, which is
the point: it proves the client is correct, not that the model is good.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# What this stand-in claims to have pulled. OllamaClient.probe() accepts a tag
# whose family matches the configured model, so these have to stay in the same
# family as config.toml or the break-glass demo path silently stops working.
MODEL_NAMES = ["qwen2.5:1.5b-instruct", "qwen2.5:0.5b-instruct", "qwen2.5:3b-instruct"]

# --rogue makes this stand-in behave like a small model that has gone wrong:
# it prescribes, it diagnoses, it invents a condition for a healthy person, it
# contradicts the NEWS2 band, and it cites a symptom nobody measured as though
# an instrument had recorded it.
#
# It exists so that "the station blocks this" is something you can watch rather
# than something we assert. Every one of these behaviours is drawn from the
# safety audit of this schema, and server/ai/validate.py has to catch all of
# them with nothing reaching the panel unlabelled. Run:
#
#     python tools/fake_ollama.py --rogue
#
# then assess anybody, and read what the panel says was suppressed.
ROGUE = False


def _rogue(prompt: str) -> dict:
    """What a 3B model writes when the schema does not stop it."""
    return {
        "summary": "A low NEWS2 aggregate, overall reassuring and stable.",
        "insufficient_data": False,
        "hypotheses": [{
            "name": "Bacterial pneumonia",
            "fit": "all measured parameters fit",
            "supporting_signs": [
                {"source": "reported_by_crew_member",
                 "text": "crushing chest pain radiating to the left arm"},
                {"source": "clinical_judgement", "text": "the patient looks unwell"},
            ],
        }],
        "questions_for_patient": ["Any past history of chest infection?"],
        "information_to_gather": [
            "Administer paracetamol 1g orally, repeat at 6 hours",
            "Start supplemental oxygen at 2 L/min via nasal cannula",
        ],
        # Neither of these is in the schema. They used to travel straight
        # through json.loads into the API response.
        "diagnosis": "bacterial pneumonia",
        "escalate": True,
    }

# The prompt the real client sends is plain text with aligned columns. Pull the
# numbers back out of it so the reply is grounded in the same readings the
# board is showing, rather than invented.
NUMBER_PATTERNS = {
    "temperature": re.compile(r"temperature\s+([\d.]+)"),
    "spo2": re.compile(r"SpO2\s+([\d.]+)"),
    "pulse": re.compile(r"pulse\s+([\d.]+)"),
    "respiration": re.compile(r"respiration\s+([\d.]+)"),
}
NEWS2_PATTERN = re.compile(r"NEWS2 aggregate (\d+) -> urgency '(\w+)'")
NAME_PATTERN = re.compile(r"Crew member ([^(]+)\(([^)]*)\)")


def _read_vitals(prompt: str) -> dict:
    out: dict[str, float] = {}
    for key, pattern in NUMBER_PATTERNS.items():
        m = pattern.search(prompt)
        if m:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                pass
    return out


def _assessment(prompt: str) -> dict:
    """Build a schema-valid assessment from the readings in the prompt.

    Every sentence here names the measurement it came from, because that is
    the rule the real assistant is held to and the stand-in must not model
    worse behaviour than the thing it stands in for.
    """
    v = _read_vitals(prompt)
    news = NEWS2_PATTERN.search(prompt)
    total = int(news.group(1)) if news else 0
    urgency = news.group(2) if news else "routine"
    who = NAME_PATTERN.search(prompt)
    name = who.group(1).strip() if who else "this crew member"

    # Every sign carries the instrument that recorded it. The stand-in is held
    # to the same provenance rule as the assistant, because a stand-in that
    # models worse behaviour than the thing it stands in for teaches the team
    # the wrong lesson every time they run it.
    signs: list[dict] = []
    if v.get("temperature") is not None:
        t = v["temperature"]
        if t >= 38.0:
            signs.append({"source": "temperature",
                          "text": f"{t:.1f} C, above the 38.0 fever threshold"})
        elif t <= 36.0:
            signs.append({"source": "temperature", "text": f"{t:.1f} C, below normal"})
    if v.get("spo2") is not None and v["spo2"] < 95:
        signs.append({"source": "spo2", "text": f"{v['spo2']:.0f}%, below the 95% floor"})
    if v.get("pulse") is not None and v["pulse"] > 100:
        signs.append({"source": "pulse", "text": f"{v['pulse']:.0f}/min, above 100"})
    if v.get("respiration") is not None and v["respiration"] > 20:
        signs.append({"source": "respiration", "text": f"{v['respiration']:.0f}/min, above 20"})

    def fit(n: int) -> str:
        return ("one measurement fits" if n <= 1
                else "several measurements fit" if n < 4
                else "all measured parameters fit")

    hypotheses = []
    fever = (v.get("temperature") or 0) >= 38.0
    hypoxic = (v.get("spo2") or 100) < 95
    tachypneic = (v.get("respiration") or 0) > 20

    if fever and (hypoxic or tachypneic):
        picked = signs[:4]
        hypotheses.append({
            "name": "Fever with respiratory involvement",
            "fit": fit(len(picked)),
            "supporting_signs": picked,
        })
    elif fever:
        picked = [s for s in signs if s["source"] == "temperature"]
        hypotheses.append({
            "name": "Raised temperature, source not localised by these instruments",
            "fit": fit(len(picked)),
            "supporting_signs": picked,
        })
    if hypoxic:
        picked = [s for s in signs if s["source"] == "spo2"]
        hypotheses.append({
            "name": "Reduced oxygen saturation",
            "fit": fit(len(picked)),
            "supporting_signs": picked,
        })

    # The honest empty answer, which the old schema could not represent. A crew
    # member whose four measured parameters are all in range gets no invented
    # pattern: they get told that this box measured four things and all four
    # were normal.
    insufficient = not hypotheses

    questions = []
    if fever:
        questions.append("When did you first feel feverish?")
    if tachypneic or hypoxic:
        questions.append("Are you short of breath at rest, or only on exertion?")
    if insufficient:
        questions.append("What are you feeling that these four instruments would not show?")
    questions.append("Has anyone you share a deck with had the same symptoms?")

    # Observations and measurements only. Never a drug, never a dose, never a
    # route — server/ai/validate.py would drop the whole array if it were, and
    # the stand-in must not be the thing that trips its own guard.
    gather = []
    if urgency in ("medium", "high"):
        gather.append("Repeat the full set of observations now, then every 15 minutes.")
    if fever and (hypoxic or tachypneic):
        gather.append("Check whether respiratory isolation precautions are already in place.")
    gather.append("Record temperature hourly.")

    summary = (
        "The instruments recorded "
        + ("; ".join(f"{s['source']} {s['text']}" for s in signs)
           if signs else "no parameter outside its normal range")
        + f" for {name}. NEWS2 aggregate {total}."
    )

    return {
        "summary": summary,
        "insufficient_data": insufficient,
        "hypotheses": hypotheses[:3],
        "questions_for_patient": questions[:4],
        "information_to_gather": gather[:3],
    }


def _plain(prompt: str) -> str:
    """The honest answer to any free-text prompt: there is nobody here.

    The one place MedBox asks for free text is the assistant introducing
    itself, and that screen already carries the station's own guide. So the
    stand-in points at it instead of pretending to be a voice.
    """
    return (
        "There is no language model running. This is the stand-in, which reads "
        "instrument values back and applies fixed rules, so it has nothing of "
        "its own to say about the station. Everything listed on this screen is "
        "the station's own description of what it does, and all of it is true "
        "whether or not a model is running. Start Ollama and ask again to hear "
        "it in the assistant's words."
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeOllama/1.0"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        if self.path.startswith("/api/tags"):
            self._send(200, {"models": [{"name": n} for n in MODEL_NAMES]})
        elif self.path in ("/", "/api/version"):
            self._send(200, {"version": "stand-in"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._send(400, {"error": "bad json"})
            return

        if not self.path.startswith("/api/chat"):
            self._send(404, {"error": "not found"})
            return

        prompt = "\n".join(
            m.get("content", "") for m in body.get("messages", []) if m.get("role") == "user"
        )
        if body.get("format"):
            content = json.dumps(_rogue(prompt) if ROGUE else _assessment(prompt))
        else:
            # A free-text request. A stand-in has no words of its own, so it
            # says exactly that rather than improvising something that would
            # read like the assistant talking.
            content = _plain(prompt)
        self._send(200, {
            "model": body.get("model", MODEL_NAMES[0]),
            "done": True,
            "message": {"role": "assistant", "content": content},
        })

    def log_message(self, fmt: str, *a) -> None:
        # Quiet by default; the station's own log is the one that matters.
        pass


def serve(port: int = 11434, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=11434)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--rogue", action="store_true",
                    help="misbehave on purpose, to show the station blocking it")
    args = ap.parse_args()
    global ROGUE
    ROGUE = args.rogue
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Stand-in Ollama on http://{args.host}:{args.port}")
    if ROGUE:
        print("ROGUE MODE: prescribing, diagnosing and contradicting NEWS2 on purpose.")
        print("Everything it sends should be caught by server/ai/validate.py.")
    print("This is NOT a language model. It reads the vitals out of the prompt")
    print("and states them back. Use it to test the path, never to claim a result.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
