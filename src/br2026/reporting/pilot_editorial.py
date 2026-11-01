"""Versão editorial do piloto T1×T2 (handoff 24): resumo executivo, relatório principal e apêndice.

Os três documentos saem das mesmas tabelas de `tabelas_piloto/` e `data/analytics/`. Todo número
passa por `Doc.cite` ou `Doc.table` e vai para `RASTRO_RELATORIO_PILOTO.csv` (coluna `documento`).
O texto fixo (`prose`) não tem números; frases com números são montadas a partir dos dados, e
qualquer juízo (por exemplo, "maior", "virou") é condicionado ao valor calculado.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from br2026.reporting.build import Doc, _read

UF_NOME = {"AC": "Acre", "RS": "Rio Grande do Sul", "MG": "Minas Gerais", "TOTAL": "Piloto (3 UFs)"}
UF_EM = {"AC": "no Acre", "RS": "no Rio Grande do Sul", "MG": "em Minas Gerais", "TOTAL": "no piloto"}


def _nome(uf) -> str:
    return UF_NOME.get(str(uf), str(uf))


def _em(uf) -> str:
    return UF_EM.get(str(uf), f"em {uf}")


def _ufs(t: dict) -> list[str]:
    """UFs do piloto na ordem da tab01 (sem o total)."""
    return [str(u) for u in t["tab01"].sg_uf if str(u) != "TOTAL"]

STATUS_LEGIVEL = {
    "REPRODUZIDA": "reproduzida",
    "PARCIALMENTE_REPRODUZIDA": "parcialmente reproduzida",
    "DIRECAO_REPRODUZIDA_MAGNITUDE_DIFERE": "direção reproduzida; magnitude difere",
    "DIVERGENTE": "divergente",
    "NAO_IDENTIFICAVEL": "não identificável com estes dados",
    "NAO_TESTAVEL_COM_INSUMOS": "não testável com os insumos deste ciclo",
    "NAO_REPRODUZIDA": "não reproduzida",
    "REFUTADA_NO_SENTIDO_ARITMETICO": "refutada no sentido aritmético",
    "INCOMPATIVEL_NO_CENARIO_E_NAO_NECESSARIA": "incompatível no cenário testado e não necessária",
    "COMPATIVEL_NAO_NECESSARIA": "compatível, mas não necessária",
    "PARCIALMENTE_VERDADEIRA_NA_CONTAGEM": "parcialmente verdadeira na contagem; vínculo com fraude não testável",
    "REFUTADA_NA_CONTAGEM": "refutada na contagem",
    "SUPORTE_INSUFICIENTE_NO_PILOTO": "suporte insuficiente no piloto",
}

TERMO = {
    "CAND_14": "Renan Santos (MISSÃO)", "CAND_55": "Ronaldo Caiado (PSD)", "CAND_70": "Augusto Cury (AVANTE)",
    "OUTROS": "demais candidatos menores", "LULA_T1": "Lula no 1º turno", "FLAVIO_T1": "Flávio no 1º turno",
    "BRANCO": "brancos no 1º turno", "NULO": "nulos no 1º turno",
    "perfil_faixa_etaria_16_24": "aptos de 16 a 24 anos", "perfil_faixa_etaria_45_59": "aptos de 45 a 59 anos",
    "perfil_faixa_etaria_60_mais": "aptos com 60 anos ou mais", "perfil_genero_feminino": "aptos mulheres",
    "perfil_grau_escolaridade_ate_fund_incompleto": "aptos até fundamental incompleto",
    "perfil_grau_escolaridade_fund_completo_medio_incompleto": "aptos com fundamental completo",
    "perfil_grau_escolaridade_superior_completo": "aptos com superior completo",
}
REFERENCIA = {"ABSTENCAO": "abstenção no 1º turno", "25_44": "25 a 44 anos", "masculino": "homens",
              "medio_completo_sup_incompleto": "médio completo"}


def _r(df: pd.DataFrame, key: str, val) -> pd.Series:
    return df[df[key].astype(str) == str(val)].iloc[0]


def _resumo(d: Doc, t: dict, ctr: pd.DataFrame | None) -> None:
    t1, t7, t3 = t["tab01"], t["tab07"], t["tab03"]
    f1, f7, f3 = "tab01_resumo_uf_t1_t2.csv", "tab07_identidade_saldos_e_teste_100pct.csv", "tab03_sensibilidade_agregacao_uf.csv"
    tot = _r(t1, "sg_uf", "TOTAL")
    k = {"sg_uf": "TOTAL"}
    d.prose("# Resumo executivo — piloto AC, RS e MG, 1º × 2º turno de 2026")
    d.line(
        "**Escopo.** Acre, Rio Grande do Sul e Minas Gerais, todas as seções, em "
        f"{d.cite(f1, k, 'n_unidades', int(tot['n_unidades']), 'int')} unidades comparáveis entre os turnos. "
        "Os totais de cada UF e turno conferem exatamente com o resultado oficial do TSE. Três UFs não "
        "representam o país: este não é um estudo nacional.")
    d.prose("## O que mudou")
    m1, m2 = float(tot["margem_lula_flavio_validos_t1"]), float(tot["margem_lula_flavio_validos_t2"])
    d.line(
        f"- **Margem.** A diferença Lula − Flávio sobre os votos válidos foi de "
        f"{d.cite(f1, k, 'margem_lula_flavio_validos_t1', m1, 'pp')} no 1º turno para "
        f"{d.cite(f1, k, 'margem_lula_flavio_validos_t2', m2, 'pp')} no 2º. Lula ganhou "
        f"{d.cite(f1, k, 'delta_qt_lula', int(tot['delta_qt_lula']), 'int')} votos e Flávio, "
        f"{d.cite(f1, k, 'delta_qt_flavio', int(tot['delta_qt_flavio']), 'int')}.")
    viradas = [uf for uf in _ufs(t)
               if np.sign(_r(t1, "sg_uf", uf)["margem_lula_flavio_validos_t1"]) != np.sign(_r(t1, "sg_uf", uf)["margem_lula_flavio_validos_t2"])]
    partes = []
    for uf in _ufs(t):
        r = _r(t1, "sg_uf", uf)
        v = float(r["delta_margem_lula_flavio_validos"])
        partes.append(f"{d.cite(f1, {'sg_uf': uf}, 'delta_margem_lula_flavio_validos', v, 'pp')} {_em(uf)}")
    sentido = "a favor de Lula" if all(float(_r(t1, "sg_uf", u)["delta_margem_lula_flavio_validos"]) > 0
                                       for u in _ufs(t)) else "de forma diferente entre as UFs"
    d.line(f"- **Por UF**, a margem se deslocou {sentido}: " + ", ".join(partes) + "."
           + (f" A liderança mudou de lado {', '.join(_em(u) for u in viradas)}." if viradas else ""))
    abst = {uf: float(_r(t1, "sg_uf", uf)["delta_abstencao_aptos"]) for uf in _ufs(t)}
    sobe = [uf for uf, v in abst.items() if v > 0]
    d.line(
        f"- **Participação.** A abstenção sobre os aptos variou "
        f"{d.cite(f1, k, 'delta_abstencao_aptos', float(tot['delta_abstencao_aptos']), 'pp')} no piloto"
        + (", mas subiu " + ", ".join(f"{_em(u)} ({d.cite(f1, {'sg_uf': u}, 'delta_abstencao_aptos', abst[u], 'pp')})"
                                      for u in sobe) if sobe else "")
        + f". Os votos brancos variaram {d.cite(f1, k, 'delta_qt_votos_brancos', int(tot['delta_qt_votos_brancos']), 'int')} "
        f"e os nulos, {d.cite(f1, k, 'delta_qt_votos_nulos', int(tot['delta_qt_votos_nulos']), 'int')}.")
    t2 = t["tab02"]
    lul = t2[t2.candidato.astype(str).str.startswith("Lula")]
    tops = []
    for uf in _ufs(t):
        g = lul[lul.sg_uf == uf]
        if not g.empty:
            r = g.loc[g.contribuicao_delta_votos.abs().idxmax()]
            tops.append(f"{str(r.get('nm_municipio', r['cd_municipio_tse'])).title()} "
                        f"({d.cite('tab02_top_municipios_contribuicao.csv', {'sg_uf': uf, 'cd_municipio_tse': str(r['cd_municipio_tse']), 'candidato': 'Lula'}, 'contribuicao_delta_votos', int(r['contribuicao_delta_votos']), 'int')} votos)")
    if tops:
        d.line("- **Onde.** O município que mais acrescentou votos a Lula em cada UF foi " + ", ".join(tops) + ".")
    t5 = t["tab05"]
    a = t5[(t5.familia == "ef_municipio") & (t5.recorte == "territorial") & (t5.desfecho == "delta_share_lula_validos")
           & t5.termo.isin(["CAND_14", "CAND_55", "CAND_70", "OUTROS"])]
    if not a.empty:
        r = a.loc[a.pp_por_10pp_ajustado.idxmax()]
        sinal = "maior" if (a.pp_por_10pp_inf_ajustado > 0).all() else "variável"
        d.line("- **Bases iniciais.** Dentro de um mesmo município, o avanço de Lula foi "
               f"{sinal} onde os candidatos eliminados tiveram mais votos no 1º turno, comparado a unidades com "
               "mais abstenção; o maior coeficiente é o de "
               f"{TERMO[r['termo']]}: {d.cite('tab05_associacoes_perfil_t1_t2.csv', {'termo': r['termo'], 'recorte': 'territorial', 'familia': 'ef_municipio'}, 'pp_por_10pp_ajustado', float(r['pp_por_10pp_ajustado']), 'f4')} "
               "p.p. por dez pontos a mais de votos dele no lugar da abstenção. É associação entre unidades, não "
               "transferência de eleitores.")
    tt = _r(t7, "sg_uf", "TOTAL")
    d.line(
        f"- **Saldos.** Os demais candidatos tiveram {d.cite(f7, k, 'o1_demais_candidatos_t1', int(tt['o1_demais_candidatos_t1']), 'int')} "
        f"votos no 1º turno. A conta ΔLula + ΔFlávio = votos dos demais + Δválidos fecha com diferença "
        f"{d.cite(f7, k, 'identidade_saldos_dif', int(tt['identidade_saldos_dif']), 'int')}. Ela explica os saldos, "
        "não de onde vieram os votos.")
    d.prose("## O que os dados não permitem dizer")
    d.line(
        "- **Quem votou em quem.** O voto é secreto e os dados são agregados: não há como saber que fração dos "
        "eleitores de terceiros, ou de quem se absteve no 1º turno, votou em Lula no 2º. A hipótese de que "
        "\"todos os votos dos demais foram para Lula\" não é necessária para explicar o resultado (limite mínimo "
        f"{d.cite(f7, k, 'limite_min_demais_para_lula', float(tt['limite_min_demais_para_lula']), 'pct')}) e, no "
        "cenário de unidades estáveis, é incompatível em "
        f"{d.cite(f7, k, 'unidades_que_impedem_100pct', int(tt['unidades_que_impedem_100pct']), 'int')} unidades "
        f"({d.cite(f7, k, 'votos_demais_que_nao_cabem_em_lula', int(tt['votos_demais_que_nao_cabem_em_lula']), 'int')} votos)."
        if not bool(tt["teste_100pct_necessario"]) and not bool(tt["teste_100pct_possivel"]) else
        "- **Quem votou em quem.** O voto é secreto e os dados são agregados: as transições individuais não são "
        "identificáveis.")
    d.prose("- **Horários.** A comparação entre seções que fecharam às 17h e às 19h ainda não foi feita. O horário "
            "de votação está documentado, e os boletins de urna do 2º turno podem ser lidos seção a seção no portal "
            "Resultados; falta a cobertura completa das seções, que o projeto aguarda no arquivo consolidado de "
            "boletins do 2º turno do TSE.")
    if ctr is not None and not ctr.empty:
        d.prose("## Contraste com imprensa e alegações")
        n = len(ctr)
        rep = int(ctr.status_conclusao.isin(["REPRODUZIDA"]).sum())
        d.line(f"De {d.cite('contraste_resultados.csv', {'todas': True}, 'n_proposicoes', n, 'int')} proposições "
               f"examinadas, {d.cite('contraste_resultados.csv', {'status_conclusao': 'REPRODUZIDA'}, 'n', rep, 'int')} "
               "se reproduzem exatamente com os dados oficiais; as demais têm conclusão parcial, divergente ou não "
               "testável, detalhada por proposição no relatório e em `CONTRASTE_IMPRENSA_E_ALEGACOES.md`.")
    sa = t3.set_index("nivel_agregacao")
    d.prose("## Confiança")
    conf = ("- **Alta:** totais, margens e saldos, conferidos com o TSE nos dois turnos.\n"
            "- **Média:** a ligação das seções agregadas no 2º turno (decisão D-T2-01), que o TSE ainda não "
            "publicou de forma efetiva.")
    d.line(conf + (" Refazendo as contas só com unidades sem agregação, a margem muda "
                   f"{d.cite(f3, {'nivel_agregacao': 'SECAO_UNIDADE_SEM_AGREGACAO - SECAO_UNIDADE'}, 'delta_margem_lula_flavio_validos', float(sa.at['SECAO_UNIDADE_SEM_AGREGACAO', 'delta_margem_lula_flavio_validos'] - sa.at['SECAO_UNIDADE', 'delta_margem_lula_flavio_validos']), 'pp')}"
                   if {"SECAO_UNIDADE", "SECAO_UNIDADE_SEM_AGREGACAO"} <= set(sa.index) else ""))
    d.prose("- **Baixa:** qualquer taxa de transferência pontual entre candidatos, que depende de hipótese "
            "não verificável (modelo de taxas constantes, no apêndice técnico).\n"
            "- **Sem conclusão:** horários de votação e logs.")


def _relatorio(d: Doc, t: dict, figs: list[str], ctr: pd.DataFrame | None, analytics: Path) -> None:
    t1, t2, t3, t4, t5, t6, t7 = (t[k] for k in ("tab01", "tab02", "tab03", "tab04", "tab05", "tab06", "tab07"))
    f1, f2, f4, f5, f7 = ("tab01_resumo_uf_t1_t2.csv", "tab02_top_municipios_contribuicao.csv",
                          "tab04_limites_fluxos_agregados_uf.csv", "tab05_associacoes_perfil_t1_t2.csv",
                          "tab07_identidade_saldos_e_teste_100pct.csv")
    d.prose("# Lula × Flávio entre o 1º e o 2º turno de 2026 — piloto AC, RS e MG")
    d.prose("Relatório do piloto estadual. O resumo de uma página está em `RESUMO_EXECUTIVO_PILOTO.md` e as "
            "definições, tabelas completas e proveniência estão em `APENDICE_TECNICO_PILOTO.md`.")
    # d.line: o identificador da decisão (D-T2-01) tem dígitos, que o linter do texto fixo recusa
    d.line("## Como ler este relatório\n"
            "- **Unidade de análise:** a seção eleitoral, ou o grupo de seções que foram apuradas juntas em algum "
            "dos turnos. Os totais por UF são somas dessas unidades, nunca médias de percentuais.\n"
            "- **Dois denominadores:** participação nos votos válidos (sem brancos e nulos) e participação nos "
            "aptos (todo o eleitorado).\n"
            "- **Três tipos de resultado:** observado (contas exatas sobre os totais oficiais); cenário (vale sob "
            "hipóteses que são ditas no texto); não identificável (o dado agregado não responde).\n"
            "- **Fontes:** dados abertos do TSE por seção e resultado oficial por UF. No 2º turno, a ligação "
            "entre seções agregadas usa a decisão D-T2-01 (presença das seções no resultado do turno), porque o "
            "boletim de urna em formato aberto ainda não foi publicado.")
    # --- 1. O que mudou
    d.prose("## 1. O que mudou entre os turnos")
    tab_m = t1.assign(uf=t1.sg_uf.map(_nome))
    d.table(f1, tab_m, ["uf", "qt_lula_t1", "qt_lula_t2", "qt_flavio_t1", "qt_flavio_t2",
                        "margem_lula_flavio_validos_t1", "margem_lula_flavio_validos_t2", "delta_margem_lula_flavio_validos"],
            {c: "int" for c in ("qt_lula_t1", "qt_lula_t2", "qt_flavio_t1", "qt_flavio_t2")}
            | {c: "pp" for c in ("margem_lula_flavio_validos_t1", "margem_lula_flavio_validos_t2", "delta_margem_lula_flavio_validos")},
            headers={"uf": "UF", "qt_lula_t1": "Lula 1º turno", "qt_lula_t2": "Lula 2º turno",
                     "qt_flavio_t1": "Flávio 1º turno", "qt_flavio_t2": "Flávio 2º turno",
                     "margem_lula_flavio_validos_t1": "Margem 1º (Lula − Flávio, válidos)",
                     "margem_lula_flavio_validos_t2": "Margem 2º", "delta_margem_lula_flavio_validos": "Variação da margem"})
    for uf in _ufs(t):
        r = _r(t1, "sg_uf", uf)
        k = {"sg_uf": uf}
        dl, df_ = int(r["delta_qt_lula"]), int(r["delta_qt_flavio"])
        txt = (f"- **{_nome(uf)}:** Lula {'ganhou' if dl >= 0 else 'perdeu'} "
               f"{d.cite(f1, k, 'delta_qt_lula', abs(dl), 'int')} votos e Flávio {'ganhou' if df_ >= 0 else 'perdeu'} "
               f"{d.cite(f1, k, 'delta_qt_flavio', abs(df_), 'int')}.")
        if np.sign(r["margem_lula_flavio_validos_t1"]) != np.sign(r["margem_lula_flavio_validos_t2"]):
            txt += " A liderança mudou de lado."
        if df_ < 0 and r["delta_share_flavio_validos"] > 0:
            txt += (" Flávio perdeu votos e ainda assim subiu na participação, porque os válidos caíram "
                    f"({d.cite(f1, k, 'delta_qt_votos_validos', int(r['delta_qt_votos_validos']), 'int')}).")
        d.line(txt)
    if "fig01_resumo_uf_t1_t2.png" in figs:
        d.line("![Figura 1 — Variação entre turnos por UF](figuras_piloto/fig01_resumo_uf_t1_t2.png)")
    # --- 2. Onde
    d.prose("## 2. Onde: municípios que mais pesaram\n"
            "A variação de cada UF se decompõe exatamente na soma das contribuições dos seus municípios. A "
            "contribuição é contábil: mede quanto o município moveu o total da UF, não por que.")
    tm = t2[t2.candidato.astype(str).str.startswith("Lula")].copy()
    tm["uf"] = tm.sg_uf.map(_nome)
    tm["municipio"] = tm.get("nm_municipio", tm.cd_municipio_tse).astype(str).str.title()
    d.table(f2, tm, ["uf", "municipio", "contribuicao_delta_share", "contribuicao_delta_votos"],
            {"contribuicao_delta_share": "pp3", "contribuicao_delta_votos": "int"},
            filtro="cinco maiores contribuições por UF, Lula",
            headers={"uf": "UF", "municipio": "Município", "contribuicao_delta_share": "Contribuição à variação de Lula na UF",
                     "contribuicao_delta_votos": "Votos de Lula a mais"})
    if "fig02_contribuicoes_municipais_uf.png" in figs:
        d.line("![Figura 2 — Municípios com maior contribuição](figuras_piloto/fig02_contribuicoes_municipais_uf.png)")
    # --- 3. Participação e não válidos
    d.prose("## 3. Participação, brancos e nulos")
    tab_p = t1.assign(uf=t1.sg_uf.map(_nome))
    d.table(f1, tab_p, ["uf", "abstencao_aptos_t1", "abstencao_aptos_t2", "delta_abstencao_aptos",
                        "delta_qt_comparecimento", "delta_qt_votos_brancos", "delta_qt_votos_nulos", "delta_qt_votos_validos"],
            {"abstencao_aptos_t1": "pct", "abstencao_aptos_t2": "pct", "delta_abstencao_aptos": "pp",
             "delta_qt_comparecimento": "int", "delta_qt_votos_brancos": "int", "delta_qt_votos_nulos": "int",
             "delta_qt_votos_validos": "int"},
            headers={"uf": "UF", "abstencao_aptos_t1": "Abstenção 1º", "abstencao_aptos_t2": "Abstenção 2º",
                     "delta_abstencao_aptos": "Variação", "delta_qt_comparecimento": "Δ comparecimento",
                     "delta_qt_votos_brancos": "Δ brancos", "delta_qt_votos_nulos": "Δ nulos",
                     "delta_qt_votos_validos": "Δ válidos"})
    d.prose("Os saldos fecham numa conta exata: o que Lula e Flávio ganharam juntos é igual aos votos que os "
            "demais candidatos tiveram no 1º turno mais a variação dos votos válidos; e a variação dos válidos é a "
            "do comparecimento menos as de brancos e nulos. A conta explica saldos, não trajetórias de eleitores.")
    for uf in (*_ufs(t), "TOTAL"):
        r = _r(t7, "sg_uf", uf)
        k = {"sg_uf": uf}
        d.line(f"- **{_nome(uf)}:** {d.cite(f7, k, 'delta_lula', int(r['delta_lula']), 'int')} + "
               f"{d.cite(f7, k, 'delta_flavio', int(r['delta_flavio']), 'int')} = "
               f"{d.cite(f7, k, 'o1_demais_candidatos_t1', int(r['o1_demais_candidatos_t1']), 'int')} + "
               f"{d.cite(f7, k, 'delta_validos', int(r['delta_validos']), 'int')} (diferença "
               f"{d.cite(f7, k, 'identidade_saldos_dif', int(r['identidade_saldos_dif']), 'int')}).")
    tb = _read(analytics, "turnout_bounds.csv")
    if not tb.empty and "variacao_liquida_comparecimento_com_limites" in tb.columns:
        r = tb.iloc[0]
        kk = {"universo": r["universo"]}
        d.line(f"O saldo do comparecimento não conta pessoas. Nas "
               f"{d.cite('turnout_bounds.csv', kk, 'unidades_com_limites', int(r['unidades_com_limites']), 'int')} "
               "unidades com o mesmo número de aptos nos dois turnos, e supondo os mesmos eleitores, o saldo de "
               f"{d.cite('turnout_bounds.csv', kk, 'variacao_liquida_comparecimento_com_limites', int(r['variacao_liquida_comparecimento_com_limites']), 'int')} "
               "é compatível com algo entre "
               f"{d.cite('turnout_bounds.csv', kk, 'entradas_min', int(r['entradas_min']), 'int')} e "
               f"{d.cite('turnout_bounds.csv', kk, 'entradas_max', int(r['entradas_max']), 'int')} pessoas "
               "que passaram a votar, com saídas simultâneas.")
    if "fig03_decomposicao_comparecimento_nao_validos.png" in figs:
        d.line("![Figura 3 — Composição do eleitorado apto](figuras_piloto/fig03_decomposicao_comparecimento_nao_validos.png)")
    # --- 4. Bases iniciais e perfil
    d.prose("## 4. Bases iniciais e perfil do eleitorado\n"
            "Comparamos unidades dentro do mesmo município (efeito fixo de município): onde a composição do "
            "voto no 1º turno ou o perfil cadastral dos aptos era diferente, quanto variou a participação de "
            "Lula? Os números abaixo são a variação, em pontos percentuais, associada a dez pontos a mais na "
            "categoria indicada (no lugar da referência), mantidos os demais termos. São associações entre "
            "unidades, não comportamento de eleitores.")
    a = t5[(t5.familia == "ef_municipio") & (t5.recorte == "territorial") & (t5.desfecho == "delta_share_lula_validos")
           & t5.termo.isin(TERMO)].copy()
    a["categoria"] = a.termo.map(TERMO)
    a["referencia_legivel"] = a.referencia.map(lambda v: REFERENCIA.get(str(v), str(v)))
    d.table(f5, a, ["categoria", "referencia_legivel", "pp_por_10pp_ajustado", "pp_por_10pp_inf_ajustado",
                    "pp_por_10pp_sup_ajustado"],
            {"pp_por_10pp_ajustado": "f4", "pp_por_10pp_inf_ajustado": "f4", "pp_por_10pp_sup_ajustado": "f4"},
            filtro="efeito fixo de município, todas as unidades, desfecho Δ participação de Lula",
            headers={"categoria": "Categoria (+10 p.p.)", "referencia_legivel": "No lugar de",
                     "pp_por_10pp_ajustado": "Δ Lula (p.p.)", "pp_por_10pp_inf_ajustado": "IC 95% inf.",
                     "pp_por_10pp_sup_ajustado": "IC 95% sup."})
    if "fig04_associacoes_perfil_simples_vs_ajustado.png" in figs:
        d.line("![Figura 4 — Associações simples e ajustadas](figuras_piloto/fig04_associacoes_perfil_simples_vs_ajustado.png)")
    comp = a[a.termo.isin(["CAND_14", "CAND_55", "CAND_70", "OUTROS"])]
    if not comp.empty:
        r = comp.loc[comp.pp_por_10pp_ajustado.idxmax()]
        d.line(f"Os maiores coeficientes são os dos candidatos eliminados no 1º turno: o de {TERMO[r['termo']]} é "
               f"{d.cite(f5, {'termo': r['termo'], 'recorte': 'territorial', 'familia': 'ef_municipio'}, 'pp_por_10pp_ajustado', float(r['pp_por_10pp_ajustado']), 'f4')} "
               "p.p. Isso é compatível com várias trajetórias (eleitores desses candidatos votando em Lula, "
               "eleitores que mudaram de lado, ou comparecimento diferente nessas unidades), que os dados não "
               "separam." if (comp.pp_por_10pp_ajustado == comp.pp_por_10pp_ajustado.max()).any()
               and float(r["pp_por_10pp_ajustado"]) >= float(a.pp_por_10pp_ajustado.max()) else
               "Os coeficientes dos candidatos eliminados não são os maiores da tabela.")
    if ctr is not None and "C06" in set(ctr.claim_id):
        r = _r(ctr, "claim_id", "C06")
        d.line("Entre municípios do piloto (comparação com o El País): "
               f"{d.cite('contraste_resultados.csv', {'claim_id': 'C06'}, 'resultado_numerico', str(r['resultado_numerico']), None)}.")
    # --- 5. Não identificável
    d.prose("## 5. O que os dados não identificam: transferências entre candidatos\n"
            "As marginais de cada unidade (quantos votaram em quem em cada turno) limitam, mas não determinam, "
            "quantos eleitores passaram de uma opção a outra. A tabela mostra, para cada origem no 1º turno e "
            "destino no 2º, o intervalo de frações compatível com os dados no piloto.")
    t4v = t4[t4.destino.isin(["LULA", "FLAVIO"])].copy() if "destino" in t4.columns else t4
    d.table(f4, t4v, ["origem_rotulo", "destino_rotulo", "taxa_min", "taxa_max"],
            {"taxa_min": "pct", "taxa_max": "pct"}, filtro="destinos Lula e Flávio",
            headers={"origem_rotulo": "No 1º turno", "destino_rotulo": "No 2º turno", "taxa_min": "Fração mínima",
                     "taxa_max": "Fração máxima"})
    if "tab08" in t:
        d.prose("Uma matriz pontual de transferências só existe sob a hipótese adicional de taxas constantes "
                "entre unidades, que os dados não permitem verificar; ela fica no apêndice técnico.")
    else:
        mot = (str(t4["motivo_nao_publicacao"].iloc[0]) if "motivo_nao_publicacao" in t4.columns and not t4.empty
               else "sem motivo registrado")
        d.line("A matriz pontual de taxas constantes **não é publicada**: a regra pré-registrada a reprovou "
               f"(motivo: `{mot}`).")
    tt = _r(t7, "sg_uf", "TOTAL")
    k = {"sg_uf": "TOTAL"}
    d.line(
        "**\"Todos os votos dos demais foram para Lula?\"** No cenário de unidades estáveis (cada eleitor vota na "
        "mesma unidade nos dois turnos) e cadastro com rotatividade mínima: "
        + ("é *possível*" if bool(tt["teste_100pct_possivel"]) else
           f"é *incompatível* em {d.cite(f7, k, 'unidades_que_impedem_100pct', int(tt['unidades_que_impedem_100pct']), 'int')} "
           f"unidades, onde {d.cite(f7, k, 'votos_demais_que_nao_cabem_em_lula', int(tt['votos_demais_que_nao_cabem_em_lula']), 'int')} "
           "votos dos demais não cabem nos votos de Lula — uma impossibilidade que se apoia em poucos votos e "
           "desaparece se eleitores puderem mudar de unidade")
        + "; "
        + ("é *necessária*" if bool(tt["teste_100pct_necessario"]) else
           f"*não é necessária* (limite mínimo {d.cite(f7, k, 'limite_min_demais_para_lula', float(tt['limite_min_demais_para_lula']), 'pct')})")
        + "; e *não é observável*, porque o voto é secreto. "
        + (f"O ganho de Lula equivale a {d.cite(f7, k, 'razao_delta_lula_sobre_o1', float(tt['razao_delta_lula_sobre_o1']), 'pct')} "
           "dos votos dos demais: mesmo uma transferência integral não fecharia a conta sem outras origens "
           "(comparecimento, brancos e nulos, ou eleitores de Flávio no 1º turno)."
           if float(tt["razao_delta_lula_sobre_o1"]) > 1 else ""))
    # --- 6. Horários e operação
    d.prose("## 6. Horários e ocorrências de urna")
    st = _read(analytics, "analysis_status.csv")
    sti = st.set_index("bloco") if not st.empty else pd.DataFrame()
    if "horarios:conclusao_principal" in sti.index:
        d.line("- **17h × 19h:** sem conclusão (estado "
               f"{d.cite('analysis_status.csv', {'bloco': 'horarios:conclusao_principal'}, 'status', str(sti.at['horarios:conclusao_principal', 'status']), None)}"
               "): o staging ainda não tem os horários de encerramento do 2º turno.")
    d.prose("- **Situação dos horários:** o horário de votação está documentado, e os dados indicam que o relógio "
            "do boletim marca a hora local. Os boletins do 2º turno podem ser lidos seção a seção no portal "
            "Resultados, mas só uma amostra foi lida; a cobertura completa aguarda o arquivo consolidado do TSE. "
            "Ver `PROVA_CONCEITO_HORARIOS.md`.")
    oc = (t6[t6.nr_turno == 1] if "nr_turno" in t6.columns else t6).assign(uf=lambda x: x.sg_uf.map(_nome))
    cols6 = [c for c in ("uf", "anexo_v_secoes", "anexo_v_troca_urna", "anexo_v_red_mesma_urna", "status_conciliacao")
             if c in oc.columns]
    d.table("tab06_auditoria_operacional_uf.csv", oc if len(cols6) > 1 else oc.iloc[0:0], cols6,
            {"anexo_v_secoes": "int", "anexo_v_troca_urna": "int", "anexo_v_red_mesma_urna": "int"},
            filtro="1º turno; o 2º turno não tem Anexo V nem CEFT publicados",
            headers={"uf": "UF", "anexo_v_secoes": "Seções com ocorrência (1º turno)",
                     "anexo_v_troca_urna": "Troca de urna", "anexo_v_red_mesma_urna": "Recuperação na mesma urna",
                     "status_conciliacao": "Concilia com a CEFT"})
    d.prose("Uma ocorrência documentada e conciliada não é, por si, indício de irregularidade, nem dispensa "
            "auditoria; a tabela mostra que dois registros oficiais independentes concordam.")
    # --- 7. Contraste
    if ctr is not None and not ctr.empty:
        d.prose("## 7. Contraste com imprensa e alegações\n"
                "Cada proposição foi reproduzida com os dados oficiais no mesmo universo possível, com a conclusão "
                "tirada de condições verificadas. Detalhes, fontes e limites em `CONTRASTE_IMPRENSA_E_ALEGACOES.md`.")
        c = ctr.sort_values("claim_id").copy()
        c["conclusao"] = c.status_conclusao.map(lambda s: STATUS_LEGIVEL.get(str(s), str(s)))
        d.table("contraste_resultados.csv", c, ["claim_id", "afirmacao_resumo", "conclusao"],
                headers={"claim_id": "Prop.", "afirmacao_resumo": "Afirmação (paráfrase)", "conclusao": "Conclusão"})


def _apendice(d: Doc, t: dict, man: dict, analytics: Path) -> None:
    d.prose("# Apêndice técnico — piloto AC, RS e MG")
    d.prose("## A.1 Definições\n"
            "Participação nos válidos = votos do candidato / votos válidos. Margem = participação de Lula − "
            "participação de Flávio. Abstenção sobre aptos = abstenções / aptos. Todas as razões são razões de "
            "somas no universo indicado.")
    d.prose("## A.2 Cobertura e reconciliação")
    cov = _read(analytics, "coverage_uf.csv")
    d.table("coverage_uf.csv", cov, ["sg_uf", "unidades_incluida", "unidades_excluida", "qt_aptos_t1_pct_incluida",
                                      "qt_votos_validos_t2_pct_incluida"],
            {"unidades_incluida": "int", "unidades_excluida": "int", "qt_aptos_t1_pct_incluida": "pct",
             "qt_votos_validos_t2_pct_incluida": "pct"})
    rec = _read(analytics, "panel_reconciliation.csv")
    d.line(f"Soma absoluta das diferenças seção → painel nos dois turnos: "
           f"{d.cite('panel_reconciliation.csv', {'todas': True}, 'dif', int(rec.dif.abs().sum()), 'int')}.")
    d.line("## A.3 Correspondência de seções e sensibilidade (D-T2-01)\n"
            "1º turno: agregação pelo BU web (`DS_SECOES_AGREGADAS`). 2º turno: sem BU web nem CEFT publicados, a "
            "agregação do cadastro é aceita quando a seção agregada não tem apuração própria no detalhe do turno "
            "e a principal tem; conflito vira ambígua. A sensibilidade refaz as métricas só com unidades de uma "
            "seção de origem.")
    t3 = t["tab03"]
    d.table("tab03_sensibilidade_agregacao_uf.csv", t3, list(t3.columns),
            {c: ("pp" if c.startswith("delta") else "int") for c in t3.columns if c != "nivel_agregacao"})
    d.prose("## A.4 Tabela completa por UF")
    t1 = t["tab01"]
    cols1 = ["sg_uf", "qt_aptos_t1", "qt_aptos_t2", "qt_comparecimento_t1", "qt_comparecimento_t2",
             "qt_votos_validos_t1", "qt_votos_validos_t2", "qt_votos_brancos_t1", "qt_votos_brancos_t2",
             "qt_votos_nulos_t1", "qt_votos_nulos_t2", "share_lula_validos_t1", "share_lula_validos_t2",
             "share_flavio_validos_t1", "share_flavio_validos_t2"]
    d.table("tab01_resumo_uf_t1_t2.csv", t1, cols1,
            {c: ("pct" if c.startswith("share") else "int") for c in cols1 if c != "sg_uf"})
    if "tab08" in t:
        t8 = t["tab08"]
        f8 = "tab08_modelo_taxas_constantes_apendice.csv"
        d.prose("## A.5 Modelo de taxas constantes (dependente de hipótese)\n"
                "Sob a hipótese de que a taxa de cada origem para cada destino é igual em todas as unidades, a "
                "regressão ecológica dá um parâmetro β. β vem de um ajuste aproximado (com resíduo) e não é um "
                "fluxo; pode cair fora dos limites exatos. A taxa IPF vem de tabelas por unidade que conservam as "
                "marginais, semeadas por β, e por isso respeita os limites. Nenhuma das duas descreve trajetórias "
                "individuais, e a hipótese não é verificável.")
        n_fora = int((~t8["beta_dentro_dos_limites"].astype(bool)).sum())
        n_ipf = int((~t8["ipf_dentro_dos_limites"].astype(bool)).sum())
        d.line(f"β fora dos limites: {d.cite(f8, {'beta_dentro_dos_limites': False}, 'n_celulas', n_fora, 'int')} "
               f"célula(s); IPF fora dos limites: {d.cite(f8, {'ipf_dentro_dos_limites': False}, 'n_celulas', n_ipf, 'int')}.")
        d.table(f8, t8, ["origem_rotulo", "destino_rotulo", "taxa_min", "taxa_max", "beta_parametro",
                         "beta_bootstrap_inf", "beta_bootstrap_sup", "beta_dentro_dos_limites", "taxa_ipf",
                         "ipf_dentro_dos_limites"],
                {"taxa_min": "pct", "taxa_max": "pct", "beta_parametro": "pct", "beta_bootstrap_inf": "pct",
                 "beta_bootstrap_sup": "pct", "taxa_ipf": "pct"})
    d.prose("## A.6 Associações completas")
    t5 = t["tab05"]
    d.table("tab05_associacoes_perfil_t1_t2.csv", t5,
            ["familia", "especificacao_ajustada", "desfecho", "recorte", "termo", "referencia", "unidade_termo",
             "pp_por_10pp_simples", "pp_por_10pp_ajustado", "pp_por_10pp_inf_ajustado", "pp_por_10pp_sup_ajustado",
             "n", "grupos_cluster"],
            {"pp_por_10pp_simples": "f4", "pp_por_10pp_ajustado": "f4", "pp_por_10pp_inf_ajustado": "f4",
             "pp_por_10pp_sup_ajustado": "f4", "n": "int", "grupos_cluster": "int"})
    d.prose("Recortes por UF do Acre e do Rio Grande do Sul não foram estimados: categorias \"desconhecido\" do "
            "perfil não variam dentro dos municípios (ver `analysis_status.csv`).")
    d.prose("## A.7 Proveniência")
    ins = pd.DataFrame([{"insumo": k, "sha256": v} for k, v in sorted(man.get("insumos_sha256", {}).items())])
    d.table("analysis_manifest.json:insumos_sha256", ins, ["insumo", "sha256"])
    fb = pd.DataFrame(man.get("fontes_brutas", []))
    if not fb.empty:
        if "fonte" not in fb.columns:
            fb["fonte"] = ""
        fb["fonte"] = fb["fonte"].fillna("")
        d.table("analysis_manifest.json:fontes_brutas", fb.sort_values(["tabela", "nr_turno", "fonte"]),
                ["tabela", "nr_turno", "fonte", "source_id"])
    dirty = man.get("codigo_com_alteracoes_nao_commitadas")
    estado = {True: "sim", False: "não"}.get(dirty, f"desconhecido ({man.get('git_diagnostico') or 'sem diagnóstico'})")
    d.line(f"Commit `{man.get('git_commit')}` · código com alterações não commitadas: {estado} · contrato "
           f"`{man.get('contract_version')}` · execução `{man.get('executado_em_utc')}`.")


def write_editorial(out: Path, analytics: Path, tables: dict, figs: list[str], man: dict) -> dict:
    """Gera os três documentos e o rastro; devolve {documento: texto} já renderizado (linter aplicado)."""
    tab_dir = out / "tabelas_piloto"
    t = {"tab01": tables["tab01_resumo_uf_t1_t2.csv"], "tab02": tables["tab02_top_municipios_contribuicao.csv"],
         "tab03": tables["tab03_sensibilidade_agregacao_uf.csv"], "tab04": tables["tab04_limites_fluxos_agregados_uf.csv"],
         "tab05": tables["tab05_associacoes_perfil_t1_t2.csv"], "tab06": tables["tab06_auditoria_operacional_uf.csv"],
         "tab07": tables["tab07_identidade_saldos_e_teste_100pct.csv"]}
    if "tab08_modelo_taxas_constantes_apendice.csv" in tables:
        t["tab08"] = tables["tab08_modelo_taxas_constantes_apendice.csv"]
    cr = tab_dir / "contraste_resultados.csv"
    ctr = pd.read_csv(cr) if cr.exists() else None
    docs = {}
    traces = []
    for nome, fn in (("RESUMO_EXECUTIVO_PILOTO.md", lambda d: _resumo(d, t, ctr)),
                     ("RELATORIO_COMPARATIVO_PILOTO_T1_T2.md", lambda d: _relatorio(d, t, figs, ctr, analytics)),
                     ("APENDICE_TECNICO_PILOTO.md", lambda d: _apendice(d, t, man, analytics))):
        d = Doc()
        fn(d)
        docs[nome] = d.render()
        traces += [{**r, "documento": nome} for r in d.trace]
    return {"docs": docs, "trace": traces}
