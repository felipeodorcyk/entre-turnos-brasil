"""O4: perfil por unidade — marginais por dimensão, sem duplicação."""
import numpy as np
import pandas as pd
import pytest

from br2026.analysis.profile import profile_design, unit_profile
from br2026.config import load_config
from br2026.contract import ContractError, validate

CFG = load_config()
GEO = {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001"}


def prof_rows(sec, gen, age, edu):
    rows = []
    for dim, cats in (("GENERO", gen), ("FAIXA_ETARIA", age), ("GRAU_ESCOLARIDADE", edu)):
        for cd, q in cats.items():
            rows.append({"ano_referencia": 2026, "dt_geracao": pd.Timestamp("2026-07-14"),
                         "dt_referencia_cadastro": pd.NaT, **GEO, "nr_secao": sec, "dimensao": dim,
                         "cd_categoria": cd, "ds_categoria": cd, "flag_desconhecido": cd in ("-3", "0"),
                         "qt_eleitores": q, "source_id": "0" * 64})
    return rows


def frames(prof):
    p = pd.DataFrame(prof)
    p["ano_referencia"] = p.ano_referencia.astype("int16")
    p["dt_referencia_cadastro"] = p.dt_referencia_cadastro.astype("datetime64[ns]")
    cw = pd.DataFrame([{"nr_turno": 1, **GEO, "nr_secao": s, "nr_secao_apuradora": a,
                        "status_correspondencia": "EFETIVADA"} for s, a in
                       (("0001", "0001"), ("0002", "0001"), ("0003", "0003"))])
    mem = pd.DataFrame([{"nr_turno": 1, **GEO, "nr_secao": "0001", "id_unidade": "U1"},
                        {"nr_turno": 1, **GEO, "nr_secao": "0003", "id_unidade": "U3"}])
    return p, cw, mem


BASE = (prof_rows("0001", {"2": 40, "4": 60}, {"1800": 10, "3034": 50, "6569": 40}, {"3": 30, "8": 70})
        + prof_rows("0002", {"2": 20, "4": 30}, {"1800": 5, "3034": 25, "-3": 20}, {"6": 50})
        + prof_rows("0003", {"2": 10, "4": 10}, {"4549": 20}, {"0": 20}))


def test_aggregated_origin_sections_sum_within_dimension():
    p, cw, mem = frames(BASE)
    validate(p, "profiles")
    shares, diag = unit_profile(p, cw, mem, CFG)
    d = diag.set_index("id_unidade")
    assert d.at["U1", "total_cadastro"] == 150   # 100 + 50, não 3 × 150
    assert shares.at["U1", "perfil_genero_feminino"] == pytest.approx(90 / 150)
    assert shares.at["U1", "perfil_faixa_etaria_desconhecido"] == pytest.approx(20 / 150)
    assert shares.at["U1", "perfil_faixa_etaria_16_24"] == pytest.approx(15 / 150)
    for dim in ("genero", "faixa_etaria", "grau_escolaridade"):
        cols = [c for c in shares if c.startswith(f"perfil_{dim}_")]
        np.testing.assert_allclose(shares[cols].sum(axis=1), 1.0)


def test_duplicate_profile_row_rejected_by_contract():
    p, _, _ = frames(BASE + BASE[:1])
    with pytest.raises(ContractError, match="chave primária"):
        validate(p, "profiles")


def test_incoherent_marginals_flagged_and_dropped():
    bad = [r if not (r["nr_secao"] == "0003" and r["dimensao"] == "GENERO" and r["cd_categoria"] == "2")
           else {**r, "qt_eleitores": 15} for r in BASE]
    p, cw, mem = frames(bad)
    shares, diag = unit_profile(p, cw, mem, CFG)
    assert diag.set_index("id_unidade").at["U3", "marginais_incoerentes"]
    assert "U3" not in shares.index and "U1" in shares.index


def test_design_drops_one_reference_per_dimension():
    p, cw, mem = frames(BASE)
    X = profile_design(unit_profile(p, cw, mem, CFG)[0], CFG)
    for dim, ref in CFG["profile"]["referencias"].items():
        assert f"perfil_{dim.lower()}_{ref}" not in X.columns
    assert "perfil_faixa_etaria_desconhecido" in X.columns
