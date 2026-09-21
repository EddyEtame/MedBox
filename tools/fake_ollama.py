"""A stand-in for Ollama that speaks its HTTP API without a model.

This exists for three reasons, and none of them is "pretend we have an AI":

1. The AI integration can be tested in CI, on a laptop, or on a machine that
   has never pulled a model. Without this, every test of the slow track needs
   four gigabytes of weights.
2. The second developer can work on the interface without installing Ollama.
3. If the model will not load ten minutes before the defence, the demo still
   has a path that exercises the real client, the real schema and the real
   rendering, and we say out loud on stage that it is a stand-in.

It is deliberately honest: every response it produces carries
`"stand_in": true`, and the interface is expected to say so. It does not
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

MODEL_NAMES = ["qwen2.5:3b-instruct", "llama3.2:3b", "gemma2:2b"]

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

    signs: list[str] = []
    if v.get("temperature") is not None:
        t = v["temperature"]
        if t >= 38.0:
            signs.append(f"temperature {t:.1f} C, above the 38.0 fever threshold")
        elif t <= 36.0:
            signs.append(f"temperature {t:.1f} C, below normal")
    if v.get("spo2") is not None and v["spo2"] < 95:
        signs.append(f"SpO2 {v['spo2']:.0f}%, below the 95% floor")
    if v.get("pulse") is not None and v["pulse"] > 100:
        signs.append(f"pulse {v['pulse']:.0f}/min, above 100")
    if v.get("respiration") is not None and v["respiration"] > 20:
        signs.append(f"respiration {v['respiration']:.0f}/min, above 20")

    hypotheses = []
    fever = (v.get("temperature") or 0) >= 38.0
    hypoxic = (v.get("spo2") or 100) < 95
    tachypneic = (v.get("respiration") or 0) > 20

    if fever and (hypoxic or tachypneic):
        hypotheses.append({
            "name": "Respiratory infection",
            "confidence": "moderate",
            "supporting_signs": signs[:4] or ["fever with respiratory involvement"],
        })
    elif fever:
        hypotheses.append({
            "name": "Febrile illness, source not yet localised",
            "confidence": "low",
            "supporting_signs": signs[:3] or ["raised temperature"],
        })
    if hypoxic:
        hypotheses.append({
            "name": "Impaired gas exchange",
            "confidence": "low",
            "supporting_signs": [s for s in signs if "SpO2" in s] or ["reduced oxygen saturation"],
        })
    if not hypotheses:
        hypotheses.append({
            "name": "No pattern in the measured parameters",
            "confidence": "low",
            "supporting_signs": ["all four measured parameters within normal ranges"],
        })

    questions = []
    if fever:
        questions.append("When did you first feel feverish?")
    if tachypneic or hypoxic:
        questions.append("Are you short of breath at rest, or only on exertion?")
    questions.append("Has anyone you share a deck with had the same symptoms?")

    protocol = []
    if urgency in ("medium", "high"):
        protocol.append("Repeat the full set of observations now, then every 15 minutes.")
    if fever and (hypoxic or tachypneic):
        protocol.append("Apply respiratory isolation precautions until a cause is established.")
    protocol.append("Record fluid intake and temperature every hour.")

    summary = (
        f"The instruments recorded "
        + (", ".join(signs) if signs else "no parameter outside its normal range")
        + f" for {name}. NEWS2 aggregate {total}, band '{urgency}'."
    )

    return {
        "summary": summary,
        "hypotheses": hypotheses[:4],
        "questions_for_patient": questions[:4],
        "suggested_protocol": protocol,
        "escalate": urgency in ("medium", "high"),
        "stand_in": True,
    }


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
        content = json.dumps(_assessment(prompt))
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
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Stand-in Ollama on http://{args.host}:{args.port}")
    print("This is NOT a language model. It reads the vitals out of the prompt")
    print("and states them back. Use it to test the path, never to claim a result.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
