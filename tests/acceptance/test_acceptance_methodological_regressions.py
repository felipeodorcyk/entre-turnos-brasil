"""Testes de regressão metodológica independente (Frente C).

Cobre os requisitos C2 de 15_HANDOFF_ANTIGRAVITY_REVISAO_PONTUAL.md e achados O-R1, O-R2, O-R3, O-R5:
1. Perfil cadastral (O-R1):
   - Dimensão ausente por unidade e globalmente não vira zero nem perfil completo (DIMENSAO_AUSENTE, SEM_PERFIL).
   - Origem parcialmente ausente em unidade agregada gera PERFIL_PARCIAL_ORIGENS.
   - Categoria zero genuína em dimensão observada é preservada como 0.0.
   - Total zero gera TOTAL_ZERO.
2. Fusos e encerramento na sensibilidade (O-R2):
   - Recebimento documentado com encerramento inferido não contamina a variante estritamente documental.
   - Deslocamento inferido zero continua sendo inferência e não é promovido a documental.
3. Premissa temporal e relógio (O-R3):
   - Sem premissa legal ou semântica de relógio confirmadas, inferência de fuso permanece como
     cenário exploratório e não é promovida a análise principal.
4. Linter de alegações (O-R5):
   - Ressalvas legítimas de ausência de causalidade são aceitas pelo linter contextual de C,
     mas documenta-se a persistência do falso positivo no linter ingênuo de produção.
5. Interpretação de abstenção e transições:
   - Saldo agregado não identifica transição individual observada.

Atualização de 26/10/2026 (handoff 17, frente B/Opus — AUTOVERIFICAÇÃO): R16-3. O teste da
trava temporal, que calculava `promoted`/`roles` localmente, foi substituído por execuções
reais de `run_analyze` e `build_report` em raiz temporária. Os valores esperados são fixados
pela regra do handoff, não pela função sob teste.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from br2026.analysis.closure_tz import select_closure_variant
from br2026.analysis.profile import unit_profile
from br2026.reporting.report import lint_template
from tests.acceptance.test_acceptance_linter_alegacoes import AcceptanceLinter


# -----------------------------------------------------------------------------
# 1. Perfil Cadastral (O-R1)
# -----------------------------------------------------------------------------

def test_profile_missing_dimension_and_partial_origins_not_converted_to_zero():
    """Valida que dimensão cadastral ausente ou origem parcial não viram proporção zero (O-R1)."""
    cfg = {
        "profile": {
            "ano_referencia": 2026,
            "grupos": {
                "GENERO": {"masc": ["M"], "fem": ["F"]},
                "FAIXA_ETARIA": {"jovem": ["16", "17"], "adulto": ["18_MAIS"]},
            },
            "referencias": {"GENERO": "masc", "FAIXA_ETARIA": "jovem"},
        }
    }

    # Crosswalk e Membership para unidades de teste:
    # U0: completa com jovem=15 e adulto=15
    # U1: completa, com categoria zero genuína (0 jovens, 30 adultos)
    # U2: falta a dimensão FAIXA_ETARIA inteira (DIMENSAO_AUSENTE)
    # U3: agregada com 2 seções, onde a seção 0004 não tem perfil (PERFIL_PARCIAL_ORIGENS)
    # U4: sem nenhum dado de perfil (SEM_PERFIL)
    # U5: total de eleitores zero (TOTAL_ZERO)
    cw = pd.DataFrame([
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0000", "nr_turno": 1,
         "nr_secao_apuradora": "0000", "status_correspondencia": "EFETIVADA", "flag_ambigua": False},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "nr_turno": 1,
         "nr_secao_apuradora": "0001", "status_correspondencia": "EFETIVADA", "flag_ambigua": False},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0002", "nr_turno": 1,
         "nr_secao_apuradora": "0002", "status_correspondencia": "EFETIVADA", "flag_ambigua": False},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0003", "nr_turno": 1,
         "nr_secao_apuradora": "0003", "status_correspondencia": "EFETIVADA", "flag_ambigua": False},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0004", "nr_turno": 1,
         "nr_secao_apuradora": "0003", "status_correspondencia": "EFETIVADA", "flag_ambigua": False},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0005", "nr_turno": 1,
         "nr_secao_apuradora": "0005", "status_correspondencia": "EFETIVADA", "flag_ambigua": False},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0006", "nr_turno": 1,
         "nr_secao_apuradora": "0006", "status_correspondencia": "EFETIVADA", "flag_ambigua": False},
    ])
    mem = pd.DataFrame([
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0000", "nr_turno": 1, "id_unidade": "U0"},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "nr_turno": 1, "id_unidade": "U1"},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0002", "nr_turno": 1, "id_unidade": "U2"},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0003", "nr_turno": 1, "id_unidade": "U3"},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0004", "nr_turno": 1, "id_unidade": "U3"},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0005", "nr_turno": 1, "id_unidade": "U4"},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0006", "nr_turno": 1, "id_unidade": "U5"},
    ])

    prof_rows = [
        # U0: completa, com jovem=15 e adulto=15
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0000", "ano_referencia": 2026,
         "dimensao": "GENERO", "cd_categoria": "M", "qt_eleitores": 30},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0000", "ano_referencia": 2026,
         "dimensao": "FAIXA_ETARIA", "cd_categoria": "16", "qt_eleitores": 15},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0000", "ano_referencia": 2026,
         "dimensao": "FAIXA_ETARIA", "cd_categoria": "18_MAIS", "qt_eleitores": 15},

        # U1 (seção 0001): Completa. GENERO M=10, F=20 (tot 30). FAIXA_ETARIA: só 18_MAIS=30 (jovem=0 observado).
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "ano_referencia": 2026,
         "dimensao": "GENERO", "cd_categoria": "M", "qt_eleitores": 10},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "ano_referencia": 2026,
         "dimensao": "GENERO", "cd_categoria": "F", "qt_eleitores": 20},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "ano_referencia": 2026,
         "dimensao": "FAIXA_ETARIA", "cd_categoria": "18_MAIS", "qt_eleitores": 30},

        # U2 (seção 0002): Falta FAIXA_ETARIA inteiramente. Tem apenas GENERO.
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0002", "ano_referencia": 2026,
         "dimensao": "GENERO", "cd_categoria": "M", "qt_eleitores": 25},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0002", "ano_referencia": 2026,
         "dimensao": "GENERO", "cd_categoria": "F", "qt_eleitores": 25},

        # U3: seção 0003 tem dados completos, mas seção agregada 0004 não tem nenhuma linha no perfil
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0003", "ano_referencia": 2026,
         "dimensao": "GENERO", "cd_categoria": "M", "qt_eleitores": 15},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0003", "ano_referencia": 2026,
         "dimensao": "FAIXA_ETARIA", "cd_categoria": "18_MAIS", "qt_eleitores": 15},

        # U4: seção 0005 não tem linhas de perfil
        # U5 (seção 0006): Total zero
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0006", "ano_referencia": 2026,
         "dimensao": "GENERO", "cd_categoria": "M", "qt_eleitores": 0},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0006", "ano_referencia": 2026,
         "dimensao": "FAIXA_ETARIA", "cd_categoria": "18_MAIS", "qt_eleitores": 0},
    ]

    profiles = pd.DataFrame(prof_rows)
    shares, diag = unit_profile(profiles, cw, mem, cfg)

    diag_by_unit = diag.set_index("id_unidade")

    # 1. U1 é a única elegível; categoria jovem tem zero observado legítimo
    assert diag_by_unit.loc["U1", "elegivel"] == True
    assert diag_by_unit.loc["U1", "motivo_exclusao"] is None
    assert shares.loc["U1", "perfil_faixa_etaria_jovem"] == 0.0
    assert shares.loc["U1", "perfil_faixa_etaria_adulto"] == 1.0
    assert shares.loc["U1", "perfil_genero_masc"] == pytest.approx(10 / 30)
    assert shares.loc["U1", "perfil_genero_fem"] == pytest.approx(20 / 30)

    # 2. U2: dimensão faltante não vira proporção zero; unidade é excluída
    assert diag_by_unit.loc["U2", "elegivel"] == False
    assert diag_by_unit.loc["U2", "motivo_exclusao"] == "DIMENSAO_AUSENTE"
    assert "FAIXA_ETARIA" in diag_by_unit.loc["U2", "dimensoes_faltantes"]
    assert "U2" not in shares.index

    # 3. U3: unidade agregada com origem faltante
    assert diag_by_unit.loc["U3", "elegivel"] == False
    assert diag_by_unit.loc["U3", "motivo_exclusao"] == "PERFIL_PARCIAL_ORIGENS"
    assert "U3" not in shares.index

    # 4. U4: sem dados de perfil
    assert diag_by_unit.loc["U4", "elegivel"] == False
    assert diag_by_unit.loc["U4", "motivo_exclusao"] == "SEM_PERFIL"
    assert "U4" not in shares.index

    # 5. U5: total zero
    assert diag_by_unit.loc["U5", "elegivel"] == False
    assert diag_by_unit.loc["U5", "motivo_exclusao"] == "TOTAL_ZERO"
    assert "U5" not in shares.index


# -----------------------------------------------------------------------------
# 2. Fusos e Encerramento na Sensibilidade (O-R2)
# -----------------------------------------------------------------------------

def test_closure_documented_receipt_does_not_admit_inferred_closure():
    """Valida que recebimento documentado não promove encerramento inferido a documental (O-R2)."""
    # Seção com ABERTURA (inferida), ENCERRAMENTO (inferido +2h) e RECEBIMENTO_BU (documentado SP)
    df = pd.DataFrame([
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "nr_turno": 1,
         "semantica": "ABERTURA_URNA", "status_fuso": "INFERIDO_ABERTURA_MUNICIPAL", "offset_h": 2,
         "ts_brasilia": pd.Timestamp("2026-10-04 08:00:00")},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "nr_turno": 1,
         "semantica": "ENCERRAMENTO_URNA", "status_fuso": "INFERIDO_ABERTURA_MUNICIPAL", "offset_h": 2,
         "ts_brasilia": pd.Timestamp("2026-10-04 17:00:00")},
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "nr_turno": 1,
         "semantica": "RECEBIMENTO_BU", "status_fuso": "DOCUMENTADO", "offset_h": 0,
         "ts_brasilia": pd.Timestamp("2026-10-04 17:30:00")},
    ])

    res_doc = select_closure_variant(df, "documental")
    enc_row = res_doc[res_doc.semantica == "ENCERRAMENTO_URNA"].iloc[0]

    # O encerramento não pode ser admitido na variante documental apenas pelo recebimento ter fuso
    assert enc_row["status_fuso"] == "NAO_ADMITIDO_NA_VARIANTE"
    assert pd.isna(enc_row["ts_brasilia"])


def test_closure_inferred_offset_zero_is_still_inference():
    """Valida que deslocamento inferido zero continua fora da variante estritamente documental (O-R2)."""
    df = pd.DataFrame([
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001", "nr_turno": 1,
         "semantica": "ENCERRAMENTO_URNA", "status_fuso": "INFERIDO_ABERTURA_MUNICIPAL", "offset_h": 0,
         "ts_brasilia": pd.Timestamp("2026-10-04 17:00:00")},
    ])

    res_doc = select_closure_variant(df, "documental")
    enc_row = res_doc[res_doc.semantica == "ENCERRAMENTO_URNA"].iloc[0]

    # Offset zero por inferência não equivale a comprovação documental
    assert enc_row["status_fuso"] == "NAO_ADMITIDO_NA_VARIANTE"
    assert pd.isna(enc_row["ts_brasilia"])


# -----------------------------------------------------------------------------
# 3. Premissa Temporal Não Comprovada e Publicação Principal (O-R3)
# -----------------------------------------------------------------------------

def _synthetic_run(tmp_path, cz_overrides, undocument=True):
    """Staging sintético (B) sem nenhum fuso documentado, executado pela produção real."""
    import importlib.util

    from br2026.analysis.run import run_analyze
    from br2026.config import load_config
    from br2026.contract import PROJECT_ROOT
    from br2026.panel.run import run_panel
    from br2026.reporting.build import build_report

    fix = PROJECT_ROOT / "tests" / "fixtures" / "contract" / "synth_staging.py"
    spec = importlib.util.spec_from_file_location("synth_staging_c", fix)
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    staging, out = tmp_path / "data" / "staging", tmp_path / "data" / "analytics"
    synth.make_staging(staging)
    if undocument:
        cl = pd.read_parquet(staging / "closure.parquet")
        cl["fuso_documentado"] = None
        cl["motivo_ausencia"] = "FUSO_NAO_DOCUMENTADO"
        cl.to_parquet(staging / "closure.parquet", index=False)
    cfg = load_config()
    cfg["ecological"]["bootstrap_reps"] = 3
    # base sem confirmação (a config versionada passou a confirmá-las no handoff 29)
    cfg["closure_tz"].update({"premissa_horario_unico_confirmada": False, "fonte_premissa": "",
                             "semantica_relogio_validada": False, "fonte_validacao_relogio": ""})
    cfg["closure_tz"].update(cz_overrides)
    run_panel(staging, out, cfg)
    run_analyze(staging, out, cfg)
    build_report(out, tmp_path / "rep")
    status = pd.read_csv(out / "analysis_status.csv").set_index("bloco").status
    text = (tmp_path / "rep" / "relatorio.md").read_text(encoding="utf-8")
    return status, pd.read_csv(out / "closure_adjusted.csv"), text


@pytest.mark.parametrize("cz", [
    {},  # premissas ausentes
    {"premissa_horario_unico_confirmada": True, "fonte_premissa": "https://exemplo.invalid/norma"},
    {"semantica_relogio_validada": True, "fonte_validacao_relogio": "https://exemplo.invalid/relogio"},
    {"premissa_horario_unico_confirmada": True, "fonte_premissa": "",
     "semantica_relogio_validada": True, "fonte_validacao_relogio": "https://exemplo.invalid/relogio"},
], ids=["sem_premissas", "so_norma", "so_relogio", "norma_sem_fonte"])
def test_unconfirmed_premises_block_main_temporal_conclusion_in_production(tmp_path, cz):
    """R16-3: premissas ausentes/incompletas → sem conclusão temporal principal; eleitoral intacto."""
    status, adj, text = _synthetic_run(tmp_path, cz)
    assert status["horarios:inferencia_fuso"] == "EXPLORATORIO"
    assert status["horarios:conclusao_principal"] == "BLOCKED"
    principal = adj[adj.papel == "principal"] if "papel" in adj else adj
    assert not (principal.status == "PASS").any()
    assert status["descricao:pareado_territorial"] == "PASS"
    horarios = text.split("## Horários de encerramento")[1].split("## Blocos")[0]
    assert "Conclusão temporal principal: **BLOCKED**" in horarios
    assert "EXPLORATÓRIO" not in horarios and "beta_ajustado" not in horarios


def test_complete_synthetic_premises_exercise_promotion_mechanism_only(tmp_path):
    """Mecanismo: com as duas confirmações (fontes fictícias) a inferência é promovida.

    Isto testa o código, não prova documentação real do relógio das urnas.
    """
    status, adj, _ = _synthetic_run(tmp_path, {
        "premissa_horario_unico_confirmada": True, "fonte_premissa": "https://exemplo.invalid/norma",
        "semantica_relogio_validada": True, "fonte_validacao_relogio": "https://exemplo.invalid/relogio"})
    assert status["horarios:inferencia_fuso"] == "PASS"
    assert set(adj.variante) == {"exploratorio_inferido", "documental"} or set(adj.variante) == {"exploratorio_inferido"}


# -----------------------------------------------------------------------------
# 4. Linter: Ressalva Legítima vs Falhas de Produção (O-R5)
# -----------------------------------------------------------------------------

def test_linter_production_and_acceptance_distinguish_caveats_from_violations():
    """Valida que tanto o AcceptanceLinter quanto o linter de produção (report.py)

    foram corrigidos para distinguir ressalvas legítimas de afirmações causais indevidas (O-R5).
    """
    caveat_text = (
        "Esta analise nao demonstra relacao causal entre o perfil cadastral e o voto. "
        "Nao sabemos em quem votaram apos as 17h, pois a urna preserva apenas o agregado."
    )
    violation_text = "A variacao no encerramento causou aumento de votos e relacao causal direta."

    # 1. O linter contextual de aceite da Frente C aprova ressalvas legítimas e barra afirmações
    res_c_caveat = AcceptanceLinter.audit(caveat_text)
    assert res_c_caveat.is_clean, f"Linter de C gerou falso positivo: {res_c_caveat.violations}"
    assert len(res_c_caveat.legitimate_caveats) >= 1

    res_c_viol = AcceptanceLinter.audit(violation_text)
    assert not res_c_viol.is_clean
    assert "ASSOCIATION_AS_CAUSALITY" in res_c_viol.violations

    # 2. O linter de produção (report.py) agora também respeita a negação da mesma oração (O-R5 corrigido)
    prod_caveat_issues = lint_template(caveat_text)
    assert len(prod_caveat_issues) == 0, f"Produção ainda rejeita ressalva legítima: {prod_caveat_issues}"

    prod_viol_issues = lint_template(violation_text)
    assert any("frase proibida" in issue and "caus" in issue for issue in prod_viol_issues), (
        f"Produção não detectou afirmação causal: {prod_viol_issues}"
    )


# -----------------------------------------------------------------------------
# 5. Interpretação de Fluxos: Saldo Agregado vs Transição Individual
# -----------------------------------------------------------------------------

def test_aggregate_net_zero_variation_does_not_identify_individual_transitions():
    """Valida matematicamente que saldo líquido agregado nulo não prova ausência de migração."""
    # Cenário: Seção com 100 eleitores nos dois turnos.
    # T1: Lula = 50, Candidato X = 50.
    # T2: Lula = 50, Flavio = 50.
    # Saldo líquido: Delta Lula = 0.
    # Transição A: Nenhum eleitor de Lula mudou de voto (retencao 100%, migracao de X = 0).
    # Transição B: 20 eleitores de Lula migraram para Flavio, e 20 eleitores de X migraram para Lula.
    # Em ambos os casos, os dados agregados observados são idênticos: Lula T1=50, Lula T2=50.
    # Logo, os dados observados agregados NÃO identificam a taxa individual de retenção/migração.
    t1_lula = 50
    t2_lula = 50
    delta_agregado = t2_lula - t1_lula
    assert delta_agregado == 0

    # Sob transição individual micro A:
    fluxo_lula_lula_A = 50
    # Sob transição individual micro B:
    fluxo_lula_lula_B = 30  # 20 mudaram para Flávio, compensados por 20 de X para Lula

    assert fluxo_lula_lula_A != fluxo_lula_lula_B
    # Conclusão metodológica inegociável: saldo agregado é identificável, transição individual micro não é
