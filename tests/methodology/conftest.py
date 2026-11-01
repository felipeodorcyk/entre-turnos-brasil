"""Carrega fixtures de contrato com os tipos do contrato v1 e isola a suíte rápida (O-R4)."""
import json
import socket
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from br2026.contract import PROJECT_ROOT

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "contract"
SRC = "0" * 63 + "a"
KEY_STR = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
# Saídas reais de B que a suíte rápida nunca pode criar nem alterar.
REAL_B_OUTPUTS = [PROJECT_ROOT / "data" / "analytics", PROJECT_ROOT / "reports" / "analysis" / "relatorio.md",
                  PROJECT_ROOT / "reports" / "analysis" / "relatorio_rastro.csv"]


def _snapshot():
    out = {}
    for p in REAL_B_OUTPUTS:
        files = [p] if p.is_file() else (sorted(p.rglob("*")) if p.exists() else [])
        out.update({str(f): f.stat().st_mtime_ns for f in files if f.is_file()})
    return out


@pytest.fixture(scope="session", autouse=True)
def _real_outputs_untouched():
    before = _snapshot()
    yield
    assert _snapshot() == before, "suíte rápida alterou saídas reais de B (data/analytics ou relatório)"


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Rede proibida fora dos testes marcados integration (que também não a usam)."""
    if request.node.get_closest_marker("integration"):
        return

    def deny(*_a, **_k):
        raise RuntimeError("rede proibida na suíte rápida (O-R4)")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def _read(name):
    return pd.read_csv(FIX / name, dtype=str, keep_default_na=False, na_values=[""])


def _as_contract(df, ints, bools=()):
    df = df.copy()
    for c in ints:
        df[c] = pd.to_numeric(df[c]).astype("int64")
    for c in bools:
        df[c] = df[c].map({"True": True, "False": False}).astype("boolean")
    return df


@pytest.fixture
def section_turn():
    st = _read("panel_section_turn.csv")
    counts = ["qt_aptos", "qt_comparecimento", "qt_abstencoes", "qt_votos_nominais",
              "qt_votos_legenda", "qt_votos_brancos", "qt_votos_nulos"]
    st = _as_contract(st, counts, ["st_secao_instalada", "st_secao_anulada"])
    st["nr_turno"] = st.nr_turno.astype("int8")
    st.insert(0, "ano", np.int16(2026))
    st["ano"] = st.ano.astype("int16")
    st.insert(1, "cd_eleicao", st.nr_turno.map({1: "6257", 2: "6258"}))
    st["cd_cargo"] = np.int16(1)
    st["cd_cargo"] = st.cd_cargo.astype("int16")
    st["qt_votos_anulados_apu_sep"] = np.int64(0)
    st["ds_origem_voto"] = "Urna Eletrônica"
    st["flag_identidade_aptos"] = (st.qt_aptos == st.qt_comparecimento + st.qt_abstencoes).astype("boolean")
    st["flag_identidade_comparecimento"] = (
        st.qt_comparecimento == st.qt_votos_nominais + st.qt_votos_legenda
        + st.qt_votos_brancos + st.qt_votos_nulos).astype("boolean")
    st["source_id"] = SRC
    return st


@pytest.fixture
def votes_long():
    v = _as_contract(_read("panel_votes.csv"), ["qt_votos"])
    v["nr_turno"] = v.nr_turno.astype("int8")
    v["nr_votavel"] = v.nr_votavel.astype("int32")
    v.insert(0, "ano", np.int16(2026))
    v["ano"] = v.ano.astype("int16")
    v.insert(1, "cd_eleicao", v.nr_turno.map({1: "6257", 2: "6258"}))
    v["cd_cargo"] = np.int16(1)
    v["cd_cargo"] = v.cd_cargo.astype("int16")
    v["tipo_votavel"] = v.nr_votavel.map({95: "BRANCO", 96: "NULO"}).fillna("NOMINAL")
    v["sq_candidato"] = np.where(v.tipo_votavel == "NOMINAL", "28000" + v.nr_votavel.astype(str), None)
    v["source_id"] = SRC
    return v


@pytest.fixture
def crosswalk():
    c = _read("panel_crosswalk.csv")
    c["nr_turno"] = c.nr_turno.astype("int8")
    c.insert(0, "ano", np.int16(2026))
    c["ano"] = c.ano.astype("int16")
    c["nr_local_votacao_original"] = c.nr_local_votacao
    c["fonte"] = "fixture"
    c["justificativa"] = None
    c["flag_ambigua"] = False
    c.insert(c.columns.get_loc("tipo_correspondencia") + 1, "status_correspondencia", "EFETIVADA")
    c["source_id"] = SRC
    return c


@pytest.fixture
def expected():
    return json.loads((FIX / "panel_expected.json").read_text(encoding="utf-8"))
