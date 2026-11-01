"""Relatório comparativo do piloto (AC, RS e MG — 1º e 2º turnos), figuras e contraste público (Handoffs 19 e 22).

Gera:
  * `RELATORIO_COMPARATIVO_PILOTO_T1_T2.md`: Relatório principal + Contraste Imprensa/Alegações + Apêndice Técnico
  * `figuras_piloto/*.png`: Figuras estáticas com padrão editorial executivo-técnico
  * `tabelas_piloto/*.csv`: Tabelas finais de suporte citadas no texto e nas figuras
  * `RASTRO_RELATORIO_PILOTO.csv`: Rastro integral de cada número citado no texto

Regras estritas de validação pré-publicação (`R20-2`, `R20-3`, `R20-4`, `R20-5`):
  * Se `pares_entre_turnos` não for explicitamente `True`, ou se faltarem as 3 UFs do piloto (`AC`, `RS`, `MG`),
    os 2 turnos reconciliados (`dif == 0`), status `PASS` no painel entre turnos, ou as tabelas/colunas
    essenciais com denominadores estritamente positivos, recusa emitir o relatório e devolve `status="BLOCKED"`,
    removendo artefatos comparativos obsoletos do diretório de saída.
  * Nenhuma taxa ecológica com `publicavel == False` ou `publicar_matriz_pontual == False` entra em tabelas,
    figuras ou texto (`R20-3`).
  * A transformação de escala `+10 p.p.` aplica-se exclusivamente a variáveis de proporção (`composicao` e
    `perfil`), nunca a controles municipais em log (`R20-4`).
  * `matplotlib` é importado sob demanda apenas após a aprovação das pré-condições (`R20-5`).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from br2026.reporting.build import _read
from br2026.reporting.report import forbidden_matches

PILOT_UFS = ("AC", "RS", "MG")
REQUIRED_METRICS_UF_COLS = {
    "sg_uf", "n_unidades",
    "qt_aptos_t1", "qt_aptos_t2",
    "qt_comparecimento_t1", "qt_comparecimento_t2",
    "qt_abstencoes_t1", "qt_abstencoes_t2",
    "qt_votos_validos_t1", "qt_votos_validos_t2",
    "qt_votos_brancos_t1", "qt_votos_brancos_t2",
    "qt_votos_nulos_t1", "qt_votos_nulos_t2",
    "qt_lula_t1", "qt_lula_t2",
    "qt_flavio_t1", "qt_flavio_t2",
    "share_lula_validos_t1", "share_lula_validos_t2", "delta_share_lula_validos",
    "share_flavio_validos_t1", "share_flavio_validos_t2", "delta_share_flavio_validos",
    "margem_lula_flavio_validos_t1", "margem_lula_flavio_validos_t2", "delta_margem_lula_flavio_validos",
    "comparecimento_aptos_t1", "comparecimento_aptos_t2", "delta_comparecimento_aptos",
    "abstencao_aptos_t1", "abstencao_aptos_t2", "delta_abstencao_aptos",
}
POSITIVE_DENOMINATOR_COLS = (
    "qt_aptos_t1", "qt_aptos_t2",
    "qt_comparecimento_t1", "qt_comparecimento_t2",
    "qt_votos_validos_t1", "qt_votos_validos_t2",
)
IPF_TOLERANCIA_VOTOS = 0.5   # tolerância fixa de publicação do IPF, em votos do fluxo agregado (R27-1)
FLOW_JOIN_KEYS = [
    "limiar_candidato", "cenario_populacao", "universo_fluxo", "principal", "origem", "destino"
]

# Paleta editorial consistente com o padrão visual de referência
PALETTE = {
    "navy": "#1e3a5f",
    "lula": "#c0392b",
    "flavio": "#2980b9",
    "terceiros": "#6c7a89",
    "nao_validos": "#7f8c8d",
    "abstencao": "#d35400",
    "ajustado": "#16a085",
    "simples": "#8e44ad",
    "grid": "#dce1e7",
    "bg_box": "#f8f9fa",
}

# Handoff 26: o mesmo gerador serve ao piloto e ao país; o escopo decide nomes de arquivos e pastas.
NATIONAL_UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
                "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO")
ESCOPOS = {
    "piloto": {"figuras": "figuras_piloto", "tabelas": "tabelas_piloto",
               "rastro": "RASTRO_RELATORIO_PILOTO.csv",
               "documentos": ("RESUMO_EXECUTIVO_PILOTO.md", "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md",
                              "APENDICE_TECNICO_PILOTO.md"),
               "principal": "RELATORIO_COMPARATIVO_PILOTO_T1_T2.md"},
    "nacional": {"figuras": "figuras_nacional", "tabelas": "tabelas_nacional",
                 "rastro": "RASTRO_RELATORIO_NACIONAL.csv",
                 "documentos": ("RESUMO_EXECUTIVO_NACIONAL.md", "RELATORIO_NACIONAL_T1_T2.md",
                                "APENDICE_TECNICO_NACIONAL.md"),
                 "principal": "RELATORIO_NACIONAL_T1_T2.md"},
}


def escopo_do_analytics(analytics: Path) -> str:
    """`nacional` quando a cobertura tem as 27 UFs; senão `piloto`."""
    cov = _read(analytics, "coverage_uf.csv")
    ufs = set(cov["sg_uf"].astype(str)) if not cov.empty and "sg_uf" in cov.columns else set()
    return "nacional" if set(NATIONAL_UFS) <= ufs else "piloto"


def _cleanup_stale_outputs(out: Path, escopo: str = "piloto") -> None:
    """Remove artefatos comparativos anteriores do escopo quando uma execução é bloqueada (`R20-2`)."""
    e = ESCOPOS[escopo]
    for fname in (*e["documentos"], e["rastro"]):
        p = out / fname
        if p.exists():
            p.unlink(missing_ok=True)
    fig_dir = out / e["figuras"]
    if fig_dir.exists():
        for fp in fig_dir.glob("*.png"):
            fp.unlink(missing_ok=True)
    tab_dir = out / e["tabelas"]
    if tab_dir.exists():
        for tp in tab_dir.glob("tab*.csv"):
            tp.unlink(missing_ok=True)


def _validate_comparative_inputs(
    analytics: Path, expected_ufs: tuple[str, ...] | None = None
) -> tuple[str | None, dict, list[str]]:
    """Valida todas as pré-condições de M2, escopo, reconciliação e tabelas (`R20-2`)."""
    man_path = analytics / "analysis_manifest.json"
    if not man_path.exists():
        return "analysis_manifest.json ausente; rode `analyze` antes", {}, []
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"analysis_manifest.json ilegível ({exc})", {}, []
    if not isinstance(man, dict) or man.get("pares_entre_turnos") is not True:
        return "analysis_manifest.json sem `pares_entre_turnos == True`", man if isinstance(man, dict) else {}, []

    st_all = _read(analytics, "analysis_status.csv")
    if st_all.empty or not {"bloco", "status"} <= set(st_all.columns):
        return "analysis_status.csv ausente ou sem colunas obrigatórias", man, []
    if (st_all["status"] == "FAIL").any():
        failed_blocks = list(st_all.loc[st_all["status"] == "FAIL", "bloco"])
        return f"analysis_status.csv contém bloco(s) com FAIL: {failed_blocks}", man, []
    pares = st_all[st_all["bloco"] == "t1:painel_entre_turnos"]
    if pares.empty or not (pares["status"] == "PASS").all():
        motivo = (
            str(pares.iloc[0].get("motivo") or "")
            if not pares.empty
            else "bloco t1:painel_entre_turnos ausente em analysis_status.csv"
        )
        return f"painel entre turnos não aprovado ({motivo})", man, []

    rec = _read(analytics, "panel_reconciliation.csv")
    if rec.empty or not {"nr_turno", "metrica", "status_painel", "dif"} <= set(rec.columns):
        return "panel_reconciliation.csv ausente ou incompleto", man, []
    turnos_rec = set(pd.to_numeric(rec["nr_turno"], errors="coerce").dropna().astype(int))
    if turnos_rec != {1, 2}:
        return f"panel_reconciliation.csv não cobre ambos os turnos (observado: {sorted(turnos_rec)})", man, []
    dif_num = pd.to_numeric(rec["dif"], errors="coerce")
    if dif_num.isna().any() or (dif_num != 0).any():
        return "panel_reconciliation.csv apresenta dif != 0 ou valor inválido", man, []

    cov = _read(analytics, "coverage_uf.csv")
    if cov.empty or not {"sg_uf", "unidades_incluida", "unidades_excluida"} <= set(cov.columns):
        return "coverage_uf.csv ausente ou incompleto", man, []
    ufs_cov = {u.strip() for u in cov["sg_uf"].astype(str) if u.strip() and u.strip() not in ("ZZ", "TOTAL")}
    if expected_ufs is not None:
        if not set(expected_ufs) <= ufs_cov:
            return f"coverage_uf.csv não contém as UFs esperadas {expected_ufs} (observado: {sorted(ufs_cov)})", man, []
        ufs_list = list(expected_ufs)
    elif set(PILOT_UFS) <= ufs_cov:
        ufs_list = list(PILOT_UFS)
    elif len(ufs_cov) >= 3:
        ufs_list = sorted(ufs_cov)
    else:
        return f"coverage_uf.csv não contém pelo menos 3 UFs territoriais (observado: {sorted(ufs_cov)})", man, []

    cov_pilot = cov[cov["sg_uf"].isin(ufs_list)]
    inc_num = pd.to_numeric(cov_pilot["unidades_incluida"], errors="coerce")
    if len(cov_pilot) < len(ufs_list) or inc_num.isna().any() or (inc_num <= 0).any():
        return "coverage_uf.csv tem UF sem unidades pareadas incluídas", man, []

    m_uf = _read(analytics, "metrics_uf.csv")
    if m_uf.empty:
        return "metrics_uf.csv ausente ou vazio", man, []
    missing_m_cols = sorted(REQUIRED_METRICS_UF_COLS - set(m_uf.columns))
    if missing_m_cols:
        return f"metrics_uf.csv sem colunas obrigatórias: {missing_m_cols}", man, []
    expected_uf_rows = set(ufs_list) | {"TOTAL"}
    if not expected_uf_rows <= set(m_uf["sg_uf"].astype(str)):
        return f"metrics_uf.csv não contém todas as linhas {sorted(expected_uf_rows)}", man, []
    m_sub = m_uf[m_uf["sg_uf"].isin(expected_uf_rows)]
    num_cols = sorted(REQUIRED_METRICS_UF_COLS - {"sg_uf"})
    for col in num_cols:
        s_val = pd.to_numeric(m_sub[col], errors="coerce")
        if s_val.isna().any() or not np.isfinite(s_val.to_numpy(dtype=float)).all():
            return f"metrics_uf.csv contém valor ausente ou não finito em {col}", man, []
    for dcol in POSITIVE_DENOMINATOR_COLS:
        s_den = pd.to_numeric(m_sub[dcol], errors="coerce")
        if (s_den <= 0).any():
            return f"metrics_uf.csv contém denominador não positivo em {dcol}", man, []

    for cand_file in ("contributions_municipio_lula.csv", "contributions_municipio_flavio.csv"):
        df_c = _read(analytics, cand_file)
        req_c = {"sg_uf", "cd_municipio_tse", "contribuicao_delta_share", "efeito_participacao", "efeito_peso"}
        if df_c.empty or not req_c <= set(df_c.columns):
            return f"{cand_file} ausente ou sem colunas obrigatórias", man, []
        if not set(ufs_list) <= set(df_c["sg_uf"].astype(str)):
            return f"{cand_file} não cobre todas as UFs {ufs_list}", man, []

    sens = _read(analytics, "panel_aggregation_sensitivity.csv")
    req_s = {"nivel_agregacao", "n_grupos", "delta_share_lula_validos", "delta_share_flavio_validos"}
    if sens.empty or not req_s <= set(sens.columns):
        return "panel_aggregation_sensitivity.csv ausente ou incompleto", man, []

    fb = _read(analytics, "flow_bounds.csv")
    req_fb = set(FLOW_JOIN_KEYS) | {"taxa_min", "taxa_max", "largura_taxa", "pouco_informativo"}
    if fb.empty or not req_fb <= set(fb.columns):
        return "flow_bounds.csv ausente ou sem colunas obrigatórias", man, []
    fb_main = fb[fb["principal"] == True]  # noqa: E712
    if fb_main.empty:
        return "flow_bounds.csv sem linhas do cenário principal (`principal == True`)", man, []
    if fb_main.duplicated(subset=FLOW_JOIN_KEYS).any():
        return "flow_bounds.csv contém chaves duplicadas no cenário principal", man, []

    dec_path = analytics / "ecological_decision.json"
    if not dec_path.exists():
        return "ecological_decision.json ausente", man, []
    try:
        dec = json.loads(dec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"ecological_decision.json ilegível ({exc})", man, []
    if not isinstance(dec, dict) or not isinstance(dec.get("publicar_matriz_pontual"), bool):
        return "ecological_decision.json sem booleano `publicar_matriz_pontual`", man, []

    assoc_sa = _read(analytics, "associations_simple_vs_adjusted.csv")
    req_assoc = {
        "familia", "desfecho", "recorte", "pesos", "termo", "bloco_termo",
        "beta_simples", "inf_simples", "sup_simples",
        "beta_ajustado", "inf_ajustado", "sup_ajustado",
        "n", "grupos_cluster",
    }
    if assoc_sa.empty or not req_assoc <= set(assoc_sa.columns):
        return "associations_simple_vs_adjusted.csv ausente ou sem colunas obrigatórias", man, []

    return None, man, ufs_list


def _normalize_associations_table(assoc_sa: pd.DataFrame) -> pd.DataFrame:
    """Garante colunas de unidade e escala `+10 p.p.` apenas para proporções (`R20-4`)."""
    df = assoc_sa.copy()
    if "especificacao_ajustada" not in df.columns:
        df["especificacao_ajustada"] = "multivariada_ajustada"
    if "referencia" not in df.columns:
        df["referencia"] = ""
    if "unidade_termo" not in df.columns:
        df["unidade_termo"] = np.where(
            df["bloco_termo"].isin(["composicao", "perfil"]), "proporcao", "log_contexto"
        )
    is_prop = df["unidade_termo"].astype(str) == "proporcao"
    scale = np.where(is_prop, 10.0, np.nan)
    # Sempre recalcula / valida que log_contexto fica NaN na escala +10 p.p.
    df["pp_por_10pp_simples"] = pd.to_numeric(df["beta_simples"], errors="coerce") * scale
    df["pp_por_10pp_inf_simples"] = pd.to_numeric(df["inf_simples"], errors="coerce") * scale
    df["pp_por_10pp_sup_simples"] = pd.to_numeric(df["sup_simples"], errors="coerce") * scale
    df["pp_por_10pp_ajustado"] = pd.to_numeric(df["beta_ajustado"], errors="coerce") * scale
    df["pp_por_10pp_inf_ajustado"] = pd.to_numeric(df["inf_ajustado"], errors="coerce") * scale
    df["pp_por_10pp_sup_ajustado"] = pd.to_numeric(df["sup_ajustado"], errors="coerce") * scale
    # Escala editorial para todos os termos (handoff 37, item 9): proporção → p.p. por +10 p.p.;
    # contexto em log → p.p. por duplicação (β·ln 2·100). Coeficiente ausente continua ausente e é
    # marcado como "não estimado", distinto de "sem escala editorial".
    is_log = df["unidade_termo"].astype(str) == "log_contexto"
    fator = np.where(is_prop, 10.0, np.where(is_log, 100.0 * np.log(2.0), np.nan))
    df["escala_editorial"] = np.where(is_prop, "p.p. por +10 p.p.",
                                      np.where(is_log, "p.p. por duplicação", "sem escala editorial"))
    for lado in ("simples", "ajustado"):
        for pre, col in (("efeito_", "beta_"), ("efeito_inf_", "inf_"), ("efeito_sup_", "sup_")):
            df[f"{pre}{lado}"] = pd.to_numeric(df[f"{col}{lado}"], errors="coerce") * fator
    df["situacao_estimativa"] = np.where(pd.to_numeric(df["beta_ajustado"], errors="coerce").isna(),
                                         "não estimado", "estimado")
    return df


def _build_accounting_and_100pct_table(m_uf: pd.DataFrame, demais: pd.DataFrame) -> pd.DataFrame:
    """Constrói `tab07_identidade_saldos_e_teste_100pct.csv` (Handoff 22, Etapa 3).

    Verifica contabilmente:
      * ΔL + ΔF = O1 + ΔV
      * ΔV = ΔC - ΔB - ΔN = ΔE - ΔA - ΔB - ΔN
    E traz, por UF e no total do piloto, o teste "100% dos demais candidatos do T1 → Lula"
    calculado em `analyze` (`flow_demais_para_lula.csv`) com limites de Fréchet conjuntos da
    origem agregada, unidade a unidade:
      * possível: o limite superior alcança 100% dos votos dos demais candidatos;
      * necessário: o limite inferior já exige 100%;
      * observado: sempre `NAO_IDENTIFICAVEL_POR_SIGILO` (voto secreto).
    """
    lim = demais.set_index(demais["sg_uf"].astype(str)) if not demais.empty else pd.DataFrame()

    rows = []
    for _, r in m_uf.iterrows():
        uf = str(r["sg_uf"])
        l1, l2 = int(r["qt_lula_t1"]), int(r["qt_lula_t2"])
        f1, f2 = int(r["qt_flavio_t1"]), int(r["qt_flavio_t2"])
        v1, v2 = int(r["qt_votos_validos_t1"]), int(r["qt_votos_validos_t2"])
        c1, c2 = int(r["qt_comparecimento_t1"]), int(r["qt_comparecimento_t2"])
        b1, b2 = int(r["qt_votos_brancos_t1"]), int(r["qt_votos_brancos_t2"])
        n1, n2 = int(r["qt_votos_nulos_t1"]), int(r["qt_votos_nulos_t2"])
        e1, e2 = int(r["qt_aptos_t1"]), int(r["qt_aptos_t2"])
        a1, a2 = int(r["qt_abstencoes_t1"]), int(r["qt_abstencoes_t2"])

        o1 = v1 - l1 - f1
        dl = l2 - l1
        df_ = f2 - f1
        dv = v2 - v1
        dc = c2 - c1
        db = b2 - b1
        dn = n2 - n1
        de = e2 - e1
        da = a2 - a1

        id_saldos_dif = (dl + df_) - (o1 + dv)
        id_validos_comp_dif = dv - (dc - db - dn)
        id_validos_aptos_dif = dv - (de - da - db - dn)

        denom_ganho = dl + df_
        razao_dl_ganho_liq = (dl / denom_ganho) if denom_ganho > 0 else np.nan
        razao_dl_o1 = (dl / o1) if o1 > 0 else np.nan

        rows.append({
            "sg_uf": uf,
            "o1_demais_candidatos_t1": o1,
            "delta_lula": dl,
            "delta_flavio": df_,
            "delta_validos": dv,
            "delta_comparecimento": dc,
            "delta_brancos": db,
            "delta_nulos": dn,
            "delta_aptos": de,
            "delta_abstencoes": da,
            "identidade_saldos_dif": id_saldos_dif,
            "identidade_validos_comp_dif": id_validos_comp_dif,
            "identidade_validos_aptos_dif": id_validos_aptos_dif,
            "razao_delta_lula_sobre_o1": razao_dl_o1,
            "razao_delta_lula_sobre_soma_deltas": razao_dl_ganho_liq,
            "limite_min_demais_para_lula": lim.at[uf, "taxa_min"] if uf in lim.index else np.nan,
            "limite_max_demais_para_lula": lim.at[uf, "taxa_max"] if uf in lim.index else np.nan,
            "unidades_que_impedem_100pct": lim.at[uf, "unidades_que_impedem_100pct"] if uf in lim.index else np.nan,
            # votos dos demais que não cabem nos votos de Lula do 2º turno, somando as unidades (exato;
            # a taxa máxima em % pode arredondar para 100% mesmo quando a transferência integral é impossível)
            "votos_demais_que_nao_cabem_em_lula": (lim.at[uf, "qt_demais_t1"] - lim.at[uf, "fluxo_max"]
                                                   if uf in lim.index else np.nan),
            "teste_100pct_possivel": (bool(lim.at[uf, "teste_100pct_possivel"]) if uf in lim.index
                                      else "NAO_AVALIADO"),
            "teste_100pct_necessario": (bool(lim.at[uf, "teste_100pct_necessario"]) if uf in lim.index
                                        else "NAO_AVALIADO"),
            "teste_100pct_observado": "NAO_IDENTIFICAVEL_POR_SIGILO",
        })
    return pd.DataFrame(rows)


def _labels(analytics: Path) -> dict[str, str]:
    """Rótulos legíveis (docs/sources/rotulos_votaveis.csv, gerado do JSON oficial); código se ausente."""
    p = analytics.parents[1] / "docs" / "sources" / "rotulos_votaveis.csv"
    if not p.exists():
        return {}
    r = pd.read_csv(p, dtype=str)
    return dict(zip(r["codigo"], r["rotulo"]))


def _with_labels(df: pd.DataFrame, analytics: Path) -> pd.DataFrame:
    lab = _labels(analytics)
    out = df.copy()
    for c in ("origem", "destino"):
        if c in out.columns:
            out[f"{c}_rotulo"] = out[c].map(lambda v: lab.get(str(v), str(v)))
    return out


def _build_model_appendix_table(analytics: Path, merged: pd.DataFrame, dec: dict) -> pd.DataFrame | None:
    """Apêndice do modelo de taxas constantes (R23-2): β (parâmetro) e taxa implícita nos fluxos IPF.

    β é a solução de um ajuste aproximado das marginais agregadas (resíduo > 0): não é um fluxo
    factível e pode cair fora dos limites de Fréchet. Os fluxos IPF são tabelas por unidade que
    conservam as marginais; por isso precisam respeitar os limites célula a célula, o que é
    conferido aqui. Sem os fluxos IPF, o apêndice não é publicado.
    """
    ipf = _read(analytics, "ecological_ipf_flows.csv")
    if ipf.empty or not {"origem", "destino", "fluxo"} <= set(ipf.columns):
        return None
    tot_orig = ipf.groupby("origem")["fluxo"].transform("sum")
    ipf = ipf.assign(taxa_ipf=ipf["fluxo"] / tot_orig.where(tot_orig > 0))
    t = merged.merge(ipf[["origem", "destino", "fluxo", "taxa_ipf", "erro_marginal_max_unidade"]],
                     on=["origem", "destino"], how="left", validate="one_to_one")
    if t["fluxo"].isna().any():
        return None
    bs = _read(analytics, "ecological_bootstrap.csv")
    if not bs.empty and {"origem", "destino", "inf", "sup"} <= set(bs.columns):
        t = t.merge(bs[["origem", "destino", "inf", "sup"]].rename(columns={"inf": "beta_bootstrap_inf",
                                                                            "sup": "beta_bootstrap_sup"}),
                    on=["origem", "destino"], how="left", validate="one_to_one")
    tol = 1e-12   # só ponto flutuante: um limite mínimo de 3e-7 contra β = 0 é fora (revisão 23)
    t["beta_dentro_dos_limites"] = (t["beta_parametro"] >= t["taxa_min"] - tol) & (t["beta_parametro"] <= t["taxa_max"] + tol)
    # R27-1: a tolerância de publicação é fixa (meio voto no fluxo agregado, abaixo da unidade de
    # contagem) e não cresce com o erro do próprio ajuste; separa-se "dentro dos limites exatos"
    # (só arredondamento de ponto flutuante) de "aceito com a tolerância". O IPF conserva as
    # marginais só aproximadamente quando para no teto de iterações: o erro observado é publicado.
    t["ipf_distancia_fora_dos_limites_votos"] = np.maximum(0.0, np.maximum(t["fluxo_min"] - t["fluxo"],
                                                                         t["fluxo"] - t["fluxo_max"]))
    t["ipf_dentro_dos_limites_exatos"] = t["ipf_distancia_fora_dos_limites_votos"] <= 1e-6
    t["ipf_tolerancia_publicacao_votos"] = IPF_TOLERANCIA_VOTOS
    t["ipf_dentro_dos_limites"] = t["ipf_distancia_fora_dos_limites_votos"] <= IPF_TOLERANCIA_VOTOS
    t["ipf_conservacao_marginais"] = np.where(t["erro_marginal_max_unidade"] < 1e-6, "exata", "aproximada")
    t["residuo_relativo_max_modelo"] = dec.get("residuo_relativo_max")
    keep = ["origem", "destino", "taxa_min", "taxa_max", "beta_parametro", "beta_bootstrap_inf",
            "beta_bootstrap_sup", "beta_dentro_dos_limites", "taxa_ipf", "fluxo",
            "ipf_distancia_fora_dos_limites_votos", "ipf_dentro_dos_limites_exatos",
            "ipf_tolerancia_publicacao_votos", "ipf_dentro_dos_limites", "ipf_conservacao_marginais",
            "erro_marginal_max_unidade", "residuo_relativo_max_modelo"]
    return _with_labels(t[[c for c in keep if c in t.columns]], analytics)


def _build_support_tables(
    analytics: Path, tab_dir: Path, ufs_list: list[str], escopo: str = "piloto"
) -> dict[str, pd.DataFrame]:
    """Constrói e salva as tabelas finais de suporte em `tabelas_piloto/` (`R20-2`, `R20-3`, `R20-4`)."""
    tab_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, pd.DataFrame] = {}

    # Tab 01: Resumo por UF (T1, T2 e variação)
    m_uf = _read(analytics, "metrics_uf.csv").copy()
    order_map = {uf: idx for idx, uf in enumerate(ufs_list)}
    order_map["TOTAL"] = len(ufs_list) + 1
    m_uf["_ord"] = m_uf["sg_uf"].map(lambda u: order_map.get(str(u), 99))
    m_uf = m_uf.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)
    m_uf.to_csv(tab_dir / "tab01_resumo_uf_t1_t2.csv", index=False)
    tables["tab01_resumo_uf_t1_t2.csv"] = m_uf

    # Tab 02: Principais municípios por contribuição à variação da UF (Lula e Flávio)
    c_lula = _read(analytics, "contributions_municipio_lula.csv")
    c_flavio = _read(analytics, "contributions_municipio_flavio.csv")
    top_rows = []
    for cand_label, df_c in (("Lula (13)", c_lula), ("Flávio Bolsonaro (22)", c_flavio)):
        df_cp = df_c.copy()
        df_cp["candidato"] = cand_label
        df_cp["abs_contrib"] = pd.to_numeric(df_cp["contribuicao_delta_share"], errors="coerce").abs()
        for uf in ufs_list:
            grp = df_cp[df_cp["sg_uf"] == uf]
            top_uf = grp.sort_values("abs_contrib", ascending=False).head(5).drop(columns=["abs_contrib"])
            top_rows.append(top_uf)
    tab02 = pd.concat(top_rows, ignore_index=True)
    # rótulos (só nomes) de docs/sources/municipios.csv (28 unidades) ou municipios_piloto.csv,
    # gerados do eleitorado oficial
    fontes_nomes = analytics.parents[1] / "docs" / "sources"
    nomes_path = next((p for p in (fontes_nomes / "municipios.csv", fontes_nomes / "municipios_piloto.csv")
                       if p.exists()), None)
    nomes = (pd.read_csv(nomes_path, dtype=str)[["sg_uf", "cd_municipio_tse", "nm_municipio"]]
             if nomes_path is not None else None)
    if nomes is not None:
        tab02["cd_municipio_tse"] = tab02["cd_municipio_tse"].astype(str).str.zfill(5)
        tab02 = tab02.merge(nomes, on=["sg_uf", "cd_municipio_tse"], how="left", validate="many_to_one")
    tab02.to_csv(tab_dir / "tab02_top_municipios_contribuicao.csv", index=False)
    tables["tab02_top_municipios_contribuicao.csv"] = tab02

    # Tab 03: Sensibilidade ao tratamento de agregação de seções
    sens_ag = _read(analytics, "panel_aggregation_sensitivity.csv").copy()
    sens_ag.to_csv(tab_dir / "tab03_sensibilidade_agregacao_uf.csv", index=False)
    tables["tab03_sensibilidade_agregacao_uf.csv"] = sens_ag

    # Tab 04: Limites determinísticos de Fréchet e (somente se aprovada) taxa ecológica constante (`R20-3`)
    fb = _read(analytics, "flow_bounds.csv")
    tab04 = fb[fb["principal"] == True].copy().reset_index(drop=True)  # noqa: E712
    dec = json.loads((analytics / "ecological_decision.json").read_text(encoding="utf-8"))
    pub_ok = bool(dec.get("publicar_matriz_pontual", False))
    tab08 = None
    motivos_dec = "; ".join(str(x) for x in (dec.get("motivos") or [])) or "condicao_numerica_ou_residuo"

    if pub_ok:
        er = _read(analytics, "ecological_rates.csv")
        req_er = set(FLOW_JOIN_KEYS) | {"especificacao", "taxa", "publicavel"}
        if not er.empty and req_er <= set(er.columns):
            er_pub = er[
                (er["principal"] == True)  # noqa: E712
                & (er["especificacao"] == "global_lambda_0.0")
                & (er["publicavel"] == True)  # noqa: E712
            ].copy()
            if (
                len(er_pub) == len(tab04)
                and not er_pub.duplicated(subset=FLOW_JOIN_KEYS).any()
            ):
                er_sub = er_pub[FLOW_JOIN_KEYS + ["taxa"]].rename(columns={"taxa": "beta_parametro"})
                merged = tab04.merge(er_sub, on=FLOW_JOIN_KEYS, how="left", validate="one_to_one")
                if merged["beta_parametro"].notna().all():
                    tab08 = _build_model_appendix_table(analytics, merged, dec)
                    if tab08 is None:
                        pub_ok = False
                else:
                    pub_ok = False
            else:
                pub_ok = False
        else:
            pub_ok = False

    # Revisão 23 (R23-2): a tab04 traz só os limites exatos. Os parâmetros β do modelo de taxas
    # constantes e os fluxos IPF ficam no apêndice (tab08), separados e conferidos contra os limites.
    for forbidden_col in ("taxa", "taxa_ipf_regularizada", "taxa_ecologica_constante", "beta_parametro"):
        if forbidden_col in tab04.columns:
            tab04 = tab04.drop(columns=[forbidden_col])
    tab04 = _with_labels(tab04, analytics)
    if pub_ok:
        tab04["status_matriz_pontual"] = "PUBLICADA_NO_APENDICE"
        tab08.to_csv(tab_dir / "tab08_modelo_taxas_constantes_apendice.csv", index=False)
        tables["tab08_modelo_taxas_constantes_apendice.csv"] = tab08
    else:
        # Nenhuma estimativa pontual reprovada entra nas tabelas finais (`R20-3`)
        (tab_dir / "tab08_modelo_taxas_constantes_apendice.csv").unlink(missing_ok=True)
        tab04["status_matriz_pontual"] = "NAO_PUBLICADA"
        tab04["motivo_nao_publicacao"] = motivos_dec

    tab04.to_csv(tab_dir / "tab04_limites_fluxos_agregados_uf.csv", index=False)
    tables["tab04_limites_fluxos_agregados_uf.csv"] = tab04

    # Tab 05: Associações ecológicas simples vs ajustadas (`R20-4`)
    assoc_sa = _normalize_associations_table(_read(analytics, "associations_simple_vs_adjusted.csv"))
    assoc_sa.to_csv(tab_dir / "tab05_associacoes_perfil_t1_t2.csv", index=False)
    tables["tab05_associacoes_perfil_t1_t2.csv"] = assoc_sa

    # Tab 06: Auditoria operacional (horários, recebimento e ocorrências de urna)
    oc = _read(analytics, "closure_ocorrencias.csv")
    rc = _read(analytics, "closure_receipt_consistency.csv")
    if rc.empty:
        rc = _read(analytics, "t1_receipt_consistency.csv")
    if not oc.empty and not rc.empty and {"sg_uf", "nr_turno", "classe", "secoes"} <= set(rc.columns):
        rc_piv = (
            rc.pivot_table(index=["sg_uf", "nr_turno"], columns="classe", values="secoes", aggfunc="sum", fill_value=0)
            .reset_index()
        )
        tab06 = oc.merge(rc_piv, on=["sg_uf", "nr_turno"], how="left")
    else:
        tab06 = oc.copy()
    tab06.to_csv(tab_dir / "tab06_auditoria_operacional_uf.csv", index=False)
    tables["tab06_auditoria_operacional_uf.csv"] = tab06

    # Tab 07: Identidade contábil de saldos e quadro de identificação "100% dos demais para Lula"
    tab07 = _build_accounting_and_100pct_table(m_uf, _read(analytics, "flow_demais_para_lula.csv"))
    tab07.to_csv(tab_dir / "tab07_identidade_saldos_e_teste_100pct.csv", index=False)
    tables["tab07_identidade_saldos_e_teste_100pct.csv"] = tab07

    if escopo == "nacional":
        # Tab 09: camadas (regiões, território, exterior, Brasil), mesmas somas por unidade
        cam = _read(analytics, "metrics_camadas.csv")
        cam.to_csv(tab_dir / "tab09_camadas_regioes_exterior.csv", index=False)
        tables["tab09_camadas_regioes_exterior.csv"] = cam
        # Tab 10: maiores contribuições municipais em votos no país (Lula e Flávio)
        topn = []
        for cand_label, df_c in (("Lula (13)", c_lula), ("Flávio Bolsonaro (22)", c_flavio)):
            x = df_c.copy()
            x["candidato"] = cand_label
            x["cd_municipio_tse"] = x["cd_municipio_tse"].astype(str).str.zfill(5)
            x = x.reindex(x["contribuicao_delta_votos"].abs().sort_values(ascending=False).index).head(15)
            topn.append(x)
        tab10 = pd.concat(topn, ignore_index=True)
        if nomes is not None:
            tab10 = tab10.merge(nomes, on=["sg_uf", "cd_municipio_tse"], how="left", validate="many_to_one")
        tab10.to_csv(tab_dir / "tab10_top_municipios_brasil.csv", index=False)
        tables["tab10_top_municipios_brasil.csv"] = tab10
        # Tab 11: municípios — votos dos eliminados no 1º turno × variação de Lula (figura de bases)
        mm = _read(analytics, "metrics_municipio.csv")
        if not mm.empty:
            v1 = mm["qt_votos_validos_t1"].astype(float)
            tab11 = pd.DataFrame({
                "sg_uf": mm["sg_uf"], "cd_municipio_tse": mm["cd_municipio_tse"].astype(str).str.zfill(5),
                "qt_votos_validos_t1": mm["qt_votos_validos_t1"],
                "share_demais_validos_t1": (v1 - mm["qt_lula_t1"] - mm["qt_flavio_t1"]) / v1.where(v1 > 0),
                "delta_share_lula_validos": mm["delta_share_lula_validos"],
                "delta_margem_lula_flavio_validos": mm["delta_margem_lula_flavio_validos"],
            })
            tab11.to_csv(tab_dir / "tab11_municipios_bases_iniciais.csv", index=False)
            tables["tab11_municipios_bases_iniciais.csv"] = tab11
        # Tab 12–14: horários de encerramento (handoff 29)
        for nome, df_h in _build_closure_tables(analytics, tab_dir.parent / "evidencias_horarios").items():
            df_h.to_csv(tab_dir / nome, index=False)
            tables[nome] = df_h
        # Tab 15–22: contexto socioeconômico (handoff 37; tools/analise_socio.py)
        for nome, df_s in _build_socio_tables(analytics / "socio").items():
            df_s.to_csv(tab_dir / nome, index=False)
            tables[nome] = df_s

    return tables


SOCIO_TABELAS = {"tab15_socio_faixas.csv": "faixas_nacional.csv",
                 "tab16_socio_faixas_regiao.csv": "faixas_regiao.csv",
                 "tab17_socio_modelos_municipais.csv": "modelos_municipais.csv",
                 "tab18_socio_entorno.csv": "modelos_entorno.csv",
                 "tab19_socio_perfis_bases.csv": "perfis_bases.csv",
                 "tab20_socio_correlacoes_bases.csv": "correlacoes_bases.csv",
                 "tab21_socio_tardias_contexto.csv": "tardias_com_contexto.csv",
                 "tab22_socio_cobertura_entorno_uf.csv": "cobertura_entorno_uf.csv",
                 "tab23_socio_faixas_uf.csv": "faixas_uf.csv",
                 "tab24_socio_modelo_conjunto.csv": "modelo_conjunto.csv"}


def _build_socio_tables(socio: Path) -> dict[str, pd.DataFrame]:
    """Tabelas socioeconômicas: cópias rastreáveis das saídas de `tools/analise_socio.py`."""
    out = {}
    for nome, arq in SOCIO_TABELAS.items():
        p = socio / arq
        if p.exists():
            out[nome] = pd.read_csv(p)
    return out


FAIXAS_COMPARACAO = ("17H00_17H15", "17H15_18H", "18H_19H", "A_PARTIR_19H")


def _build_closure_tables(analytics: Path, evid: Path) -> dict[str, pd.DataFrame]:
    """Faixas de encerramento (variante principal): contagens, médias brutas e associações ajustadas
    pela faixa do 2º turno; e a tabela de reprodução das contagens externas (`reconciliar_tardias.py`)."""
    out: dict[str, pd.DataFrame] = {}
    bc, raw, adj = (_read(analytics, f) for f in ("closure_band_counts.csv", "closure_raw_deltas.csv",
                                                   "closure_adjusted.csv"))
    if not bc.empty and (bc.papel == "principal").any():
        b = bc[bc.papel == "principal"].pivot_table(index="faixa", columns="nr_turno", values="secoes",
                                                    aggfunc="sum", fill_value=0)
        b = b.rename(columns={1: "secoes_t1", 2: "secoes_t2"}).reset_index()
        for c in ("secoes_t1", "secoes_t2"):
            if c not in b:
                b[c] = 0
        if not raw.empty:
            r = raw[(raw.papel == "principal") & (raw.agrupamento == "faixa_t2")]
            w = r.pivot_table(index="faixa", columns="desfecho", values="media_ponderada_aptos", aggfunc="first")
            w.columns = [f"media_{c}" for c in w.columns]
            u = r[r.desfecho == "delta_margem_lula_flavio_validos"].set_index("faixa").unidades.rename("unidades_t2")
            b = b.merge(w.join(u).reset_index(), on="faixa", how="outer")
        ordem = {f: i for i, f in enumerate(("ANTES_17H",) + FAIXAS_COMPARACAO + ("MISTA", "INVALIDO"))}
        b["ordem"] = b.faixa.map(ordem).fillna(99)
        out["tab12_horarios_faixas.csv"] = b.sort_values("ordem").drop(columns="ordem").reset_index(drop=True)
    if not adj.empty and (adj.papel == "principal").any():
        a = adj[(adj.papel == "principal") & (adj.agrupamento == "faixa_t2")].copy()
        cols = [c for c in ("recorte", "referencia", "faixa", "desfecho", "status", "motivo", "diferenca_bruta",
                            "beta_ajustado", "ep", "inf", "sup", "n", "grupos", "municipios_com_ambas", "n_aparados",
                            "aviso") if c in a.columns]
        out["tab13_horarios_ajustado.csv"] = a[cols].reset_index(drop=True)
    rp = evid / "reconciliacao_tardias.csv"
    if rp.exists():
        out["tab14_reproducao_tardias.csv"] = pd.read_csv(rp)
    return out


def _generate_figures(tables: dict[str, pd.DataFrame], fig_dir: Path, escopo: str = "piloto") -> list[str]:
    """Gera as figuras estáticas padronizadas (`R20-2`, `R20-4`, `R20-5`); no país, a versão nacional."""
    if escopo == "nacional":
        from br2026.reporting.national_figures import generate_national_figures
        return generate_national_figures(tables, fig_dir, PALETTE)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "axes.edgecolor": "#cbd5e1",
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "grid.color": PALETTE["grid"],
        "grid.linestyle": "--",
        "grid.linewidth": 0.6,
        "grid.alpha": 0.7,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 220,
    })

    fig_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    tab01 = tables["tab01_resumo_uf_t1_t2.csv"]
    ufs = list(tab01["sg_uf"].astype(str))
    x = np.arange(len(ufs))
    width = 0.25

    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.8), constrained_layout=True)
    ax0 = axes[0]
    dl = 100.0 * tab01["delta_share_lula_validos"].to_numpy(dtype=float)
    df_ = 100.0 * tab01["delta_share_flavio_validos"].to_numpy(dtype=float)
    da = 100.0 * tab01["delta_abstencao_aptos"].to_numpy(dtype=float)

    b1 = ax0.bar(x - width, dl, width, label="Δ Lula (13) / válidos", color=PALETTE["lula"])
    b2 = ax0.bar(x, df_, width, label="Δ Flávio (22) / válidos", color=PALETTE["flavio"])
    b3 = ax0.bar(x + width, da, width, label="Δ Abstenção / aptos", color=PALETTE["abstencao"])
    ax0.axhline(0, color="#334155", linewidth=0.9)
    ax0.set_xticks(x)
    ax0.set_xticklabels(ufs, fontweight="bold")
    ax0.set_ylabel("Variação T1 → T2 (p.p.)")
    ymin0 = min(float(np.min(np.concatenate([dl, df_, da]))), 0.0)
    ymax0 = max(float(np.max(np.concatenate([dl, df_, da]))), 0.0)
    pad0 = max((ymax0 - ymin0) * 0.22, 2.0)
    ax0.set_ylim(ymin0 - pad0, ymax0 + pad0)
    ax0.set_title("A. Variação entre turnos (T2 − T1, em p.p.)", fontsize=10.5, fontweight="bold", color=PALETTE["navy"])
    ax0.legend(frameon=True, facecolor="white", fontsize=8.5, loc="best")
    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax0.annotate(
                f"{h:+.2f}".replace(".", ","),
                xy=(bar.get_x() + bar.get_width() / 2, h),
                xytext=(0, 3 if h >= 0 else -11),
                textcoords="offset points",
                ha="center", va="bottom" if h >= 0 else "top",
                fontsize=7.3,
            )

    ax1 = axes[1]
    l_t1 = 100.0 * tab01["share_lula_validos_t1"].to_numpy(dtype=float)
    l_t2 = 100.0 * tab01["share_lula_validos_t2"].to_numpy(dtype=float)
    f_t1 = 100.0 * tab01["share_flavio_validos_t1"].to_numpy(dtype=float)
    f_t2 = 100.0 * tab01["share_flavio_validos_t2"].to_numpy(dtype=float)

    w2 = 0.18
    ax1.bar(x - 1.5 * w2, l_t1, w2, label="Lula T1", color=PALETTE["lula"], alpha=0.55)
    ax1.bar(x - 0.5 * w2, l_t2, w2, label="Lula T2", color=PALETTE["lula"])
    ax1.bar(x + 0.5 * w2, f_t1, w2, label="Flávio T1", color=PALETTE["flavio"], alpha=0.55)
    ax1.bar(x + 1.5 * w2, f_t2, w2, label="Flávio T2", color=PALETTE["flavio"])
    ax1.set_xticks(x)
    ax1.set_xticklabels(ufs, fontweight="bold")
    ax1.set_ylabel("% dos votos válidos nominais")
    ax1.set_ylim(0, 108)
    ax1.set_title("B. Participação sobre votos válidos nominais (T1 vs. T2)", fontsize=10.5, fontweight="bold", color=PALETTE["navy"])
    ax1.legend(frameon=True, facecolor="white", fontsize=8.0, ncol=2, loc="upper right")

    fig.suptitle("Figura 1 — Resumo da mudança agregada entre 1º e 2º turnos por UF", fontsize=12, fontweight="bold", color=PALETTE["navy"])
    f1_path = fig_dir / "fig01_resumo_uf_t1_t2.png"
    fig.savefig(f1_path)
    plt.close(fig)
    generated.append(f1_path.name)

    # Figura 2: Contribuições municipais por UF (Lula e Flávio)
    tab02 = tables["tab02_top_municipios_contribuicao.csv"]
    ufs_c = [u for u in ufs if u != "TOTAL" and u in set(tab02["sg_uf"].astype(str))]
    fig, axes = plt.subplots(len(ufs_c), 2, figsize=(11.8, 3.1 * len(ufs_c)), squeeze=False, constrained_layout=True)
    for i, uf in enumerate(ufs_c):
        for j, (cand_label, color) in enumerate((("Lula (13)", PALETTE["lula"]), ("Flávio Bolsonaro (22)", PALETTE["flavio"]))):
            ax = axes[i][j]
            sub = tab02[(tab02["sg_uf"] == uf) & (tab02["candidato"] == cand_label)].copy()
            sub = sub.sort_values("contribuicao_delta_share", ascending=True)
            vals = 100.0 * sub["contribuicao_delta_share"].to_numpy(dtype=float)
            nomes_m = (sub["nm_municipio"] if "nm_municipio" in sub.columns
                       else pd.Series([None] * len(sub), index=sub.index))
            labels = [f"{str(n).title()} ({m})" if isinstance(n, str) else f"Mun. {m}"
                      for m, n in zip(sub["cd_municipio_tse"].astype(str), nomes_m)]
            y = np.arange(len(labels))
            ax.barh(y, vals, color=color, alpha=0.88, height=0.6)
            ax.axvline(0, color="#334155", linewidth=0.8)
            ax.set_yticks(y)
            ax.set_yticklabels(labels, fontsize=8.5)
            ax.set_xlabel("Contribuição para Δ UF (p.p. nos válidos)")
            ax.set_title(f"{uf} — {cand_label}", fontsize=9.8, fontweight="bold", color=PALETTE["navy"])
    fig.suptitle("Figura 2 — Principais municípios por contribuição aritmética à variação estadual (T1 → T2)",
                 fontsize=11.5, fontweight="bold", color=PALETTE["navy"])
    f2_path = fig_dir / "fig02_contribuicoes_municipais_uf.png"
    fig.savefig(f2_path)
    plt.close(fig)
    generated.append(f2_path.name)

    # Figura 3: Decomposição do comparecimento, abstenção, brancos e nulos sobre aptos
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.6), constrained_layout=True)
    for idx, (turno_num, suffix) in enumerate(((1, "t1"), (2, "t2"))):
        ax = axes[idx]
        aptos = tab01[f"qt_aptos_{suffix}"].to_numpy(dtype=float)
        if (aptos <= 0).any():
            raise ValueError(f"Denominador qt_aptos_{suffix} não positivo em tab01")
        lula_p = 100.0 * tab01[f"qt_lula_{suffix}"].to_numpy(dtype=float) / aptos
        flav_p = 100.0 * tab01[f"qt_flavio_{suffix}"].to_numpy(dtype=float) / aptos
        val_p = 100.0 * tab01[f"qt_votos_validos_{suffix}"].to_numpy(dtype=float) / aptos
        outros_p = np.clip(val_p - lula_p - flav_p, 0.0, None)
        br_p = 100.0 * tab01[f"qt_votos_brancos_{suffix}"].to_numpy(dtype=float) / aptos
        nu_p = 100.0 * tab01[f"qt_votos_nulos_{suffix}"].to_numpy(dtype=float) / aptos
        ab_p = 100.0 * tab01[f"qt_abstencoes_{suffix}"].to_numpy(dtype=float) / aptos

        ax.bar(x, lula_p, width=0.5, label="Lula (13)", color=PALETTE["lula"])
        bottom = lula_p.copy()
        ax.bar(x, flav_p, width=0.5, bottom=bottom, label="Flávio (22)", color=PALETTE["flavio"])
        bottom += flav_p
        if turno_num == 1 and (outros_p > 0.01).any():
            ax.bar(x, outros_p, width=0.5, bottom=bottom, label="Demais candidatos (T1)", color=PALETTE["terceiros"])
            bottom += outros_p
        ax.bar(x, br_p + nu_p, width=0.5, bottom=bottom, label="Brancos + Nulos", color=PALETTE["nao_validos"])
        bottom += br_p + nu_p
        ax.bar(x, ab_p, width=0.5, bottom=bottom, label="Abstenção", color=PALETTE["abstencao"])

        ax.set_xticks(x)
        ax.set_xticklabels(ufs, fontweight="bold")
        ax.set_ylim(0, 128)  # faixa acima de 100 só para a legenda não cobrir as barras
        ax.set_yticks(range(0, 101, 20))
        ax.set_ylabel("% dos eleitores aptos")
        ax.set_title(f"{turno_num}º Turno — Composição integral dos aptos (%)", fontsize=10.5, fontweight="bold", color=PALETTE["navy"])
        ax.legend(frameon=True, facecolor="white", fontsize=8.0, loc="upper center", ncol=3)

    fig.suptitle("Figura 3 — Decomposição integral do eleitorado apto em votos nominais, brancos/nulos e abstenção",
                 fontsize=11.5, fontweight="bold", color=PALETTE["navy"])
    f3_path = fig_dir / "fig03_decomposicao_comparecimento_nao_validos.png"
    fig.savefig(f3_path)
    plt.close(fig)
    generated.append(f3_path.name)

    # Figura 4: Associações ecológicas simples vs ajustadas na escala +10 p.p. (`R20-4`)
    tab05 = tables["tab05_associacoes_perfil_t1_t2.csv"]
    sub_a = tab05[tab05["unidade_termo"] == "proporcao"].copy()
    if not sub_a.empty:
        target_desf = "delta_share_lula_validos" if "delta_share_lula_validos" in set(sub_a["desfecho"]) else str(sub_a["desfecho"].iloc[0])
        sub_a = sub_a[sub_a["desfecho"] == target_desf]
        if "recorte" in sub_a.columns and "territorial" in set(sub_a["recorte"]):
            sub_a = sub_a[sub_a["recorte"] == "territorial"]
        if "familia" in sub_a.columns and "ef_municipio" in set(sub_a["familia"]):
            sub_a = sub_a[sub_a["familia"] == "ef_municipio"]
        elif "familia" in sub_a.columns:
            sub_a = sub_a[sub_a["familia"] == sub_a["familia"].iloc[0]]

        # Priorizar termos de perfil e composição com estimativa finita
        sub_a = sub_a.dropna(subset=["pp_por_10pp_simples", "pp_por_10pp_ajustado"]).drop_duplicates(subset=["termo"])
        if not sub_a.empty:
            sub_a = sub_a.head(12).reset_index(drop=True)
            terms = list(sub_a["termo"].astype(str))
            y_pos = np.arange(len(terms))

            fig, ax = plt.subplots(figsize=(11.2, max(4.4, 0.52 * len(terms) + 1.6)), constrained_layout=True)
            bs_s = sub_a["pp_por_10pp_simples"].to_numpy(dtype=float)
            lo_s = np.clip(bs_s - sub_a["pp_por_10pp_inf_simples"].to_numpy(dtype=float), 0.0, None)
            hi_s = np.clip(sub_a["pp_por_10pp_sup_simples"].to_numpy(dtype=float) - bs_s, 0.0, None)

            bs_a = sub_a["pp_por_10pp_ajustado"].to_numpy(dtype=float)
            lo_a = np.clip(bs_a - sub_a["pp_por_10pp_inf_ajustado"].to_numpy(dtype=float), 0.0, None)
            hi_a = np.clip(sub_a["pp_por_10pp_sup_ajustado"].to_numpy(dtype=float) - bs_a, 0.0, None)

            ax.errorbar(
                bs_s, y_pos - 0.14, xerr=[lo_s, hi_s], fmt="o", color=PALETTE["simples"],
                label="Simples (bivariada c/ EF)", capsize=3.5, markersize=5.5, linewidth=1.3
            )
            ax.errorbar(
                bs_a, y_pos + 0.14, xerr=[lo_a, hi_a], fmt="s", color=PALETTE["ajustado"],
                label="Ajustada (multivariada c/ EF)", capsize=3.5, markersize=5.5, linewidth=1.3
            )
            ax.axvline(0, color="#334155", linewidth=0.9, linestyle="--")
            ax.set_yticks(y_pos)
            ax.set_yticklabels(terms, fontsize=8.5)
            ax.set_xlabel(f"Variação em {target_desf} associada a +10 p.p. na categoria focal vs. referência (em p.p., IC 95%)")
            ax.set_title("Figura 4 — Associações ecológicas entre perfil/composição e variação entre turnos (simples vs. ajustada)",
                         fontsize=10.6, fontweight="bold", color=PALETTE["navy"])
            ax.legend(frameon=True, facecolor="white", fontsize=8.5, loc="best")
            f4_path = fig_dir / "fig04_associacoes_perfil_simples_vs_ajustado.png"
            fig.savefig(f4_path)
            plt.close(fig)
            generated.append(f4_path.name)

    # Figura 5: Cobertura, sensibilidade de agregação e auditoria operacional
    tab03 = tables["tab03_sensibilidade_agregacao_uf.csv"]
    tab06 = tables.get("tab06_auditoria_operacional_uf.csv", pd.DataFrame())
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.5), constrained_layout=True)

    ax0 = axes[0]
    lvls = list(tab03["nivel_agregacao"].astype(str))
    x0 = np.arange(len(lvls))
    w = 0.32
    dl_s = 100.0 * tab03["delta_share_lula_validos"].to_numpy(dtype=float)
    df_s = 100.0 * tab03["delta_share_flavio_validos"].to_numpy(dtype=float)
    ax0.bar(x0 - w / 2, dl_s, w, label="Δ Lula (13)", color=PALETTE["lula"])
    ax0.bar(x0 + w / 2, df_s, w, label="Δ Flávio (22)", color=PALETTE["flavio"])
    ax0.axhline(0, color="#334155", linewidth=0.8)
    ax0.set_xticks(x0)
    rot_lvls = {"SECAO_UNIDADE": "Unidade", "LOCAL": "Local", "MUNICIPIO": "Município",
                "SECAO_UNIDADE_SEM_AGREGACAO": "Sem\nagregação"}
    ax0.set_xticklabels([rot_lvls.get(v, v) for v in lvls], fontweight="bold", fontsize=8.5)
    ax0.set_ylim(0, max(float(np.nanmax(dl_s)), float(np.nanmax(df_s))) * 1.3)
    ax0.set_ylabel("Variação T1 → T2 nos válidos (p.p.)")
    ax0.set_title("A. Sensibilidade ao nível de agregação e ao universo", fontsize=9.8, fontweight="bold", color=PALETTE["navy"])
    ax0.legend(frameon=True, facecolor="white", fontsize=8.0, loc="upper center", ncol=2)

    ax1 = axes[1]
    # só o 1º turno: no 2º não há Anexo V nem CEFT publicados (NAO_VERIFICADO, não zero)
    oc_t1 = tab06[tab06["nr_turno"] == 1] if "nr_turno" in tab06.columns else tab06
    if not oc_t1.empty and {"sg_uf", "secoes_reemissao_bu", "anexo_v_secoes"} <= set(oc_t1.columns):
        sub_oc = oc_t1.groupby("sg_uf", as_index=False).agg(
            reemissao=("secoes_reemissao_bu", "sum"),
            anexo_v=("anexo_v_secoes", "sum"),
        )
        x2 = np.arange(len(sub_oc))
        ax1.bar(x2 - 0.18, sub_oc["reemissao"], 0.35, label="Seções c/ reemissão BU", color=PALETTE["navy"])
        ax1.bar(x2 + 0.18, sub_oc["anexo_v"], 0.35, label="Ocorrências Anexo V", color=PALETTE["abstencao"])
        ax1.set_xticks(x2)
        ax1.set_xticklabels(list(sub_oc["sg_uf"]), fontweight="bold")
        ax1.set_ylabel("Número de seções")
        ax1.set_title("B. Reemissões e Anexo V por UF — 1º turno (2º não verificado)", fontsize=10.0, fontweight="bold", color=PALETTE["navy"])
        ax1.legend(frameon=True, facecolor="white", fontsize=8.0)
    else:
        ax1.text(0.5, 0.5, "Sem ocorrências operacionais registradas", ha="center", va="center")

    fig.suptitle("Figura 5 — Sensibilidade à regra de agregação de seções e auditoria de ocorrências de urna",
                 fontsize=11.5, fontweight="bold", color=PALETTE["navy"])
    f5_path = fig_dir / "fig05_cobertura_agregacao_ocorrencias.png"
    fig.savefig(f5_path)
    plt.close(fig)
    generated.append(f5_path.name)

    return generated


def build_pilot_comparative_report(
    analytics: Path, out: Path, expected_ufs: tuple[str, ...] | None = None, escopo: str | None = None
) -> dict:
    """Constrói `RELATORIO_COMPARATIVO_PILOTO_T1_T2.md`, `figuras_piloto/`, `tabelas_piloto/` e `RASTRO_RELATORIO_PILOTO.csv`.

    Aplica validação pré-publicação estrita (`R20-2`..`R20-5`): qualquer falha retorna `status="BLOCKED"`
    e remove artefatos comparativos obsoletos de `out`.
    """
    escopo = escopo or escopo_do_analytics(analytics)
    e = ESCOPOS[escopo]
    if escopo == "nacional" and expected_ufs is None:
        expected_ufs = NATIONAL_UFS
    err, man, ufs_list = _validate_comparative_inputs(analytics, expected_ufs=expected_ufs)
    if err is None and escopo == "nacional" and _read(analytics, "metrics_camadas.csv").empty:
        err = "metrics_camadas.csv ausente; rode `analyze` com a versão nacional"
    if err is not None:
        _cleanup_stale_outputs(out, escopo)
        return {
            "status": "BLOCKED",
            "motivo": f"Relatório comparativo T1×T2 bloqueado: {err}",
        }

    fig_dir = out / e["figuras"]
    tab_dir = out / e["tabelas"]
    tables = _build_support_tables(analytics, tab_dir, ufs_list, escopo)
    figs = _generate_figures(tables, fig_dir, escopo)

    # Handoff 24: versão editorial em três documentos (resumo, relatório, apêndice), mesmas tabelas;
    # handoff 26: a versão nacional tem texto próprio
    if escopo == "nacional":
        from br2026.reporting.national_editorial import write_editorial
    else:
        from br2026.reporting.pilot_editorial import write_editorial
    ed = write_editorial(out, analytics, tables, figs, man)
    bad_terms = [t for txt in ed["docs"].values() for t in forbidden_matches(txt)]
    if bad_terms:
        _cleanup_stale_outputs(out, escopo)
        return {
            "status": "BLOCKED",
            "motivo": f"Relatório comparativo bloqueado pelo linter semântico: {bad_terms}",
        }

    out.mkdir(parents=True, exist_ok=True)
    for nome, txt in ed["docs"].items():
        (out / nome).write_text(txt, encoding="utf-8")
    trace_path = out / e["rastro"]
    pd.DataFrame(ed["trace"]).to_csv(trace_path, index=False)
    report_path = out / e["principal"]

    return {
        "status": "PASS",
        "escopo": escopo,
        "relatorio": str(report_path),
        "documentos": sorted(ed["docs"]),
        "rastro_linhas": len(ed["trace"]),
        "figuras": figs,
        "tabelas": sorted(tables.keys()),
        "bytes": sum(len(t.encode("utf-8")) for t in ed["docs"].values()),
    }
