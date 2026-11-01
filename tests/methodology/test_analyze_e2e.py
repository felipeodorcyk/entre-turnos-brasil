"""Ponta a ponta OFFLINE em staging sintético: panel → analyze.

Verifica orquestração, rastreabilidade e regras, não resultados empíricos.
"""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from br2026.analysis.run import run_analyze
from br2026.config import load_config
from br2026.contract import CONTRACT_VERSION
from br2026.panel.run import run_panel

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "synth_staging.py"
_spec = importlib.util.spec_from_file_location("synth_staging", FIX)
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("e2e")
    staging, analytics = root / "staging", root / "analytics"
    truth = synth.make_staging(staging)
    cfg = load_config()
    cfg["ecological"]["bootstrap_reps"] = 20
    # estes testes descrevem o caso sem confirmação da premissa e do relógio (O-R3); o caso
    # confirmado (handoff 29) está em test_timezone_inference_promoted_when_confirmed
    cfg["closure_tz"].update(premissa_horario_unico_confirmada=False, semantica_relogio_validada=False)
    p = run_panel(staging, analytics, cfg)
    a = run_analyze(staging, analytics, cfg)
    status = pd.read_csv(analytics / "analysis_status.csv")
    return {"panel": p, "analyze": a, "out": analytics, "truth": truth, "status": status}


def test_panel_pass_and_classifications(run):
    assert run["panel"]["status"] == "PASS"
    panel = pd.read_parquet(run["out"] / "panel.parquet")
    assert (panel.status_painel == "EXCLUIDA_AUSENTE_T2").sum() == 1
    assert (panel.tipo_unidade == "AGREGADO_SECOES").sum() == 1
    assert panel.flag_aptos_divergente.sum() > 0


def test_analyze_runs_and_records_every_block(run):
    assert run["analyze"]["status"] == "PASS"
    st = run["status"]
    assert set(st.status) <= {"PASS", "NAO_ESTIMADO", "BLOCKED", "EXPLORATORIO"}
    assert (st.motivo.fillna("") != "").loc[st.status != "PASS"].all()
    man = json.loads((run["out"] / "analysis_manifest.json").read_text(encoding="utf-8"))
    for name in man["saidas_linhas"]:
        assert (run["out"] / name).exists(), name
    assert len(man["insumos_sha256"]) >= 4 and man["contract_version"] == CONTRACT_VERSION


def test_exterior_kept_separate(run):
    m = pd.read_csv(run["out"] / "metrics_aggregate.csv")
    assert {"pareado_territorial", "pareado_exterior", "pareado_total"} <= set(m.universo)
    n = m.groupby("universo").n_unidades.first()
    assert n["pareado_total"] == n["pareado_territorial"] + n["pareado_exterior"]


def test_contributions_sum_to_territorial_change(run):
    m = pd.read_csv(run["out"] / "metrics_aggregate.csv")
    d = m[(m.universo == "pareado_territorial") & (m.metrica == "delta_share_lula_validos")].valor.iloc[0]
    c = pd.read_csv(run["out"] / "contributions_uf_lula.csv")
    assert c.contribuicao_delta_share.sum() == pytest.approx(d, abs=1e-14)


def test_flow_outputs_bounds_and_labels(run):
    b = pd.read_csv(run["out"] / "flow_bounds.csv")
    # O sintético só aumenta aptos: há entrada de cadastro e nenhuma saída.
    main = b[b.principal]
    assert "ENTRADA_CADASTRO_CENARIO" in set(main.origem) and "SAIDA_CADASTRO_CENARIO" not in set(main.destino)
    assert set(b.cenario_populacao) == {"rotatividade_minima", "rotatividade_0.005_aptos",
                                        "rotatividade_0.02_aptos"}
    assert "aptos_iguais" in set(b.universo_fluxo)
    assert b.condicao.str.contains("não são fluxos observados").all()
    assert (b.fluxo_min <= b.fluxo_max).all()
    assert b.limiar_candidato.nunique() == 2 and main.limiar_candidato.nunique() == 1
    r = pd.read_csv(run["out"] / "ecological_rates.csv")
    assert r.rotulo.str.contains("não é voto individual").all()
    # taxas nas linhas somam 1 em cada especificação
    s = r.groupby(["limiar_candidato", "cenario_populacao", "universo_fluxo", "especificacao",
                   "origem"]).taxa.sum()
    np.testing.assert_allclose(s, 1, atol=1e-9)
    dec = json.loads((run["out"] / "ecological_decision.json").read_text(encoding="utf-8"))
    assert dec["publicar_limites"] is True
    assert dec["transicoes_individuais_identificadas"] is False
    assert not r.transicoes_individuais_identificadas.any()
    assert r.publicavel.any() == dec["publicar_matriz_pontual"]
    assert dec["convergiu"], "otimização deve convergir no sintético bem identificado"
    ipf = pd.read_csv(run["out"] / "ecological_ipf_flows.csv")
    assert ipf.erro_marginal_max_unidade.max() < 1e-6
    boot = pd.read_csv(run["out"] / "ecological_bootstrap.csv")
    assert boot.rotulo.str.contains("condicional ao modelo").all()


def test_ipf_flows_inside_bounds(run):
    b = pd.read_csv(run["out"] / "flow_bounds.csv")
    b = b[b.principal].set_index(["origem", "destino"])
    ipf = pd.read_csv(run["out"] / "ecological_ipf_flows.csv").set_index(["origem", "destino"])
    j = ipf.join(b, how="inner")
    assert len(j) == len(ipf)
    assert ((j.fluxo >= j.fluxo_min - 1e-6) & (j.fluxo <= j.fluxo_max + 1e-6)).all()


def test_associations_reference_and_weights(run):
    cfg = load_config()
    a = pd.read_csv(run["out"] / "associations.csv")
    assert not a.empty
    comp = a[a.bloco_termo == "composicao"]
    assert (comp.referencia == "ABSTENCAO").all() and "ABSTENCAO" not in set(a.termo)
    prof = a[a.bloco_termo == "perfil"]
    assert not prof.empty
    for dim, ref in cfg["profile"]["referencias"].items():
        assert f"perfil_{dim.lower()}_{ref}" not in set(a.termo)
        assert (prof[prof.termo.str.startswith(f"perfil_{dim.lower()}_")].referencia == ref).all()
    assert {"aptos_t1", "validos_t1", "sem_pesos"} <= set(a.pesos)
    assert set(a.familia) == {"ef_municipio", "ef_uf"}
    assert {"composicao", "composicao+perfil"} <= set(a.especificacao)
    # Mesmo universo para todas as especificações dentro de cada família.
    assert (a.groupby("familia").universo_familia.nunique() == 1).all()
    assert a.rotulo.str.contains("não características de quem votou").all()
    assert (a.inf <= a.sup).all()
    st = run["status"].set_index("bloco")
    # O-R6: variáveis definidas; sem staging municipal_context o bloco é BLOCKED, não concluído.
    assert st.loc["associacao:ef_uf:composicao+perfil+contexto", "status"] == "BLOCKED"


def test_profile_integration_marginals(run):
    cov = pd.read_csv(run["out"] / "profile_coverage.csv")
    assert cov[cov.motivo_exclusao == "ELEGIVEL"].unidades.sum() > 0
    assert not (cov.motivo_exclusao == "MARGINAIS_INCOERENTES").any()
    diag = pd.read_parquet(run["out"] / "profile_unit_diagnostics.parquet")
    assert diag.motivo_exclusao.notna().all()
    # Toda unidade pareada territorial aparece na cobertura, elegível ou com motivo.
    panel = pd.read_parquet(run["out"] / "panel.parquet")
    assert cov.unidades.sum() == ((panel.status_painel == "PAREADA") & (panel.sg_uf != "ZZ")).sum()
    units = pd.read_parquet(run["out"] / "profile_units.parquet").set_index("id_unidade")
    for dim in ("genero", "faixa_etaria", "grau_escolaridade"):
        cols = [c for c in units if c.startswith(f"perfil_{dim}_")]
        np.testing.assert_allclose(units[cols].sum(axis=1), 1.0, atol=1e-12)
    assert "perfil_faixa_etaria_desconhecido" in units.columns


def test_timezone_inference_is_exploratory_not_main(run):
    """O-R3: premissa e relógio não confirmados → inferência só exploratória."""
    off = pd.read_csv(run["out"] / "closure_tz_offsets.csv", dtype={"cd_municipio_tse": str})
    assert set(off.sg_uf) == {"AM", "AC"}  # SP é documentado: não entra na inferência
    assert (off[off.sg_uf == "AM"].offset_h == 1).all() and (off[off.sg_uf == "AC"].offset_h == 2).all()
    st = run["status"].set_index("bloco")
    assert st.loc["horarios:inferencia_fuso", "status"] == "EXPLORATORIO"
    assert not st.loc[st.index.str.startswith("horarios:inferencia"), "status"].eq("PASS").any()
    s = pd.read_csv(run["out"] / "closure_sections.csv", dtype={"nr_secao": str})
    inferred = s.sg_uf.isin(["AC", "AM"])
    assert (s[inferred].faixa == "INVALIDO").all(), "fuso inferido não pode entrar na análise principal"
    assert (s[~inferred].faixa != "INVALIDO").any()
    counts = pd.read_csv(run["out"] / "closure_band_counts.csv")
    assert set(counts.papel) == {"principal", "sensibilidade", "exploratorio"}
    assert set(counts[counts.papel == "principal"].variante) == {"documental"}
    expl = counts[counts.variante == "exploratorio_inferido"]
    assert expl[expl.faixa != "INVALIDO"].secoes.sum() > counts[(counts.variante == "documental")
                                                                & (counts.faixa != "INVALIDO")].secoes.sum()
    cov = pd.read_csv(run["out"] / "closure_coverage.csv")
    assert (cov.variante_principal == "documental").all() and cov.INFERIDO.sum() > 0


def test_closure_main_comparisons_documental_only(run):
    adj = pd.read_csv(run["out"] / "closure_adjusted.csv")
    assert set(adj.variante) == {"documental"} and set(adj.papel) == {"principal"}
    assert "ANTES_17H" not in set(adj.faixa) and (adj.referencia == "17H00_17H15").all()
    assert adj.loc[adj.status != "PASS", "motivo"].fillna("").astype(str).str.len().gt(0).all()
    ok = adj[adj.status == "PASS"]
    assert (ok.municipios_com_ambas >= load_config()["closure"]["suporte_min_municipios"]).all()
    expl = pd.read_csv(run["out"] / "closure_exploratorio_adjusted.csv")
    assert set(expl.papel) == {"exploratorio"}
    assert expl.loc[expl.status == "PASS", "rotulo"].str.startswith("EXPLORATÓRIO").all()
    st = run["status"].set_index("bloco")
    concl = st.loc["horarios:conclusao_principal", "status"]
    assert concl == ("PASS" if (ok.papel == "principal").any() else "BLOCKED")
    raw = pd.read_csv(run["out"] / "closure_raw_deltas.csv")
    assert {"faixa_t1", "faixa_t2", "transicao"} == set(raw.agrupamento)


def _rerun(run, tmp_path, cfg_update=None, closure_update=None):
    import shutil
    staging = tmp_path / "staging"
    shutil.copytree(run["out"].parent / "staging", staging)
    if closure_update is not None:
        cl = pd.read_parquet(staging / "closure.parquet")
        closure_update(cl).to_parquet(staging / "closure.parquet", index=False)
    cfg = load_config()
    cfg["ecological"]["bootstrap_reps"] = 5
    # base sem confirmação (O-R3); cada teste liga só o que quer examinar
    cfg["closure_tz"].update({"premissa_horario_unico_confirmada": False, "fonte_premissa": "",
                             "semantica_relogio_validada": False, "fonte_validacao_relogio": ""})
    for sec, kv in (cfg_update or {}).items():
        cfg[sec].update(kv)
    out = tmp_path / "analytics"
    run_panel(staging, out, cfg)
    run_analyze(staging, out, cfg)
    return out, pd.read_csv(out / "analysis_status.csv").set_index("bloco")


def test_without_documented_closures_main_conclusion_blocked_and_report_says_so(run, tmp_path):
    def undocument(cl):
        cl = cl.copy()
        cl["fuso_documentado"] = None
        cl["motivo_ausencia"] = "FUSO_NAO_DOCUMENTADO"
        return cl
    out, st = _rerun(run, tmp_path, closure_update=undocument)
    assert st.loc["horarios:conclusao_principal", "status"] == "BLOCKED"
    assert "closure_coverage.csv" in st.loc["horarios:conclusao_principal", "motivo"]
    adj = pd.read_csv(out / "closure_adjusted.csv")
    assert not (adj.status == "PASS").any()
    # Resultados eleitorais independentes do horário continuam produzidos.
    assert st.loc["descricao:pareado_territorial", "status"] == "PASS"
    from br2026.reporting.build import build_report
    build_report(out, tmp_path / "rep")
    text = (tmp_path / "rep" / "relatorio.md").read_text(encoding="utf-8")
    assert "Conclusão temporal principal: **BLOCKED**" in text
    assert "não é apresentada" in text and "17H15_18H" not in text.split("## Horários")[1].split("## Blocos")[0]


def test_premise_alone_does_not_promote_inference(run, tmp_path):
    _, st = _rerun(run, tmp_path, {"closure_tz": {"premissa_horario_unico_confirmada": True,
                                                  "fonte_premissa": "https://exemplo.invalid/norma"}})
    assert st.loc["horarios:inferencia_fuso", "status"] == "EXPLORATORIO"


def test_both_confirmations_promote_inference(run, tmp_path):
    out, st = _rerun(run, tmp_path, {"closure_tz": {
        "premissa_horario_unico_confirmada": True, "fonte_premissa": "https://exemplo.invalid/norma",
        "semantica_relogio_validada": True, "fonte_validacao_relogio": "https://exemplo.invalid/relogio"}})
    assert st.loc["horarios:inferencia_fuso", "status"] == "PASS"
    cov = pd.read_csv(out / "closure_coverage.csv")
    assert (cov.variante_principal == "exploratorio_inferido").all()


def test_analyze_blocked_without_panel(tmp_path):
    r = run_analyze(tmp_path / "staging", tmp_path / "analytics")
    assert r["status"] == "BLOCKED"


def test_analyze_refuses_unreconciled_panel(run, tmp_path):
    import shutil
    out = tmp_path / "a"
    shutil.copytree(run["out"], out)
    rec = pd.read_csv(out / "panel_reconciliation.csv")
    rec.loc[0, "dif"] = 1
    rec.to_csv(out / "panel_reconciliation.csv", index=False)
    r = run_analyze(tmp_path / "unused", out)
    assert r["status"] == "BLOCKED" and "reconciliação" in r["motivo"]


def test_timezone_inference_promoted_when_confirmed(tmp_path):
    """Handoff 29: com premissa legal e relógio validados com fonte, a inferência pela abertura é a
    variante principal; o documental vira sensibilidade e AC/AM entram com o fuso inferido."""
    staging, analytics = tmp_path / "staging", tmp_path / "analytics"
    synth.make_staging(staging)
    cfg = load_config()
    cfg["ecological"]["bootstrap_reps"] = 5
    cfg["closure_tz"].update(premissa_horario_unico_confirmada=True, fonte_premissa="norma",
                             semantica_relogio_validada=True, fonte_validacao_relogio="validação")
    run_panel(staging, analytics, cfg)
    run_analyze(staging, analytics, cfg)
    counts = pd.read_csv(analytics / "closure_band_counts.csv")
    assert set(counts[counts.papel == "principal"].variante) == {"exploratorio_inferido"}
    assert "sensibilidade" in set(counts[counts.variante == "documental"].papel)
    s = pd.read_csv(analytics / "closure_sections.csv", dtype={"nr_secao": str})
    assert (s[s.sg_uf.isin(["AC", "AM"])].faixa != "INVALIDO").any()
    # sem fonte, a confirmação não vale: volta a ser exploratória
    cfg["closure_tz"]["fonte_premissa"] = ""
    run_analyze(staging, analytics, cfg)
    counts = pd.read_csv(analytics / "closure_band_counts.csv")
    assert set(counts[counts.papel == "principal"].variante) == {"documental"}
