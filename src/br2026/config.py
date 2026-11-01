"""Leitura de config/analysis.toml (parâmetros pré-registrados)."""
from __future__ import annotations

import tomllib
from pathlib import Path

from br2026.contract import PROJECT_ROOT


def load_config(path: Path | None = None) -> dict:
    with open(path or PROJECT_ROOT / "config" / "analysis.toml", "rb") as f:
        return tomllib.load(f)


def election_numbers(cfg: dict | None = None) -> tuple[int, int]:
    e = (cfg or load_config())["election"]
    return e["nr_votavel_lula"], e["nr_votavel_flavio"]


def election_dates(cfg: dict | None = None) -> dict[int, str]:
    e = (cfg or load_config())["election"]
    return {1: e["data_t1"], 2: e["data_t2"]}
