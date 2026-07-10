"""TOML config with environment-variable overrides and token bootstrap."""

from __future__ import annotations

import contextlib
import os
import secrets
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.config/steamdeck-bridge/config.toml").expanduser()


@dataclass(slots=True)
class DeviceConfig:
    id: str = "steamdeck"
    name: str = "Steam Deck"


@dataclass(slots=True)
class DetectionConfig:
    interval: float = 2.0
    rom_roots: list[str] = field(
        default_factory=lambda: ["~/Emulation/roms", "/run/media/mmcblk0p1/Emulation/roms"]
    )


@dataclass(slots=True)
class HttpConfig:
    host: str = "127.0.0.1"
    port: int = 8480
    token: str = ""


@dataclass(slots=True)
class MqttConfig:
    enabled: bool = True
    host: str = "homeassistant.local"
    port: int = 1883
    username: str = ""
    password: str = ""
    base_topic: str = "steamdeck_bridge"
    discovery_prefix: str = "homeassistant"


@dataclass(slots=True)
class ArtworkConfig:
    cache_dir: str = "~/.cache/steamdeck-bridge/artwork"
    steamgriddb_api_key: str = ""
    allow_remote: bool = True


@dataclass(slots=True)
class ActionsConfig:
    enabled: bool = True
    allow_power: bool = True
    allow_launch: bool = True
    allow_steam_restart: bool = True


@dataclass(slots=True)
class Config:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    artwork: ArtworkConfig = field(default_factory=ArtworkConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    path: Path = DEFAULT_CONFIG_PATH


_SECTIONS = {
    "device": DeviceConfig,
    "detection": DetectionConfig,
    "http": HttpConfig,
    "mqtt": MqttConfig,
    "artwork": ArtworkConfig,
    "actions": ActionsConfig,
}


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, apply SDB_<SECTION>_<KEY> env overrides,
    and generate a persistent HTTP token on first run."""
    path = path or DEFAULT_CONFIG_PATH
    cfg = Config(path=path)

    if path.is_file():
        # utf-8-sig tolerates BOMs from Windows editors/tools
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        for section, cls in _SECTIONS.items():
            values = data.get(section, {})
            target = getattr(cfg, section)
            for key, value in values.items():
                if hasattr(target, key):
                    setattr(target, key, value)
            _ = cls  # sections are dataclasses; unknown keys ignored above

    for section in _SECTIONS:
        target = getattr(cfg, section)
        for key in (f.name for f in fields(target)):
            env = os.environ.get(f"SDB_{section.upper()}_{key.upper()}")
            if env is None:
                continue
            current = getattr(target, key)
            if isinstance(current, bool):
                setattr(target, key, env.lower() in ("1", "true", "yes", "on"))
            elif isinstance(current, int):
                setattr(target, key, int(env))
            elif isinstance(current, float):
                setattr(target, key, float(env))
            elif isinstance(current, list):
                setattr(target, key, [p.strip() for p in env.split(",") if p.strip()])
            else:
                setattr(target, key, env)

    if not cfg.http.token:
        cfg.http.token = secrets.token_urlsafe(32)
        _persist_token(path, cfg.http.token)

    return cfg


def _persist_token(path: Path, token: str) -> None:
    """Write the generated token back so it survives restarts."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if '\ntoken = ""' in text:
                text = text.replace('\ntoken = ""', f'\ntoken = "{token}"', 1)
            else:
                text += f'\n[http]\ntoken = "{token}"\n'
        else:
            text = f'[http]\ntoken = "{token}"\n'
        path.write_text(text, encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except OSError:
        # Read-only config location: token stays process-lifetime only.
        pass
