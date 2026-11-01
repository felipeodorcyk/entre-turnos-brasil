"""Apoio comum aos aceites reais por marco (M1–M4).

Caminhos substituíveis por variáveis de ambiente (outro snapshot, revisão de C):
BR2026_STAGING, BR2026_MANIFEST, BR2026_REFERENCE. Insumo ausente → SKIP com
prefixo BLOCKED; um SKIP nunca conta como aprovação de marco.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from br2026.config import election_dates, election_numbers, load_config
from br2026.contract import PROJECT_ROOT, validate_parquet
from br2026.panel.run import staging_path
from br2026.reporting.acceptance import check_reference, expected_keys, observed_totals

STAGING = Path(os.environ.get("BR2026_STAGING", PROJECT_ROOT / "data" / "staging"))
MANIFEST = Path(os.environ.get("BR2026_MANIFEST", PROJECT_ROOT / "data" / "raw" / "manifest.json"))
REFERENCE = Path(os.environ.get("BR2026_REFERENCE",
                                PROJECT_ROOT / "docs" / "sources" / "official_totals_reference.csv"))
# 26 estados + DF + exterior = 28 unidades.
ALL_UNITS = {"AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB",
             "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"}
MIN_PILOT_UFS, MIN_SIZE_RATIO = 3, 3.0


def blocked(msg: str):
    pytest.skip(f"BLOCKED: {msg}")


@lru_cache(maxsize=None)
def table(name: str) -> pd.DataFrame | None:
    path = staging_path(STAGING, name)
    return validate_parquet(path, name) if path.exists() else None


def require(*names: str) -> list[pd.DataFrame]:
    missing = [n for n in names if table(n) is None]
    if missing:
        blocked(f"staging real ausente {missing} em {STAGING}")
    return [table(n) for n in names]


def manifest_text() -> str:
    if not MANIFEST.exists():
        pytest.fail(f"{MANIFEST} ausente: staging sem proveniência verificável")
    return MANIFEST.read_text(encoding="utf-8")


def manifest_hashes() -> set:
    return set(re.findall(r"\b[0-9a-f]{64}\b", manifest_text()))


def manifest_urls() -> set:
    return set(re.findall(r"https?://[^\s\"']+", manifest_text()))


def reference_problems(turnos) -> list[str]:
    st, vl = require("section_turn", "votes_long")
    if not REFERENCE.exists():
        blocked(f"referência oficial independente ausente em {REFERENCE}")
    cfg = load_config()
    obs = observed_totals(st, vl, *election_numbers(cfg))
    obs = {k: v for k, v in obs.items() if k[0] in turnos}
    ref = pd.read_csv(REFERENCE, dtype={"sg_uf": str, "sha256_fonte": str})
    staging_hashes = set().union(*(set(table(n).source_id) for n in
                                   ("section_turn", "votes_long") if table(n) is not None))
    return check_reference(ref[ref.nr_turno.isin(turnos)], obs, expected_keys(obs, turnos),
                           election_dates(cfg), staging_hashes, manifest_urls())


def turns_by_uf() -> dict:
    st = require("section_turn")[0]
    return {uf: set(g.nr_turno.unique()) for uf, g in st[st.cd_cargo == 1].groupby("sg_uf")}


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
