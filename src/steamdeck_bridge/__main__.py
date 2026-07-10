"""Entry point: wire up the bridge, HTTP server, and MQTT loop."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from pathlib import Path

from aiohttp import web

from . import __version__
from .api.rest import build_app
from .config import DEFAULT_CONFIG_PATH, load_config
from .daemon import Bridge
from .mqtt import MqttBridge

log = logging.getLogger("steamdeck_bridge")


async def _amain(config_path: Path, verbose: bool) -> int:
    config = load_config(config_path)
    bridge = Bridge(config)

    runner = web.AppRunner(build_app(bridge, __version__))
    await runner.setup()
    site = web.TCPSite(runner, config.http.host, config.http.port)
    await site.start()
    log.info("REST/WS listening on http://%s:%s", config.http.host, config.http.port)

    tasks = [asyncio.create_task(bridge.run(), name="bridge")]
    if config.mqtt.enabled:
        bridge.mqtt = MqttBridge(config, bridge.run_action)
        tasks.append(asyncio.create_task(bridge.mqtt.run(), name="mqtt"))

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows dev shells
            loop.add_signal_handler(sig, stop.set)

    try:
        await stop.wait()
    finally:
        bridge.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="steamdeck-bridge",
        description="SteamOS/Bazzite now-playing + device bridge for Home Assistant",
    )
    parser.add_argument(
        "-c", "--config", type=Path, default=DEFAULT_CONFIG_PATH,
        help=f"config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        sys.exit(asyncio.run(_amain(args.config, args.verbose)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
