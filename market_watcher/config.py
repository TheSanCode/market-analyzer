"""Application configuration (TOML file + Python defaults)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .scoring import ScoringConfig

DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "JPM",
    "XOM",
    "UNH",
    "COST",
]


@dataclass
class IndicatorConfig:
    rvol_window: int = 20
    rsi_window: int = 14
    atr_window: int = 14
    cmf_window: int = 20
    obv_window: int = 20
    sma_fast: int = 50
    sma_slow: int = 200
    return_short: int = 20
    return_long: int = 63


@dataclass
class DataConfig:
    provider: str = "yfinance"  # "yfinance" or "demo"
    history_days: int = 450  # calendar days requested from the provider
    min_sessions: int = 60  # fewer sessions -> INSUFFICIENT DATA
    max_stale_days: int = 4  # calendar days since last bar before "stale"
    retries: int = 1  # extra attempts per ticker on provider errors
    demo_path: str = ""  # optional override for the simulated CSV


@dataclass
class OllamaConfig:
    enabled: bool = True
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:8b"
    timeout_seconds: float = 120.0
    temperature: float = 0.2
    explain_top_n: int = 5  # explain this many top-ranked tickers per scan


@dataclass
class AppConfig:
    universe: list[str] = field(default_factory=lambda: list(DEFAULT_UNIVERSE))
    benchmark: str = "SPY"
    database_path: str = "data/market_watcher.db"
    export_dir: str = "exports"
    data: DataConfig = field(default_factory=DataConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)


class ConfigError(ValueError):
    pass


def _apply(section: Any, values: dict[str, Any], name: str) -> None:
    known = {f.name: f for f in fields(section)}
    for key, value in values.items():
        if key not in known:
            raise ConfigError(f"unknown setting [{name}].{key}")
        current = getattr(section, key)
        if isinstance(current, bool) and not isinstance(value, bool):
            raise ConfigError(f"[{name}].{key} must be true/false")
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"[{name}].{key} must be a number")
            value = type(current)(value) if isinstance(current, float) else value
        setattr(section, key, value)


def _normalise_tickers(values: Any, name: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ConfigError(f"{name} must be a list of ticker strings")
    out: list[str] = []
    for v in values:
        t = v.strip().upper()
        if t and t not in out:
            out.append(t)
    return out


def config_from_dict(raw: dict[str, Any]) -> AppConfig:
    cfg = AppConfig()
    sections = {
        "data": cfg.data,
        "indicators": cfg.indicators,
        "scoring": cfg.scoring,
        "ollama": cfg.ollama,
    }
    for key, value in raw.items():
        if key == "universe":
            cfg.universe = _normalise_tickers(value, "universe")
        elif key == "benchmark":
            if not isinstance(value, str) or not value.strip():
                raise ConfigError("benchmark must be a ticker string")
            cfg.benchmark = value.strip().upper()
        elif key in ("database_path", "export_dir"):
            setattr(cfg, key, str(value))
        elif key in sections:
            if not isinstance(value, dict):
                raise ConfigError(f"[{key}] must be a table")
            _apply(sections[key], value, key)
        else:
            raise ConfigError(f"unknown top-level setting '{key}'")
    if cfg.data.provider not in ("yfinance", "demo"):
        raise ConfigError("data.provider must be 'yfinance' or 'demo'")
    if not cfg.universe:
        raise ConfigError("universe is empty")
    return cfg


def load_config(path: str | Path | None) -> AppConfig:
    """Load a TOML config. ``None`` returns defaults."""
    if path is None:
        return AppConfig()
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    with p.open("rb") as fh:
        raw = tomllib.load(fh)
    return config_from_dict(raw)
