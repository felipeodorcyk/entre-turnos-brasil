"""Versão editorial nacional T1×T2 (handoff 26): resumo executivo, relatório principal e apêndice.

Mesmas regras do piloto (`pilot_editorial`): os três documentos saem das tabelas de
`tabelas_nacional/` e de `data/analytics/`; todo número passa por `Doc.cite` ou `Doc.table` e vai
para `RASTRO_RELATORIO_NACIONAL.csv`; o texto fixo não tem números; juízos ("maior", "virou",
"em todas") são condicionados aos valores calculados. O exterior é uma camada à parte: entra nos
totais do Brasil e fica fora das regiões, das UFs e dos modelos territoriais.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from br2026.reporting.build import Doc, _read
from br2026.reporting.pilot_editorial import REFERENCIA, STATUS_LEGIVEL, TERMO

UF_NOME = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
    "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins", "TOTAL": "Território (27 UFs)", "ZZ": "Exterior",
}
UF_EM = {"AC": "no Acre", "AL": "em Alagoas", "AM": "no Amazonas", "AP": "no Amapá", "BA": "na Bahia",
         "CE": "no Ceará", "DF": "no Distrito Federal", "ES": "no Espírito Santo", "GO": "em Goiás",
         "MA": "no Maranhão", "MG": "em Minas Gerais", "MS": "em Mato Grosso do Sul", "MT": "em Mato Grosso",
         "PA": "no Pará", "PB": "na Paraíba", "PE": "em Pernambuco", "PI": "no Piauí", "PR": "no Paraná",
         "RJ": "no Rio de Janeiro", "RN": "no Rio Grande do Norte", "RO": "em Rondônia", "RR": "em Roraima",
         "RS": "no Rio Grande do Sul", "SC": "em Santa Catarina", "SE": "em Sergipe", "SP": "em São Paulo",
         "TO": "no Tocantins"}
MINUSCULAS = {"De", "Da", "Do", "Das", "Dos", "E", "D'Oeste"}
CAMADA = {"REGIAO_NORTE": "Norte", "REGIAO_NORDESTE": "Nordeste", "REGIAO_CENTRO_OESTE": "Centro-Oeste",
          "REGIAO_SUDESTE": "Sudeste", "REGIAO_SUL": "Sul", "TERRITORIO": "Território (27 UFs)",
          "EXTERIOR": "Exterior", "BRASIL": "Brasil"}
REGIOES = ("REGIAO_NORTE", "REGIAO_NORDESTE", "REGIAO_CENTRO_OESTE", "REGIAO_SUDESTE", "REGIAO_SUL")
F1, F2, F3, F4, F5 = ("tab01_resumo_uf_t1_t2.csv", "tab02_top_municipios_contribuicao.csv",
                      "tab03_sensibilidade_agregacao_uf.csv", "tab04_limites_fluxos_agregados_uf.csv",
                      "tab05_associacoes_perfil_t1_t2.csv")
F6, F7, F9, F10 = ("tab06_auditoria_operacional_uf.csv", "tab07_identidade_saldos_e_teste_100pct.csv",
                   "tab09_camadas_regioes_exterior.csv", "tab10_top_municipios_brasil.csv")
FIG = "figuras_nacional"
ELIMINADOS = ("CAND_14", "CAND_55", "CAND_70", "OUTROS")


def _nome(uf) -> str:
    return UF_NOME.get(str(uf), str(uf))


def _em(uf) -> str:
    return UF_EM.get(str(uf), f"em {_nome(uf)}")


def _fim(txt: str) -> str:
    """Ponto final sem duplicar o de "p.p."."""
    return txt if txt.endswith(".") else txt + "."


def _titulo(nome: str) -> str:
    """Nome de município em caixa de título, com preposições em minúscula (Rio de Janeiro)."""
    ps = str(nome).title().split(" ")
    return " ".join(w.lower() if i and w in MINUSCULAS else w for i, w in enumerate(ps))


def _r(df: pd.DataFrame, key: str, val) -> pd.Series:
    return df[df[key].astype(str) == str(val)].iloc[0]


def _ufs(t1: pd.DataFrame) -> list[str]:
    return [str(u) for u in t1.sg_uf if str(u) != "TOTAL"]


def _lista(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def _mun(r: pd.Series) -> str:
    n = r.get("nm_municipio")
    return f"{_titulo(n) if isinstance(n, str) else r['cd_municipio_tse']} ({r['sg_uf']})"


def _camada(d: Doc, cam: pd.DataFrame, nome: str, col: str, fmt: str) -> str:
    return d.cite(F9, {"camada": nome}, col, float(_r(cam, "camada", nome)[col]) if fmt != "int"
                  else int(_r(cam, "camada", nome)[col]), fmt)


# --------------------------------------------------------------------------- resumo
def _resumo(d: Doc, t: dict, ctr: pd.DataFrame | None, cor: pd.DataFrame | None, analytics: Path) -> None:
    t1, t7, cam, t3 = t["tab01"], t["tab07"], t["tab09"], t["tab03"]
    br = _r(cam, "camada", "BRASIL")
    d.prose("# Resumo executivo — Lula × Flávio, 1º × 2º turno de 2026, Brasil")
    n_ufs = len(_ufs(t1))
    cov = _read(analytics, "coverage_uf.csv")
    exc = cov[cov.unidades_excluida > 0] if not cov.empty else cov
    n_exc = int(cov.unidades_excluida.sum()) if not cov.empty else 0
    votos_exc = int(cov.qt_votos_validos_t1_excluida.sum() + cov.qt_votos_validos_t2_excluida.sum()) if not cov.empty else 0
    d.line(f"**Escopo.** As {d.cite(F1, {'sg_uf': '≠TOTAL'}, 'n_ufs', n_ufs, 'int')} UFs e o exterior, em "
           f"{_camada(d, cam, 'BRASIL', 'n_unidades', 'int')} unidades comparáveis entre os turnos, que reúnem todos os "
           "votos. Os totais de cada UF e do exterior, nos dois turnos, conferem exatamente com o resultado oficial do TSE."
           + (f" Ficam fora {d.cite('coverage_uf.csv', {'todas': True}, 'unidades_excluida', n_exc, 'int')} unidades "
              + ("do " if list(exc.sg_uf) == ["ZZ"] else f"({_lista([_nome(u) for u in exc.sg_uf])}) ")
              + ("exterior " if list(exc.sg_uf) == ["ZZ"] else "")
              + "sem apuração em nenhum turno"
              + (f", com {d.cite('coverage_uf.csv', {'todas': True}, 'votos_validos_excluidos', votos_exc, 'int')} votos."
                 if votos_exc else f" ({d.cite('coverage_uf.csv', {'todas': True}, 'votos_validos_excluidos', votos_exc, 'int')} votos válidos).")
              if n_exc else ""))
    _destaques(d, t, t.get("al", {}))
    d.prose("## O que mudou")
    dl, dfv = int(br["qt_lula_t2"] - br["qt_lula_t1"]), int(br["qt_flavio_t2"] - br["qt_flavio_t1"])
    d.line(f"- **Brasil.** A margem Lula − Flávio sobre os válidos foi de "
           f"{_camada(d, cam, 'BRASIL', 'margem_lula_flavio_validos_t1', 'pp')} no 1º turno para "
           f"{_camada(d, cam, 'BRASIL', 'margem_lula_flavio_validos_t2', 'pp')} no 2º "
           f"(variação de {_camada(d, cam, 'BRASIL', 'delta_margem_lula_flavio_validos', 'pp')}). Lula ganhou "
           f"{d.cite(F9, {'camada': 'BRASIL'}, 'qt_lula_t2 - qt_lula_t1', dl, 'int')} votos e Flávio, "
           f"{d.cite(F9, {'camada': 'BRASIL'}, 'qt_flavio_t2 - qt_flavio_t1', dfv, 'int')}.")
    reg = [(CAMADA[c], float(_r(cam, "camada", c)["delta_margem_lula_flavio_validos"])) for c in REGIOES
           if c in set(cam.camada)]
    sentido = ("a favor de Lula em todas as regiões" if all(v > 0 for _, v in reg)
               else "em sentidos diferentes entre as regiões")
    d.line(_fim(f"- **Regiões.** A margem se deslocou {sentido}: " + ", ".join(
        f"{n} {_camada(d, cam, c, 'delta_margem_lula_flavio_validos', 'pp')}"
        for (n, _), c in zip(reg, [c for c in REGIOES if c in set(cam.camada)]))))
    ufs = _ufs(t1)
    dm = {u: float(_r(t1, "sg_uf", u)["delta_margem_lula_flavio_validos"]) for u in ufs}
    pos = [u for u in ufs if dm[u] > 0]
    mx, mn = max(ufs, key=dm.get), min(ufs, key=dm.get)
    viradas = [u for u in ufs if np.sign(_r(t1, "sg_uf", u)["margem_lula_flavio_validos_t1"])
               != np.sign(_r(t1, "sg_uf", u)["margem_lula_flavio_validos_t2"])]
    quantas = (f"em todas as {d.cite(F1, {'delta_margem_lula_flavio_validos': '>0'}, 'n_ufs', len(pos), 'int')} UFs"
               if len(pos) == n_ufs else
               f"em {d.cite(F1, {'delta_margem_lula_flavio_validos': '>0'}, 'n_ufs', len(pos), 'int')} "
               f"das {d.cite(F1, {'sg_uf': '≠TOTAL'}, 'n_ufs', n_ufs, 'int')} UFs")
    txt = (f"- **UFs.** A margem andou a favor de Lula {quantas}. O maior deslocamento foi "
           f"{_em(mx)} ({d.cite(F1, {'sg_uf': mx}, 'delta_margem_lula_flavio_validos', dm[mx], 'pp')}) e o menor, "
           f"{_em(mn)} ({d.cite(F1, {'sg_uf': mn}, 'delta_margem_lula_flavio_validos', dm[mn], 'pp')}).")
    if viradas:
        lado = {u: ("Lula" if _r(t1, "sg_uf", u)["margem_lula_flavio_validos_t2"] > 0 else "Flávio") for u in viradas}
        txt += (f" A liderança mudou de lado em {d.cite(F1, {'virada': True}, 'n_ufs', len(viradas), 'int')} "
                + ("UF: " if len(viradas) == 1 else "UFs: ")
                + _lista([f"{_nome(u)} (para {lado[u]})" for u in viradas]) + ".")
    d.line(txt)
    abst = {u: float(_r(t1, "sg_uf", u)["delta_abstencao_aptos"]) for u in ufs}
    sobe = [u for u in ufs if abst[u] > 0]
    d.line(f"- **Participação.** A abstenção sobre os aptos variou "
           f"{_camada(d, cam, 'BRASIL', 'delta_abstencao_aptos', 'pp')} no Brasil"
           + (f"; subiu em {d.cite(F1, {'delta_abstencao_aptos': '>0'}, 'n_ufs', len(sobe), 'int')} UFs"
              + (f" ({_lista([_nome(u) for u in sobe])})" if 0 < len(sobe) <= 10 else "") if sobe
              else "; caiu em todas as UFs")
           + f". Brancos variaram {d.cite(F9, {'camada': 'BRASIL'}, 'qt_votos_brancos_t2 - qt_votos_brancos_t1', int(br['qt_votos_brancos_t2'] - br['qt_votos_brancos_t1']), 'int')} "
           f"e nulos, {d.cite(F9, {'camada': 'BRASIL'}, 'qt_votos_nulos_t2 - qt_votos_nulos_t1', int(br['qt_votos_nulos_t2'] - br['qt_votos_nulos_t1']), 'int')}.")
    t10 = t["tab10"]
    lul = t10[t10.candidato.astype(str).str.startswith("Lula")].sort_values("contribuicao_delta_votos", ascending=False).head(3)
    if not lul.empty:
        d.line("- **Onde.** Os municípios com maior ganho de votos de Lula foram " + _lista([
            f"{_mun(r)} ({d.cite(F10, {'candidato': 'Lula', 'sg_uf': r['sg_uf'], 'cd_municipio_tse': r['cd_municipio_tse']}, 'contribuicao_delta_votos', int(r['contribuicao_delta_votos']), 'int')})"
            for _, r in lul.iterrows()]) + ".")
    t5 = t["tab05"]
    a = t5[(t5.familia == "ef_municipio") & (t5.recorte == "territorial") & (t5.desfecho == "delta_share_lula_validos")
           & t5.termo.isin(ELIMINADOS)].dropna(subset=["pp_por_10pp_ajustado"])
    if not a.empty:
        r = a.loc[a.pp_por_10pp_ajustado.idxmax()]
        todos_pos = bool((a.pp_por_10pp_inf_ajustado > 0).all())
        d.line("- **Bases iniciais.** Dentro de um mesmo município, unidades com mais votos dos candidatos "
               "eliminados no 1º turno (no lugar de abstenção) tiveram "
               + ("avanço maior de Lula, com todos os intervalos acima de zero" if todos_pos else
                  "associações de sinal e precisão variáveis com o avanço de Lula")
               + f"; o maior coeficiente é o de {TERMO[r['termo']]}, "
               f"{d.cite(F5, {'termo': r['termo'], 'recorte': 'territorial', 'familia': 'ef_municipio', 'desfecho': 'delta_share_lula_validos'}, 'pp_por_10pp_ajustado', float(r['pp_por_10pp_ajustado']), 'f4')} "
               "p.p. por dez pontos. É associação entre unidades, não transferência de eleitores.")
    tt = _r(t7, "sg_uf", "TOTAL")
    k = {"sg_uf": "TOTAL"}
    d.line(f"- **Saldos (território).** Os demais candidatos tiveram "
           f"{d.cite(F7, k, 'o1_demais_candidatos_t1', int(tt['o1_demais_candidatos_t1']), 'int')} votos no 1º turno; a "
           f"conta ΔLula + ΔFlávio = votos dos demais + Δválidos fecha com diferença "
           f"{d.cite(F7, k, 'identidade_saldos_dif', int(tt['identidade_saldos_dif']), 'int')}, e o ganho de Lula equivale a "
           f"{d.cite(F7, k, 'razao_delta_lula_sobre_o1', float(tt['razao_delta_lula_sobre_o1']), 'pct')} dos votos dos demais.")
    ex = _r(cam, "camada", "EXTERIOR") if "EXTERIOR" in set(cam.camada) else None
    if ex is not None:
        d.line(f"- **Exterior.** Margem de {_camada(d, cam, 'EXTERIOR', 'margem_lula_flavio_validos_t1', 'pp')} para "
               f"{_camada(d, cam, 'EXTERIOR', 'margem_lula_flavio_validos_t2', 'pp')}; abstenção de "
               f"{_camada(d, cam, 'EXTERIOR', 'abstencao_aptos_t1', 'pct')} para "
               f"{_camada(d, cam, 'EXTERIOR', 'abstencao_aptos_t2', 'pct')}. Analisado à parte: não entra nas regiões "
               "nem nos modelos territoriais.")
    d.prose("## O que os dados não permitem dizer")
    if not bool(tt["teste_100pct_necessario"]):
        d.line("- **Quem votou em quem.** O voto é secreto e os dados são agregados. A hipótese \"todos os votos "
               "dos demais foram para Lula\" não é necessária (limite mínimo "
               f"{d.cite(F7, k, 'limite_min_demais_para_lula', float(tt['limite_min_demais_para_lula']), 'pct')})"
               + ("" if bool(tt["teste_100pct_possivel"]) else
                  f" e, no cenário de unidades estáveis, é incompatível em "
                  f"{d.cite(F7, k, 'unidades_que_impedem_100pct', int(tt['unidades_que_impedem_100pct']), 'int')} unidades")
               + ("; mesmo integral, não fecharia a conta sem outras origens." if float(tt["razao_delta_lula_sobre_o1"]) > 1 else "."))
    else:
        d.prose("- **Quem votou em quem.** O voto é secreto e os dados são agregados: as transições individuais "
                "não são identificáveis.")
    t12, t13 = t.get("tab12"), t.get("tab13")
    if t12 is not None and t13 is not None and not t13.empty and "A_PARTIR_19H" in set(t12.faixa):
        a = t13[t13.recorte == "territorial"]
        r = _ajustada(d, a, "A_PARTIR_19H", "delta_margem_lula_flavio_validos")
        n19 = int(t12.set_index("faixa").at["A_PARTIR_19H", "secoes_t2"])
        txt = (f"- **Horários.** Fecharam às 19h ou depois "
               f"{d.cite(F12, {'faixa': 'A_PARTIR_19H'}, 'secoes_t2', n19, 'int')} seções no 2º turno. ")
        if r is None:
            txt += "A comparação ajustada com as que fecharam no horário não teve suporte pela regra pré-registrada."
        else:
            sentido, num = r
            txt += ({"maior": "Nelas, a margem de Lula avançou mais do que em seções do mesmo município que fecharam "
                              "entre 17h00 e 17h15",
                     "menor": "Nelas, a margem de Lula avançou menos do que em seções do mesmo município que fecharam "
                              "entre 17h00 e 17h15",
                     "indistinguível": "Nelas, o avanço da margem de Lula não se distingue do de seções do mesmo "
                                       "município que fecharam entre 17h00 e 17h15"}[sentido]
                    + f": {num}. É associação, não efeito do horário: o que teria acontecido sem a prorrogação não é "
                      "observado.")
        d.line(txt)
    else:
        d.prose("- **Horários.** A comparação entre seções por horário de encerramento não foi feita neste ciclo.")
    t17 = t.get("tab17")
    if t17 is not None and not t17.empty:
        p = t17[(t17.papel == "principal") & (t17.especificacao == "ajustado")]
        pb = t17[(t17.papel == "principal") & (t17.especificacao == "bruto")]
        partes = []
        for y in ("delta_share_lula_validos", "delta_comparecimento_aptos"):
            q = p[p.desfecho == y].set_index("indicador")
            itens = []
            for ind in SOCIO_IND:
                if ind in q.index and _sinal(q.loc[ind]) != "zero":
                    k = {"indicador": ind, "desfecho": y, "especificacao": "ajustado", "papel": "principal"}
                    itens.append(f"{SOCIO_CURTO[ind]} {d.cite(F17, k, 'efeito_pp', float(q.loc[ind].efeito_pp), 'f4')} "
                                 f"p.p. {SOCIO_ESCALA[ind]}")
            if itens:
                partes.append(f"com intervalo que exclui zero {Y_ART[y]} {Y_ROT[y]}: " + "; ".join(itens))
        trocas, pares = 0, 0
        for ind in SOCIO_IND:
            for y in ("delta_share_lula_validos", "delta_comparecimento_aptos"):
                a = p[(p.indicador == ind) & (p.desfecho == y)]
                b = pb[(pb.indicador == ind) & (pb.desfecho == y)]
                if not a.empty and not b.empty:
                    pares += 1
                    trocas += int(_sinal(a.iloc[0]) != _sinal(b.iloc[0]))
        del partes   # coeficientes completos na tabela 17; os achados principais abrem o resumo
        d.line("- **Contexto socioeconômico (municípios; Censo 2022, RAIS 31/12/2025, Bolsa Família 08/2026).** "
               "Os achados socioeconômicos do topo comparam territórios, não eleitores: dizem onde o voto mudou, não "
               "quem mudou nem por quê. A leitura depende do ajuste pela votação do 1º turno, que absorve parte da "
               "associação bruta sem dizer qual das duas é a \"verdadeira\";"
               + f" em {d.cite(F17, {'papel': 'principal', 'comparacao': 'bruto x ajustado'}, 'trocas_de_sinal', trocas, 'int')} "
               f"de {d.cite(F17, {'papel': 'principal', 'comparacao': 'bruto x ajustado'}, 'pares', pares, 'int')} "
               "pares indicador × desfecho ela muda depois do ajuste (tabela 17 e figura 8 do relatório).")
        rs = analytics / "socio" / "resumo_socio.json"
        t22, t21, t18 = t.get("tab22"), t.get("tab21"), t.get("tab18")
        if rs.exists() and t22 is not None and not t22.empty:
            tot = t22[t22.sg_uf == "TOTAL"].iloc[0]
            k = {"sg_uf": "TOTAL"}
            txt = (f"- **Entorno dos locais (raio de 1 km, Censo 2022; tabelas 18 e 22).** A camada espacial é "
                   f"parcialmente observada: {d.cite(F22, k, 'unidades_entorno_valido', int(tot.unidades_entorno_valido), 'int')} "
                   f"de {d.cite(F22, k, 'unidades', int(tot.unidades), 'int')} unidades "
                   f"({d.cite(F22, k, 'aptos_entorno_valido/aptos', float(tot.aptos_entorno_valido / tot.aptos), 'pct')} "
                   "dos aptos) têm entorno válido; não equivale integralmente à base do RS.")
            txt += (" Os coeficientes valem para o raio adotado de 1 km e não demonstram o mesmo resultado em "
                    "outras escalas.")
            d.line(txt)
        if t21 is not None and not t21.empty and (t21.status == "PASS").all():
            q = t21[t21.desfecho == "delta_share_lula_validos"].set_index("etapa")
            if {"a_amostra_original", "c_amostra_com_entorno_com_controles"} <= set(q.index):
                ka = {"etapa": "a_amostra_original", "desfecho": "delta_share_lula_validos"}
                kc = {**ka, "etapa": "c_amostra_com_entorno_com_controles"}
                ra, rc = q.loc["a_amostra_original"], q.loc["c_amostra_com_entorno_com_controles"]
                pouco = abs(rc.beta_ajustado - ra.beta_ajustado) < (ra.sup - ra.inf) / 4
                d.line("- **Seções tardias com contexto (tabela 21).** Restringir às unidades com entorno e acrescentar "
                       "renda, urbanização, densidade e favela do entorno "
                       + ("muda pouco" if pouco else "muda")
                       + " a comparação entre seções que fecharam às 19h ou depois e as de 17h00–17h15 no mesmo "
                       "município: de "
                       f"{d.cite(F21, ka, 'beta_ajustado', float(q.loc['a_amostra_original'].beta_ajustado), 'pp')} para "
                       f"{d.cite(F21, kc, 'beta_ajustado', float(q.loc['c_amostra_com_entorno_com_controles'].beta_ajustado), 'pp')} "
                       "na participação de Lula"
                       + (", com intervalos que incluem zero." if all(_sinal(pd.Series({"inf_pp": r.inf, "sup_pp": r.sup})) == "zero"
                                                                  for _, r in q.iterrows()) else "."))
    if ctr is not None and not ctr.empty:
        rep = int(ctr.status_conclusao.isin(["REPRODUZIDA"]).sum())
        d.line(f"- **Imprensa e alegações.** De {d.cite('contraste_resultados.csv', {'todas': True}, 'n_proposicoes', len(ctr), 'int')} "
               f"proposições examinadas, {d.cite('contraste_resultados.csv', {'status_conclusao': 'REPRODUZIDA'}, 'n', rep, 'int')} "
               "se reproduzem, dentro da tolerância de arredondamento de cada fonte; ver `CONTRASTE_IMPRENSA_E_ALEGACOES.md`.")
    d.prose("## Confiança")
    sa = t3.set_index("nivel_agregacao")
    conf = ("- **Alta:** totais, margens e saldos, conferidos com o TSE por UF nos dois turnos.\n"
            "- **Média:** a ligação das seções agregadas no 2º turno (decisão D-T2-01), porque o TSE não publicou a "
            "correspondência efetiva desse turno")
    if cor is not None and not cor.empty:
        conf += (f"; a regra foi corroborada em {d.cite('corroboracao_dt201_uf.csv', {'status': 'PASS'}, 'n_ufs', int((cor.status == 'PASS').sum()), 'int')} "
                 f"de {d.cite('corroboracao_dt201_uf.csv', {'todas': True}, 'n_ufs', len(cor), 'int')} unidades")
    if {"SECAO_UNIDADE", "SECAO_UNIDADE_SEM_AGREGACAO"} <= set(sa.index):
        v = float(sa.at["SECAO_UNIDADE_SEM_AGREGACAO", "delta_margem_lula_flavio_validos"]
                  - sa.at["SECAO_UNIDADE", "delta_margem_lula_flavio_validos"])
        conf += (". Só com unidades sem agregação, a variação da margem muda "
                 f"{d.cite(F3, {'nivel_agregacao': 'SECAO_UNIDADE_SEM_AGREGACAO - SECAO_UNIDADE'}, 'delta_margem_lula_flavio_validos', v, 'pp')}")
    d.line(_fim(conf))
    d.prose("- **Baixa:** qualquer taxa pontual de transferência entre candidatos (modelo de taxas constantes, no "
            "apêndice).\n- **Associação, sem efeito causal:** a diferença entre seções por horário de encerramento; "
            "os horários vêm do boletim de cada seção e se conferem com as contagens externas.\n"
            "- **Sem conclusão:** o total exato de votos depois das 17h, que exigiria os logs de todas as seções.")


# --------------------------------------------------------------------------- relatório
def _relatorio(d: Doc, t: dict, figs: list[str], ctr: pd.DataFrame | None, analytics: Path) -> None:
    t1, t3, t4, t5, t6, t7, cam, t10 = (t[k] for k in ("tab01", "tab03", "tab04", "tab05", "tab06", "tab07",
                                                        "tab09", "tab10"))
    d.prose("# Lula × Flávio entre o 1º e o 2º turno de 2026 — Brasil")
    d.prose("Relatório nacional. O resumo de uma página está em `RESUMO_EXECUTIVO_NACIONAL.md`; definições, "
            "tabelas completas, custos e proveniência estão em `APENDICE_TECNICO_NACIONAL.md`.")
    d.line("## Como ler este relatório\n"
           "- **Unidade de análise:** a seção eleitoral, ou o grupo de seções apuradas juntas em algum dos turnos. "
           "Totais de UF, região e Brasil são somas dessas unidades, nunca médias de percentuais.\n"
           "- **Camadas:** UFs; grandes regiões do IBGE; território (as UFs somadas); exterior, analisado à parte; "
           "e Brasil (território mais exterior), que é o resultado oficial nacional.\n"
           "- **Dois denominadores:** votos válidos (sem brancos e nulos) e aptos (todo o eleitorado).\n"
           "- **Quatro tipos de resultado:** saldo (contas exatas sobre os totais oficiais); associação (entre "
           "unidades, não entre eleitores); cenário (vale sob hipóteses ditas no texto); não identificável.\n"
           "- **Fontes:** dados abertos do TSE por seção e Relatório de Totalização por UF. No 2º turno, a ligação "
           "entre seções agregadas usa a decisão D-T2-01, porque o boletim de urna aberto do turno não saiu.")
    # 1. Brasil e regiões
    d.prose("## 1. Brasil e regiões")
    c = cam.assign(nome=cam.camada.map(CAMADA))
    d.table(F9, c, ["nome", "n_ufs", "n_unidades", "margem_lula_flavio_validos_t1", "margem_lula_flavio_validos_t2",
                    "delta_margem_lula_flavio_validos", "delta_share_lula_validos", "delta_share_flavio_validos",
                    "delta_abstencao_aptos"],
            {"n_ufs": "int", "n_unidades": "int", **{x: "pp" for x in ("margem_lula_flavio_validos_t1",
             "margem_lula_flavio_validos_t2", "delta_margem_lula_flavio_validos", "delta_share_lula_validos",
             "delta_share_flavio_validos", "delta_abstencao_aptos")}},
            headers={"nome": "Camada", "n_ufs": "UFs", "n_unidades": "Unidades", "margem_lula_flavio_validos_t1": "Margem 1º",
                     "margem_lula_flavio_validos_t2": "Margem 2º", "delta_margem_lula_flavio_validos": "Δ margem",
                     "delta_share_lula_validos": "Δ Lula", "delta_share_flavio_validos": "Δ Flávio",
                     "delta_abstencao_aptos": "Δ abstenção"})
    reg = cam[cam.camada.isin(REGIOES)]
    if not reg.empty:
        rmx = reg.loc[reg.delta_margem_lula_flavio_validos.idxmax()]
        rmn = reg.loc[reg.delta_margem_lula_flavio_validos.idxmin()]
        d.line(f"O deslocamento foi maior no {CAMADA[rmx.camada]} "
               f"({_camada(d, cam, rmx.camada, 'delta_margem_lula_flavio_validos', 'pp')}) e menor no {CAMADA[rmn.camada]} "
               f"({_camada(d, cam, rmn.camada, 'delta_margem_lula_flavio_validos', 'pp')}). A margem é razão de somas: a do "
               "Brasil não é a média das regiões, porque cada região pesa pelo seu número de válidos.")
    if "fig03_composicao_camadas.png" in figs:
        d.line(f"![Figura 3 — Composição do eleitorado apto por camada]({FIG}/fig03_composicao_camadas.png)")
    # 2. UFs
    d.prose("## 2. Unidades da Federação")
    tab = t1.assign(uf=t1.sg_uf.map(_nome), _tot=t1.sg_uf.astype(str) == "TOTAL").sort_values(
        ["_tot", "delta_margem_lula_flavio_validos"], ascending=[True, False])
    d.table(F1, tab, ["uf", "margem_lula_flavio_validos_t1", "margem_lula_flavio_validos_t2",
                      "delta_margem_lula_flavio_validos", "delta_share_lula_validos", "delta_share_flavio_validos",
                      "delta_abstencao_aptos"],
            {c_: "pp" for c_ in ("margem_lula_flavio_validos_t1", "margem_lula_flavio_validos_t2",
                                 "delta_margem_lula_flavio_validos", "delta_share_lula_validos",
                                 "delta_share_flavio_validos", "delta_abstencao_aptos")},
            filtro="ordenadas pela variação da margem; território ao final",
            headers={"uf": "UF", "margem_lula_flavio_validos_t1": "Margem 1º", "margem_lula_flavio_validos_t2": "Margem 2º",
                     "delta_margem_lula_flavio_validos": "Δ margem", "delta_share_lula_validos": "Δ Lula",
                     "delta_share_flavio_validos": "Δ Flávio", "delta_abstencao_aptos": "Δ abstenção"})
    if "fig01_variacao_uf.png" in figs:
        d.line(f"![Figura 1 — Variação entre turnos por UF]({FIG}/fig01_variacao_uf.png)")
    ufs = _ufs(t1)
    viradas = [u for u in ufs if np.sign(_r(t1, "sg_uf", u)["margem_lula_flavio_validos_t1"])
               != np.sign(_r(t1, "sg_uf", u)["margem_lula_flavio_validos_t2"])]
    for u in viradas:
        r = _r(t1, "sg_uf", u)
        d.line(f"- **{_nome(u)}:** a liderança mudou de lado, de "
               f"{d.cite(F1, {'sg_uf': u}, 'margem_lula_flavio_validos_t1', float(r['margem_lula_flavio_validos_t1']), 'pp')} para "
               f"{d.cite(F1, {'sg_uf': u}, 'margem_lula_flavio_validos_t2', float(r['margem_lula_flavio_validos_t2']), 'pp')}")
    perde = [u for u in ufs if float(_r(t1, "sg_uf", u)["delta_qt_flavio"]) < 0]
    if perde:
        d.line(f"Flávio perdeu votos em {d.cite(F1, {'delta_qt_flavio': '<0'}, 'n_ufs', len(perde), 'int')} UFs "
               f"({_lista([_nome(u) for u in perde])})."
               if len(perde) <= 8 else
               f"Flávio perdeu votos em {d.cite(F1, {'delta_qt_flavio': '<0'}, 'n_ufs', len(perde), 'int')} UFs.")
    # 3. Municípios
    d.prose("## 3. Municípios com maior variação\n"
            "A variação de cada UF se decompõe exatamente na soma das contribuições dos seus municípios; a tabela "
            "mostra, no país, os municípios com maior variação de votos de cada finalista. É contábil: mede quanto o "
            "município moveu o total, não por quê.")
    tm = t10.copy()
    tm["municipio"] = tm.apply(_mun, axis=1)
    d.table(F10, tm[tm.candidato.astype(str).str.startswith("Lula")].head(10), ["municipio", "contribuicao_delta_votos"],
            {"contribuicao_delta_votos": "int"}, filtro="dez maiores variações de Lula",
            headers={"municipio": "Município (UF)", "contribuicao_delta_votos": "Votos de Lula a mais"})
    d.table(F10, tm[tm.candidato.astype(str).str.startswith("Flávio")].head(10), ["municipio", "contribuicao_delta_votos"],
            {"contribuicao_delta_votos": "int"}, filtro="dez maiores variações de Flávio, em módulo",
            headers={"municipio": "Município (UF)", "contribuicao_delta_votos": "Votos de Flávio a mais"})
    if "fig02_municipios_brasil.png" in figs:
        d.line(f"![Figura 2 — Municípios com maior variação]({FIG}/fig02_municipios_brasil.png)")
    # 4. Participação
    d.prose("## 4. Participação, brancos e nulos\n"
            "O que Lula e Flávio ganharam juntos é igual aos votos dos demais candidatos no 1º turno mais a variação "
            "dos válidos; e a variação dos válidos é a do comparecimento menos as de brancos e nulos. A conta "
            "explica saldos, não trajetórias de eleitores.")
    for nome in ("BRASIL", "TERRITORIO", "EXTERIOR"):
        if nome not in set(cam.camada):
            continue
        r = _r(cam, "camada", nome)
        dl, dfv = int(r.qt_lula_t2 - r.qt_lula_t1), int(r.qt_flavio_t2 - r.qt_flavio_t1)
        o1 = int(r.qt_votos_validos_t1 - r.qt_lula_t1 - r.qt_flavio_t1)
        dv = int(r.qt_votos_validos_t2 - r.qt_votos_validos_t1)
        kk = {"camada": nome}
        d.line(f"- **{CAMADA[nome]}:** {d.cite(F9, kk, 'Δlula', dl, 'int')} + {d.cite(F9, kk, 'Δflavio', dfv, 'int')} = "
               f"{d.cite(F9, kk, 'demais_t1', o1, 'int')} + {d.cite(F9, kk, 'Δvalidos', dv, 'int')} (diferença "
               f"{d.cite(F9, kk, 'identidade', dl + dfv - o1 - dv, 'int')}); abstenção "
               f"{_camada(d, cam, nome, 'abstencao_aptos_t1', 'pct')} → {_camada(d, cam, nome, 'abstencao_aptos_t2', 'pct')}.")
    difs = t7.identidade_saldos_dif.abs().sum()
    d.line(f"A mesma identidade fecha em cada UF (soma das diferenças absolutas: "
           f"{d.cite(F7, {'todas': True}, 'identidade_saldos_dif', int(difs), 'int')}).")
    tb = _read(analytics, "turnout_bounds.csv")
    if not tb.empty and "variacao_liquida_comparecimento_com_limites" in tb.columns:
        r = tb.iloc[0]
        kk = {"universo": r["universo"]}
        d.line("O saldo do comparecimento não conta pessoas. Nas "
               f"{d.cite('turnout_bounds.csv', kk, 'unidades_com_limites', int(r['unidades_com_limites']), 'int')} "
               "unidades com o mesmo número de aptos nos dois turnos, e supondo os mesmos eleitores, o saldo de "
               f"{d.cite('turnout_bounds.csv', kk, 'variacao_liquida_comparecimento_com_limites', int(r['variacao_liquida_comparecimento_com_limites']), 'int')} "
               f"é compatível com algo entre {d.cite('turnout_bounds.csv', kk, 'entradas_min', int(r['entradas_min']), 'int')} e "
               f"{d.cite('turnout_bounds.csv', kk, 'entradas_max', int(r['entradas_max']), 'int')} pessoas que passaram a "
               "votar, com saídas simultâneas.")
    # 5. Bases iniciais e perfil
    d.prose("## 5. Bases iniciais e perfil do eleitorado\n"
            "Comparamos unidades dentro do mesmo município (efeito fixo de município): onde a composição do voto "
            "no 1º turno ou o perfil cadastral dos aptos era diferente, quanto variou a participação de Lula? Os "
            "números são a variação, em pontos percentuais, associada a dez pontos a mais na categoria indicada (no "
            "lugar da referência), mantidos os demais termos. São associações entre unidades, não comportamento "
            "de eleitores; o perfil descreve os aptos, não quem votou.")
    a = t5[(t5.familia == "ef_municipio") & (t5.recorte == "territorial") & (t5.desfecho == "delta_share_lula_validos")
           & t5.termo.isin(TERMO)].copy()
    a["categoria"] = a.termo.map(TERMO)
    a["referencia_legivel"] = a.referencia.map(lambda v: REFERENCIA.get(str(v), str(v)))
    d.table(F5, a, ["categoria", "referencia_legivel", "pp_por_10pp_ajustado", "pp_por_10pp_inf_ajustado",
                    "pp_por_10pp_sup_ajustado"],
            {"pp_por_10pp_ajustado": "f4", "pp_por_10pp_inf_ajustado": "f4", "pp_por_10pp_sup_ajustado": "f4"},
            filtro="efeito fixo de município, território, desfecho Δ participação de Lula",
            headers={"categoria": "Categoria (+10 p.p.)", "referencia_legivel": "No lugar de",
                     "pp_por_10pp_ajustado": "Δ Lula (p.p.)", "pp_por_10pp_inf_ajustado": "IC 95% inf.",
                     "pp_por_10pp_sup_ajustado": "IC 95% sup."})
    comp = a[a.termo.isin(ELIMINADOS)].dropna(subset=["pp_por_10pp_ajustado"])
    if not comp.empty:
        r = comp.loc[comp.pp_por_10pp_ajustado.idxmax()]
        maior = float(r["pp_por_10pp_ajustado"]) >= float(a.pp_por_10pp_ajustado.max())
        d.line((f"O maior coeficiente da tabela é o de {TERMO[r['termo']]}, " if maior else
                f"Entre os eliminados, o maior coeficiente é o de {TERMO[r['termo']]}, ")
               + f"{d.cite(F5, {'termo': r['termo'], 'recorte': 'territorial', 'familia': 'ef_municipio', 'desfecho': 'delta_share_lula_validos'}, 'pp_por_10pp_ajustado', float(r['pp_por_10pp_ajustado']), 'f4')} "
               "p.p. Isso é compatível com várias trajetórias (eleitores desses candidatos votando em Lula, "
               "eleitores que mudaram de lado, ou comparecimento diferente nessas unidades), que os dados não separam.")
    for fig, rot in (("fig04_bases_iniciais_municipios.png", "Figura 4 — Municípios: votos dos eliminados e avanço de Lula"),
                     ("fig05_associacoes.png", "Figura 5 — Associações simples e ajustadas")):
        if fig in figs:
            d.line(f"![{rot}]({FIG}/{fig})")
    # 6. Não identificável
    d.prose("## 6. O que os dados não identificam: transferências entre candidatos\n"
            "As marginais de cada unidade limitam, mas não determinam, quantos eleitores passaram de uma opção a "
            "outra. A tabela mostra, no território, o intervalo de frações compatível com os dados.")
    t4v = t4[t4.destino.isin(["LULA", "FLAVIO"])].copy() if "destino" in t4.columns else t4
    d.table(F4, t4v, ["origem_rotulo", "destino_rotulo", "taxa_min", "taxa_max"], {"taxa_min": "pct", "taxa_max": "pct"},
            filtro="destinos Lula e Flávio",
            headers={"origem_rotulo": "No 1º turno", "destino_rotulo": "No 2º turno", "taxa_min": "Fração mínima",
                     "taxa_max": "Fração máxima"})
    tt = _r(t7, "sg_uf", "TOTAL")
    k = {"sg_uf": "TOTAL"}
    d.line("**\"Todos os votos dos demais foram para Lula?\"** No cenário de unidades estáveis (cada eleitor vota na "
           "mesma unidade nos dois turnos) e cadastro com rotatividade mínima: "
           + ("é *possível*" if bool(tt["teste_100pct_possivel"]) else
              f"é *incompatível* em {d.cite(F7, k, 'unidades_que_impedem_100pct', int(tt['unidades_que_impedem_100pct']), 'int')} "
              f"unidades, onde {d.cite(F7, k, 'votos_demais_que_nao_cabem_em_lula', int(tt['votos_demais_que_nao_cabem_em_lula']), 'int')} "
              "votos dos demais não cabem nos votos de Lula — impossibilidade que desaparece se eleitores mudarem de unidade")
           + "; "
           + ("é *necessária*" if bool(tt["teste_100pct_necessario"]) else
              f"*não é necessária* (limite mínimo {d.cite(F7, k, 'limite_min_demais_para_lula', float(tt['limite_min_demais_para_lula']), 'pct')})")
           + "; e *não é observável*, porque o voto é secreto."
           + (f" O ganho de Lula equivale a {d.cite(F7, k, 'razao_delta_lula_sobre_o1', float(tt['razao_delta_lula_sobre_o1']), 'pct')} "
              "dos votos dos demais: mesmo uma transferência integral não fecharia a conta sem outras origens."
              if float(tt["razao_delta_lula_sobre_o1"]) > 1 else ""))
    # 7. Exterior
    if "EXTERIOR" in set(cam.camada):
        r = _r(cam, "camada", "EXTERIOR")
        d.prose("## 7. Exterior\n"
                "O exterior tem cadastro, seções e comparecimento próprios, sem contexto municipal do IBGE; por isso "
                "fica fora das regiões e dos modelos territoriais e entra só nos totais do Brasil.")
        d.line(f"Em {_camada(d, cam, 'EXTERIOR', 'n_unidades', 'int')} unidades, a margem foi de "
               f"{_camada(d, cam, 'EXTERIOR', 'margem_lula_flavio_validos_t1', 'pp')} para "
               f"{_camada(d, cam, 'EXTERIOR', 'margem_lula_flavio_validos_t2', 'pp')}, com abstenção de "
               f"{_camada(d, cam, 'EXTERIOR', 'abstencao_aptos_t1', 'pct')} e "
               f"{_camada(d, cam, 'EXTERIOR', 'abstencao_aptos_t2', 'pct')}.")
    # 8. Horários e ocorrências
    _horarios(d, t, figs, analytics)
    d.prose("### Ocorrências de urna")
    if not t6.empty and "anexo_v_secoes" in t6.columns:
        oc = t6.groupby("nr_turno", as_index=False)[["anexo_v_secoes", "anexo_v_troca_urna"]].sum()
        oc["turno"] = oc.nr_turno.map(lambda x: f"{int(x)}º")
        d.table(F6, oc, ["turno", "anexo_v_secoes", "anexo_v_troca_urna"],
                {"anexo_v_secoes": "int", "anexo_v_troca_urna": "int"}, filtro="soma das UFs e do exterior",
                headers={"turno": "Turno", "anexo_v_secoes": "Seções com ocorrência (Anexo V)",
                         "anexo_v_troca_urna": "Troca de urna"})
        conc = t6[t6.nr_turno == 1].status_conciliacao.astype(str) if "status_conciliacao" in t6.columns else pd.Series(dtype=str)
        n_ok = int((conc == "PASS").sum())
        d.line(f"No 1º turno, as ocorrências conciliam com a correspondência efetivada (CEFT) em "
               f"{d.cite(F6, {'nr_turno': 1, 'status_conciliacao': 'PASS'}, 'n_unidades', n_ok, 'int')} de "
               f"{d.cite(F6, {'nr_turno': 1}, 'n_unidades', len(conc), 'int')} unidades"
               + (f"; as seções não instaladas do exterior ({d.cite(F6, {'sg_uf': 'ZZ', 'nr_turno': 1}, 'anexo_v_nao_instalada', int(t6[(t6.sg_uf == 'ZZ') & (t6.nr_turno == 1)].anexo_v_nao_instalada.iloc[0]), 'int')}) "
                  "não têm urna efetivada e ficam fora da conta"
                  if "anexo_v_nao_instalada" in t6.columns and ((t6.sg_uf == "ZZ") & (t6.nr_turno == 1)).any() else "")
               + ". No 2º, a CEFT não foi publicada e a conciliação fica não verificada. Ocorrência documentada não "
               "é, por si, indício de irregularidade.")
    # 9. Contexto socioeconômico (handoff 37)
    _socio(d, t, figs, analytics)
    # 10. Contraste
    if ctr is not None and not ctr.empty:
        d.prose("## 10. Contraste com imprensa e alegações\n"
                "Cada proposição foi reproduzida com os dados oficiais no universo nacional pertinente, com a conclusão "
                "tirada de condições verificadas. Detalhes em `CONTRASTE_IMPRENSA_E_ALEGACOES.md`.")
        cc = ctr.sort_values("claim_id").copy()
        cc["conclusao"] = cc.status_conclusao.map(lambda s: STATUS_LEGIVEL.get(str(s), str(s)))
        d.table("contraste_resultados.csv", cc, ["claim_id", "afirmacao_resumo", "conclusao"],
                headers={"claim_id": "Prop.", "afirmacao_resumo": "Afirmação (paráfrase)", "conclusao": "Conclusão"})
    _fraude(d, t.get("al", {}))


F12, F13, F14 = "tab12_horarios_faixas.csv", "tab13_horarios_ajustado.csv", "tab14_reproducao_tardias.csv"
FAIXA_ROT = {"ANTES_17H": "antes das 17h", "17H00_17H15": "17h00–17h15", "17H15_18H": "17h15–18h",
             "18H_19H": "18h–19h", "A_PARTIR_19H": "19h ou depois", "MISTA": "unidade com seções em faixas diferentes",
             "INVALIDO": "sem horário válido"}
REPRO_ROT = {"EXATO": "igual", "APROXIMADO": "próximo", "DIVERGE": "difere", "LISTA_PARCIAL": "lista pública parcial",
             "FORA_DO_RECORTE": "fora do recorte dos logs", "NAO_REPRODUZIVEL": "não reproduzível"}
DESFECHO_ROT = {"delta_margem_lula_flavio_validos": "margem Lula − Flávio", "delta_comparecimento_aptos": "comparecimento",
                "delta_share_lula_validos": "participação de Lula"}


def _evid(analytics: Path, nome: str) -> Path:
    return analytics.parents[1] / "reports" / "analysis" / "evidencias_horarios" / nome


def _ajustada(d: Doc, a: pd.DataFrame, faixa: str, desfecho: str) -> tuple[str, str] | None:
    """Frase condicionada ao IC da diferença ajustada; None se a comparação não foi estimada."""
    r = a[(a.faixa == faixa) & (a.desfecho == desfecho)]
    if r.empty or r.status.iloc[0] != "PASS":
        return None
    r = r.iloc[0]
    k = {"recorte": "territorial", "faixa": faixa, "desfecho": desfecho}
    num = (f"{d.cite(F13, k, 'beta_ajustado', float(r.beta_ajustado), 'pp')} (IC 95% de "
           f"{d.cite(F13, k, 'inf', float(r.inf), 'pp')} a {d.cite(F13, k, 'sup', float(r.sup), 'pp')}; "
           f"{d.cite(F13, k, 'municipios_com_ambas', int(r.municipios_com_ambas), 'int')} municípios com as duas faixas)")
    sentido = ("maior" if float(r.inf) > 0 else "menor" if float(r.sup) < 0 else "indistinguível")
    return sentido, num


def _horarios(d: Doc, t: dict, figs: list[str], analytics: Path) -> None:
    d.prose("## 8. Horário de encerramento das seções")
    t12, t13, t14 = t.get("tab12"), t.get("tab13"), t.get("tab14")
    if t12 is None or t12.empty or t13 is None or t13.empty:
        d.prose("A comparação por horário de encerramento não foi produzida neste ciclo: faltam os horários do "
                "2º turno.")
        return
    cov = _read(analytics, "closure_coverage.csv")
    cv = cov.set_index("nr_turno") if not cov.empty else pd.DataFrame()
    vf = _evid(analytics, "validacao_fuso_municipios.csv")
    fz = pd.read_csv(vf) if vf.exists() else pd.DataFrame()
    fz1 = fz[fz.nr_turno == 2] if not fz.empty else fz
    linha = ("No 2º turno, parte das seções ficou aberta depois das 17h para quem estava na fila. Os horários vêm do "
             "boletim de urna de cada seção publicado no portal do TSE, lido seção a seção: "
             f"{d.cite('closure_coverage.csv', {'nr_turno': 2}, 'secoes_com_faixa_principal', int(cv.at[2, 'secoes_com_faixa_principal']), 'int')} "
             "seções com horário de encerramento válido no 2º turno e "
             f"{d.cite('closure_coverage.csv', {'nr_turno': 1}, 'secoes_com_faixa_principal', int(cv.at[1, 'secoes_com_faixa_principal']), 'int')} "
             "no 1º, contando o exterior (a comparação abaixo usa só o território). O relógio da urna marca a hora local; a conversão para Brasília usa o deslocamento de cada município, "
             "inferido pela abertura")
    if not fz1.empty:
        linha += (f" e igual ao fuso legal em "
                  f"{d.cite('validacao_fuso_municipios.csv', {'nr_turno': 2, 'resultado': 'CONFERE'}, 'municipios', int((fz1.resultado == 'CONFERE').sum()), 'int')} "
                  f"de {d.cite('validacao_fuso_municipios.csv', {'nr_turno': 2}, 'municipios', len(fz1), 'int')} municípios no 2º turno")
    d.line(linha + ". As faixas foram fixadas antes de ver os resultados.")
    b = t12[t12.faixa.isin(FAIXA_ROT)].copy()
    b["faixa_rot"] = b.faixa.map(FAIXA_ROT)
    d.table(F12, b, ["faixa_rot", "secoes_t1", "secoes_t2", "unidades_t2", "media_delta_margem_lula_flavio_validos",
                     "media_delta_comparecimento_aptos"],
            {"secoes_t1": "int", "secoes_t2": "int", "unidades_t2": "int",
             "media_delta_margem_lula_flavio_validos": "pp", "media_delta_comparecimento_aptos": "pp"},
            headers={"faixa_rot": "Encerramento (Brasília)", "secoes_t1": "Seções no 1º turno (com exterior)",
                     "secoes_t2": "Seções no 2º turno (com exterior)", "unidades_t2": "Unidades do território (faixa do 2º)",
                     "media_delta_margem_lula_flavio_validos": "Δ margem média",
                     "media_delta_comparecimento_aptos": "Δ comparecimento médio"})
    bi = t12.set_index("faixa")
    if "A_PARTIR_19H" in bi.index:
        k = {"faixa": "A_PARTIR_19H"}
        d.line(f"Às 19h ou depois fecharam {d.cite(F12, k, 'secoes_t2', int(bi.at['A_PARTIR_19H', 'secoes_t2']), 'int')} "
               f"seções no 2º turno, contra {d.cite(F12, k, 'secoes_t1', int(bi.at['A_PARTIR_19H', 'secoes_t1']), 'int')} "
               "no 1º. As médias brutas da tabela misturam lugares diferentes: as seções que fecharam tarde se "
               "concentram em poucos municípios.")
    a = t13[t13.recorte == "territorial"]
    frases = []
    for f in ("17H15_18H", "18H_19H", "A_PARTIR_19H"):
        for y in ("delta_margem_lula_flavio_validos", "delta_comparecimento_aptos"):
            r = _ajustada(d, a, f, y)
            if r is None:
                frases.append(f"- **{FAIXA_ROT[f]}, {DESFECHO_ROT[y]}:** não estimada (sem suporte pela regra "
                              "pré-registrada).")
                continue
            sentido, num = r
            txt = {"maior": "variação maior que a das seções do mesmo município que fecharam entre 17h00 e 17h15",
                   "menor": "variação menor que a das seções do mesmo município que fecharam entre 17h00 e 17h15",
                   "indistinguível": "não se distingue das seções do mesmo município que fecharam entre 17h00 e 17h15"}[sentido]
            frases.append(f"- **{FAIXA_ROT[f]}, {DESFECHO_ROT[y]}:** {txt}: {num}.")
    d.line("Comparando unidades do mesmo município, com os mesmos controles de tamanho, comparecimento e voto do "
           "1º turno e perfil do eleitorado (diferença em relação a 17h00–17h15):\n" + "\n".join(frases))
    if "fig06_horarios_encerramento.png" in figs:
        d.line(f"![Figura 6 — Seções por horário de encerramento]({FIG}/fig06_horarios_encerramento.png)")
    d.prose("**Como ler.** É associação entre seções, não efeito do horário. As seções prorrogadas são as que tinham "
            "fila às 17h, e fila depende do tamanho da seção, do local e do perfil de quem vota ali; os controles "
            "reduzem, mas não eliminam, essas diferenças. O que teria acontecido sem a prorrogação não é observado, e "
            "encerrar tarde não é, por si, indício de irregularidade nem de benefício a candidato.")
    # votos após 17h e reprodução
    rj = _evid(analytics, "reconciliacao_tardias.json")
    if t14 is not None and not t14.empty and rj.exists():
        js = json.loads(rj.read_text(encoding="utf-8"))
        vt, val = js["votos_apos_17h_pais"], js["validacao_campos_tatu"]
        cam = t["tab09"]
        br = _r(cam, "camada", "BRASIL")
        m2 = int(br.qt_lula_t2) - int(br.qt_flavio_t2)
        n_max = max(int(vt["tse"]), int(vt["tatu_todos_logs"]), int(vt["congresso_em_foco_cnn"]))
        d.line("### Votos depois das 17h e seções \"até 19h\"")
        d.line(f"Votos registrados depois das 17h no país: "
               f"{d.cite('reconciliacao_tardias.json', {'chave': 'votos_apos_17h_pais'}, 'tse', int(vt['tse']), 'int')} "
               "segundo o TSE e "
               f"{d.cite('reconciliacao_tardias.json', {'chave': 'votos_apos_17h_pais'}, 'tatu_todos_logs', int(vt['tatu_todos_logs']), 'int')} "
               "na contagem da Agência Tatu, que leu todos os logs. O projeto baixou os logs de "
               f"{d.cite('reconciliacao_tardias.json', {'chave': 'logs'}, 'tardias', int(js['logs']['tardias']), 'int')} "
               "seções que encerraram ou emitiram o boletim a partir das 18h e de "
               f"{d.cite('reconciliacao_tardias.json', {'chave': 'logs'}, 'amostra', int(js['logs']['amostra']), 'int')} "
               "sorteadas entre as demais: o número de votos depois das 17h por seção da Tatu é igual ao do log em "
               f"{d.cite('reconciliacao_tardias.json', {'chave': 'validacao_campos_tatu', 'estrato': 'TARDIA'}, 'votos_apos17_iguais', float(val['TARDIA']['votos_apos17_iguais']), 'pct')} "
               "das seções tardias e em "
               f"{d.cite('reconciliacao_tardias.json', {'chave': 'validacao_campos_tatu', 'estrato': 'AMOSTRA'}, 'votos_apos17_iguais', float(val['AMOSTRA']['votos_apos17_iguais']), 'pct')} "
               "das sorteadas.")
        rl = js.get("reconciliacao_logs")
        if rl:
            kr = {"chave": "reconciliacao_logs"}
            d.line("Cada log foi conferido com o comparecimento oficial da seção. Quando a urna foi trocada, o pacote "
                   "publicado traz também os logs das urnas anteriores; isso ocorreu em "
                   f"{d.cite('reconciliacao_tardias.json', kr, 'com_logs_aninhados', int(rl['com_logs_aninhados']), 'int')} "
                   "seções. Lido só o log da urna final, "
                   f"{d.cite('reconciliacao_tardias.json', kr, 'divergentes_so_log_final', int(rl['divergentes_so_log_final']), 'int')} "
                   "seções não fecham com o comparecimento; lidos todos, fecham "
                   f"{d.cite('reconciliacao_tardias.json', kr, 'reconciliadas', int(rl['reconciliadas']), 'int')} de "
                   f"{d.cite('reconciliacao_tardias.json', kr, 'secoes_com_log', int(rl['secoes_com_log']), 'int')}. "
                   "As contagens a seguir usam só seções reconciliadas.")
        d.line(f"Como cenário aritmético, e não como efeito da prorrogação: a margem nacional de Lula no 2º turno foi de "
               f"{d.cite(F9, {'camada': 'BRASIL'}, 'qt_lula_t2-qt_flavio_t2', m2, 'int')} votos; retirar a maior dessas "
               f"contagens ({d.cite('reconciliacao_tardias.json', {'chave': 'votos_apos_17h_pais'}, 'maximo', n_max, 'int')}) "
               f"mudaria a margem em no máximo esse número, e passar todos eles de um candidato para o outro, em no máximo "
               f"{d.cite('reconciliacao_tardias.json', {'chave': 'votos_apos_17h_pais'}, '2*maximo', 2 * n_max, 'int')} "
               f"({d.cite('reconciliacao_tardias.json', {'chave': 'votos_apos_17h_pais'}, '2*maximo/margem', 2 * n_max / m2, 'pct')} da margem).")
        d.line("Reprodução, com os boletins e os logs, das contagens publicadas pela UOL/Agência Tatu e pelo TSE. "
               "Nenhuma das duas fontes publicou o evento usado para definir \"fechou depois das 19h\"; a tabela "
               "mostra a definição que reproduz cada número.")
        rp = t14.copy()
        rp["status_rot"] = rp.status.map(lambda s: REPRO_ROT.get(str(s), str(s)))
        d.table(F14, rp, ["fonte", "item", "publicado", "nosso_valor", "diferenca", "definicao_testada", "status_rot"],
                {"publicado": "int", "nosso_valor": "int", "diferenca": "int"},
                headers={"fonte": "Fonte", "item": "Número publicado", "publicado": "Publicado",
                         "nosso_valor": "Projeto", "diferenca": "Diferença", "definicao_testada": "Definição que reproduz",
                         "status_rot": "Resultado"})
        p1 = rp[rp.item == "seções 'até 19h', critério pedido1"]
        pf = rp[rp.item == "seções 'até 19h', critério pedido1, só log final"]
        pb = rp[rp.item == "seções 'até 19h', critério bu"]
        if not p1.empty and not pb.empty and not pf.empty:
            d.line(f"- **UOL/Tatu:** as {d.cite(F14, {'item': p1.item.iloc[0]}, 'publicado', int(p1.publicado.iloc[0]), 'int')} "
                   "seções \"até 19h\" são compatíveis com as que tiveram o primeiro pedido de encerramento do mesário "
                   "às 19h ou depois, lido só no log da urna final "
                   f"({d.cite(F14, {'item': pf.item.iloc[0]}, 'nosso_valor', int(pf.nosso_valor.iloc[0]), 'int')}, "
                   "o mesmo número da lista pública). Lendo também os logs de urnas substituídas, são "
                   f"{d.cite(F14, {'item': p1.item.iloc[0]}, 'nosso_valor', int(p1.nosso_valor.iloc[0]), 'int')}: "
                   "em algumas seções a urna anterior já tinha pedido o encerramento antes das 19h. O horário gravado "
                   "no boletim, que vem logo após o pedido, dá a variante maior "
                   f"({d.cite(F14, {'item': pb.item.iloc[0]}, 'publicado', int(pb.publicado.iloc[0]), 'int')}), "
                   "que a própria Tatu também publicou.\n"
                   "- **TSE:** as contagens de seções são compatíveis com o horário de emissão do boletim, a definição "
                   "testada mais próxima; proximidade não prova que foi a usada, porque o TSE não publicou a sua. A "
                   "pequena diferença restante e a dos votos entre 17h e 18h não se explicam com os dados públicos.")


F15, F16, F17, F18 = ("tab15_socio_faixas.csv", "tab16_socio_faixas_regiao.csv", "tab17_socio_modelos_municipais.csv",
                      "tab18_socio_entorno.csv")
F19, F20, F21, F22 = ("tab19_socio_perfis_bases.csv", "tab20_socio_correlacoes_bases.csv",
                      "tab21_socio_tardias_contexto.csv", "tab22_socio_cobertura_entorno_uf.csv")
SOCIO_IND = {"renda_pc": "Renda domiciliar per capita média (Censo 2022)",
             "baixa_renda": "Pessoas com até ½ salário mínimo, % (Censo 2022)",
             "desocupacao": "Taxa de desocupação, % (Censo 2022)",
             "vinculos": "Vínculos formais por mil habitantes (RAIS, 31/12/2025)",
             "pbf": "Registros do Bolsa Família por 100 domicílios (folha 08/2026)",
             "urbana": "População urbana, % (Censo 2022)"}
SOCIO_CURTO = {"renda_pc": "renda per capita", "baixa_renda": "pessoas até ½ SM", "desocupacao": "desocupação",
               "vinculos": "vínculos formais", "pbf": "registros do PBF", "urbana": "população urbana"}
ENT_ROT = {"renda_resp": "renda média dos responsáveis (por duplicação)",
           "urbana_entorno": "população urbana do entorno (+10 p.p.)",
           "densidade": "densidade do entorno (por duplicação)",
           "favela": "população em favelas e comunidades urbanas (+10 p.p.)"}
ENT_AMOSTRA = {"principal": "principal (1 km)", "cobertura_area_075": "cobertura de área ≥ 0,75",
               "cobertura_area_095": "cobertura de área ≥ 0,95", "cobertura_renda_0.50": "cobertura de renda ≥ 0,50",
               "cobertura_renda_0.90": "cobertura de renda ≥ 0,90", "peso_domicilios": "renda pesada por domicílios",
               "sem_mudanca_local": "sem unidades que mudaram de local",
               "sem_coord_fora_municipio": "sem coordenada fora do município"}
ENT_ERRO = {"id_local": "local", "municipio": "município"}
SOCIO_ESCALA = {"renda_pc": "por duplicação", "baixa_renda": "por +10 p.p.", "desocupacao": "por +5 p.p.",
                "vinculos": "por +100 por mil hab.", "pbf": "por +10 por 100 domicílios", "urbana": "por +10 p.p."}
Y_ART = {"delta_share_lula_validos": "na", "delta_comparecimento_aptos": "no", "delta_margem_lula_flavio_validos": "na"}
Y_ROT = {"delta_share_lula_validos": "participação de Lula", "delta_comparecimento_aptos": "comparecimento",
         "delta_margem_lula_flavio_validos": "margem Lula − Flávio"}


def _ic(d: Doc, f: str, k: dict, r: pd.Series) -> str:
    return (f"{d.cite(f, k, 'efeito_pp', float(r.efeito_pp), 'f4')} p.p. (IC 95% de "
            f"{d.cite(f, k, 'inf_pp', float(r.inf_pp), 'f4')} a {d.cite(f, k, 'sup_pp', float(r.sup_pp), 'f4')})")


def _sinal(r: pd.Series) -> str:
    return "positivo" if r.inf_pp > 0 else "negativo" if r.sup_pp < 0 else "zero"


def _socio(d: Doc, t: dict, figs: list[str], analytics: Path) -> None:
    t15, t17 = t.get("tab15"), t.get("tab17")
    if t15 is None or t15.empty or t17 is None or t17.empty:
        return
    d.prose("## 9. Contexto socioeconômico dos municípios e dos locais de votação\n"
            "Em que contextos Lula e Flávio cresceram, e como o comparecimento e a composição inicial se associam a "
            "esse crescimento. São associações entre territórios: o contexto descreve o município ou o entorno do "
            "local de votação, não quem votou, e nada aqui é efeito causal ou voto individual. O plano estatístico "
            "foi registrado antes das estimativas (`docs/methodology/PLANO_ESTATISTICO_37.md`).")
    rs = json.loads((analytics / "socio" / "resumo_socio.json").read_text(encoding="utf-8")) \
        if (analytics / "socio" / "resumo_socio.json").exists() else {}
    pm = rs.get("painel_municipal", {})
    if pm:
        k = {"chave": "painel_municipal"}
        d.line(f"- **Municípios:** {d.cite('resumo_socio.json', k, 'municipios_territorio', int(pm['municipios_territorio']), 'int')} "
               f"no território; os indicadores do Censo 2022 cobrem "
               f"{d.cite('resumo_socio.json', k, 'cobertura.renda_pc', int(pm['cobertura']['renda_pc']), 'int')} "
               "(o município criado depois do Censo fica sem indicador e sem faixa, mas seus votos continuam nos totais). "
               "Um valor por município: nada é replicado por seção.")
    eu = rs.get("entorno_unidades", {})
    t22 = t.get("tab22")
    if eu and t22 is not None and not t22.empty:
        tot = t22[t22.sg_uf == "TOTAL"].iloc[0]
        k = {"sg_uf": "TOTAL"}
        d.line(f"- **Entorno dos locais (raio de 1 km):** "
               f"{d.cite(F22, k, 'unidades_entorno_valido', int(tot.unidades_entorno_valido), 'int')} de "
               f"{d.cite(F22, k, 'unidades', int(tot.unidades), 'int')} unidades do painel "
               f"({d.cite(F22, k, 'aptos_entorno_valido/aptos', float(tot.aptos_entorno_valido / tot.aptos), 'pct')} "
               f"dos aptos) têm entorno válido, em "
               f"{d.cite('resumo_socio.json', {'chave': 'entorno_unidades'}, 'locais_validos', int(eu['locais_validos']), 'int')} "
               "locais de votação. A camada espacial é parcialmente observada: faltam coordenadas válidas ou "
               "cobertura de setores em parte dos locais, e unidades com seções em mais de um local não recebem entorno. "
               "A cobertura por UF está na tabela 22 do apêndice. Não é equivalente integral à base do RS.")
    _socio_destaques(d, t)
    # faixas
    d.prose("### Faixas de municípios\n"
            "Quintis de municípios fixados uma vez em cada indicador (cada município conta igual; empates na mesma "
            "faixa). A votação de cada faixa é a soma dos votos dividida pela soma dos válidos, no 1º e no 2º turno.")
    f = t15.copy()
    f["ind_rot"] = f.indicador.map(SOCIO_CURTO)
    f["limites"] = f.apply(lambda r: f"{r.valor_min:,.1f} a {r.valor_max:,.1f}".replace(",", "X").replace(".", ",")
                           .replace("X", "."), axis=1)
    d.table(F15, f, ["ind_rot", "faixa", "limites", "municipios", "qt_aptos_t1", "share_lula_t1", "share_lula_t2",
                     "delta_share_lula", "delta_comparecimento"],
            {"municipios": "int", "qt_aptos_t1": "int", "share_lula_t1": "pct", "share_lula_t2": "pct",
             "delta_share_lula": "pp", "delta_comparecimento": "pp"},
            headers={"ind_rot": "Indicador", "faixa": "Quintil", "limites": "Valores no quintil",
                     "municipios": "Municípios", "qt_aptos_t1": "Aptos (1º turno)", "share_lula_t1": "Lula, 1º",
                     "share_lula_t2": "Lula, 2º", "delta_share_lula": "Δ Lula", "delta_comparecimento": "Δ comparecimento"})
    if "fig07_socio_faixas.png" in figs:
        d.line(f"![Figura 7 — Variação por quintil de municípios]({FIG}/fig07_socio_faixas.png)")
    linhas = []
    for ind in SOCIO_IND:
        s = t15[t15.indicador == ind].set_index("faixa")
        if s.empty or 1 not in s.index or 5 not in s.index:
            continue
        a, b = s.loc[1], s.loc[5]
        k1, k5 = {"indicador": ind, "faixa": 1}, {"indicador": ind, "faixa": 5}
        linhas.append(f"- **{SOCIO_CURTO[ind]}:** Lula avançou "
                      f"{d.cite(F15, k1, 'delta_share_lula', float(a.delta_share_lula), 'pp')} no quintil mais baixo e "
                      f"{d.cite(F15, k5, 'delta_share_lula', float(b.delta_share_lula), 'pp')} no mais alto; o comparecimento "
                      f"variou {d.cite(F15, k1, 'delta_comparecimento', float(a.delta_comparecimento), 'pp')} e "
                      f"{d.cite(F15, k5, 'delta_comparecimento', float(b.delta_comparecimento), 'pp')}")
    d.line("\n".join(linhas))
    d.line("As faixas brutas misturam diferenças regionais e de composição inicial; por região, a tabela 16 do "
            "apêndice; por UF, a tabela 23, com todas as UFs.")
    # modelos municipais
    d.prose("### Modelos municipais\n"
            "Uma observação por município, um indicador por vez. Bruto: só o indicador e efeito fixo de UF. Ajustado: "
            "mais tamanho, urbanização e composição do 1º turno (participação de Lula e dos demais, comparecimento, "
            "brancos e nulos). As duas especificações usam a mesma amostra, ponderada pelos aptos do 1º turno, com "
            "erros agrupados por região geográfica imediata do IBGE.")
    p = t17[(t17.papel == "principal") & t17.desfecho.isin(["delta_share_lula_validos", "delta_comparecimento_aptos"])].copy()
    p["ind_rot"] = p.indicador.map(SOCIO_CURTO)
    p["y_rot"] = p.desfecho.map(Y_ROT)
    d.table(F17, p, ["ind_rot", "y_rot", "especificacao", "escala", "efeito_pp", "inf_pp", "sup_pp", "n", "grupos", "vif"],
            {"efeito_pp": "f4", "inf_pp": "f4", "sup_pp": "f4", "n": "int", "grupos": "int", "vif": "f4"},
            filtro="papel=principal",
            headers={"ind_rot": "Indicador", "y_rot": "Desfecho", "especificacao": "Especificação", "escala": "Escala",
                     "efeito_pp": "p.p.", "inf_pp": "IC inf.", "sup_pp": "IC sup.", "n": "Municípios",
                     "grupos": "Grupos", "vif": "VIF"})
    if "fig08_socio_modelos.png" in figs:
        d.line(f"![Figura 8 — Associação entre municípios, bruta e ajustada]({FIG}/fig08_socio_modelos.png)")
    frases = []
    for ind in SOCIO_IND:
        for y in ("delta_share_lula_validos", "delta_comparecimento_aptos"):
            q = p[(p.indicador == ind) & (p.desfecho == y)].set_index("especificacao")
            if not {"bruto", "ajustado"} <= set(q.index):
                continue
            rb, ra = q.loc["bruto"], q.loc["ajustado"]
            kb = {"indicador": ind, "desfecho": y, "especificacao": "bruto", "papel": "principal"}
            ka = {**kb, "especificacao": "ajustado"}
            sb, sa = _sinal(rb), _sinal(ra)
            if sb != sa and "zero" not in (sb, sa):
                leitura = "a associação muda de sinal depois do ajuste"
            elif sb != "zero" and sa == "zero":
                leitura = "a associação bruta deixa de se distinguir de zero depois do ajuste"
            elif sb == "zero" and sa != "zero":
                leitura = "a associação só aparece depois do ajuste"
            elif sa == "zero":
                leitura = "nem bruta nem ajustada se distingue de zero"
            else:
                leitura = "a associação mantém o sinal depois do ajuste"
            frases.append(f"- **{SOCIO_CURTO[ind]} ({SOCIO_ESCALA[ind]}) × {Y_ROT[y]}:** bruta {_ic(d, F17, kb, rb)}; ajustada "
                          f"{_ic(d, F17, ka, ra)}; {leitura}.")
    d.line("\n".join(frases))
    d.prose("Os coeficientes são diferenças condicionais entre municípios, não efeito do indicador sobre o voto. A "
            "composição do 1º turno entra como controle e absorve parte da associação bruta; isso não diz qual das "
            "duas é a \"verdadeira\". Pesos iguais por município, erros por UF, erros robustos sem agrupamento, "
            "exclusão dos municípios com mais de um milhão de aptos, indicadores alternativos e o modelo com todos os "
            "indicadores juntos estão no apêndice.")
    # entorno
    t18 = t.get("tab18")
    if t18 is not None and not t18.empty and (t18.status == "PASS").any():
        d.prose("### Entorno dos locais de votação\n"
                "Unidades comparadas com outras do mesmo município (efeito fixo de município), com controles de perfil "
                "cadastral dos aptos e de composição do 1º turno, peso pelos aptos e erros agrupados pelo local de "
                "votação, porque as unidades de um mesmo local compartilham o entorno. O entorno é o do local onde a "
                "unidade votou no 1º turno. Renda do responsável no círculo não é a renda do eleitor.")
        d.line("O entorno corresponde a um círculo de 1 km ao redor do local de votação; seus indicadores são "
               "estimados a partir dos setores censitários de 2022, por interpolação de área (cada setor contribui na "
               "proporção da sua área dentro do círculo, supondo população distribuída uniformemente no setor). O "
               "local só tem entorno válido se os setores cobrirem ao menos 90% do círculo; a renda exige também "
               "cobertura de renda de ao menos 75%. A camada é parcialmente observada (tabela 22). O estudo adota "
               "esse raio único: as conclusões valem para essa definição de entorno e não demonstram o mesmo "
               "resultado em outras escalas.")
        e = t18[(t18.status == "PASS") & (t18.filtro == "principal") & (t18.cluster == "id_local")
                & t18.desfecho.isin(["delta_share_lula_validos", "delta_comparecimento_aptos"])].copy()
        e["ind_rot"] = e.indicador.map(ENT_ROT)
        e["y_rot"] = e.desfecho.map(Y_ROT)
        d.table(F18, e, ["ind_rot", "y_rot", "efeito_pp", "inf_pp", "sup_pp", "n_unidades", "n_locais", "n_municipios"],
                {"efeito_pp": "f4", "inf_pp": "f4", "sup_pp": "f4", "n_unidades": "int", "n_locais": "int",
                 "n_municipios": "int"}, filtro="filtro=principal; cluster=id_local",
                headers={"ind_rot": "Entorno", "y_rot": "Desfecho", "efeito_pp": "p.p.", "inf_pp": "IC inf.",
                         "sup_pp": "IC sup.", "n_unidades": "Unidades", "n_locais": "Locais",
                         "n_municipios": "Municípios"})
        d.line("Verificações de qualidade no mesmo raio (outros limites de cobertura de área e de renda, renda "
                "pesada por domicílios, sem unidades que mudaram de local, sem coordenadas fora do município e erros "
                "agrupados por município) estão na tabela 18 completa, no apêndice.")
    # afinidade
    t19, t20 = t.get("tab19"), t.get("tab20")
    if t19 is not None and not t19.empty:
        d.line("### Perfil territorial das bases de voto\n"
                "Média de cada indicador do município ponderada pelos votos de cada base, na mesma amostra de "
                "municípios. Mostra em que tipo de lugar cada base se concentra; semelhança de perfil não é "
                "transferência de votos, e os limites e cenários de fluxo do capítulo 6 ficam separados.")
        pf = t19.copy()
        d.table(F19, pf, ["base", "renda_pc", "baixa_renda", "desocupacao", "vinculos", "pbf", "urbana"],
                {"renda_pc": "f4", "baixa_renda": "f4", "desocupacao": "f4", "vinculos": "f4", "pbf": "f4",
                 "urbana": "f4"},
                headers={"base": "Base", "renda_pc": "Renda pc (R$)", "baixa_renda": "Até ½ SM (%)",
                         "desocupacao": "Desocupação (%)", "vinculos": "Vínculos/mil", "pbf": "PBF/100 dom.",
                         "urbana": "Urbana (%)"})
    if t20 is not None and not t20.empty:
        c = t20[t20.variacao.isin(["delta_lula_por_apto", "delta_flavio_por_apto"])].pivot_table(
            index="base_t1", columns="variacao", values="correlacao_ponderada").reset_index()
        d.table(F20, c, ["base_t1", "delta_lula_por_apto", "delta_flavio_por_apto"],
                {"delta_lula_por_apto": "f4", "delta_flavio_por_apto": "f4"},
                headers={"base_t1": "Votação no 1º turno, por apto", "delta_lula_por_apto": "Correlação com Δ Lula por apto",
                         "delta_flavio_por_apto": "Correlação com Δ Flávio por apto"})
        d.prose("Correlações entre municípios, ponderadas pelos aptos. Uma correlação positiva diz que os municípios "
                "onde a base era maior tenderam a ter ganho maior do finalista; não diz que os eleitores dessa base "
                "mudaram de voto.")
    # seções tardias
    t21 = t.get("tab21")
    if t21 is not None and not t21.empty and (t21.status == "PASS").all():
        d.line("### Seções tardias com o contexto do entorno\n"
                "A comparação do capítulo 8 (seções encerradas às 19h ou depois contra as de 17h00–17h15, no mesmo "
                "município) repetida em três etapas: (a) amostra original; (b) só unidades com entorno e renda "
                "válidos, sem controles novos; (c) a mesma amostra de (b), com renda, urbanização, densidade e favela "
                "do entorno como controles. A diferença entre (a) e (b) é efeito da amostra, não da renda; só a "
                "diferença entre (b) e (c) se deve aos controles. Indicadores municipais não entram: o efeito fixo de "
                "município os absorve.")
        tt = t21[t21.desfecho.isin(["delta_share_lula_validos", "delta_comparecimento_aptos"])].copy()
        tt["y_rot"] = tt.desfecho.map(Y_ROT)
        tt["etapa_rot"] = tt.etapa.map({"a_amostra_original": "(a) amostra original",
                                        "b_amostra_com_entorno_sem_controles": "(b) com entorno, sem controles novos",
                                        "c_amostra_com_entorno_com_controles": "(c) com entorno e controles de entorno"})
        d.table(F21, tt, ["etapa_rot", "y_rot", "beta_ajustado", "inf", "sup", "n", "municipios_com_ambas"],
                {"beta_ajustado": "pp", "inf": "pp", "sup": "pp", "n": "int", "municipios_com_ambas": "int"},
                headers={"etapa_rot": "Etapa", "y_rot": "Desfecho", "beta_ajustado": "Diferença ajustada",
                         "inf": "IC inf.", "sup": "IC sup.", "n": "Unidades", "municipios_com_ambas": "Municípios com as duas faixas"})


# --------------------------------------------------------------------------- apêndice
def _apendice(d: Doc, t: dict, man: dict, analytics: Path, out: Path, cor: pd.DataFrame | None) -> None:
    d.prose("# Apêndice técnico — relatório nacional")
    d.prose("## A.1 Definições\n"
            "Participação nos válidos = votos do candidato / votos válidos. Margem = participação de Lula − "
            "participação de Flávio. Abstenção sobre aptos = abstenções / aptos. Todas as razões são razões de "
            "somas no universo indicado. Regiões: grandes regiões do IBGE.")
    d.prose("## A.2 Cobertura e reconciliação por UF")
    cov = _read(analytics, "coverage_uf.csv")
    d.table("coverage_uf.csv", cov, ["sg_uf", "unidades_incluida", "unidades_excluida", "qt_aptos_t1_pct_incluida",
                                      "qt_votos_validos_t2_pct_incluida"],
            {"unidades_incluida": "int", "unidades_excluida": "int", "qt_aptos_t1_pct_incluida": "pct",
             "qt_votos_validos_t2_pct_incluida": "pct"})
    rec = _read(analytics, "panel_reconciliation.csv")
    d.line(f"Soma absoluta das diferenças seção → painel nos dois turnos: "
           f"{d.cite('panel_reconciliation.csv', {'todas': True}, 'dif', int(rec.dif.abs().sum()), 'int')}.")
    ref = out / "evidencias_nacional" / "referencia_m1_m2_uf.csv"
    if ref.exists():
        rr = pd.read_csv(ref)
        d.line(f"Confronto com a referência oficial independente (Relatório de Totalização, por UF e turno): "
               f"{d.cite('referencia_m1_m2_uf.csv', {'dif': 0}, 'n_linhas', int((rr.dif == 0).sum()), 'int')} de "
               f"{d.cite('referencia_m1_m2_uf.csv', {'todas': True}, 'n_linhas', len(rr), 'int')} métricas iguais.")
    d.line("## A.3 Correspondência de seções no 2º turno (D-T2-01) por UF\n"
           "Sem BU web nem CEFT do 2º turno, a seção agregada é ligada à principal esperada pelo cadastro quando não "
           "tem apuração própria no turno e a principal tem; conflito vira ambígua. A regra foi corroborada UF a UF "
           "com as mesmas quatro checagens do piloto.")
    if cor is not None and not cor.empty:
        d.table("corroboracao_dt201_uf.csv", cor, ["sg_uf", "t1_esperada_diverge_efetivada", "esperada_muda_entre_turnos",
                                                    "agregadas_t2", "agregadas_t2_com_apuracao_propria",
                                                    "principais_t2_sem_apuracao", "apuradoras_so_t1", "apuradoras_so_t2",
                                                    "aptos_dif_abs_max", "status"],
                {c: "int" for c in ("t1_esperada_diverge_efetivada", "esperada_muda_entre_turnos", "agregadas_t2",
                                    "agregadas_t2_com_apuracao_propria", "principais_t2_sem_apuracao",
                                    "apuradoras_so_t1", "apuradoras_so_t2", "aptos_dif_abs_max")})
    t3 = t["tab03"]
    d.table(F3, t3, list(t3.columns), {c: ("pp" if c.startswith("delta") else "int") for c in t3.columns
                                       if c != "nivel_agregacao"})
    d.prose("## A.4 Tabela completa por UF")
    t1 = t["tab01"]
    cols1 = ["sg_uf", "qt_aptos_t1", "qt_aptos_t2", "qt_comparecimento_t1", "qt_comparecimento_t2",
             "qt_votos_validos_t1", "qt_votos_validos_t2", "qt_lula_t1", "qt_lula_t2", "qt_flavio_t1", "qt_flavio_t2",
             "qt_votos_brancos_t1", "qt_votos_brancos_t2", "qt_votos_nulos_t1", "qt_votos_nulos_t2"]
    d.table(F1, t1, cols1, {c: "int" for c in cols1 if c != "sg_uf"})
    d.table(F9, t["tab09"].assign(nome=t["tab09"].camada.map(CAMADA)),
            ["nome", "qt_aptos_t1", "qt_aptos_t2", "qt_comparecimento_t1", "qt_comparecimento_t2",
             "qt_lula_t1", "qt_lula_t2", "qt_flavio_t1", "qt_flavio_t2"],
            {c: "int" for c in ("qt_aptos_t1", "qt_aptos_t2", "qt_comparecimento_t1", "qt_comparecimento_t2",
                                "qt_lula_t1", "qt_lula_t2", "qt_flavio_t1", "qt_flavio_t2")})
    t7 = t["tab07"]
    d.table(F7, t7, ["sg_uf", "o1_demais_candidatos_t1", "delta_lula", "delta_flavio", "delta_validos",
                     "identidade_saldos_dif", "limite_min_demais_para_lula", "limite_max_demais_para_lula",
                     "unidades_que_impedem_100pct"],
            {"o1_demais_candidatos_t1": "int", "delta_lula": "int", "delta_flavio": "int", "delta_validos": "int",
             "identidade_saldos_dif": "int", "limite_min_demais_para_lula": "pct", "limite_max_demais_para_lula": "pct",
             "unidades_que_impedem_100pct": "int"})
    if "tab08" in t:
        t8 = t["tab08"]
        f8 = "tab08_modelo_taxas_constantes_apendice.csv"
        d.prose("## A.5 Modelo de taxas constantes (dependente de hipótese)\n"
                "Sob a hipótese de taxa igual em todas as unidades, a regressão ecológica dá um parâmetro β, que não é "
                "fluxo e pode cair fora dos limites exatos. A taxa IPF vem de tabelas por unidade ajustadas às "
                "marginais; nenhuma das duas descreve trajetórias individuais, e a hipótese não é verificável.")
        err = float(t8.erro_marginal_max_unidade.max())
        aprox = err >= 1e-6
        d.line(("O IPF parou no teto de iterações: a conservação das marginais é **aproximada**, com erro máximo de "
                if aprox else "O IPF convergiu: erro máximo nas marginais de ")
               + f"{d.cite(f8, {'todas': True}, 'erro_marginal_max_unidade', err, 'f4')} voto por unidade. "
               "Tolerância de publicação fixa: "
               f"{d.cite(f8, {'todas': True}, 'ipf_tolerancia_publicacao_votos', float(t8.ipf_tolerancia_publicacao_votos.iloc[0]), 'f4')} "
               "voto no fluxo agregado, independente do erro obtido.")
        d.line(f"β fora dos limites: {d.cite(f8, {'beta_dentro_dos_limites': False}, 'n_celulas', int((~t8.beta_dentro_dos_limites.astype(bool)).sum()), 'int')} "
               f"célula(s). IPF fora dos limites exatos: {d.cite(f8, {'ipf_dentro_dos_limites_exatos': False}, 'n_celulas', int((~t8.ipf_dentro_dos_limites_exatos.astype(bool)).sum()), 'int')}; "
               f"fora da tolerância: {d.cite(f8, {'ipf_dentro_dos_limites': False}, 'n_celulas', int((~t8.ipf_dentro_dos_limites.astype(bool)).sum()), 'int')}.")
        d.table(f8, t8, ["origem_rotulo", "destino_rotulo", "taxa_min", "taxa_max", "beta_parametro",
                         "beta_dentro_dos_limites", "taxa_ipf", "ipf_dentro_dos_limites_exatos", "ipf_dentro_dos_limites"],
                {"taxa_min": "pct", "taxa_max": "pct", "beta_parametro": "pct", "taxa_ipf": "pct"})
    d.prose("## A.6 Associações completas")
    t5 = t["tab05"]
    d.line("Escala editorial: proporções em pontos percentuais por +10 p.p.; termos de contexto em log em pontos "
            "percentuais por duplicação da variável. \"Não estimado\" indica coeficiente ausente; a escala vale "
            "para todos os termos estimados.")
    cols5 = ["familia", "especificacao_ajustada", "desfecho", "recorte", "termo", "referencia", "escala_editorial",
             "efeito_simples", "efeito_ajustado", "efeito_inf_ajustado", "efeito_sup_ajustado", "n", "grupos_cluster"]
    if "escala_editorial" not in t5.columns:          # tabela antiga, sem a escala geral
        cols5 = [c for c in cols5 if c in t5.columns]
    d.table(F5, t5, cols5,
            {"efeito_simples": "f4", "efeito_ajustado": "f4", "efeito_inf_ajustado": "f4",
             "efeito_sup_ajustado": "f4", "n": "int", "grupos_cluster": "int"})
    d.prose("## A.7 Custos medidos")
    tempos = _read(analytics, "analysis_tempos.csv")
    if not tempos.empty:
        d.table("analysis_tempos.csv", tempos, ["etapa", "tempo_s", "pico_memoria_gb_acumulado"])
    nl = out / "evidencias_nacional" / "normalize_log.jsonl"
    if nl.exists():
        lg = pd.read_json(nl, lines=True)
        lg = lg[lg.codigo_saida.notna()].drop_duplicates(["uf", "turno"], keep="last")
        d.line(f"Normalize: {d.cite('normalize_log.jsonl', {'todas': True}, 'tarefas', len(lg), 'int')} tarefas UF × turno, "
               f"pico máximo de {d.cite('normalize_log.jsonl', {'todas': True}, 'pico_memoria_gb_max', float(lg.pico_memoria_gb.max()), 'f4')} GB "
               f"e soma de {d.cite('normalize_log.jsonl', {'todas': True}, 'tempo_s_soma', int(lg.tempo_s.sum()), 'int')} s de processo.")
    cp = _evid(analytics, "custos_coleta.json")
    if cp.exists():
        cu = json.loads(cp.read_text(encoding="utf-8"))
        c, lg, ln = cu["censo_bu"], cu["logs"], cu["logs_nacional_estimado"]
        ck = lambda bloco, col, v, fmt="int": d.cite("custos_coleta.json", {"bloco": bloco}, col, v, fmt)
        d.line(f"Boletins de urna do 2º turno no portal: {ck('censo_bu', 'secoes', c['secoes'])} seções, "
               f"{ck('censo_bu', 'requisicoes', c['requisicoes'])} requisições, "
               f"{ck('censo_bu', 'megabytes', round(c['bytes'] / 1e6))} MB e "
               f"{ck('censo_bu', 'minutos', round(c['segundos'] / 60))} min, com "
               f"{ck('censo_bu', 'pausas_por_limitacao', c['pausas_por_limitacao'])} pausas por limitação do portal. "
               f"Logs das seções tardias e da amostra: {ck('logs', 'secoes', lg['secoes'])} seções, "
               f"{ck('logs', 'requisicoes', lg['requisicoes'])} requisições, "
               f"{ck('logs', 'megabytes', round(lg['bytes'] / 1e6))} MB e {ck('logs', 'segundos', lg['segundos'])} s. "
               f"Os logs de todas as seções seriam {ck('logs_nacional_estimado', 'requisicoes', ln['requisicoes'])} "
               f"requisições e cerca de {ck('logs_nacional_estimado', 'gigabytes', round(ln['bytes'] / 1e9))} GB; "
               "não foram baixados.")
    d.prose("## A.8 Proveniência")
    ins = pd.DataFrame([{"insumo": k, "sha256": v} for k, v in sorted(man.get("insumos_sha256", {}).items())])
    d.table("analysis_manifest.json:insumos_sha256", ins, ["insumo", "sha256"])
    fb = pd.DataFrame(man.get("fontes_brutas", []))
    if not fb.empty:
        fb["fonte"] = fb["fonte"].fillna("") if "fonte" in fb.columns else ""
        fb = fb.drop_duplicates(["tabela", "nr_turno", "fonte", "source_id"])
        d.table("analysis_manifest.json:fontes_brutas", fb.sort_values(["tabela", "nr_turno", "fonte"]),
                ["tabela", "nr_turno", "fonte", "source_id"])
    dirty = man.get("codigo_com_alteracoes_nao_commitadas")
    estado = {True: "sim", False: "não"}.get(dirty, f"desconhecido ({man.get('git_diagnostico') or 'sem diagnóstico'})")
    d.line(f"Commit `{man.get('git_commit')}` · código com alterações não commitadas: {estado} · contrato "
           f"`{man.get('contract_version')}` · execução `{man.get('executado_em_utc')}`.")
    _apendice_socio(d, t)
    _apendice_fraude(d, t.get("al", {}))


FONTES_SOCIO = pd.DataFrame([
    {"indicador": "renda_pc", "medida": "rendimento domiciliar per capita médio (R$)", "fonte": "IBGE, SIDRA 10295",
     "periodo": "Censo 2022", "universo": "amostra; município", "escala": "por duplicação"},
    {"indicador": "baixa_renda", "medida": "pessoas com rendimento domiciliar per capita até ½ SM (%)",
     "fonte": "IBGE, SIDRA 10296", "periodo": "Censo 2022", "universo": "amostra; município", "escala": "+10 p.p."},
    {"indicador": "desocupacao", "medida": "desocupados / força de trabalho (%)", "fonte": "IBGE, SIDRA 6580",
     "periodo": "Censo 2022", "universo": "amostra; 14 anos ou mais", "escala": "+5 p.p."},
    {"indicador": "vinculos", "medida": "vínculos ativos no estabelecimento por mil habitantes",
     "fonte": "MTE, RAIS estabelecimentos", "periodo": "31/12/2025", "universo": "município do estabelecimento",
     "escala": "+100 por mil"},
    {"indicador": "pbf", "medida": "registros da folha do Novo Bolsa Família por 100 domicílios ocupados",
     "fonte": "CGU/MDS, Portal da Transparência; IBGE 4712", "periodo": "folha 08/2026; domicílios 2022",
     "universo": "razão administrativa; não são famílias", "escala": "+10 por 100"},
    {"indicador": "urbana", "medida": "população urbana (%)", "fonte": "IBGE, SIDRA 9923", "periodo": "Censo 2022",
     "universo": "universo; município", "escala": "+10 p.p."},
    {"indicador": "entorno", "medida": "renda média do responsável, urbanização, densidade e favela num raio de 1 km",
     "fonte": "IBGE, agregados por setor e malha 2022; TSE, locais de votação 2026", "periodo": "Censo 2022",
     "universo": "interpolação por área; local do 1º turno", "escala": "duplicação ou +10 p.p."},
])


def _apendice_socio(d: Doc, t: dict) -> None:
    if t.get("tab17") is None:
        return
    d.prose("## A.9 Contexto socioeconômico: fontes, cobertura e sensibilidades")
    d.table("PLANO_ESTATISTICO_37.md", FONTES_SOCIO, ["indicador", "medida", "fonte", "periodo", "universo", "escala"],
            headers={"indicador": "Indicador", "medida": "Medida", "fonte": "Fonte", "periodo": "Período",
                     "universo": "Universo", "escala": "Escala do coeficiente"})
    t22 = t.get("tab22")
    if t22 is not None and not t22.empty:
        c = t22.copy()
        c["pct_aptos_entorno"] = c.aptos_entorno_valido / c.aptos
        c["pct_aptos_renda"] = c.aptos_renda_valida / c.aptos
        d.prose("**Cobertura do entorno por UF** (unidades do painel; entorno válido e com renda válida):")
        d.table(F22, c, ["sg_uf", "unidades", "unidades_entorno_valido", "pct_aptos_entorno", "unidades_renda_valida",
                         "pct_aptos_renda"],
                {"unidades": "int", "unidades_entorno_valido": "int", "pct_aptos_entorno": "pct",
                 "unidades_renda_valida": "int", "pct_aptos_renda": "pct"},
                headers={"sg_uf": "UF", "unidades": "Unidades", "unidades_entorno_valido": "Com entorno",
                         "pct_aptos_entorno": "Aptos com entorno", "unidades_renda_valida": "Com renda",
                         "pct_aptos_renda": "Aptos com renda"})
    t16 = t.get("tab16")
    if t16 is not None and not t16.empty:
        r = t16.copy()
        r["ind_rot"] = r.indicador.map(SOCIO_CURTO)
        d.prose("**Faixas por região** (mesmos cortes nacionais):")
        d.table(F16, r.sort_values(["indicador", "regiao", "faixa"]),
                ["ind_rot", "regiao", "faixa", "municipios", "share_lula_t1", "share_lula_t2", "delta_share_lula",
                 "delta_comparecimento"],
                {"municipios": "int", "share_lula_t1": "pct", "share_lula_t2": "pct", "delta_share_lula": "pp",
                 "delta_comparecimento": "pp"},
                headers={"ind_rot": "Indicador", "regiao": "Região", "faixa": "Quintil", "municipios": "Municípios",
                         "share_lula_t1": "Lula, 1º", "share_lula_t2": "Lula, 2º", "delta_share_lula": "Δ Lula",
                         "delta_comparecimento": "Δ comparecimento"})
    s = t["tab17"].copy()
    s["ind_rot"] = s.indicador.map(lambda i: SOCIO_CURTO.get(i, i))
    s["y_rot"] = s.desfecho.map(Y_ROT)
    s["variante"] = s.apply(lambda r: "principal" if r.papel == "principal" else (
        "indicador alternativo" if r.papel == "sensibilidade_indicador" else
        "pesos iguais" if r.pesos == "iguais" else "erros por UF" if r.cluster == "sg_uf" else
        "erros robustos (HC1)" if r.cluster == "HC1" else "sem municípios > 1 milhão de aptos" if r.sem_grandes
        else "outra"), axis=1)
    d.prose("**Modelos municipais, todas as variantes** (inclui a margem Lula − Flávio, desfecho secundário):")
    d.table(F17, s[s.especificacao == "ajustado"].sort_values(["indicador", "desfecho", "variante"]),
            ["ind_rot", "y_rot", "variante", "efeito_pp", "inf_pp", "sup_pp", "n", "grupos"],
            {"efeito_pp": "f4", "inf_pp": "f4", "sup_pp": "f4", "n": "int", "grupos": "int"},
            filtro="especificacao=ajustado",
            headers={"ind_rot": "Indicador", "y_rot": "Desfecho", "variante": "Variante", "efeito_pp": "p.p.",
                     "inf_pp": "IC inf.", "sup_pp": "IC sup.", "n": "Municípios", "grupos": "Grupos"})
    t24 = t.get("tab24")
    if t24 is not None and not t24.empty:
        j = t24.copy()
        j["ind_rot"] = j.indicador.map(SOCIO_CURTO)
        j["y_rot"] = j.desfecho.map(Y_ROT)
        d.prose("**Todos os indicadores no mesmo modelo** (só para diagnosticar colinearidade):")
        d.table("tab24_socio_modelo_conjunto.csv", j, ["ind_rot", "y_rot", "efeito_pp", "inf_pp", "sup_pp", "vif"],
                {"efeito_pp": "f4", "inf_pp": "f4", "sup_pp": "f4", "vif": "f4"},
                headers={"ind_rot": "Indicador", "y_rot": "Desfecho", "efeito_pp": "p.p.", "inf_pp": "IC inf.",
                         "sup_pp": "IC sup.", "vif": "VIF"})
    t18 = t.get("tab18")
    if t18 is not None and not t18.empty:
        e = t18[t18.status == "PASS"].copy()
        e["ind_rot"] = e.indicador.map(ENT_ROT)
        e["y_rot"] = e.desfecho.map(Y_ROT)
        e["amostra_rot"] = e.filtro.map(ENT_AMOSTRA).fillna(e.filtro)
        e["erro_rot"] = e.cluster.map(ENT_ERRO).fillna(e.cluster)
        d.prose("**Entorno, todas as variantes:**")
        d.table(F18, e.sort_values(["indicador", "desfecho", "filtro", "cluster"]),
                ["ind_rot", "y_rot", "amostra_rot", "erro_rot", "efeito_pp", "inf_pp", "sup_pp", "n_unidades",
                 "n_locais"],
                {"efeito_pp": "f4", "inf_pp": "f4", "sup_pp": "f4", "n_unidades": "int", "n_locais": "int"},
                headers={"ind_rot": "Entorno", "y_rot": "Desfecho", "amostra_rot": "Amostra", "erro_rot": "Erros por",
                         "efeito_pp": "p.p.", "inf_pp": "IC inf.", "sup_pp": "IC sup.", "n_unidades": "Unidades",
                         "n_locais": "Locais"})
    t23 = t.get("tab23")
    if t23 is not None and not t23.empty:
        d.prose("## A.10 Faixas por UF\n"
                "Todas as UFs e todos os indicadores, sem seleção por significância: Δ participação de Lula no quintil "
                "mais baixo e no mais alto de cada UF (cortes nacionais; quintil vazio na UF fica sem valor).")
        u = t23.pivot_table(index=["indicador", "sg_uf"], columns="faixa", values="delta_share_lula").reset_index()
        u.columns = [f"q{c}" if isinstance(c, (int, np.integer)) else c for c in u.columns]
        u["ind_rot"] = u.indicador.map(SOCIO_CURTO)
        d.table("tab23_socio_faixas_uf.csv", u, ["ind_rot", "sg_uf"] + [f"q{k}" for k in range(1, 6) if f"q{k}" in u],
                {f"q{k}": "pp" for k in range(1, 6)},
                headers={"ind_rot": "Indicador", "sg_uf": "UF", **{f"q{k}": f"Q{k}" for k in range(1, 6)}})


# --------------------------------------------------------------------------- destaques (revisão editorial de 29/10)
F25 = "tab25_socio_pbf_clt.csv"
FA = {k: f"alegacoes_{k}.csv" for k in ("a00_integridade", "a01_secoes_tardias", "a02_benford", "a03_biometria",
                                         "a04_unanimes", "a06_modelo_urna", "a07_uf", "a08_teixeira",
                                         "a09_secoes_regiao", "a10_curva_totalizacao")}
FA_CLAIMS = "alegacoes_fraude.csv"
FIG_AL = "figuras_alegacoes"
CONTRIB_IND = ("pbf", "renda_pc", "vinculos", "urbana")
MODELO_ROT = {"pct_lula_t2": "2026, mesmo município", "pct_lula_t2_mesmo_local": "2026, mesma escola",
              "delta_lula": "2026, variação 1º → 2º turno, mesmo município",
              "pct_lula_t2_2022": "2022, mesmo município", "pct_lula_t2_2022_mesmo_local": "2022, mesma escola",
              "delta_2022_2026_mesma_secao": "mesma seção 2022 → 2026, mesmo município",
              "delta_2022_2026_mesma_secao_mesmo_local": "mesma seção 2022 → 2026, mesma escola"}


def _contrib(t15: pd.DataFrame) -> pd.DataFrame:
    """Fração dos válidos do 1º turno, do ganho de votos de Lula e do aumento do comparecimento por quintil."""
    f = t15[t15.indicador.isin(CONTRIB_IND)].copy()
    f["d_comp"] = f.qt_comparecimento_t2 - f.qt_comparecimento_t1
    g = f.groupby("indicador")
    f["fracao_validos_t1"] = f.qt_votos_validos_t1 / g.qt_votos_validos_t1.transform("sum")
    f["fracao_ganho_lula"] = f.delta_qt_lula / g.delta_qt_lula.transform("sum")
    f["fracao_aumento_comparecimento"] = f.d_comp / g.d_comp.transform("sum")
    return f


def _alegacoes(out: Path) -> dict:
    tab = out / "tabelas_nacional"
    al = {k: pd.read_csv(tab / f) for k, f in FA.items() if (tab / f).exists()}
    claims = out.parents[1] / "docs" / "sources" / "contraste" / FA_CLAIMS
    if claims.exists():
        al["claims"] = pd.read_csv(claims)
    if "a10_curva_totalizacao" in al:
        c = al["a10_curva_totalizacao"]
        c["minuto"] = pd.to_datetime(c.minuto)
        c["lider_sem_tardias"] = np.where(c.pct_lula_sem_tardias >= 50, "Lula", "Flávio")
    return al


def _hora(ts) -> str:
    return f"{ts.hour}h{ts.minute:02d}"


def _janela(ts) -> str:
    """Faixa de cinco minutos da curva reconstruída."""
    fim = ts + pd.Timedelta(minutes=5)
    return f"entre {_hora(ts)} e {_hora(fim)}"


def _trocas(c: pd.DataFrame, col: str) -> pd.DataFrame:
    return c[c[col] != c[col].shift()].iloc[1:]


def _destaques(d: Doc, t: dict, al: dict) -> None:
    """Resumo: os achados próprios do estudo antes das contas que a imprensa já publicou."""
    t15, t17, t18, t25 = t.get("tab15"), t.get("tab17"), t.get("tab18"), t.get("tab25")
    d.prose("## Principais achados\n"
            "O ajuste por município, o entorno e o horário de encerramento seguem planos registrados antes das "
            "estimativas. A divisão do ganho de Lula por faixa, a reprodução do recorte de imprensa e os testes das "
            "alegações de fraude foram feitos depois, na revisão editorial: são descritivos e estão marcados assim "
            "no relatório.")
    if t15 is not None and not t15.empty:
        f = _contrib(t15).set_index(["indicador", "faixa"])
        if ("pbf", 5) in f.index and ("renda_pc", 5) in f.index:
            p5, r5 = f.loc[("pbf", 5)], f.loc[("renda_pc", 5)]
            kp, kr = {"indicador": "pbf", "faixa": 5}, {"indicador": "renda_pc", "faixa": 5}
            menos = p5.fracao_ganho_lula < p5.fracao_validos_t1
            d.line("- **"
                   + ("A virada veio mais dos municípios ricos e urbanos do que da base do Bolsa Família."
                      if menos and r5.fracao_ganho_lula > r5.fracao_validos_t1 else
                      "O ganho de Lula nas faixas de Bolsa Família e de renda.")
                   + f"** Os {d.cite(F15, kp, 'municipios', int(p5.municipios), 'int')} municípios com mais registros "
                   f"do Bolsa Família por domicílio (o quinto mais alto) tinham "
                   f"{d.cite(F15, kp, 'qt_votos_validos_t1/soma', float(p5.fracao_validos_t1), 'pct')} dos votos válidos do "
                   f"1º turno, {'mas' if menos else 'e'} responderam por "
                   f"{d.cite(F15, kp, 'delta_qt_lula/soma', float(p5.fracao_ganho_lula), 'pct')} do ganho de votos de Lula"
                   + (f"; o comparecimento ali diminuiu, na contramão do país (fração do aumento nacional: "
                      f"{d.cite(F15, kp, 'delta_comparecimento_votos/soma', float(p5.fracao_aumento_comparecimento), 'pct')})."
                      if p5.fracao_aumento_comparecimento < 0 else
                      f" e por {d.cite(F15, kp, 'delta_comparecimento_votos/soma', float(p5.fracao_aumento_comparecimento), 'pct')} "
                      "do aumento do comparecimento.")
                   + " No quinto de maior renda per capita, a fração dos válidos, a do ganho de Lula e a do aumento do comparecimento foram "
                   f"{d.cite(F15, kr, 'qt_votos_validos_t1/soma', float(r5.fracao_validos_t1), 'pct')}, "
                   f"{d.cite(F15, kr, 'delta_qt_lula/soma', float(r5.fracao_ganho_lula), 'pct')} e "
                   f"{d.cite(F15, kr, 'delta_comparecimento_votos/soma', float(r5.fracao_aumento_comparecimento), 'pct')}.")
    if t25 is not None and {"pbf_maior_que_clt", "demais"} <= set(t25.grupo):
        g, o = t25.set_index("grupo").loc["pbf_maior_que_clt"], t25.set_index("grupo").loc["demais"]
        kg, ko = {"grupo": "pbf_maior_que_clt"}, {"grupo": "demais"}
        menor = g.delta_share_lula < o.delta_share_lula
        d.line("- **O recorte da imprensa sobre o Bolsa Família se reproduz, "
               + ("mas não indica que o programa decidiu a virada.** " if menor else "e indica avanço maior nele.** ")
               + f"Nos {d.cite(F25, kg, 'municipios', int(g.municipios), 'int')} municípios em que os registros do "
               "Bolsa Família superam os empregos com carteira assinada (o recorte do Poder360, aproximado com a folha "
               f"de agosto e a RAIS), Lula foi de {d.cite(F25, kg, 'share_lula_t1', float(g.share_lula_t1), 'pct')} para "
               f"{d.cite(F25, kg, 'share_lula_t2', float(g.share_lula_t2), 'pct')} dos válidos e ganhou "
               f"{d.cite(F25, kg, 'delta_qt_lula', int(g.delta_qt_lula), 'int')} votos. Esse grupo tinha "
               f"{d.cite(F25, kg, 'fracao_validos_t1', float(g.fracao_validos_t1), 'pct')} dos válidos e deu "
               f"{d.cite(F25, kg, 'fracao_ganho_lula', float(g.fracao_ganho_lula), 'pct')} do ganho de Lula; a "
               f"participação dele subiu {d.cite(F25, kg, 'delta_share_lula', float(g.delta_share_lula), 'pp')} ali e "
               f"{d.cite(F25, ko, 'delta_share_lula', float(o.delta_share_lula), 'pp')} nos demais municípios"
               + (", como a UOL notou ao apontar que Lula cresceu mais onde o programa pesa menos." if menor else "."))
    if t17 is not None and not t17.empty:
        p = t17[(t17.papel == "principal") & (t17.especificacao == "ajustado")]
        pb = t17[(t17.papel == "principal") & (t17.especificacao == "bruto")]

        def lin(ind, y, base=p):
            r = base[(base.indicador == ind) & (base.desfecho == y)]
            return None if r.empty else r.iloc[0]
        pl, pc = lin("pbf", "delta_share_lula_validos"), lin("pbf", "delta_comparecimento_aptos")
        rl, rlb = lin("renda_pc", "delta_share_lula_validos"), lin("renda_pc", "delta_share_lula_validos", pb)
        if pl is not None and pc is not None and rl is not None and rlb is not None:
            def ic(ind, y, esp, r):
                k = {"indicador": ind, "desfecho": y, "especificacao": esp, "papel": "principal"}
                return (f"{d.cite(F17, k, 'efeito_pp', float(r.efeito_pp), 'ppv')}, IC 95% de "
                        f"{d.cite(F17, k, 'inf_pp', float(r.inf_pp), 'ppv')} a {d.cite(F17, k, 'sup_pp', float(r.sup_pp), 'ppv')}")
            frase_pl = {"zero": "não se associa ao avanço de Lula", "positivo": "se associa a avanço maior de Lula",
                        "negativo": "se associa a avanço menor de Lula"}[_sinal(pl)]
            frase_pc = {"zero": "não se associa à variação do comparecimento",
                        "positivo": "se associa a aumento maior do comparecimento",
                        "negativo": "se associa a aumento menor do comparecimento"}[_sinal(pc)]
            frase_rl = ("muda de sinal depois do ajuste" if _sinal(rl) != _sinal(rlb) and "zero" not in (_sinal(rl), _sinal(rlb))
                        else "deixa de se distinguir de zero" if _sinal(rl) == "zero" else "mantém o sinal")
            d.line("- **Comparando municípios parecidos** (mesma UF e mesma votação no 1º turno), a presença maior do "
                   f"Bolsa Família {frase_pl} ({ic('pbf', 'delta_share_lula_validos', 'ajustado', pl)}, por +10 por "
                   f"100 domicílios) e {frase_pc} ({ic('pbf', 'delta_comparecimento_aptos', 'ajustado', pc)}). A renda "
                   f"per capita, que na comparação bruta acompanha avanço {'maior' if _sinal(rlb) == 'positivo' else 'menor'} "
                   f"de Lula, {frase_rl} ({ic('renda_pc', 'delta_share_lula_validos', 'ajustado', rl)}, por duplicação). "
                   "São associações entre territórios, não efeitos nem votos individuais.")
    if t18 is not None and not t18.empty:
        e = t18[(t18.status == "PASS") & (t18.filtro == "principal") & (t18.cluster == "id_local")
                & (t18.desfecho == "delta_share_lula_validos")].set_index("indicador")
        if {"densidade", "renda_resp"} <= set(e.index):
            kd = {"indicador": "densidade", "desfecho": "delta_share_lula_validos", "filtro": "principal", "cluster": "id_local"}
            kr = {**kd, "indicador": "renda_resp"}
            sd, sr = _sinal(e.loc["densidade"]), _sinal(e.loc["renda_resp"])
            d.line("- **Dentro de cada cidade** (seções comparadas com outras do mesmo município, entorno de 1 km do "
                   "local de votação pelos setores do Censo), a participação de Lula avançou "
                   + {"positivo": "mais", "negativo": "menos", "zero": "de forma indistinguível"}[sd]
                   + f" onde o entorno é mais denso ({d.cite(F18, kd, 'efeito_pp', float(e.loc['densidade'].efeito_pp), 'f3')} "
                   "p.p. por duplicação da densidade); com a renda do entorno, a associação "
                   + {"zero": "não se distingue de zero", "positivo": "é positiva", "negativo": "é negativa"}[sr]
                   + f" ({d.cite(F18, kr, 'efeito_pp', float(e.loc['renda_resp'].efeito_pp), 'f3')} p.p. por duplicação).")
    a00, a01, a10 = al.get("a00_integridade"), al.get("a01_secoes_tardias"), al.get("a10_curva_totalizacao")
    if a00 is not None and a01 is not None and a10 is not None:
        r0 = a00.iloc[0]
        f1 = a01.set_index("faixa")
        norm = f1.loc["b) 17h00–17h10"]
        pior = f1.loc[[i for i in f1.index if str(i).startswith("pior caso")][0]]
        tard = f1.loc[["c) 17h10–19h00", "d) 19h00 ou depois"]].secoes.sum()
        tc, ts = _trocas(a10, "lider"), _trocas(a10, "lider_sem_tardias")
        iguais = list(tc.lider) == list(ts.lider_sem_tardias) and len(tc) > 0
        perto = iguais and all(abs((a - b).total_seconds()) <= 600 for a, b in zip(tc.minuto, ts.minuto))
        txt = ("- **Prorrogação e alegações de fraude.** Os boletins de urna das "
               f"{d.cite(FA['a00_integridade'], {'linha': 0}, 'secoes_bu', int(r0.secoes_bu), 'int')} seções do território, "
               f"lidos um a um, somam o resultado oficial com {d.cite(FA['a00_integridade'], {'linha': 0}, 'secoes_com_diferenca', int(r0.secoes_com_diferenca), 'int')} "
               "seções divergentes. Só nas seções encerradas até 17h10, Lula vence por "
               f"{d.cite(FA['a01_secoes_tardias'], {'faixa': 'b) 17h00–17h10'}, 'margem_lula', int(norm.margem_lula), 'int')} votos; "
               f"mesmo que todo voto do dia nas {d.cite(FA['a01_secoes_tardias'], {'faixa': 'c+d'}, 'secoes', int(tard), 'int')} "
               "seções que fecharam depois fosse de Flávio, Lula venceria por "
               f"{d.cite(FA['a01_secoes_tardias'], {'faixa': 'pior caso'}, 'margem_lula', int(pior.margem_lula), 'int')}.")
        if perto:
            txt += (" Sem essas seções, a curva do painel de totalização troca de líder praticamente nos mesmos "
                    "momentos ("
                    + _lista([f"para {r.lider_sem_tardias} {_janela(r.minuto)}" for r in ts.itertuples()])
                    + "; com elas, "
                    + _lista([f"{_janela(r.minuto)}" for r in tc.itertuples()])
                    + "): a virada do painel vem da ordem de chegada dos boletins.")
        d.line(txt)


def _socio_destaques(d: Doc, t: dict) -> None:
    """Capítulo 9: quem respondeu pela virada e reprodução do recorte de imprensa."""
    t15, t25 = t.get("tab15"), t.get("tab25")
    if t15 is None or t15.empty:
        return
    d.prose("### Quem respondeu pela virada\n"
            "Para cada quinto de municípios, a fração que ele tinha dos votos válidos do 1º turno, a fração do ganho "
            "de votos de Lula e a fração do aumento do comparecimento. Uma faixa que responde por mais ganho do que "
            "o seu peso contribuiu acima da média. É contabilidade de saldos, não de eleitores. Esta seção e a "
            "reprodução do recorte de imprensa abaixo não estavam no plano pré-registrado: foram acrescentadas na "
            "revisão editorial, usam os mesmos quintis e insumos e não alteram nenhuma estimativa do plano.")
    f = _contrib(t15)
    f["ind_rot"] = f.indicador.map(SOCIO_CURTO)
    d.table(F15, f.sort_values(["indicador", "faixa"]),
            ["ind_rot", "faixa", "fracao_validos_t1", "fracao_ganho_lula", "fracao_aumento_comparecimento",
             "delta_share_lula"],
            {"fracao_validos_t1": "pct", "fracao_ganho_lula": "pct", "fracao_aumento_comparecimento": "pct",
             "delta_share_lula": "pp"},
            filtro="indicador∈{pbf,renda_pc,vinculos,urbana}",
            headers={"ind_rot": "Indicador", "faixa": "Quintil", "fracao_validos_t1": "Fração dos válidos (1º)",
                     "fracao_ganho_lula": "Fração do ganho de Lula",
                     "fracao_aumento_comparecimento": "Fração do aumento do comparecimento", "delta_share_lula": "Δ Lula"})
    if t25 is not None and {"pbf_maior_que_clt", "demais"} <= set(t25.grupo):
        d.prose("**Recorte da imprensa: Bolsa Família contra emprego formal.** A reportagem do Poder360 agrupou os "
                "municípios com mais famílias no Bolsa Família do que empregos com carteira assinada e atribuiu ao "
                "reajuste do benefício o freio a Flávio. O projeto refaz o recorte com os registros de pagamento da "
                "folha de agosto (CGU/MDS) e os vínculos CLT da RAIS; as definições e os períodos da reportagem não "
                "foram publicados, e a contagem de municípios difere.")
        g = t25[t25.grupo.isin(["pbf_maior_que_clt", "demais"])].copy()
        g["grupo_rot"] = g.grupo.map({"pbf_maior_que_clt": "registros do PBF > vínculos CLT", "demais": "demais municípios"})
        d.table(F25, g, ["grupo_rot", "municipios", "share_lula_t1", "share_lula_t2", "delta_share_lula",
                         "delta_qt_lula", "fracao_validos_t1", "fracao_ganho_lula", "fracao_aumento_comparecimento"],
                {"municipios": "int", "share_lula_t1": "pct", "share_lula_t2": "pct", "delta_share_lula": "pp",
                 "delta_qt_lula": "int", "fracao_validos_t1": "pct", "fracao_ganho_lula": "pct",
                 "fracao_aumento_comparecimento": "pct"},
                headers={"grupo_rot": "Grupo", "municipios": "Municípios", "share_lula_t1": "Lula, 1º",
                         "share_lula_t2": "Lula, 2º", "delta_share_lula": "Δ Lula", "delta_qt_lula": "Votos ganhos",
                         "fracao_validos_t1": "Fração dos válidos (1º)", "fracao_ganho_lula": "Fração do ganho de Lula",
                         "fracao_aumento_comparecimento": "Fração do aumento do comparecimento"})
        gg, oo = g.set_index("grupo").loc["pbf_maior_que_clt"], g.set_index("grupo").loc["demais"]
        d.prose("O número de votos e a direção se aproximam dos publicados. A leitura muda quando se olha o peso do "
                "grupo: "
                + ("ele respondeu por uma fração do ganho de Lula menor do que a sua fração dos votos, e a participação "
                   "de Lula subiu menos ali do que no resto do país. O avanço nos municípios mais dependentes do "
                   "programa é real, mas o grosso da virada veio de fora deles; o recorte não separa o reajuste de "
                   "outras diferenças entre os municípios, e nada aqui é efeito do programa."
                   if gg.fracao_ganho_lula < gg.fracao_validos_t1 and gg.delta_share_lula < oo.delta_share_lula else
                   "ele respondeu por uma fração do ganho de Lula igual ou maior do que a sua fração dos votos; o recorte "
                   "não separa o reajuste de outras diferenças entre os municípios, e nada aqui é efeito do programa."))


def _fraude(d: Doc, al: dict) -> None:
    """Capítulo 10: alegações de fraude depois do 2º turno (os três testes centrais e o quadro)."""
    a00, a01, a10, cl = (al.get(k) for k in ("a00_integridade", "a01_secoes_tardias", "a10_curva_totalizacao", "claims"))
    if a00 is None or a01 is None or a10 is None:
        return
    d.prose("### Alegações de fraude depois do 2º turno\n"
            "Alegações que circularam depois da votação, descritas pelas checagens do TSE e da Agência Lupa, testadas "
            "com o boletim de urna de cada seção do território, decodificado pelo projeto. Os três testes centrais "
            "estão abaixo; os demais, no apêndice técnico, e a fundamentação completa, em `ALEGACOES_FRAUDE_2026.md`. "
            "Os testes foram desenhados depois das alegações e dos dados, na revisão editorial, sem plano "
            "pré-registrado; os que são contas exatas (soma dos boletins, pior caso) não dependem dessa escolha, e "
            "os comparativos estão marcados como associação.")
    r0 = a00.iloc[0]
    k0 = {"linha": 0}
    d.line("- **Os boletins somam o resultado oficial (A05).** "
           f"{d.cite(FA['a00_integridade'], k0, 'secoes_bu', int(r0.secoes_bu), 'int')} boletins, um por seção do "
           f"território; seção a seção, os votos de Lula e de Flávio coincidem com o consolidado oficial em todas, com "
           f"{d.cite(FA['a00_integridade'], k0, 'secoes_com_diferenca', int(r0.secoes_com_diferenca), 'int')} divergências "
           f"(Lula {d.cite(FA['a00_integridade'], k0, 'lula_bu', int(r0.lula_bu), 'int')}, Flávio "
           f"{d.cite(FA['a00_integridade'], k0, 'flavio_bu', int(r0.flavio_bu), 'int')} no território). Não houve "
           "\"apagão de dados\": o boletim de cada seção é público no portal do TSE.")
    d.prose("**As seções que fecharam tarde não decidiram (A01).** O relatório anônimo atribuiu o resultado às seções "
            "encerradas depois das 17h, somando os votos do dia inteiro nelas como se fossem da prorrogação. Margem "
            "por horário de encerramento gravado no boletim (Brasília):")
    f = a01.copy()
    f["faixa_rot"] = f.faixa.map({"b) 17h00–17h10": "encerradas até 17h10", "c) 17h10–19h00": "entre 17h10 e 19h",
                                  "d) 19h00 ou depois": "às 19h ou depois"}).fillna(
        "pior caso: todo voto do dia nas seções tardias para Flávio")
    d.table(FA["a01_secoes_tardias"], f, ["faixa_rot", "secoes", "margem_lula", "pct_lula_validos"],
            {"secoes": "int", "margem_lula": "int", "pct_lula_validos": "f2"},
            headers={"faixa_rot": "Seções", "secoes": "Quantidade", "margem_lula": "Lula − Flávio",
                     "pct_lula_validos": "Lula nos válidos (%)"})
    d.line(f"![Figura A2 — Margem por horário de encerramento]({FIG_AL}/figA2_margem_por_encerramento.png)")
    tc, ts = _trocas(a10, "lider"), _trocas(a10, "lider_sem_tardias")
    kc = {"arquivo": FA["a10_curva_totalizacao"]}
    d.line("**A virada do painel não veio da prorrogação (A10).** Reconstruída pelo horário de primeira totalização "
           f"de cada uma das {d.cite(FA['a10_curva_totalizacao'], kc, 'secoes(acumulado final)', int(a10.secoes.max()), 'int')} "
           "seções, em faixas de cinco minutos, a curva do painel troca de líder "
           + _lista([f"{_janela(r.minuto)} (para {r.lider})" for r in tc.itertuples()])
           + "; sem nenhuma seção encerrada depois das 17h10, as trocas ficam "
           + _lista([f"{_janela(r.minuto)} (para {r.lider_sem_tardias})" for r in ts.itertuples()])
           + ". O painel parcial mostra a ordem de chegada dos boletins por região, não uma amostra do país.")
    d.line(f"![Figura A1 — Curva do painel com e sem as seções tardias]({FIG_AL}/figA1_curva_totalizacao.png)")
    if cl is not None and not cl.empty:
        d.table(FA_CLAIMS, cl, ["claim_id", "parafrase_fiel", "veredicto"],
                headers={"claim_id": "Prop.", "parafrase_fiel": "Alegação (paráfrase)", "veredicto": "Conclusão"})


def _apendice_fraude(d: Doc, al: dict) -> None:
    if not al:
        return
    d.prose("## A.11 Alegações de fraude: demais testes\n"
            "Definições, fontes e limites em `ALEGACOES_FRAUDE_2026.md`; números em "
            "`evidencias_nacional/alegacoes_numeros.json`.")
    b = al.get("a02_benford")
    if b is not None:
        d.prose("**Lei de Benford (A02).** Desvio médio absoluto (MAD) das frequências do 1º e do 2º dígito dos votos "
                "por seção em relação à lei de Benford, nos dados reais e numa eleição simulada sem fraude (cada seção "
                "sorteia os votos com a participação do candidato no município). O desvio dos dados reais é da mesma "
                "ordem do da simulação: o teste mede o tamanho das seções, não fraude.")
        d.table(FA["a02_benford"], b, ["serie", "mad_1d", "mad_2d"], {"mad_1d": "f3", "mad_2d": "f3"},
                headers={"serie": "Série", "mad_1d": "MAD, 1º dígito", "mad_2d": "MAD, 2º dígito"})
    bio = al.get("a03_biometria")
    if bio is not None:
        d.prose("**Habilitação sem biometria (A03).** Efeito de um ponto percentual a mais de eleitores habilitados "
                "sem a digital, comparando seções do mesmo município. Se essas habilitações tivessem servido para "
                "inserir votos, a variação entre os turnos seria positiva; a associação com o 1º turno, anterior a "
                "qualquer habilitação do 2º, funciona como placebo.")
        r = bio[bio.tabela == "regressao"]
        d.table(FA["a03_biometria"], r, ["desfecho", "coef", "ic95_inf", "ic95_sup"],
                {"coef": "f3", "ic95_inf": "f3", "ic95_sup": "f3"}, filtro="tabela=regressao",
                headers={"desfecho": "Desfecho", "coef": "p.p.", "ic95_inf": "IC inf.", "ic95_sup": "IC sup."})
    u = al.get("a04_unanimes")
    if u is not None:
        d.prose("**Seções com votos para um só candidato (A04).** Segundo turno, território.")
        d.table(FA["a04_unanimes"], u, ["ano", "so_votos_para", "secoes", "votos", "ufs"], {"secoes": "int", "votos": "int"},
                headers={"ano": "Ano", "so_votos_para": "Só votos para", "secoes": "Seções", "votos": "Votos", "ufs": "UFs"})
    m = al.get("a06_modelo_urna")
    if m is not None:
        d.prose("**Modelo da urna (A06).** Diferença de participação de Lula entre urnas antigas e a UE2020, em "
                "comparações cada vez mais estreitas. O sinal muda conforme o controle, o que indica diferença de "
                "lugar e não de urna; na mesma seção e na mesma escola, a troca de modelo entre 2022 e 2026 não se "
                "distingue de zero.")
        e = m[(m.tabela == "efeito_fixo") & m.desfecho.isin(MODELO_ROT)].copy()
        e["comparacao"] = e.desfecho.map(MODELO_ROT)
        d.table(FA["a06_modelo_urna"], e, ["comparacao", "termo", "coef", "ic95_inf", "ic95_sup"],
                {"coef": "f2", "ic95_inf": "f2", "ic95_sup": "f2"}, filtro="tabela=efeito_fixo",
                headers={"comparacao": "Comparação", "termo": "Modelos", "coef": "p.p.", "ic95_inf": "IC inf.",
                         "ic95_sup": "IC sup."})
    uf = al.get("a07_uf")
    if uf is not None:
        d.prose("**Bahia e ganho por UF (A07, A09).** Votos ganhos entre os turnos e, nas seções que fecharam depois "
                "das 17h10, os votos de Lula no dia inteiro. As cinco UFs com maior ganho de Lula:")
        d.table(FA["a07_uf"], uf.sort_values("rank_delta_lula").head(5),
                ["sg_uf", "delta_lula", "delta_flavio", "secoes_encerradas_apos_17h10", "lula_nessas_secoes_dia_todo"],
                {"delta_lula": "int", "delta_flavio": "int", "secoes_encerradas_apos_17h10": "int",
                 "lula_nessas_secoes_dia_todo": "int"}, filtro="cinco maiores Δ Lula",
                headers={"sg_uf": "UF", "delta_lula": "Δ Lula", "delta_flavio": "Δ Flávio",
                         "secoes_encerradas_apos_17h10": "Seções após 17h10",
                         "lula_nessas_secoes_dia_todo": "Lula nelas, dia todo"})
    tx = al.get("a08_teixeira")
    if tx is not None:
        k = {"municipio": "Teixeira de Freitas (BA)"}
        d.line("**Teixeira de Freitas (A08).** "
               f"{d.cite(FA['a08_teixeira'], k, 'n_secoes', len(tx), 'int')} boletins; somados, Lula − Flávio = "
               f"{d.cite(FA['a08_teixeira'], k, 'soma(margem)', int(tx.margem.sum()), 'int')}. Três boletins escolhidos "
               "não representam o município: o resultado é a soma de todos.")
    rg = al.get("a09_secoes_regiao")
    if rg is not None:
        d.prose("**Seções por região (A11).** Número de seções e aptos por seção no 2º turno, 2022 e 2026.")
        d.table(FA["a09_secoes_regiao"], rg, ["regiao", "secoes_2022", "secoes_2026", "aptos_por_secao_2022",
                                              "aptos_por_secao_2026"],
                {"secoes_2022": "int", "secoes_2026": "int", "aptos_por_secao_2022": "f2", "aptos_por_secao_2026": "f2"},
                headers={"regiao": "Região", "secoes_2022": "Seções 2022", "secoes_2026": "Seções 2026",
                         "aptos_por_secao_2022": "Aptos/seção 2022", "aptos_por_secao_2026": "Aptos/seção 2026"})


def write_editorial(out: Path, analytics: Path, tables: dict, figs: list[str], man: dict) -> dict:
    """Gera os três documentos nacionais e o rastro; devolve {documento: texto} já renderizado."""
    t = {"tab01": tables["tab01_resumo_uf_t1_t2.csv"], "tab03": tables["tab03_sensibilidade_agregacao_uf.csv"],
         "tab04": tables["tab04_limites_fluxos_agregados_uf.csv"], "tab05": tables["tab05_associacoes_perfil_t1_t2.csv"],
         "tab06": tables["tab06_auditoria_operacional_uf.csv"], "tab07": tables["tab07_identidade_saldos_e_teste_100pct.csv"],
         "tab09": tables["tab09_camadas_regioes_exterior.csv"], "tab10": tables["tab10_top_municipios_brasil.csv"]}
    for k, nome in (("tab12", "tab12_horarios_faixas.csv"), ("tab13", "tab13_horarios_ajustado.csv"),
                    ("tab14", "tab14_reproducao_tardias.csv"), ("tab15", F15), ("tab16", F16), ("tab17", F17),
                    ("tab18", F18), ("tab19", F19), ("tab20", F20), ("tab21", F21), ("tab22", F22),
                    ("tab23", "tab23_socio_faixas_uf.csv"), ("tab24", "tab24_socio_modelo_conjunto.csv")):
        if nome in tables:
            t[k] = tables[nome]
    if "tab08_modelo_taxas_constantes_apendice.csv" in tables:
        t["tab08"] = tables["tab08_modelo_taxas_constantes_apendice.csv"]
    p25 = out / "tabelas_nacional" / F25
    if p25.exists():
        t["tab25"] = pd.read_csv(p25)
    t["al"] = _alegacoes(out)
    cr = out / "tabelas_nacional" / "contraste_resultados.csv"
    ctr = pd.read_csv(cr) if cr.exists() else None
    cp = out / "evidencias_nacional" / "corroboracao_dt201_uf.csv"
    cor = pd.read_csv(cp) if cp.exists() else None
    docs, traces = {}, []
    for nome, fn in (("RESUMO_EXECUTIVO_NACIONAL.md", lambda d: _resumo(d, t, ctr, cor, analytics)),
                     ("RELATORIO_NACIONAL_T1_T2.md", lambda d: _relatorio(d, t, figs, ctr, analytics)),
                     ("APENDICE_TECNICO_NACIONAL.md", lambda d: _apendice(d, t, man, analytics, out, cor))):
        d = Doc()
        fn(d)
        docs[nome] = d.render()
        traces += [{**r, "documento": nome} for r in d.trace]
    return {"docs": docs, "trace": traces}
