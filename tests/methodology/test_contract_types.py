"""R16-1 (revisão 16): validador de tipos com colunas textuais nulas ou vazias.

Corrige o TypeError sem enfraquecer nulabilidade, padrões, enums nem a rejeição
de valores não textuais. Inclui regressão do painel com T1 completo e T2 ausente,
o caso real que derrubou `run_panel`.
"""
import pandas as pd
import pytest

from br2026.contract import ContractError, validate
from br2026.panel.build import build_panel


def crosswalk_with(series, section_turn_fixture_cw):
    cw = section_turn_fixture_cw.copy()
    cw["justificativa"] = series
    return cw


@pytest.mark.parametrize("dtype", ["string", "string[pyarrow]", object])
def test_fully_null_nullable_text_column_is_valid(crosswalk, dtype):
    cw = crosswalk.copy()
    cw["justificativa"] = pd.Series([None] * len(cw), dtype=dtype)
    validate(cw, "section_crosswalk")


@pytest.mark.parametrize("dtype", ["string", "string[pyarrow]", object])
def test_valid_text_in_any_string_dtype(crosswalk, dtype):
    cw = crosswalk.copy()
    cw["justificativa"] = pd.Series(["fonte BU"] * len(cw), dtype=dtype)
    validate(cw, "section_crosswalk")


def test_empty_table_is_valid(crosswalk):
    validate(crosswalk.iloc[0:0], "section_crosswalk")


def test_non_text_values_in_text_column_rejected(crosswalk):
    cw = crosswalk.copy()
    cw["justificativa"] = pd.Series([123] + [None] * (len(cw) - 1), dtype=object)
    with pytest.raises(ContractError, match="justificativa: tipo"):
        validate(cw, "section_crosswalk")


@pytest.mark.parametrize("dtype", ["string", "string[pyarrow]", object])
def test_null_in_non_nullable_text_column_still_invalid(crosswalk, dtype):
    cw = crosswalk.copy()
    cw["fonte"] = pd.Series([None] * len(cw), dtype=dtype)
    with pytest.raises(ContractError, match="fonte: .* nulo"):
        validate(cw, "section_crosswalk")


def test_pattern_still_enforced_on_string_dtype(crosswalk):
    cw = crosswalk.copy()
    cw["nr_zona"] = cw.nr_zona.str.lstrip("0").astype("string")
    with pytest.raises(ContractError, match="fora do padrão"):
        validate(cw, "section_crosswalk")


def test_panel_with_complete_t1_and_absent_t2_validates(section_turn, votes_long, crosswalk):
    """Caso real R16-1: sem T2, nr_local_votacao_t2 é string inteiramente nula."""
    st = section_turn[section_turn.nr_turno == 1]
    vl = votes_long[votes_long.nr_turno == 1]
    cw = crosswalk[crosswalk.nr_turno == 1]
    panel = build_panel(st, vl, cw, 13, 22)
    panel["nr_local_votacao_t2"] = panel.nr_local_votacao_t2.astype("string")
    assert panel.nr_local_votacao_t2.isna().all()
    validate(panel, "panel")
    assert (panel.status_painel.isin(["EXCLUIDA_AUSENTE_T2", "EXCLUIDA_NAO_APURADA"])).all()
    assert not (panel.status_painel == "PAREADA").any()
