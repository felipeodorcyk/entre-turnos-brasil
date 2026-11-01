"""A vetorização de `classify` (handoff 17, desempenho) preserva a semântica.

Oráculo: a implementação anterior, por laço, congelada em `_closure_reference_loop.py`.
"""
import numpy as np
import pandas as pd
import pytest

from _closure_reference_loop import classify as classify_loop
from br2026.analysis.closure import classify
from br2026.config import election_dates, load_config

CFG = load_config()
SEMS = ["ENCERRAMENTO_URNA", "ENCERRAMENTO_URNA", "ENCERRAMENTO_URNA", "RECEBIMENTO_BU_TSE", "ABERTURA_URNA"]
TZS = ["America/Sao_Paulo", "America/Rio_Branco", "America/Manaus", None]


def random_closure(seed, n=400):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        sec = f"{rng.integers(1, 120):04d}"
        day = "2026-10-04" if rng.random() > 0.05 else "2026-10-05"
        raw = f"{day} {rng.integers(14, 21):02d}:{rng.integers(0, 60):02d}:{rng.integers(0, 60):02d}"
        if rng.random() < 0.03:
            raw = "lixo"
        if rng.random() < 0.03:
            raw = None
        rows.append({"ano": 2026, "nr_turno": int(rng.integers(1, 3)), "sg_uf": "AC", "cd_municipio_tse": "01007",
                     "nr_zona": "0001", "nr_secao": sec, "id_registro": f"r{i}", "id_bu": None, "id_urna": None,
                     "semantica": SEMS[rng.integers(0, len(SEMS))], "ts_bruto": raw,
                     "fuso_documentado": TZS[rng.integers(0, len(TZS))], "fonte_fuso": None,
                     "ts_brasilia": pd.NaT, "motivo_ausencia": None,
                     "flag_reemissao": bool(rng.random() < 0.1), "flag_substituicao_urna": bool(rng.random() < 0.05),
                     "flag_anomalia": False})
    df = pd.DataFrame(rows)
    df["ts_brasilia"] = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, America/Sao_Paulo]")
    return df


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("tol", [None, 30])
def test_vectorized_classify_equals_loop_reference(seed, tol):
    cl = random_closure(seed)
    a = classify(cl, election_dates(CFG), CFG, tolerance_min=tol).reset_index(drop=True)
    b = classify_loop(cl, election_dates(CFG), CFG, tolerance_min=tol).reset_index(drop=True)
    cols = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao", "faixa", "motivo_invalido",
            "n_registros", "flag_reemissao", "flag_substituicao_urna"]
    pd.testing.assert_frame_equal(a[cols].astype(str), b[cols].astype(str))
    ta, tb = a.ts_brasilia.astype("datetime64[ns, America/Sao_Paulo]"), b.ts_brasilia.astype("datetime64[ns, America/Sao_Paulo]")
    assert ((ta == tb) | (ta.isna() & tb.isna())).all()
    np.testing.assert_allclose(a.minutos_apos_limite.astype(float), b.minutos_apos_limite.astype(float))
