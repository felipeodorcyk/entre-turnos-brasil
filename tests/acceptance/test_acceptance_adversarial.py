"""Testes adversos de integridade e robustez da Frente C (validação independente).

Verifica que qualquer inconsistência adversa é detectada e barrada:
1. Duplicata inserida em section_turn ou votes_long.
2. Turno inesperado ou ano trocado.
3. Ausente convertido em zero (violação da regra de valores não observados).
4. Horário de transmissão / recebimento passando por encerramento de urna.
5. Fuso horário não documentado (rejeição de suposição automática por UF).
6. Conflito de reemissões com horários divergentes.
7. Unidade crosswalk ambígua (flag_ambigua ou tipo AMBIGUA).
8. Valores negativos em contagens.
9. Não-colisão entre UFs distintas e sinalização de população variável.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from br2026.analysis.closure import classify, normalize_timestamp
from br2026.contract import ContractError, validate
from br2026.panel.build import build_panel
from tests.fixtures.acceptance.adversarial_and_timezone_fixtures import (
    build_closure_timezone_dfs,
    build_multi_uf_variable_pop_dfs,
)
from tests.fixtures.acceptance.oracle_fixtures import build_complex_oracle_dfs


def test_adversarial_duplicate_primary_key_in_section_turn():
    """Valida que duplicata inserida na chave primária de section_turn é detectada."""
    st, _, _ = build_complex_oracle_dfs()
    st_dup = pd.concat([st, st.iloc[[0]]], ignore_index=True)
    with pytest.raises(ContractError) as exc_info:
        validate(st_dup, "section_turn")
    assert "chave primária" in str(exc_info.value)
    assert "duplicada" in str(exc_info.value)


def test_adversarial_duplicate_primary_key_in_votes_long():
    """Valida que duplicata inserida na chave primária de votes_long é detectada."""
    _, _, vl = build_complex_oracle_dfs()
    vl_dup = pd.concat([vl, vl.iloc[[0]]], ignore_index=True)
    with pytest.raises(ContractError) as exc_info:
        validate(vl_dup, "votes_long")
    assert "chave primária" in str(exc_info.value)
    assert "duplicada" in str(exc_info.value)


def test_adversarial_invalid_or_swapped_turn():
    """Valida que turno inválido (ex.: turno 3 ou 0) é rejeitado pelo contrato."""
    st, _, _ = build_complex_oracle_dfs()
    st_bad = st.copy()
    st_bad.loc[0, "nr_turno"] = 3
    with pytest.raises(ContractError) as exc_info:
        validate(st_bad, "section_turn")
    assert "nr_turno" in str(exc_info.value)
    assert "enumeração" in str(exc_info.value) or "valores fora" in str(exc_info.value)


def test_adversarial_negative_counts_rejected():
    """Valida que contagens negativas de votos/aptos são rejeitadas pelo contrato."""
    st, _, _ = build_complex_oracle_dfs()
    st_neg = st.copy()
    st_neg.loc[0, "qt_votos_nominais"] = -5
    with pytest.raises(ContractError) as exc_info:
        validate(st_neg, "section_turn")
    assert "qt_votos_nominais" in str(exc_info.value)
    assert "abaixo de 0" in str(exc_info.value) or "min" in str(exc_info.value)


def test_adversarial_transmission_time_cannot_substitute_closure():
    """Valida que horário de recebimento no TSE não substitui encerramento de urna."""
    df_cl = build_closure_timezone_dfs()
    classified = classify(df_cl, election_dates={1: "2026-10-04", 2: "2026-10-25"})
    rj_row = classified[classified.sg_uf == "RJ"].iloc[0]
    assert rj_row.faixa == "INVALIDO"
    assert rj_row.motivo_invalido == "SEM_SEMANTICA_ELEGIVEL"
    assert pd.isna(rj_row.ts_brasilia)


def test_adversarial_undocumented_timezone_not_guessed_from_uf():
    """Valida que falta de fuso documentado gera FUSO_NAO_DOCUMENTADO e não deduz pela UF."""
    df_cl = build_closure_timezone_dfs()
    classified = classify(df_cl, election_dates={1: "2026-10-04", 2: "2026-10-25"})
    ba_row = classified[classified.sg_uf == "BA"].iloc[0]
    assert ba_row.faixa == "INVALIDO"
    assert ba_row.motivo_invalido == "FUSO_NAO_DOCUMENTADO"
    assert pd.isna(ba_row.ts_brasilia)


def test_adversarial_closure_missing_timezone_controlled_output():
    """Valida que fuso ausente/nulo gera saída controlada FUSO_NAO_DOCUMENTADO sem crash.

    Testa todas as representações de ausência: None, float('nan'), pd.NA e string vazia.
    Verifica a resolução do achado F-01 (não deve levantar TypeError nem crashar).
    """
    for missing_tz in (None, float("nan"), pd.NA, "", "   "):
        ts_norm, motivo = normalize_timestamp("2026-10-04 17:15:00", missing_tz)
        assert ts_norm is None, f"Esperado Timestamp nulo para tz={missing_tz!r}"
        assert motivo == "FUSO_NAO_DOCUMENTADO", f"Esperado FUSO_NAO_DOCUMENTADO para tz={missing_tz!r}"

    # Validação via DataFrame em classify() contendo float('nan')
    df_nan = pd.DataFrame([{
        "ano": 2026, "nr_turno": 1, "sg_uf": "BA", "cd_municipio_tse": "30001",
        "nr_zona": "0001", "nr_secao": "0001", "id_registro": "rec_nan",
        "semantica": "ENCERRAMENTO_URNA", "fuso_documentado": float("nan"),
        "ts_bruto": "2026-10-04 17:15:00", "ts_brasilia": None, "motivo_ausencia": None,
        "flag_reemissao": False, "flag_substituicao_urna": False, "source_id": "sha_nan",
    }])
    classified = classify(df_nan, election_dates={1: "2026-10-04", 2: "2026-10-25"})
    assert len(classified) == 1
    assert classified.iloc[0].faixa == "INVALIDO"
    assert classified.iloc[0].motivo_invalido == "FUSO_NAO_DOCUMENTADO"


def test_adversarial_reemission_closure_conflict_detected():
    """Valida que horários divergentes de encerramento em reemissão geram CONFLITO_REEMISSAO."""
    df_cl = build_closure_timezone_dfs()
    classified = classify(df_cl, election_dates={1: "2026-10-04", 2: "2026-10-25"})
    mg_row = classified[classified.sg_uf == "MG"].iloc[0]
    assert mg_row.faixa == "INVALIDO"
    assert mg_row.motivo_invalido == "CONFLITO_REEMISSAO"
    assert bool(mg_row.flag_reemissao) is True


def test_adversarial_ambiguous_crosswalk_marked_ambiguous():
    """Valida que seção com flag_ambigua=True ou tipo AMBIGUA é EXCLUIDA_AMBIGUA."""
    st, cw, vl = build_complex_oracle_dfs()
    panel = build_panel(st, vl, cw, nr_lula=13, nr_flavio=22)
    row_70 = panel[panel.id_unidade.str.endswith("0070")].iloc[0]
    assert row_70.status_painel == "EXCLUIDA_AMBIGUA"


def test_adversarial_missing_data_not_converted_to_zero_in_sums():
    """Valida que termo ausente torna o total ausente em vez de virar zero."""
    st, cw, vl = build_complex_oracle_dfs()
    panel = build_panel(st, vl, cw, nr_lula=13, nr_flavio=22)
    row_60 = panel[panel.id_unidade.str.endswith("0060")].iloc[0]
    assert pd.isna(row_60.qt_comparecimento_t1), "Dado ausente foi indevidamente convertido para zero!"
    assert row_60.status_painel == "EXCLUIDA_NAO_APURADA"


def test_adversarial_multi_uf_no_collision_and_variable_population():
    """Valida que a mesma seção em UFs distintas não colide e que população variável é sinalizada."""
    st, cw, vl = build_multi_uf_variable_pop_dfs()
    panel = build_panel(st, vl, cw, nr_lula=13, nr_flavio=22)

    assert len(panel) == 3
    assert set(panel.sg_uf) == {"AC", "SP", "ZZ"}

    sp_row = panel[panel.sg_uf == "SP"].iloc[0]
    assert sp_row.status_painel == "PAREADA"
    assert bool(sp_row.flag_aptos_divergente) is True
    assert sp_row.qt_aptos_t1 == 200
    assert sp_row.qt_aptos_t2 == 210

    ac_row = panel[panel.sg_uf == "AC"].iloc[0]
    assert bool(ac_row.flag_aptos_divergente) is False
    zz_row = panel[panel.sg_uf == "ZZ"].iloc[0]
    assert bool(zz_row.flag_aptos_divergente) is False
