"""O5: relatório montado das tabelas, rastreável e sem narrativa proibida."""
import json
import re
import shutil

import pandas as pd
import pytest

from br2026.reporting.build import Doc, build_report
from br2026.reporting.report import ReportError, forbidden_matches
from test_analyze_e2e import run  # noqa: F401  (fixture de módulo: staging sintético → analyze)


def test_report_builds_with_trace(run, tmp_path):
    r = build_report(run["out"], tmp_path)
    assert r["status"] == "PASS"
    text = (tmp_path / "relatorio.md").read_text(encoding="utf-8")
    trace = pd.read_csv(tmp_path / "relatorio_rastro.csv")
    for h in ("## Fontes e reprodutibilidade", "## Universo e cobertura", "## Variação entre turnos",
              "## Origens possíveis", "## Associações territoriais", "## Horários de encerramento",
              "## Blocos não estimados", "## Limitações"):
        assert h in text
    assert {"metrics_aggregate.csv", "coverage_uf.csv", "flow_bounds.csv", "closure_adjusted.csv",
            "analysis_manifest.json"} <= set(trace.tabela)
    assert forbidden_matches(text) == []
    assert "não constitui aceite de marco" in text


def test_point_rates_hidden_when_rule_fails(run, tmp_path):
    out = tmp_path / "a"
    shutil.copytree(run["out"], out)
    dec = json.loads((out / "ecological_decision.json").read_text(encoding="utf-8"))
    dec.update(publicar_matriz_pontual=False, motivos=["teste: regra não satisfeita"])
    (out / "ecological_decision.json").write_text(json.dumps(dec), encoding="utf-8")
    build_report(out, tmp_path / "r")
    text = (tmp_path / "r" / "relatorio.md").read_text(encoding="utf-8")
    assert "Taxas médias estimadas" not in text and "teste: regra não satisfeita" in text
    assert "Limites compatíveis com os totais" in text


def test_static_prose_rejects_numbers_and_forbidden():
    d = Doc()
    with pytest.raises(ReportError):
        d.prose("Lula ganhou 1234 votos.")
    with pytest.raises(ReportError):
        d.prose("Os eleitores transferiram votos.")


def test_report_blocked_without_analyze(tmp_path):
    assert build_report(tmp_path, tmp_path / "r")["status"] == "BLOCKED"


def test_pilot_comparative_report_and_figures_build_and_honest_stop(run, tmp_path):
    """Handoff 19: gera relatório comparativo T1×T2 + figuras + tabelas quando há pares; bloqueia sem T2."""
    from br2026.reporting.pilot_comparative import build_pilot_comparative_report

    out_dir = tmp_path / "rep_full"
    res = build_pilot_comparative_report(run["out"], out_dir)
    assert res["status"] == "PASS"
    md_path = out_dir / "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md"
    trace_path = out_dir / "RASTRO_RELATORIO_PILOTO.csv"
    assert md_path.exists() and trace_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert forbidden_matches(md_text) == []
    # handoff 24: três documentos, mesmas tabelas, um só rastro
    resumo = (out_dir / "RESUMO_EXECUTIVO_PILOTO.md").read_text(encoding="utf-8")
    apendice = (out_dir / "APENDICE_TECNICO_PILOTO.md").read_text(encoding="utf-8")
    for sec in ("## O que mudou", "## O que os dados não permitem dizer", "## Confiança"):
        assert sec in resumo
    for sec in ("## Como ler este relatório", "## 1. O que mudou entre os turnos", "## 2. Onde:",
                "## 3. Participação, brancos e nulos", "## 4. Bases iniciais e perfil do eleitorado",
                "## 5. O que os dados não identificam", "## 6. Horários e ocorrências de urna"):
        assert sec in md_text
    for sec in ("## A.1 Definições", "## A.2 Cobertura e reconciliação", "## A.7 Proveniência"):
        assert sec in apendice
    assert "sg_uf" not in md_text.split("## 1.")[1].split("## 2.")[0], "cabeçalhos legíveis no relatório principal"
    rastro = pd.read_csv(trace_path)
    assert set(rastro.documento) == {"RESUMO_EXECUTIVO_PILOTO.md", "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md",
                                     "APENDICE_TECNICO_PILOTO.md"}
    for fig_name in (
        "fig01_resumo_uf_t1_t2.png",
        "fig02_contribuicoes_municipais_uf.png",
        "fig03_decomposicao_comparecimento_nao_validos.png",
        "fig04_associacoes_perfil_simples_vs_ajustado.png",
        "fig05_cobertura_agregacao_ocorrencias.png",
    ):
        assert (out_dir / "figuras_piloto" / fig_name).exists(), fig_name
    for tab_name in (
        "tab01_resumo_uf_t1_t2.csv",
        "tab02_top_municipios_contribuicao.csv",
        "tab03_sensibilidade_agregacao_uf.csv",
        "tab04_limites_fluxos_agregados_uf.csv",
        "tab05_associacoes_perfil_t1_t2.csv",
        "tab06_auditoria_operacional_uf.csv",
        "tab07_identidade_saldos_e_teste_100pct.csv",
    ):
        assert (out_dir / "tabelas_piloto" / tab_name).exists(), tab_name
    t7 = pd.read_csv(out_dir / "tabelas_piloto" / "tab07_identidade_saldos_e_teste_100pct.csv")
    dem = pd.read_csv(run["out"] / "flow_demais_para_lula.csv")
    assert set(dem.sg_uf) >= {"TOTAL"} and (dem.fluxo_min <= dem.fluxo_max).all()
    assert (dem.fluxo_max <= dem.qt_demais_t1).all()
    assert (t7.identidade_saldos_dif == 0).all() and (t7.identidade_validos_aptos_dif == 0).all()
    assert (t7.teste_100pct_observado == "NAO_IDENTIFICAVEL_POR_SIGILO").all()
    assert set(t7.teste_100pct_possivel.astype(str)) <= {"True", "False"}

    # Parada honesta: quando pares_entre_turnos == False, recusa gerar falso relatório T1×T2
    analytics_t1_only = tmp_path / "analytics_t1"
    shutil.copytree(run["out"], analytics_t1_only)
    man = json.loads((analytics_t1_only / "analysis_manifest.json").read_text(encoding="utf-8"))
    man["pares_entre_turnos"] = False
    (analytics_t1_only / "analysis_manifest.json").write_text(json.dumps(man), encoding="utf-8")
    out_blocked = tmp_path / "rep_blocked"
    res_blocked = build_pilot_comparative_report(analytics_t1_only, out_blocked)
    assert res_blocked["status"] == "BLOCKED"
    assert not (out_blocked / "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md").exists()


def test_r20_2_negative_guards_and_stale_cleanup(run, tmp_path):
    """R20-2: bloqueia manifesto vazio, 1 UF apenas, status FAIL, dif != 0, denominador <= 0 e limpa artefatos obsoletos."""
    from br2026.reporting.pilot_comparative import build_pilot_comparative_report

    # 1. Manifesto vazio {} -> BLOCKED
    empty_dir = tmp_path / "empty_analytics"
    empty_dir.mkdir()
    (empty_dir / "analysis_manifest.json").write_text("{}", encoding="utf-8")
    out_empty = tmp_path / "out_empty"
    res_empty = build_pilot_comparative_report(empty_dir, out_empty)
    assert res_empty["status"] == "BLOCKED"
    assert not (out_empty / "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md").exists()

    # 2. Apenas 1 UF em coverage_uf.csv -> BLOCKED
    one_uf = tmp_path / "one_uf"
    shutil.copytree(run["out"], one_uf)
    cov = pd.read_csv(one_uf / "coverage_uf.csv")
    cov.iloc[:1].to_csv(one_uf / "coverage_uf.csv", index=False)
    assert build_pilot_comparative_report(one_uf, tmp_path / "out_one_uf")["status"] == "BLOCKED"

    # 3. Bloco com status == FAIL -> BLOCKED
    fail_dir = tmp_path / "fail_dir"
    shutil.copytree(run["out"], fail_dir)
    st = pd.read_csv(fail_dir / "analysis_status.csv")
    st.loc[0, "status"] = "FAIL"
    st.to_csv(fail_dir / "analysis_status.csv", index=False)
    assert build_pilot_comparative_report(fail_dir, tmp_path / "out_fail")["status"] == "BLOCKED"

    # 4. Denominador <= 0 em metrics_uf.csv -> BLOCKED
    bad_den = tmp_path / "bad_den"
    shutil.copytree(run["out"], bad_den)
    m_uf = pd.read_csv(bad_den / "metrics_uf.csv")
    m_uf.loc[0, "qt_aptos_t1"] = 0
    m_uf.to_csv(bad_den / "metrics_uf.csv", index=False)
    assert build_pilot_comparative_report(bad_den, tmp_path / "out_bad_den")["status"] == "BLOCKED"

    # 5. Reexecução bloqueada remove artefatos anteriores do diretório de saída
    out_reuse = tmp_path / "out_reuse"
    assert build_pilot_comparative_report(run["out"], out_reuse)["status"] == "PASS"
    assert (out_reuse / "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md").exists()
    assert build_pilot_comparative_report(empty_dir, out_reuse)["status"] == "BLOCKED"
    assert not (out_reuse / "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md").exists()
    assert not (out_reuse / "RESUMO_EXECUTIVO_PILOTO.md").exists()
    assert not (out_reuse / "APENDICE_TECNICO_PILOTO.md").exists()
    assert not (out_reuse / "RASTRO_RELATORIO_PILOTO.csv").exists()
    assert not list((out_reuse / "figuras_piloto").glob("*.png"))


def test_r20_3_unpublishable_rates_excluded_and_no_duplication(run, tmp_path):
    """R20-3: taxas com publicavel=False ou decisão negativa jamais entram em tab04 ou no relatório."""
    from br2026.reporting.pilot_comparative import build_pilot_comparative_report

    a_neg = tmp_path / "a_neg"
    shutil.copytree(run["out"], a_neg)
    dec = json.loads((a_neg / "ecological_decision.json").read_text(encoding="utf-8"))
    dec.update(publicar_matriz_pontual=False, motivos=["teste_reprovado_r20_3"])
    (a_neg / "ecological_decision.json").write_text(json.dumps(dec), encoding="utf-8")

    er = pd.read_csv(a_neg / "ecological_rates.csv")
    er["publicavel"] = False
    er.loc[er.index[:2], "taxa"] = [0.876543, 0.123456]
    # Duplicar com outra especificação para testar proteção contra produto cartesiano
    er_dup = pd.concat([er, er.assign(especificacao="outra_especificacao", taxa=0.876543)], ignore_index=True)
    er_dup.to_csv(a_neg / "ecological_rates.csv", index=False)

    fb_main = pd.read_csv(a_neg / "flow_bounds.csv")
    n_expected = int((fb_main["principal"] == True).sum())  # noqa: E712

    out_neg = tmp_path / "out_neg"
    res = build_pilot_comparative_report(a_neg, out_neg)
    assert res["status"] == "PASS"
    tab04 = pd.read_csv(out_neg / "tabelas_piloto" / "tab04_limites_fluxos_agregados_uf.csv")
    assert len(tab04) == n_expected, "tab04 não pode duplicar linhas de flow_bounds"
    assert "taxa_ecologica_constante" not in tab04.columns
    assert "taxa_ipf_regularizada" not in tab04.columns
    assert (tab04["status_matriz_pontual"] == "NAO_PUBLICADA").all()
    md_neg = (out_neg / "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md").read_text(encoding="utf-8")
    assert "87,65%" not in md_neg and "0,8765" not in md_neg
    assert "teste_reprovado_r20_3" in md_neg


def test_r20_4_associations_scale_10pp_only_for_proportions(run, tmp_path):
    """R20-4: escala +10 p.p. aplica-se a proporções (10 * beta) e mantém NaN para log_contexto."""
    from br2026.reporting.pilot_comparative import build_pilot_comparative_report

    a_ctx = tmp_path / "a_ctx"
    shutil.copytree(run["out"], a_ctx)
    asa = pd.read_csv(a_ctx / "associations_simple_vs_adjusted.csv")
    # Adicionar uma linha sintética de log_contexto para verificar que pp_por_10pp_* fica NaN
    row_log = asa.iloc[[0]].copy()
    row_log["termo"] = "contexto_log_populacao"
    row_log["bloco_termo"] = "contexto"
    row_log["unidade_termo"] = "log_contexto"
    row_log["beta_simples"] = 0.05
    row_log["beta_ajustado"] = 0.04
    asa2 = pd.concat([asa, row_log], ignore_index=True)
    asa2.to_csv(a_ctx / "associations_simple_vs_adjusted.csv", index=False)

    out_ctx = tmp_path / "out_ctx"
    res = build_pilot_comparative_report(a_ctx, out_ctx)
    assert res["status"] == "PASS"
    tab05 = pd.read_csv(out_ctx / "tabelas_piloto" / "tab05_associacoes_perfil_t1_t2.csv")
    prop_rows = tab05[tab05["unidade_termo"] == "proporcao"]
    assert not prop_rows.empty
    assert (prop_rows["pp_por_10pp_ajustado"] - 10.0 * prop_rows["beta_ajustado"]).abs().max() < 1e-9
    log_rows = tab05[tab05["unidade_termo"] == "log_contexto"]
    assert not log_rows.empty
    assert log_rows["pp_por_10pp_simples"].isna().all()
    assert log_rows["pp_por_10pp_ajustado"].isna().all()
    assert "fig04_associacoes_perfil_simples_vs_ajustado.png" in res["figuras"]


def test_turnout_bounds_saldo_no_mesmo_universo_dos_limites(run):
    """Revisão B (27/10): o saldo citado com os limites é o das unidades com aptos iguais."""
    import numpy as np
    from br2026.analysis.metrics import turnout_flow_bounds
    tb = pd.read_csv(run["out"] / "turnout_bounds.csv").iloc[0]
    p = pd.read_parquet(run["out"] / "panel.parquet")
    p = p[(p.status_painel == "PAREADA") & (p.sg_uf != "ZZ")]  # universo territorial, como no analyze
    b = turnout_flow_bounds((p.qt_aptos_t1, p.qt_aptos_t2), p.qt_comparecimento_t1, p.qt_comparecimento_t2)
    ok = b.motivo.isna().to_numpy()
    assert tb.variacao_liquida_comparecimento_com_limites == int(b.variacao_liquida[ok].sum())
    assert tb.variacao_liquida_comparecimento == int(b.variacao_liquida.sum())
    assert np.isclose(tb.entradas_min, b.entradas_min[ok].sum())


def test_r23_2_beta_so_no_apendice_e_conferido_contra_limites(run, tmp_path):
    """R23-2: tab04 só com limites; β e IPF no apêndice, cada célula conferida contra os limites."""
    from br2026.reporting.pilot_comparative import build_pilot_comparative_report
    a = tmp_path / "a"
    shutil.copytree(run["out"], a)
    dec = json.loads((a / "ecological_decision.json").read_text(encoding="utf-8"))
    dec["publicar_matriz_pontual"] = True
    (a / "ecological_decision.json").write_text(json.dumps(dec), encoding="utf-8")
    er = pd.read_csv(a / "ecological_rates.csv")
    sel = er.principal & (er.especificacao == "global_lambda_0.0")
    er.loc[sel, "publicavel"] = True
    fb = pd.read_csv(a / "flow_bounds.csv")
    fb = fb[fb.principal]
    alvo = fb.iloc[0]
    # força um β acima do máximo exato: tem de aparecer como fora dos limites
    er.loc[sel & (er.origem == alvo.origem) & (er.destino == alvo.destino), "taxa"] = alvo.taxa_max + 1e-9
    er.to_csv(a / "ecological_rates.csv", index=False)
    out = tmp_path / "out"
    if not (a / "ecological_ipf_flows.csv").exists():
        pytest.skip("fixture sem fluxos IPF")
    assert build_pilot_comparative_report(a, out)["status"] == "PASS"
    t4 = pd.read_csv(out / "tabelas_piloto" / "tab04_limites_fluxos_agregados_uf.csv")
    assert not {"beta_parametro", "taxa_ecologica_constante", "taxa"} & set(t4.columns)
    t8 = pd.read_csv(out / "tabelas_piloto" / "tab08_modelo_taxas_constantes_apendice.csv")
    linha = t8[(t8.origem == alvo.origem) & (t8.destino == alvo.destino)].iloc[0]
    assert not bool(linha.beta_dentro_dos_limites)
    assert t8.ipf_dentro_dos_limites.all()
    md = (out / "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md").read_text(encoding="utf-8")
    assert "beta_parametro" not in md and "A.5 Modelo" not in md      # β só no apêndice
    assert "## A.5 Modelo de taxas constantes" in (out / "APENDICE_TECNICO_PILOTO.md").read_text(encoding="utf-8")


def test_r27_1_tolerancia_ipf_fixa_nao_cresce_com_o_erro(tmp_path):
    """R27-1: com erro marginal grande e muitas unidades, um fluxo 2 votos fora do limite continua
    fora; "dentro dos limites exatos" e "aceito com tolerância" são colunas distintas."""
    from br2026.reporting.pilot_comparative import IPF_TOLERANCIA_VOTOS, _build_model_appendix_table
    pd.DataFrame({"origem": ["A", "A"], "destino": ["X", "Y"], "fluxo": [102.0, 0.3],
                  "erro_marginal_max_unidade": [0.04, 0.04]}).to_csv(tmp_path / "ecological_ipf_flows.csv", index=False)
    merged = pd.DataFrame({"origem": ["A", "A"], "destino": ["X", "Y"], "taxa_min": [0.0, 0.0],
                           "taxa_max": [1.0, 1.0], "fluxo_min": [0.0, 0.0], "fluxo_max": [100.0, 0.0],
                           "beta_parametro": [0.5, 0.0]})
    t = _build_model_appendix_table(tmp_path, merged, {"unidades": 500000}).set_index("destino")
    assert IPF_TOLERANCIA_VOTOS == 0.5
    assert not t.at["X", "ipf_dentro_dos_limites"] and not t.at["X", "ipf_dentro_dos_limites_exatos"]
    assert t.at["Y", "ipf_dentro_dos_limites"] and not t.at["Y", "ipf_dentro_dos_limites_exatos"]
    assert (t.ipf_conservacao_marginais == "aproximada").all()
