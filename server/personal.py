"""One server per crew member, on its own port.

Eddy, 24 Sep: "we'll have one server for the main dashboard and then other
servers for the individual people, six of them". Each personal server is the
same ASGI application wrapped so that its root opens that member's page,
and so that it does not run the station's lifespan a second time (one
prefetch loop, one station). Everything else, the API and the static files,
is served as on the main port, so a tablet on its own port has the whole
station behind its owner's page.
"""
from __future__ import annotations


def personal_app(patient_id: str):
    from .app import app as station_app

    target = f"/me/{patient_id}".encode("ascii")

    async def wrapper(scope, receive, send):
        if scope["type"] == "lifespan":
            # The station's lifespan belongs to the main port. Answer the
            # protocol so uvicorn is satisfied, start nothing.
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope["type"] == "http" and scope.get("path") in ("", "/"):
            await send({
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", target), (b"cache-control", b"no-store")],
            })
            await send({"type": "http.response.body", "body": b""})
            return
        await station_app(scope, receive, send)

    wrapper.patient_id = patient_id  # type: ignore[attr-defined]
    return wrapper
