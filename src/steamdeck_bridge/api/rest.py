"""aiohttp REST + WebSocket API with bearer-token auth.

Endpoints (all under /api, token required except /api/health):
  GET  /api/health                       liveness (no auth)
  GET  /api/state                        current game + device state
  GET  /api/library                      installed Steam apps + shortcuts
  GET  /api/artwork/{appid}/{kind}       image; kind is one of
                                         capsule|cover|header|hero|logo|icon|background
  POST /api/actions/{action}             launch_game, switch_game, close_game,
                                         restart_steam, restart_gamescope, suspend,
                                         shutdown, reboot, refresh_library, refresh_metadata
  WS   /ws                               JSON state stream (initial snapshot + diffs)
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import TYPE_CHECKING

from aiohttp import WSMsgType, web

if TYPE_CHECKING:
    from ..daemon import Bridge

log = logging.getLogger(__name__)

MUTATING_ACTIONS = {
    "launch_game", "switch_game", "close_game", "restart_steam",
    "restart_gamescope", "suspend", "shutdown", "reboot",
    "refresh_library", "refresh_metadata",
}


def _authorized(request: web.Request, token: str) -> bool:
    header = request.headers.get("Authorization", "")
    supplied = header.removeprefix("Bearer ").strip() if header else (
        request.query.get("token", "")
    )
    return bool(supplied) and hmac.compare_digest(supplied, token)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path == "/api/health":
        return await handler(request)
    bridge: Bridge = request.app["bridge"]
    if not _authorized(request, bridge.config.http.token):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "version": request.app["version"]})


async def handle_state(request: web.Request) -> web.Response:
    bridge: Bridge = request.app["bridge"]
    return web.json_response(bridge.state.to_dict())


async def handle_library(request: web.Request) -> web.Response:
    bridge: Bridge = request.app["bridge"]
    return web.json_response({
        "steam": [
            {"appid": a.appid, "name": a.name, "installdir": a.installdir}
            for a in bridge.library.apps.values()
        ],
        "shortcuts": [
            {
                "appid": s.appid, "name": s.app_name, "exe": s.exe,
                "emulator": s.emulator, "platform": s.platform,
                "rom_title": s.rom_title, "rungameid": s.rungameid,
            }
            for s in bridge.shortcuts.shortcuts.values()
        ],
    })


async def handle_artwork(request: web.Request) -> web.StreamResponse:
    bridge: Bridge = request.app["bridge"]
    try:
        appid = int(request.match_info["appid"])
    except ValueError:
        return web.json_response({"error": "bad appid"}, status=400)
    kind = request.match_info["kind"]
    title = request.query.get("title", "")
    if not title:
        app = bridge.library.get(appid)
        sc = bridge.shortcuts.get(appid)
        title = app.name if app else (sc.app_name if sc else "")
    path = await bridge.artwork.resolve(appid, kind, title)
    if not path:
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(path, headers={"Cache-Control": "max-age=86400"})


async def handle_action(request: web.Request) -> web.Response:
    bridge: Bridge = request.app["bridge"]
    action = request.match_info["action"]
    if action not in MUTATING_ACTIONS:
        return web.json_response({"error": f"unknown action {action}"}, status=404)
    try:
        body = await request.json() if request.can_read_body else {}
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    ok = await bridge.run_action(action, body or {})
    status = 200 if ok else 409
    return web.json_response({"action": action, "ok": ok}, status=status)


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    bridge: Bridge = request.app["bridge"]
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    bridge.ws_clients.add(ws)
    try:
        await ws.send_json({"type": "state", "data": bridge.state.to_dict()})
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == "ping":
                await ws.send_str("pong")
    finally:
        bridge.ws_clients.discard(ws)
    return ws


def build_app(bridge: Bridge, version: str) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["bridge"] = bridge
    app["version"] = version
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/state", handle_state)
    app.router.add_get("/api/library", handle_library)
    app.router.add_get("/api/artwork/{appid}/{kind}", handle_artwork)
    app.router.add_post("/api/actions/{action}", handle_action)
    app.router.add_get("/ws", handle_ws)
    return app
