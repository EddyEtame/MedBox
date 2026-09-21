"""The JSON shape Ollama is forced to return.

Constraining the model with a schema is what stops it writing prose where we
need structure, and it is why the interface can never be surprised by the AI.
Note what is absent: there is no `diagnosis` field anywhere. The model offers
hypotheses and an urgency it must justify, and the wording of the prompt plus
the shape of this schema are what keep it on the right side of that line.
"""

ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "One sentence describing what the instruments recorded.",
        },
        "hypotheses": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "moderate", "high"]},
                    "supporting_signs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "confidence", "supporting_signs"],
            },
        },
        "questions_for_patient": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string"},
        },
        "suggested_protocol": {"type": "array", "items": {"type": "string"}},
        "escalate": {"type": "boolean"},
    },
    "required": ["summary", "hypotheses", "questions_for_patient", "suggested_protocol", "escalate"],
}

SYSTEM_PROMPT = """You are the assistant aboard the ESA Horizon, a deep-space vessel \
with no contact with Earth and no doctor on board.

You observe a MedBox session and support the crew member operating it.

Rules you never break:
- You do not diagnose. You offer hypotheses, ranked, each with the signs supporting it.
- Every claim names the measurement it came from. Never assert anything the instruments did not record.
- The urgency level shown to the crew is computed from NEWS2, not by you. Do not contradict it.
- If the readings are insufficient, say so and ask for what is missing.
- Be brief. The person reading you may be treating someone.
"""
