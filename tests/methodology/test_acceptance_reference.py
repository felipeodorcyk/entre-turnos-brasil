"""O2: a conferência contra referência oficial discrimina casos adversos.

Os totais "oficiais" abaixo são literais escritos à mão (oráculo), não saídas da
função sob teste. O staging simulado concorda com eles, salvo onde o caso altera.
"""
import pandas as pd
import pytest

from br2026.reporting.acceptance import REQUIRED_METRICS, check_reference, expected_keys

DATES = {1: "2026-10-04", 2: "2026-10-25"}
OFFICIAL = {  # (turno, UF) → métricas
    (1, "AC"): dict(qt_aptos=600, qt_comparecimento=480, qt_abstencoes=120, qt_votos_brancos=10,
                    qt_votos_nulos=14, qt_lula=200, qt_flavio=230),
    (2, "AC"): dict(qt_aptos=600, qt_comparecimento=470, qt_abstencoes=130, qt_votos_brancos=8,
                    qt_votos_nulos=12, qt_lula=215, qt_flavio=235),
    (1, "RS"): dict(qt_aptos=900, qt_comparecimento=720, qt_abstencoes=180, qt_votos_brancos=20,
                    qt_votos_nulos=25, qt_lula=300, qt_flavio=350),
    (2, "RS"): dict(qt_aptos=900, qt_comparecimento=730, qt_abstencoes=170, qt_votos_brancos=15,
                    qt_votos_nulos=20, qt_lula=320, qt_flavio=375),
}
OBSERVED = {(t, uf, m): v for (t, uf), d in OFFICIAL.items() for m, v in d.items()}
KEYS = expected_keys(OBSERVED)
STAGING_HASH = "a" * 64
SECTION_URLS = {"https://cdn.tse.jus.br/.../votacao_secao_2026_AC.zip"}


def ref_rows(**over):
    rows = [{"nr_turno": t, "sg_uf": uf, "metrica": m, "valor": v,
             "fonte_tipo": "RESULTADO_DIVULGADO_TSE",
             "url": f"https://resultados.tse.jus.br/oficial/{uf}/{t}.json",
             "sha256_fonte": "b" * 64, "data_corte": "2026-10-26"}
            for (t, uf), d in OFFICIAL.items() for m, v in d.items()]
    return pd.DataFrame(rows)


def check(ref):
    return check_reference(ref, OBSERVED, KEYS, DATES, {STAGING_HASH}, SECTION_URLS)


def test_complete_correct_reference_passes():
    assert check(ref_rows()) == []
    assert len(KEYS) == 4 * len(REQUIRED_METRICS)


def test_header_only_fails():
    assert check(ref_rows().iloc[0:0]) == ["referência vazia"]


@pytest.mark.parametrize("drop,label", [
    (lambda r: r[r.sg_uf != "RS"], "UF faltando"),
    (lambda r: r[r.nr_turno != 2], "turno faltando"),
    (lambda r: r[r.metrica != "qt_flavio"], "métrica omitida"),
])
def test_incomplete_coverage_fails(drop, label):
    probs = check(drop(ref_rows()))
    assert any("ausente" in p for p in probs), label


def test_duplicate_fails():
    r = ref_rows()
    assert any("duplicadas" in p for p in check(pd.concat([r, r.iloc[[3]]])))


@pytest.mark.parametrize("bad", [-1, 12.5, "abc", None])
def test_invalid_value_fails(bad):
    r = ref_rows()
    r["valor"] = r.valor.astype(object)
    r.loc[0, "valor"] = bad
    assert check(r)


def test_one_vote_difference_fails():
    r = ref_rows()
    i = r.index[(r.nr_turno == 2) & (r.sg_uf == "RS") & (r.metrica == "qt_lula")][0]
    r.loc[i, "valor"] += 1
    probs = check(r)
    assert probs == ["(2, 'RS', 'qt_lula'): staging 320 ≠ oficial 321"]


def test_source_equal_to_staging_input_fails():
    r = ref_rows()
    r.loc[0, "sha256_fonte"] = STAGING_HASH
    assert any("não independente" in p for p in check(r))


def test_section_level_url_fails():
    r = ref_rows()
    r.loc[0, "url"] = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_RS.zip"
    assert any("arquivo por seção" in p for p in check(r))


def test_cutoff_before_election_fails():
    r = ref_rows()
    r.loc[r.nr_turno == 2, "data_corte"] = "2026-10-20"
    assert any("anterior à eleição" in p for p in check(r))


def test_unknown_source_type_fails():
    r = ref_rows()
    r.loc[0, "fonte_tipo"] = "SOMA_DO_STAGING"
    assert any("fonte_tipo" in p for p in check(r))


def test_missing_staging_total_is_reported():
    obs = dict(OBSERVED)
    obs[(1, "AC", "qt_aptos")] = None
    probs = check_reference(ref_rows(), obs, KEYS, DATES, {STAGING_HASH}, SECTION_URLS)
    assert any("termo ausente" in p for p in probs)
