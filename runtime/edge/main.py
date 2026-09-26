"""The platform edge - the only thing on this platform that may assert who someone is.

Seventy lines, and the most important seventy in the repository. Everything else trusts
what happens here, which is why it does exactly four things and nothing else:

    1. work out who the caller is (stub SSO)
    2. STRIP every identity header the client sent
    3. re-inject headers it has validated itself, plus a token proving it is the edge
    4. proxy to the tenant app

Step 2 is the one people skip. Without it, `curl -H "X-Auth-Groups: comp-analyst"` is a
complete authorization bypass - and the app on the other side has no way to know.

Run:  uvicorn runtime.edge.main:app --port 8080
Log in locally:  http://localhost:8080/a/headcount-dashboard/?as=krishna@corp.example
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

HERE = Path(__file__).parent
REGISTRY = HERE.parent.parent / "control" / "registry"

USERS = yaml.safe_load((HERE / "users.yaml").read_text())["users"]
EDGE_TOKEN = os.environ.get("INSIGHTS_EDGE_TOKEN", "local-edge-token")
SESSION_COOKIE = "insights_session"

#: Headers the edge owns. Every one of these is removed from the inbound request before
#: anything is added back. Kept as one list so "strip" and "inject" cannot drift apart.
EDGE_OWNED = ("x-auth-user", "x-auth-groups", "x-auth-request-id", "x-auth-edge-token")

#: Hop-by-hop headers a proxy must not forward.
HOP_BY_HOP = ("host", "content-length", "connection", "transfer-encoding")

app = FastAPI(title="insights-edge")


def _registered() -> dict:
    """apps.local.json (written by `insights up`) shadows apps.json (written by CI)."""
    for name in ("apps.local.json", "apps.json"):
        path = REGISTRY / name
        if path.is_file():
            body = json.loads(path.read_text())
            return {k: v for k, v in body.items() if not k.startswith("_")}
    return {}


@app.get("/")
def index() -> dict:
    return {
        "edge": "insights-hub",
        "apps": sorted(_registered()),
        "how_to_sign_in": "append ?as=krishna@corp.example to any app URL",
        "users": sorted(USERS),
    }


@app.api_route("/a/{app_name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(app_name: str, path: str, request: Request):
    registry = _registered()
    entry = registry.get(app_name)
    if not entry:
        return JSONResponse({"error": f"no app '{app_name}' is registered"}, status_code=404)
    if entry.get("kind") == "job":
        return JSONResponse(
            {"error": f"'{app_name}' is a scheduled job, not a web app. Try `insights status`."},
            status_code=400,
        )

    # --- 1. who is this? (stub SSO: ?as=... sets a session cookie) -----------------
    impersonate = request.query_params.get("as")
    if impersonate:
        if impersonate not in USERS:
            return JSONResponse({"error": f"no such user '{impersonate}'"}, status_code=401)
        target = str(request.url.remove_query_params("as"))
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(SESSION_COOKIE, impersonate, httponly=True, samesite="lax")
        return response

    subject = request.cookies.get(SESSION_COOKIE)
    if subject not in USERS:
        return JSONResponse(
            {"error": "not signed in", "hint": "add ?as=krishna@corp.example to this URL"},
            status_code=401,
        )

    # --- LAYER 1 authorization: may this person reach this app at all? ------------
    #
    # The cheapest possible rejection, and the reason it belongs here rather than in
    # the app: someone with no business in an app cannot probe its routes, and the
    # app never runs a line of code for them. `groups` is reconciled from the app's
    # manifest at deploy time - the edge does not read tenant manifests.
    #
    # Layer 2 (require_role) and layer 3 (dataset entitlement) still apply inside.
    allowed = set(entry.get("groups") or ())
    caller_groups = set(USERS[subject]["groups"])
    if allowed and not (allowed & caller_groups):
        return JSONResponse(
            {
                "error": f"{subject} is not a member of any group that may use '{app_name}'",
                "hint": "ask an owner to add your group to access.manage in app.yaml",
            },
            status_code=403,
        )

    # --- 2. strip, then 3. inject --------------------------------------------------
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in EDGE_OWNED and key.lower() not in HOP_BY_HOP
    }
    request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:10]}"
    headers.update(
        {
            "X-Auth-User": subject,
            "X-Auth-Groups": ",".join(USERS[subject]["groups"]),
            "X-Auth-Request-Id": request_id,
            "X-Auth-Edge-Token": EDGE_TOKEN,
        }
    )

    # --- 4. proxy ------------------------------------------------------------------
    upstream = f"http://127.0.0.1:{entry['port']}/{path}"
    # verify=False because this hop is plain HTTP to loopback - there is no TLS in
    # the path to verify. It also avoids building an SSL context (and loading a CA
    # bundle) on every request for a connection that will never use one.
    #
    # In production TLS terminates at the load balancer in front of this, and the
    # hop from the gateway to an app stays inside the VPC. If that ever becomes a
    # real network hop, this becomes a verified mTLS client - not a verify=True.
    # trust_env=False: the edge only ever talks to apps on loopback, and a corporate
    # HTTP_PROXY would have it hand that traffic to a proxy which correctly refuses to
    # route 127.0.0.1. Every app route then fails while the edge itself looks fine.
    async with httpx.AsyncClient(timeout=20, verify=False, trust_env=False) as client:
        upstream_response = await client.request(
            request.method, upstream, headers=headers,
            params=request.query_params, content=await request.body(),
        )

    # Pass the response through unchanged. An earlier version re-encoded everything
    # as JSON, which quietly broke any app serving HTML, CSS or an image - i.e. the
    # whole `spa` shape. A front door should move bytes, not interpret them.
    passthrough = {
        k: v for k, v in upstream_response.headers.items() if k.lower() not in HOP_BY_HOP
    }
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=passthrough,
        media_type=upstream_response.headers.get("content-type"),
    )
