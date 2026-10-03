"""Config + secrets loading.

Settings live in config.toml (defaults in default_config.toml); secrets come
from environment variables or a .env file next to config.toml.
"""
from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "default_config.toml"

SECRET_KEYS = ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "ANTHROPIC_API_KEY")


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=value lines; real env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    data: dict[str, Any]
    root: Path

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.data[section]

    @property
    def output_dir(self) -> Path:
        return self._resolve(self.data["paths"]["output_dir"])

    @property
    def data_dir(self) -> Path:
        return self._resolve(self.data["paths"]["data_dir"])

    def _resolve(self, p: str) -> Path:
        path = Path(os.path.expandvars(os.path.expanduser(p)))
        return path if path.is_absolute() else (self.root / path)

    @staticmethod
    def secret(name: str) -> str | None:
        value = os.environ.get(name, "").strip()
        return value or None


def load_config(path: str | Path | None = None) -> Config:
    defaults = tomllib.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    cfg_path = Path(path) if path else Path.cwd() / "config.toml"
    root = cfg_path.resolve().parent
    load_dotenv(root / ".env")
    data = defaults
    if cfg_path.exists():
        user = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        data = _deep_merge(defaults, user)
    return Config(data=data, root=root)
