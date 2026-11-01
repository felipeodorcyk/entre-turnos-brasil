"""Etapa `report` (O5/B6): relatório montado só a partir das tabelas de data/analytics.

O documento é uma sequência de fragmentos. Texto fixo (`Prose`) passa pelo
linter: sem números digitados e sem narrativas proibidas. Números e tabelas
(`cite`, `table`) vêm das saídas de `analyze` e deixam rastro (tabela, linha,
coluna). A matriz pontual de taxas só aparece se a regra de publicação a
liberou; limites aparecem sempre. O relatório não constitui aceite de marco.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from br2026.reporting.report import ReportError, forbidden_matches, lint_template


class Doc:
    def __init__(self):
        self.parts: list[tuple[str, str]] = []
        self.trace: list[dict] = []

    def prose(self, text: str) -> None:
        issues = lint_template(text)
        if issues:
            raise ReportError("texto fixo reprovado:\n  " + "\n  ".join(issues))
        self.parts.append(("prose", text))

    def cite(self, table: str, row: dict, col: str, value, fmt: str) -> str:
        self.trace.append({"tabela": table, "linha": json.dumps(row, ensure_ascii=False, default=str),
                           "coluna": col, "valor": value})
        return _fmt(value, fmt)

    def line(self, text: str) -> None:
        """Linha gerada que contém apenas citações já rastreadas e rótulos."""
        self.parts.append(("gen", text))

    def table(self, name: str, df: pd.DataFrame, cols: list[str], fmts: dict | None = None,
              filtro: str = "", headers: dict | None = None) -> None:
        """`headers` só muda o rótulo exibido; o rastro guarda os nomes das colunas da tabela."""
        fmts = fmts or {}
        headers = headers or {}
        if df.empty:
            self.parts.append(("gen", f"_Sem linhas em `{name}`{(' (' + filtro + ')') if filtro else ''}._"))
            return
        head = "| " + " | ".join(headers.get(c, c) for c in cols) + " |\n|" + "---|" * len(cols)
        body = "\n".join("| " + " | ".join(_fmt(r[c], fmts.get(c)) for c in cols) + " |"
                         for _, r in df.iterrows())
        self.parts.append(("gen", head + "\n" + body))
        self.trace.append({"tabela": name, "linha": filtro or "todas", "coluna": "|".join(cols),
                           "valor": f"{len(df)} linha(s)"})

    def render(self) -> str:
        text = "\n\n".join(t for _, t in self.parts) + "\n"
        hits = forbidden_matches(text)
        if hits:
            raise ReportError(f"frase proibida no relatório: {hits[0]!r}")
        return text


def _fmt(v, spec) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return "—"
    if spec == "pct":
        return f"{100 * v:.2f}%".replace(".", ",")
    if spec == "pp":
        return f"{100 * v:+.2f}".replace(".", ",") + " p.p."
    if spec == "pp3":
        return f"{100 * v:+.3f}".replace(".", ",") + " p.p."
    if spec == "int":
        return f"{int(round(float(v))):,}".replace(",", ".")
    if spec == "f4":
        return f"{float(v):.4f}".replace(".", ",")
    if spec == "ppv":   # valor já em pontos percentuais
        return f"{float(v):+.2f}".replace(".", ",") + " p.p."
    if spec == "f2":
        return f"{float(v):.2f}".replace(".", ",")
    if spec == "f3":
        return f"{float(v):.3f}".replace(".", ",")
    return str(v)


def _read(dir_: Path, name: str) -> pd.DataFrame:
    p = dir_ / name
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p) if name.endswith(".parquet") else pd.read_csv(p)


def build_report(analytics: Path, out: Path) -> dict:
    man_path = analytics / "analysis_manifest.json"
    if not man_path.exists():
        return {"status": "BLOCKED", "motivo": "rode `analyze` antes: analysis_manifest.json ausente"}
    man = json.loads(man_path.read_text(encoding="utf-8"))
    d = Doc()
    d.prose("# Eleição presidencial de 2026 — Lula × Flávio Bolsonaro, 1º e 2º turnos")
    d.prose("> Relatório gerado automaticamente a partir das tabelas de `data/analytics`. "
            "Ele não constitui aceite de marco: o estado dos marcos M1 a M4 está em "
            "`reports/analysis/STATUS.md`. Unidade mínima: seção eleitoral; nenhum resultado "
            "se refere a eleitores individuais.")

    d.prose("## Pergunta e limites")
    d.prose("Como variaram as votações de Lula e de Flávio Bolsonaro, a diferença entre ambos, o "
            "comparecimento, os brancos e os nulos entre os dois turnos, e como essas variações se "
            "associam à votação inicial, ao perfil cadastral e aos horários de encerramento. "
            "Associações entre unidades não são efeitos causais. Fluxos entre categorias não são "
            "observados: só se publicam limites compatíveis com os totais e, quando a regra "
            "pré-registrada permite, taxas médias sob hipóteses explícitas.")

    d.prose("## Fontes e reprodutibilidade")
    rows = pd.DataFrame([{"insumo": k, "sha256": v} for k, v in man["insumos_sha256"].items()])
    d.table("analysis_manifest.json:insumos_sha256", rows, ["insumo", "sha256"])
    dirty = man.get("codigo_com_alteracoes_nao_commitadas")
    estado = {True: "sim", False: "não"}.get(dirty, f"desconhecido ({man.get('git_diagnostico') or 'sem diagnóstico'})")
    d.line(f"Contrato `{man['contract_version']}` · configuração `{man['config_sha256'][:12]}` · "
           f"commit `{man['git_commit']}` · código com alterações não commitadas: "
           f"{estado} · execução `{man['executado_em_utc']}`.")
    d.trace.append({"tabela": "analysis_manifest.json", "linha": "raiz", "coluna": "contract_version|config_sha256|git_commit",
                    "valor": man["git_commit"]})

    d.prose("## Universo e cobertura")
    d.prose("O painel reúne unidades comparáveis entre turnos. Unidades excluídas continuam "
            "contadas, com o motivo da exclusão; a reconciliação entre seções e painel precisa "
            "fechar sem diferença.")
    rec = _read(analytics, "panel_reconciliation.csv")
    if not rec.empty:
        ok = bool((rec.dif == 0).all())
        d.line(f"Reconciliação seção → painel: **{'sem diferenças' if ok else 'COM DIFERENÇAS'}** "
               f"({d.cite('panel_reconciliation.csv', {'todas': True}, 'dif', int(rec.dif.abs().sum()), 'int')} "
               "de diferença absoluta somada).")
    cov = _read(analytics, "coverage_uf.csv")
    want = ["sg_uf", "unidades_incluida", "unidades_excluida", "qt_aptos_t1_pct_incluida",
            "qt_votos_validos_t2_pct_incluida"]
    d.table("coverage_uf.csv", cov, [c for c in want if c in cov.columns],
            {"unidades_incluida": "int", "unidades_excluida": "int",
             "qt_aptos_t1_pct_incluida": "pct", "qt_votos_validos_t2_pct_incluida": "pct"})

    st_all = _read(analytics, "analysis_status.csv")
    pares = st_all[st_all.bloco == "t1:painel_entre_turnos"] if not st_all.empty else st_all
    pairs = pares.empty or (pares.status == "PASS").all()
    if not pairs:
        r = pares.iloc[0]
        d.trace.append({"tabela": "analysis_status.csv", "linha": "bloco=t1:painel_entre_turnos",
                        "coluna": "status", "valor": r.status})
        d.line(f"**Comparação entre turnos: {r.status}.** Faltam: {r.motivo}.")
        d.prose("Sem os dois turnos não há pares de unidades: este relatório não apresenta variações, "
                "decomposições entre turnos, limites de origem nem associações. A seção seguinte descreve "
                "somente o 1º turno.")
        d.prose("## Diagnóstico do 1º turno")
        d.prose("Piloto restrito às UFs presentes no staging: não representa o país. Totais por UF no universo "
                "com 1º turno apurado. Votos em candidatura com nulo técnico na "
                "totalização oficial estão nos nulos, não nos válidos. As identidades contábeis devem fechar "
                "com diferença zero.")
        m = _read(analytics, "t1_metrics_uf.csv")
        d.table("t1_metrics_uf.csv", m, ["sg_uf", "qt_aptos_t1", "qt_comparecimento_t1", "qt_votos_validos_t1",
                                         "qt_votos_brancos_t1", "qt_votos_nulos_t1", "qt_lula_t1", "qt_flavio_t1",
                                         "identidade_comparecimento_dif", "identidade_aptos_dif"],
                {c: "int" for c in ("qt_aptos_t1", "qt_comparecimento_t1", "qt_votos_validos_t1",
                                    "qt_votos_brancos_t1", "qt_votos_nulos_t1", "qt_lula_t1", "qt_flavio_t1",
                                    "identidade_comparecimento_dif", "identidade_aptos_dif")})
        d.table("t1_metrics_uf.csv", m, ["sg_uf", "share_lula_validos_t1", "share_flavio_validos_t1",
                                         "abstencao_aptos_t1", "brancos_comparecimento_t1",
                                         "nulos_comparecimento_t1"],
                {c: "pct" for c in ("share_lula_validos_t1", "share_flavio_validos_t1", "abstencao_aptos_t1",
                                    "brancos_comparecimento_t1", "nulos_comparecimento_t1")}, filtro="razões")
        c = _read(analytics, "t1_coverage_uf.csv")
        d.table("t1_coverage_uf.csv", c, [x for x in c.columns if x != "aptos_t1"], {}, filtro="unidades e exclusões")
        pc = _read(analytics, "t1_profile_coverage_uf.csv")
        if not pc.empty:
            d.prose("Cobertura do perfil cadastral por motivo de exclusão. O perfil descreve os aptos "
                    "cadastrados, não quem votou.")
            d.table("t1_profile_coverage_uf.csv", pc, ["sg_uf", "motivo_exclusao", "unidades", "aptos_t1"],
                    {"unidades": "int", "aptos_t1": "int"})
        sp = _read(analytics, "t1_profile_sem_perfil_uf.csv")
        if not sp.empty:
            d.prose("Classificação observada das unidades sem perfil cadastral segundo o arquivo de locais "
                    "de votação (tipo do local e contagem de eleitores permanentes na seção no campo "
                    "consultado). A data de geração do arquivo de perfil não representa data de referência "
                    "cadastral; eventual relação temporal de criação ou habilitação permanece como hipótese "
                    "não verificada pelas fontes consultadas:")
            cols_sp = [col for col in ("sg_uf", "ds_tipo_local", "unidades", "secoes", "aptos_t1",
                                       "qt_eleitor_secao_permanente") if col in sp.columns]
            d.table("t1_profile_sem_perfil_uf.csv", sp, cols_sp,
                    {col: "int" for col in ("unidades", "secoes", "aptos_t1", "qt_eleitor_secao_permanente")})

    if pairs:
        d.prose("## Variação entre turnos")
        d.prose("Participações são razões de somas no universo indicado, nunca médias de percentuais "
                "de seções. O denominador está no nome de cada métrica.")
        m = _read(analytics, "metrics_aggregate.csv")
        groups = [
            ("Participações e taxas (níveis)", "pct",
             ["share_lula_validos_t1", "share_lula_validos_t2", "share_flavio_validos_t1",
              "share_flavio_validos_t2", "abstencao_aptos_t1", "abstencao_aptos_t2"]),
            ("Variações de participações e taxas", "pp",
             ["delta_share_lula_validos", "delta_share_flavio_validos", "delta_margem_lula_flavio_validos",
              "delta_abstencao_aptos", "delta_brancos_comparecimento", "delta_nulos_comparecimento"]),
            ("Variações em votos e pessoas", "int",
             ["delta_qt_lula", "delta_qt_flavio", "delta_margem_lula_flavio_votos", "delta_qt_comparecimento",
              "delta_qt_aptos"]),
        ]
        if not m.empty:
            for title, fmt, keep in groups:
                mm = m[m.metrica.isin(keep)].pivot(index="metrica", columns="universo", values="valor")
                mm = mm.reindex([k for k in keep if k in mm.index]).reset_index()
                d.prose(f"### {title}")
                d.table("metrics_aggregate.csv", mm, list(mm.columns),
                        {u: fmt for u in mm.columns if u != "metrica"}, filtro=title)
        for cand in ("lula", "flavio"):
            c = _read(analytics, f"contributions_uf_{cand}.csv")
            d.prose(f"### Contribuição de cada UF à variação da participação — {cand.capitalize()}")
            d.table(f"contributions_uf_{cand}.csv", c, ["sg_uf", "contribuicao_delta_share",
                                                        "efeito_participacao", "efeito_peso",
                                                        "contribuicao_delta_votos"],
                    {"contribuicao_delta_share": "pp", "efeito_participacao": "pp", "efeito_peso": "pp",
                     "contribuicao_delta_votos": "int"})
        tb = _read(analytics, "turnout_bounds.csv")
        if not tb.empty:
            r = tb.iloc[0]
            d.prose("### Comparecimento: variação líquida e trocas possíveis")
            d.line("Variação líquida do comparecimento: "
                   f"{d.cite('turnout_bounds.csv', {'universo': r.universo}, 'variacao_liquida_comparecimento', r.variacao_liquida_comparecimento, 'int')}"
                   + (", das quais "
                      f"{d.cite('turnout_bounds.csv', {'universo': r.universo}, 'variacao_liquida_comparecimento_com_limites', r.variacao_liquida_comparecimento_com_limites, 'int')} "
                      "nas unidades com aptos iguais, únicas em que os limites abaixo valem"
                      if "variacao_liquida_comparecimento_com_limites" in tb.columns else "")
                   + ". Pessoas que podem ter passado a votar no 2º turno, nessas unidades: entre "
                   f"{d.cite('turnout_bounds.csv', {'universo': r.universo}, 'entradas_min', r.entradas_min, 'int')} e "
                   f"{d.cite('turnout_bounds.csv', {'universo': r.universo}, 'entradas_max', r.entradas_max, 'int')} "
                   f"({r.condicao}).")

        d.prose("## Origens possíveis da variação (não observadas)")
        dec_p = analytics / "ecological_decision.json"
        fb = _read(analytics, "flow_bounds.csv")
        if not fb.empty:
            main = fb[fb.principal]
            d.prose("Limites compatíveis com os totais de cada unidade no cenário principal de população "
                    "(rotatividade mínima). Larguras grandes indicam que os totais quase não restringem "
                    "as trocas.")
            d.table("flow_bounds.csv", main, ["origem", "destino", "taxa_min", "taxa_max", "pouco_informativo"],
                    {"taxa_min": "pct", "taxa_max": "pct"}, filtro="principal=True")
            sens = fb.groupby(["cenario_populacao", "universo_fluxo", "limiar_candidato"]).largura_taxa.mean()
            d.prose("Sensibilidade da largura média dos limites ao cenário de população e ao agrupamento "
                    "de candidatos:")
            d.table("flow_bounds.csv", sens.reset_index(), ["cenario_populacao", "universo_fluxo",
                                                            "limiar_candidato", "largura_taxa"],
                    {"largura_taxa": "pct"}, filtro="média por cenário")
        if dec_p.exists():
            dec = json.loads(dec_p.read_text(encoding="utf-8"))
            d.trace.append({"tabela": "ecological_decision.json", "linha": "raiz",
                            "coluna": "publicar_matriz_pontual", "valor": dec["publicar_matriz_pontual"]})
            if dec["publicar_matriz_pontual"]:
                rates = _read(analytics, "ecological_rates.csv")
                rates = rates[rates.publicavel]
                d.prose("Taxas médias estimadas sob a hipótese de taxas constantes entre unidades e o "
                        "cenário de rotatividade mínima. Não descrevem a decisão de nenhum eleitor; as "
                        "transições individuais continuam não identificadas.")
                piv = rates.pivot(index="origem", columns="destino", values="taxa").reset_index()
                d.table("ecological_rates.csv", piv, list(piv.columns),
                        {c: "pct" for c in piv.columns if c != "origem"}, filtro="publicavel=True")
                boot = _read(analytics, "ecological_bootstrap.csv")
                if not boot.empty:
                    d.prose("Intervalos por reamostragem de municípios, condicionais ao modelo (não incluem "
                            "a falta de identificação nem são margem de erro de contagem):")
                    d.table("ecological_bootstrap.csv", boot, ["origem", "destino", "inf", "sup"],
                            {"inf": "pct", "sup": "pct"})
            else:
                d.prose("A matriz pontual de taxas não é publicada: a regra pré-registrada não foi "
                        "satisfeita. Motivos registrados:")
                d.line("; ".join(dec["motivos"]) or "—")

        d.prose("## Associações territoriais")
        a = _read(analytics, "associations.csv")
        if not a.empty:
            sel = a[(a.recorte == "territorial") & (a.pesos == "aptos_t1")]
            spec_order = ["composicao+perfil", "composicao"]
            spec = next((sp for sp in spec_order if (sel.especificacao == sp).any()), None)
            sel = sel[(sel.especificacao == spec) & (sel.familia == "ef_municipio")]
            d.prose("Coeficientes de associação com efeito fixo de município, pesos pelos aptos do 1º "
                    "turno e erros agrupados por município. Composição do 1º turno sobre os aptos, com "
                    "a abstenção como referência; perfil cadastral com uma categoria de referência por "
                    "dimensão. O perfil é dos aptos cadastrados, não de quem votou.")
            d.table("associations.csv", sel, ["desfecho", "termo", "referencia", "beta", "inf", "sup", "n"],
                    {"beta": "f4", "inf": "f4", "sup": "f4", "n": "int"},
                    filtro=f"familia=ef_municipio, especificacao={spec}, recorte=territorial, pesos=aptos_t1")

    d.prose("## Horários de encerramento")
    st_all = _read(analytics, "analysis_status.csv")
    concl = st_all[st_all.bloco == "horarios:conclusao_principal"] if not st_all.empty else st_all
    cov = _read(analytics, "closure_coverage.csv")
    d.prose("O resultado principal usa somente encerramentos de urna com fuso documentado. O "
            "deslocamento inferido a partir da abertura das urnas é um cenário exploratório, mantido "
            "em arquivo separado, e não sustenta conclusões enquanto a semântica e o relógio dos "
            "campos não forem validados por documento.")
    if not cov.empty:
        d.table("closure_coverage.csv", cov, [c for c in ("nr_turno", "DOCUMENTADO", "INFERIDO",
                                                           "DESCONHECIDO_OU_MISTO", "secoes_com_faixa_principal",
                                                           "variante_principal") if c in cov.columns],
                {c: "int" for c in ("DOCUMENTADO", "INFERIDO", "DESCONHECIDO_OU_MISTO",
                                    "secoes_com_faixa_principal")})
    blocked = concl.empty or (concl.status != "PASS").any()
    if not concl.empty:
        r = concl.iloc[0]
        d.trace.append({"tabela": "analysis_status.csv", "linha": "bloco=horarios:conclusao_principal",
                        "coluna": "status", "valor": r.status})
        d.line(f"Conclusão temporal principal: **{r.status}** — {r.motivo}")
    if blocked:
        d.prose("Sem suporte documental suficiente, a comparação entre encerramento próximo do limite e "
                "encerramento tardio não é apresentada.")
    else:
        bc = _read(analytics, "closure_band_counts.csv")
        if not bc.empty:
            main = bc[bc.papel == "principal"]
            piv = main.pivot(index="faixa", columns="nr_turno", values="secoes")
            piv.columns = [f"secoes_t{c}" for c in piv.columns]
            d.table("closure_band_counts.csv", piv.reset_index(), ["faixa"] + list(piv.columns),
                    {c: "int" for c in piv.columns}, filtro="papel=principal")
        adj = _read(analytics, "closure_adjusted.csv")
        if not adj.empty:
            d.prose("Comparações pré-especificadas de cada faixa com a referência, para as variações entre "
                    "turnos. Uma comparação sem suporte ou sem sobreposição de covariáveis não é estimada, "
                    "e o motivo é mostrado. São associações entre unidades, não efeitos do horário.")
            t = adj[(adj.papel == "principal") & (adj.recorte == "territorial")].copy()
            for c in ("diferenca_bruta", "beta_ajustado", "inf", "sup"):
                if c not in t:
                    t[c] = np.nan
            d.table("closure_adjusted.csv", t, ["agrupamento", "faixa", "desfecho", "status",
                                                "diferenca_bruta", "beta_ajustado", "inf", "sup", "motivo"],
                    {"diferenca_bruta": "f4", "beta_ajustado": "f4", "inf": "f4", "sup": "f4"},
                    filtro="papel=principal, recorte=territorial")
    oc = _read(analytics, "closure_ocorrencias.csv")
    oc_st_row = st_all[st_all.bloco == "horarios:ocorrencias"] if not st_all.empty else pd.DataFrame()
    if not oc.empty and "anexo_v_secoes" in oc.columns:
        oc_ok = (not oc_st_row.empty and (oc_st_row.status == "PASS").all()
                 and ("status_conciliacao" not in oc.columns or (oc.status_conciliacao == "PASS").all()))
        if oc_ok:
            d.prose("Ocorrências especiais de correspondência e substituição de urna registradas no Anexo V "
                    "do Relatório de Totalização oficial e conciliadas contra as correspondências efetivadas "
                    "registradas no manifesto:")
        else:
            st_val = oc_st_row.iloc[0].status if not oc_st_row.empty else "NAO_VERIFICADO"
            mot_val = oc_st_row.iloc[0].motivo if not oc_st_row.empty else "CEFT ausente ou divergente"
            d.trace.append({"tabela": "analysis_status.csv", "linha": "bloco=horarios:ocorrencias",
                            "coluna": "status", "valor": st_val})
            d.line(f"Reconciliação de ocorrências de urna: **{st_val}** — {mot_val}")
            d.prose("Sem fonte de correspondência efetivada validada no manifesto e conciliada sem "
                    "divergências, as ocorrências do Anexo V não são dadas como reconciliadas:")
        cols_oc = [c for c in ("sg_uf", "nr_turno", "secoes_closure", "anexo_v_secoes", "anexo_v_troca_urna",
                               "anexo_v_red_mesma_urna", "anexo_v_sistema_apuracao",
                               "ceft_divergencias_conciliadas_dif", "status_conciliacao") if c in oc.columns]
        d.table("closure_ocorrencias.csv", oc, cols_oc,
                {c: "int" for c in ("nr_turno", "secoes_closure", "anexo_v_secoes", "anexo_v_troca_urna",
                                    "anexo_v_red_mesma_urna", "anexo_v_sistema_apuracao",
                                    "ceft_divergencias_conciliadas_dif")})

    d.prose("## Blocos não estimados ou bloqueados")
    st = _read(analytics, "analysis_status.csv")
    if not st.empty:
        d.table("analysis_status.csv", st[st.status != "PASS"], ["bloco", "status", "motivo"])

    d.prose("## Limitações")
    d.prose("- A unidade é a seção ou o agregado de seções; nada aqui é atribuível a eleitores.\n"
            "- O perfil cadastral foi gerado meses antes da eleição e descreve aptos, não votantes.\n"
            "- Taxas de transição dependem de hipóteses não testáveis com totais por seção.\n"
            "- Horários de encerramento sem fuso documentado ficam fora do resultado principal.\n"
            "- Intervalos de modelo não são margem de erro da contagem de votos.")

    text = d.render()
    out.mkdir(parents=True, exist_ok=True)
    (out / "relatorio.md").write_text(text, encoding="utf-8")
    pd.DataFrame(d.trace).to_csv(out / "relatorio_rastro.csv", index=False)
    from br2026.reporting.pilot_comparative import build_pilot_comparative_report
    comp_res = build_pilot_comparative_report(analytics, out)
    return {
        "status": "PASS",
        "rastro": len(d.trace),
        "bytes": len(text.encode("utf-8")),
        "relatorio_comparativo": comp_res.get("status", "BLOCKED"),
        "escopo": comp_res.get("escopo"),
    }
