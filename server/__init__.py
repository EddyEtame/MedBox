"""MedBox — autonomous medical station for the ESA Horizon.

Two tracks run side by side and never block each other:

  Fast track   sensors -> thresholds -> NEWS2 score -> screen.  Deterministic,
               no model anywhere in it, and it is what puts a number on screen.
  Slow track   patient state -> Ollama -> hypotheses and a suggested protocol.
               Best effort. If it dies, the fast track does not notice.

That separation is the whole design. Nothing in `server.triage`,
`server.sensors` or `server.db` may import from `server.ai`.
"""

__version__ = "0.1.0"
