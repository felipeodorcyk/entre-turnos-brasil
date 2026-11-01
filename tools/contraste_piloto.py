"""Reprodução das afirmações de imprensa e alegações (handoffs 22 e 24).

Insumos (todos com hash registrado na saída):
  - docs/sources/contraste/br-c0001-e00625{7,8}-u.json: resultado nacional oficial (portal
    Resultados), camada nacional separada do piloto;
  - data/analytics/panel.parquet: painel T1×T2 do piloto AC/RS/MG (unidades pareadas);
  - reports/analysis/tabelas_piloto/tab07_identidade_saldos_e_teste_100pct.csv (conferida contra o
    painel; divergência bloqueia);
  - docs/sources/contraste/alegacoes.csv (paráfrases e fontes).

Saída: reports/analysis/tabelas_piloto/contraste_resultados.csv, uma linha por proposição; com
`--escopo nacional` (handoff 26), o painel é o do país inteiro e a saída vai para
reports/analysis/tabelas_nacional/.

Revisão 23 (R23-1, R23-4): cada veredicto sai de predicados avaliados sobre os números
recalculados, registrados na coluna `condicoes`; as hipóteses de cada cenário vão na coluna
`hipoteses`. Insumo inconsistente (identidade que não fecha, tab07 diferente do painel, contas
nacionais que não fecham) bloqueia a saída inteira em vez de produzir um veredicto.

Os valores alegados (VALORES_ALEGADOS) são os números publicados pelas fontes, com a tolerância
de arredondamento do próprio texto (meia unidade do último dígito informado).

Uso: python tools/contraste_piloto.py [--root DIR] [--escopo piloto|nacional]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


class ContrasteBloqueado(Exception):
    """Insumo inconsistente: nenhuma conclusão é emitida."""


# número publicado e tolerância de arredondamento do texto da fonte
VALORES_ALEGADOS = {
    "C01_delta_lula": (10.4e6, 0.05e6), "C01_delta_flavio": (3.7e6, 0.05e6),
    "C01_razao": (0.75, 0.125 / 2),           # "3 de cada 4": quarto mais próximo
    "C01_pool": (14.1e6, 0.05e6),
    "C02_queda_abstencao": (3.0e6, 0.05e6), "C02_queda_brancos_nulos": (1.8e6, 0.05e6),
    "C04_delta_lula_mg": (1.1e6, 0.05e6),
    "C05_delta_margem_bh": (74740, 0.5),
    "C06_baixo": (0.04, 4.0), "C06_alto": (0.15, 9.0),   # (fração de demais, avanço em p.p.)
    "C07_abst_t1": (21.0, 0.5), "C07_abst_t2": (19.0, 0.5), "C07_bn_queda_pp": (1.7, 0.05),
    "C07_soma_min": 4.0e6, "C07_soma_max": 5.0e6,
}
N_LOG, N_LOG_MG = 34330, 2253   # contagens externas (F07/F08), não reproduzidas pelo projeto
# rótulo do universo por seção em cada escopo (o painel do piloto ou o do país)
ESCOPO = {"piloto": {"universo": "piloto AC/RS/MG", "tabelas": "tabelas_piloto"},
          "nacional": {"universo": "território (27 UFs, painel pareado)", "tabelas": "tabelas_nacional"}}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _perto(valor: float, chave: str) -> bool:
    """Valor publicado compatível com o calculado, arredondado OU truncado no último dígito
    (o texto jornalístico usa as duas formas: 1.162.163 aparece como "1,1 milhão")."""
    alvo, tol = VALORES_ALEGADOS[chave]
    return abs(valor - alvo) <= tol or alvo <= valor < alvo + 2 * tol


def carregar_nacional(p: Path) -> dict:
    j = json.loads(p.read_text(encoding="utf-8"))
    c = {int(x["n"]): int(x["vap"]) for a in j["carg"][0]["agr"] for pa in a["par"] for x in pa["cand"]}
    e, v = j["e"], j["v"]
    out = {"eleicao": j["ele"], "turno": int(j["t"]),
           # `te` inclui eleitores de seções não instaladas (`esni`); aptos das instaladas = `esi`
           "aptos": int(e["esi"]), "comparecimento": int(e["c"]), "abstencoes": int(e["a"]),
           "brancos": int(v["vb"]), "nulos": int(v["tvn"]), "validos": int(v["vvc"]),
           "lula": c[13], "flavio": c[22]}
    if out["comparecimento"] != out["validos"] + out["brancos"] + out["nulos"]:
        raise ContrasteBloqueado(f"{p.name}: comparecimento != válidos + brancos + nulos")
    if out["aptos"] != out["comparecimento"] + out["abstencoes"]:
        raise ContrasteBloqueado(f"{p.name}: aptos != comparecimento + abstenções")
    return out


def carregar_painel(p: Path) -> pd.DataFrame:
    """Unidades pareadas territoriais, com a contabilidade de cada unidade conferida."""
    df = pd.read_parquet(p)
    df = df[(df.status_painel == "PAREADA") & (df.sg_uf != "ZZ")].copy()
    if df.empty:
        raise ContrasteBloqueado("painel sem unidades pareadas")
    for t in (1, 2):
        s = lambda c: df[f"{c}_t{t}"].astype("int64")  # noqa: E731
        if (s("qt_aptos") != s("qt_comparecimento") + s("qt_abstencoes")).any():
            raise ContrasteBloqueado(f"painel: aptos != comparecimento + abstenções no T{t}")
        if (s("qt_comparecimento") != s("qt_votos_validos") + s("qt_votos_brancos") + s("qt_votos_nulos")).any():
            raise ContrasteBloqueado(f"painel: comparecimento != válidos + brancos + nulos no T{t}")
        if (s("qt_votos_validos") < s("qt_lula") + s("qt_flavio")).any():
            raise ContrasteBloqueado(f"painel: válidos < Lula + Flávio no T{t}")
    if (df.qt_votos_validos_t2 != df.qt_lula_t2 + df.qt_flavio_t2).any():
        raise ContrasteBloqueado("painel: válidos do T2 em votáveis além dos finalistas")
    return df


def teste_100(panel: pd.DataFrame) -> pd.DataFrame:
    """Teste 'todos os demais -> Lula' por UF e no piloto, refeito do painel.

    Cenário: unidades territoriais estáveis (cada eleitor vota na mesma unidade nos dois turnos) e
    rotatividade mínima (população da unidade = maior dos aptos dos dois turnos). Limites de
    Fréchet da origem agregada: máximo min(O1, L2); mínimo max(0, O1 + L2 - N).
    """
    o1 = panel.qt_votos_validos_t1 - panel.qt_lula_t1 - panel.qt_flavio_t1
    l2 = panel.qt_lula_t2
    n = np.maximum(panel.qt_aptos_t1, panel.qt_aptos_t2)
    u = pd.DataFrame({"sg_uf": panel.sg_uf, "o1": o1, "deficit": np.maximum(0, o1 - l2),
                      "impede": (l2 < o1).astype(int), "fmin": np.maximum(0, o1 + l2 - n),
                      "dl": panel.qt_lula_t2 - panel.qt_lula_t1, "df": panel.qt_flavio_t2 - panel.qt_flavio_t1,
                      "dv": panel.qt_votos_validos_t2 - panel.qt_votos_validos_t1})
    g = u.groupby("sg_uf")[["o1", "deficit", "impede", "fmin", "dl", "df", "dv"]].sum()
    g.loc["TOTAL"] = g.sum()
    g["identidade_dif"] = (g.dl + g.df) - (g.o1 + g.dv)
    return g.astype("int64")


def conferir_tab07(t7: pd.DataFrame, g: pd.DataFrame) -> None:
    """A tab07 publicada precisa coincidir com o recálculo a partir do painel."""
    t7 = t7.set_index("sg_uf")
    pares = {"o1_demais_candidatos_t1": "o1", "delta_lula": "dl", "unidades_que_impedem_100pct": "impede",
             "votos_demais_que_nao_cabem_em_lula": "deficit", "identidade_saldos_dif": "identidade_dif"}
    if set(t7.index) != set(g.index):
        raise ContrasteBloqueado(f"tab07 com UFs {sorted(t7.index)} != painel {sorted(g.index)}")
    for c7, cg in pares.items():
        if c7 not in t7.columns:
            raise ContrasteBloqueado(f"tab07 sem a coluna {c7}")
        dif = (pd.to_numeric(t7[c7]).round().astype("int64") - g[cg]).abs()
        if (dif != 0).any():
            raise ContrasteBloqueado(f"tab07 diverge do painel em {c7}: {dif[dif != 0].to_dict()}")
    if (g.identidade_dif != 0).any():
        raise ContrasteBloqueado("identidade de saldos não fecha no painel")


def cenarios_c03(n1: dict, n2: dict) -> list[dict]:
    """Fração dos votos dos demais que Lula precisaria para virar, sob hipóteses diferentes (R23-4)."""
    m1 = n1["lula"] - n1["flavio"]
    o1 = n1["validos"] - n1["lula"] - n1["flavio"]
    dv = n2["validos"] - n1["validos"]
    return [
        {"cenario": "A", "hipoteses": ("retenção total dos votos de Lula e Flávio; todos os votos dos demais "
                                        "vão para um dos finalistas; nenhum outro voto entra ou sai"),
         "pool": o1, "fracao_minima": (-m1 + o1) / (2 * o1)},
        {"cenario": "B", "hipoteses": ("retenção total dos finalistas; disputam-se os votos dos demais e o "
                                        "saldo de novos válidos (ΔV), divididos só entre os finalistas"),
         "pool": o1 + dv, "fracao_minima": (-m1 + o1 + dv) / (2 * (o1 + dv))},
        {"cenario": "C", "hipoteses": ("trocas entre finalistas permitidas: s eleitores de Flávio no 1º "
                                        "turno votam em Lula; com s suficiente, a virada não exige nenhuma "
                                        "fração mínima dos demais"),
         "pool": o1, "fracao_minima": 0.0,
         "trocas_necessarias_se_lula_zero_dos_demais": int(np.ceil((-m1 + o1 + 1) / 2))},
    ]


def avaliar(n1: dict, n2: dict, panel: pd.DataFrame, g: pd.DataFrame,
            c12: tuple[pd.DataFrame, pd.DataFrame] | None = None, escopo: str = "piloto",
            tardias: dict | None = None) -> list[dict]:
    """`tardias`: `reconciliacao_tardias.json` (handoff 29), com o total do TSE e o da Tatu validado
    pelos logs do projeto; ausente, C08 e C11 ficam como no ciclo anterior."""
    U = ESCOPO[escopo]["universo"]
    piloto = escopo == "piloto"
    dl, df_ = n2["lula"] - n1["lula"], n2["flavio"] - n1["flavio"]
    o1 = n1["validos"] - n1["lula"] - n1["flavio"]
    dv = n2["validos"] - n1["validos"]
    dc = n2["comparecimento"] - n1["comparecimento"]
    da = n2["abstencoes"] - n1["abstencoes"]
    dbn = (n2["brancos"] + n2["nulos"]) - (n1["brancos"] + n1["nulos"])
    m2 = n2["lula"] - n2["flavio"]
    ident_nac = (dl + df_) - (o1 + dv)
    ident_v = dv - (dc - dbn)
    linhas = []

    def add(cid, universo, resultado, cond: dict, status, hipoteses, limitacao):
        linhas.append(dict(claim_id=cid, universo=universo, resultado_numerico=resultado,
                           condicoes="; ".join(f"{k}={v}" for k, v in cond.items()),
                           hipoteses=hipoteses, status_conclusao=status, limitacao_identificacao=limitacao))

    # C01
    razao = dl / (dl + df_)
    cond = {"ΔL≈10,4mi": _perto(dl, "C01_delta_lula"), "ΔF≈3,7mi": _perto(df_, "C01_delta_flavio"),
            "razão≈3/4": _perto(razao, "C01_razao"), "O1+ΔV≈14,1mi": _perto(o1 + dv, "C01_pool"),
            "identidade_nacional_fecha": ident_nac == 0}
    add("C01", "nacional (JSON oficial, inclui exterior)",
        f"ΔL={dl}; ΔF={df_}; ΔL/(ΔL+ΔF)={razao:.4f}; O1={o1}; ΔV={dv}", cond,
        "REPRODUZIDA" if all(cond.values()) else "DIVERGENTE", "saldos líquidos nacionais",
        "razão de saldos líquidos; não mede de quem vieram os votos nem a preferência de novos votantes")
    # C02
    cond = {"queda_abstencao≈3mi": _perto(-da, "C02_queda_abstencao"),
            "queda_brancos_nulos≈1,8mi": _perto(-dbn, "C02_queda_brancos_nulos"),
            "ΔV=ΔC-ΔB-ΔN": ident_v == 0}
    add("C02", "nacional (JSON oficial)",
        f"ΔC={dc} (abstenções {da}); Δ(brancos+nulos)={dbn}; ΔV={dv}; ΔV-(ΔC-ΔB-ΔN)={ident_v}", cond,
        "PARCIALMENTE_REPRODUZIDA" if all(cond.values()) else "DIVERGENTE",
        "saldos; a leitura como contagem de pessoas exigiria fluxos brutos, não observados",
        "os saldos conferem; 'pessoas que se abstiveram e foram votar' lê saldo como contagem de pessoas")
    # C03 (R23-4)
    cen = cenarios_c03(n1, n2)
    add("C03", "nacional (JSON oficial)",
        "; ".join(f"cenário {c['cenario']}: fração mínima={c['fracao_minima']:.4f}" for c in cen)
        + f"; cenário C: {cen[2]['trocas_necessarias_se_lula_zero_dos_demais']} trocas F→L bastariam sem nenhum voto dos demais",
        {"limiar_depende_das_hipoteses": len({round(c["fracao_minima"], 4) for c in cen}) > 1},
        "NAO_IDENTIFICAVEL", " | ".join(f"{c['cenario']}: {c['hipoteses']}" for c in cen),
        "contrafactual sobre comportamento; o limiar existe só sob hipóteses de retenção e sem trocas, "
        "e as marginais não identificam quais delas valem")
    # C04
    mg = panel[panel.sg_uf == "MG"]
    dl_mg = int(mg.qt_lula_t2.sum() - mg.qt_lula_t1.sum())
    dsh = mg.qt_lula_t2.sum() / mg.qt_votos_validos_t2.sum() - mg.qt_lula_t1.sum() / mg.qt_votos_validos_t1.sum()
    cond = {"ΔL_MG≈1,1mi": _perto(dl_mg, "C04_delta_lula_mg")}
    add("C04", "piloto MG (painel pareado)" if piloto else "MG (painel nacional pareado)", f"ΔL MG={dl_mg} votos; Δ participação={100 * dsh:.2f} p.p.", cond,
        "REPRODUZIDA" if all(cond.values()) else "DIVERGENTE", "mesma UF e mesmo corte",
        "contagem de votos; não identifica eleitores")
    # C05 e C06 (municípios do painel)
    mu = panel.groupby(["sg_uf", "cd_municipio_tse"])[[f"{c}_t{t}" for c in ("qt_lula", "qt_flavio", "qt_votos_validos")
                                                       for t in (1, 2)]].sum().reset_index()
    bh = mu[(mu.sg_uf == "MG") & (mu.cd_municipio_tse == "41238")]
    if len(bh) != 1:
        raise ContrasteBloqueado("Belo Horizonte (MG 41238) ausente do painel")
    bh = bh.iloc[0]
    dm_bh = int((bh.qt_lula_t2 - bh.qt_flavio_t2) - (bh.qt_lula_t1 - bh.qt_flavio_t1))
    cond = {"Δmargem_BH=74.740": _perto(dm_bh, "C05_delta_margem_bh")}
    add("C05", "piloto MG, Belo Horizonte" if piloto else "Belo Horizonte (painel nacional)", f"Δ margem Lula-Flávio (votos)={dm_bh}", cond,
        "REPRODUZIDA" if all(cond.values()) else "DIVERGENTE", "contribuição contábil do município",
        "não identifica eleitores que mudaram")
    mu["o1_share"] = (mu.qt_votos_validos_t1 - mu.qt_lula_t1 - mu.qt_flavio_t1) / mu.qt_votos_validos_t1
    mu["d_lula"] = 100 * (mu.qt_lula_t2 / mu.qt_votos_validos_t2 - mu.qt_lula_t1 / mu.qt_votos_validos_t1)
    w = mu.qt_votos_validos_t1.astype(float).to_numpy()
    X = np.column_stack([np.ones(len(mu)), 100 * mu.o1_share])
    xtwx = X.T @ (X * w[:, None])
    # sem variação na participação dos demais a inclinação não é identificada
    beta = (np.linalg.solve(xtwx, X.T @ (w * mu.d_lula)) if np.linalg.matrix_rank(xtwx) == 2
            else np.array([np.nan, np.nan]))
    (sb, pb), (sa, pa) = VALORES_ALEGADOS["C06_baixo"], VALORES_ALEGADOS["C06_alto"]
    corr = (float(np.corrcoef(mu.o1_share, mu.d_lula)[0, 1])
            if mu.o1_share.std() > 0 and mu.d_lula.std() > 0 else float("nan"))

    def _local(s):  # média ponderada dos municípios a ±1,5 p.p. do nível citado pela fonte
        m = (mu.o1_share - s).abs() <= 0.015
        return (int(m.sum()), float(np.average(mu.d_lula[m], weights=w[m])) if m.sum() else float("nan"))

    (nb, lb), (na, la) = _local(sb), _local(sa)
    cond = {"inclinação>0": beta[1] > 0, f"munis_perto_de_{sb:.0%}>=3": nb >= 3, f"munis_perto_de_{sa:.0%}>=3": na >= 3,
            f"média_perto_de_{sb:.0%}≈+{pb:.0f}p.p.(±1,5)": abs(lb - pb) <= 1.5,
            f"média_perto_de_{sa:.0%}≈+{pa:.0f}p.p.(±1,5)": abs(la - pa) <= 1.5}
    suporte = (cond[f"munis_perto_de_{sb:.0%}>=3"] and cond[f"munis_perto_de_{sa:.0%}>=3"]
               and not np.isnan(beta[1]))
    add("C06", f"{U}, municípios ponderados por válidos T1",
        f"inclinação ponderada {beta[1]:.3f} p.p. de Δ Lula por p.p. de demais; perto de 4%: {nb} mun., "
        f"{lb:+.2f} p.p.; perto de 15%: {na} mun., {la:+.2f} p.p.; correlação={corr:.3f}; {len(mu)} municípios", cond,
        ("PARCIALMENTE_REPRODUZIDA" if all(cond.values())
         else ("SUPORTE_INSUFICIENTE_NO_PILOTO" if piloto else "SUPORTE_INSUFICIENTE") if not suporte
         else "DIRECAO_REPRODUZIDA_MAGNITUDE_DIFERE" if beta[1] > 0
         else "DIVERGENTE"),
        "associação entre municípios; só o piloto (1.372 de 5.570 municípios)" if piloto else
        "associação entre municípios, todos os municípios do país (mesmo universo da fonte, sem o exterior)",
        f"correlação ecológica não identifica transferência individual; perto de 15% há só {na} municípios "
        + ("no piloto, e a fonte usa o país inteiro" if piloto else "no país"))
    # C07
    abst = (100 * n1["abstencoes"] / n1["aptos"], 100 * n2["abstencoes"] / n2["aptos"])
    bn_c = 100 * ((n2["brancos"] + n2["nulos"]) / n2["comparecimento"] - (n1["brancos"] + n1["nulos"]) / n1["comparecimento"])
    bn_a = 100 * ((n2["brancos"] + n2["nulos"]) / n2["aptos"] - (n1["brancos"] + n1["nulos"]) / n1["aptos"])
    soma = dc - dbn
    cond = {"abstenção_T1≈21%": _perto(abst[0], "C07_abst_t1"), "abstenção_T2≈19%": _perto(abst[1], "C07_abst_t2"),
            "soma_entre_4_e_5mi": VALORES_ALEGADOS["C07_soma_min"] <= soma <= VALORES_ALEGADOS["C07_soma_max"],
            "queda_BN≈1,7p.p._sobre_comparecimento": _perto(-bn_c, "C07_bn_queda_pp"),
            "queda_BN≈1,7p.p._sobre_aptos": _perto(-bn_a, "C07_bn_queda_pp")}
    bn_ok = cond["queda_BN≈1,7p.p._sobre_comparecimento"] or cond["queda_BN≈1,7p.p._sobre_aptos"]
    resto_ok = cond["abstenção_T1≈21%"] and cond["abstenção_T2≈19%"] and cond["soma_entre_4_e_5mi"]
    add("C07", "nacional (JSON oficial)",
        f"abstenção/aptos {abst[0]:.2f}% -> {abst[1]:.2f}%; Δ brancos+nulos {bn_c:+.2f} p.p. do comparecimento, "
        f"{bn_a:+.2f} p.p. dos aptos; ΔC-Δ(B+N)={soma}", cond,
        "REPRODUZIDA" if bn_ok and resto_ok else ("PARCIALMENTE_REPRODUZIDA" if resto_ok else "DIVERGENTE"),
        "contas preliminares do analista",
        "a queda de brancos e nulos publicada não sai com nenhum dos dois denominadores oficiais"
        if not bn_ok else "contas de saldo")
    # C08
    vt = (tardias or {}).get("votos_apos_17h_pais", {})
    N8 = max(N_LOG, int(vt.get("tse") or 0), int(vt.get("tatu_todos_logs") or 0))
    add("C08", "nacional (JSON oficial) com contagem externa de votos após 17h",
        f"margem T2={m2}; N={N8} (maior entre {N_LOG} da imprensa"
        + (f", {vt['tse']} do TSE e {vt['tatu_todos_logs']} da Tatu" if vt else "") + f"); N/margem={N8 / m2:.4f}; "
        f"remover N muda a margem em no máximo {N8}; realocar N, em no máximo {2 * N8}",
        {"2N<margem": 2 * N8 < m2}, "NAO_TESTAVEL_COM_INSUMOS",
        "N é a maior das contagens publicadas; limites são cenários aritméticos, não efeito da prorrogação",
        "legalidade não é decidida por dados de votação; o que teria acontecido sem a prorrogação não é observado")
    # C09 e C10 (proposições em circulação; ver alegacoes.csv)
    ident_ufs = bool((g.identidade_dif == 0).all())
    cond = {"identidade_nacional_fecha": ident_nac == 0, "identidade_fecha_em_todas_as_UFs": ident_ufs,
            "contabilidade_de_todas_as_unidades_confere": True}
    add("C09", f"nacional (JSON oficial) e {U}",
        f"nacional: ΔL+ΔF-(O1+ΔV)={ident_nac}; {'piloto' if piloto else 'painel por UF'}: identidade com diferença "
        f"{ {k: int(v) for k, v in g.identidade_dif.items()} } e {len(panel)} unidades com contabilidade conferida", cond,
        "REFUTADA_NO_SENTIDO_ARITMETICO" if all(cond.values()) else "NAO_REFUTADA",
        "a existência de alocação compatível segue da contabilidade fechada em cada unidade",
        "mostra que a conta fecha; não diz qual alocação ocorreu")
    tot = g.loc["TOTAL"]
    possivel, necessario = int(tot.deficit) == 0, int(tot.fmin) == int(tot.o1)
    suficiente_nac = dl <= o1
    cond = {"100%_possivel_no_cenario": possivel, "100%_necessario_no_cenario": necessario,
            "ΔL<=O1_nacional": suficiente_nac}
    if possivel and not necessario:
        st10 = "COMPATIVEL_NAO_NECESSARIA"
    elif not possivel and not necessario:
        st10 = "INCOMPATIVEL_NO_CENARIO_E_NAO_NECESSARIA"
    elif necessario:
        st10 = "NECESSARIA_NO_CENARIO"
    else:
        st10 = "INDETERMINADO"
    add("C10", f"{U} (unidades pareadas) e nacional",
        f"{'piloto' if piloto else 'território'}: {int(tot.impede)} unidade(s) com Lula T2 < demais T1, {int(tot.deficit)} votos dos demais sem "
        f"lugar nos votos de Lula; limite mínimo agregado {int(tot.fmin)} de {int(tot.o1)}; nacional: ΔL={dl}, O1={o1}",
        cond, st10,
        "unidades territoriais estáveis (cada eleitor vota na mesma unidade nos dois turnos) e rotatividade "
        "mínima; aptos iguais não garantem os mesmos integrantes, nem excluem mudança de unidade",
        "o voto é secreto: a transferência não é observável; o teste diz o que as marginais admitem")
    # C12 (tools/secoes_unanimes.py sobre o consolidado oficial por seção)
    if c12 is not None:
        sec, uf_tab = c12
        n_cit, n_enc = len(sec), int(sec.encontrada.astype(bool).sum())
        n_uni = int((sec.votaveis_nominais_com_voto == 1).sum())
        n_br, n_tot = int(uf_tab.secoes_um_votavel_nominal.sum()), int(uf_tab.secoes.sum())
        cond = {"todas_as_citadas_encontradas": n_enc == n_cit, "todas_unanimes_na_contagem": n_uni == n_cit,
                "nenhuma_unanime_na_contagem": n_uni == 0}
        if not cond["todas_as_citadas_encontradas"]:
            st12 = "INDETERMINADO_SECOES_NAO_ENCONTRADAS"
        elif cond["todas_unanimes_na_contagem"]:
            st12 = "CONTAGEM_CONFIRMADA_VINCULO_COM_FRAUDE_NAO_TESTAVEL"
        elif cond["nenhuma_unanime_na_contagem"]:
            st12 = "REFUTADA_NA_CONTAGEM"
        else:
            st12 = "PARCIALMENTE_VERDADEIRA_NA_CONTAGEM"
        part = sec.participacao_mais_votado.astype(float)
        add("C12", "20 seções citadas (AM, MT, MA, PA, RR) e país, 1º turno",
            f"{n_enc} de {n_cit} seções encontradas; {n_uni} com um único votável nominal com votos; mais votado "
            f"com {part.min():.1%} a {part.max():.1%} dos votos nominais; país: {n_br} de {n_tot} seções com um "
            "único votável nominal", cond, st12,
            "contagem por seção no consolidado oficial; a lista de seções vem da checagem do TSE",
            "a contagem não diz nada sobre fraude: votação concentrada é compatível com comunidades com voto "
            "coeso; a publicação original não foi lida")
    # C11
    if vt:
        tse, tatu = int(vt["tse"]), int(vt["tatu_todos_logs"])
        cond = {"logs_T2_do_recorte_adquiridos": True, "contagem_propria_nacional": False,
                "|N-TSE|<=1%": abs(N_LOG - tse) <= 0.01 * tse, "|N-Tatu|<=1%": abs(N_LOG - tatu) <= 0.01 * tatu}
        add("C11", "nacional (TSE; Tatu validada por logs do projeto) e " + ("piloto MG" if piloto else "MG (painel nacional)"),
            f"N publicado={N_LOG}; TSE={tse} ({N_LOG - tse:+d}); Tatu, todos os logs={tatu} ({N_LOG - tatu:+d}); "
            f"{N_LOG / n2['comparecimento']:.5f} do comparecimento; nos logs do projeto: "
            f"{vt['nossa_contagem_na_cauda']} votos após 17h em {vt['secoes_na_cauda']} seções tardias; MG: N "
            f"externo={N_LOG_MG}, margem MG T2 no painel={int(mg.qt_lula_t2.sum() - mg.qt_flavio_t2.sum())}",
            cond, "PARCIALMENTE_REPRODUZIDA" if cond["|N-TSE|<=1%"] and cond["|N-Tatu|<=1%"] else "DIVERGENTE",
            "contagem por logs; a Tatu leu todos os logs, e o campo dela confere com os do projeto na cauda e "
            "numa amostra aleatória",
            "a ordem de grandeza confere com duas contagens independentes; o número exato não se reproduz "
            "sem os 497 mil logs, e as três fontes diferem em algumas centenas de votos")
    else:
        add("C11", "nacional (contagem externa) e " + ("piloto MG" if piloto else "MG (painel nacional)"),
            f"N externo={N_LOG} ({N_LOG / n2['comparecimento']:.5f} do comparecimento); MG: N externo={N_LOG_MG}, "
            f"margem MG T2 no painel={int(mg.qt_lula_t2.sum() - mg.qt_flavio_t2.sum())}",
            {"logs_T2_adquiridos": False}, "NAO_REPRODUZIDA",
            "contagem por logs dos levantamentos externos",
            "logs de urna do T2 não adquiridos (a contagem de votos após 17h exige os logs; o encerramento "
            "da seção não basta)")
    # C13 (UOL/Tatu) e C14 (TSE): reprodução com o censo dos BUs e os logs (reconciliar_tardias.py)
    rep = {(r["fonte"], r["item"]): r for r in (tardias or {}).get("reproducao", [])}
    if rep:
        def _r(fonte, item):
            r = rep[(fonte, item)]
            return f"{item}: {r['publicado']} publicado, {r['nosso_valor']} reproduzido ({r['status']})", r["status"]
        itens13 = ["seções 'até 19h', critério pedido1", "votos após 17h, critério pedido1",
                   "votos de Lula nas seções 'até 19h'", "votos de Flávio nas seções 'até 19h'"]
        res13 = [_r("UOL/Tatu", i) for i in itens13]
        cond = {f"{i}={st}": st in ("EXATO", "APROXIMADO") for i, (_, st) in zip(itens13, res13)}
        add("C13", "território (censo dos BUs do portal e logs das seções tardias)", "; ".join(t for t, _ in res13), cond,
            "REPRODUZIDA" if all(cond.values()) else "PARCIALMENTE_REPRODUZIDA",
            "seção 'até 19h' = primeiro pedido de encerramento do mesário às 19h ou depois (Brasília), critério da fonte",
            "a lista pública tem uma seção a menos que o total publicado; contar seções não diz nada sobre efeito "
            "da prorrogação")
        itens14 = ["seções encerradas após 17h10", "seções encerradas até 17h10", "seções encerradas após 19h",
                   "votos após 17h nessas seções", "votos entre 17h e 18h nessas seções",
                   "votos entre 18h e 19h nessas seções", "votos após 19h nessas seções"]
        res14 = [_r("TSE", i) for i in itens14]
        cond = {f"{i}={st}": st in ("EXATO", "APROXIMADO") for i, (_, st) in zip(itens14, res14)}
        add("C14", "território (censo dos BUs do portal e logs das seções tardias)", "; ".join(t for t, _ in res14), cond,
            "REPRODUZIDA" if all(cond.values()) else "PARCIALMENTE_REPRODUZIDA",
            "horário da seção = emissão do BU, a definição que mais se aproxima; o TSE não publicou a sua",
            "parte das diferenças não se explica com os dados públicos; o total nacional de votos após 17h fica no C11")
    return linhas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    ap.add_argument("--escopo", choices=tuple(ESCOPO), default="piloto")
    a = ap.parse_args(argv)
    root = a.root
    src = root / "docs" / "sources" / "contraste"
    j1, j2 = src / "br-c0001-e006257-u.json", src / "br-c0001-e006258-u.json"
    panel_p = root / "data" / "analytics" / "panel.parquet"
    tab_dir = root / "reports" / "analysis" / ESCOPO[a.escopo]["tabelas"]
    t7_p = tab_dir / "tab07_identidade_saldos_e_teste_100pct.csv"
    saida = tab_dir / "contraste_resultados.csv"
    try:
        n1, n2 = carregar_nacional(j1), carregar_nacional(j2)
        if (n1["turno"], n2["turno"]) != (1, 2):
            raise ContrasteBloqueado("JSONs nacionais fora de ordem de turno")
        panel = carregar_painel(panel_p)
        g = teste_100(panel)
        conferir_tab07(pd.read_csv(t7_p), g)
        # o C12 já usa o consolidado nacional por seção; suas tabelas ficam em tabelas_piloto/
        c12_dir = root / "reports" / "analysis" / "tabelas_piloto"
        c12_p, c12_uf = c12_dir / "c12_secoes_citadas_resultado.csv", c12_dir / "c12_secoes_um_votavel_por_uf.csv"
        c12 = (pd.read_csv(c12_p), pd.read_csv(c12_uf)) if c12_p.exists() and c12_uf.exists() else None
        rt_p = root / "reports" / "analysis" / "evidencias_horarios" / "reconciliacao_tardias.json"
        tardias = json.loads(rt_p.read_text(encoding="utf-8")) if a.escopo == "nacional" and rt_p.exists() else None
        linhas = avaliar(n1, n2, panel, g, c12, a.escopo, tardias)
    except ContrasteBloqueado as e:
        saida.unlink(missing_ok=True)   # nada de resultado antigo confundido com execução nova
        print(f"BLOCKED: {e}")
        return 2
    out = pd.DataFrame(linhas)
    aleg = pd.read_csv(src / "alegacoes.csv", dtype=str)[["claim_id", "source_id", "familia", "parafrase_fiel", "tipo"]]
    out = aleg.merge(out, on="claim_id", how="right", validate="one_to_one")
    if out.source_id.isna().any():
        raise SystemExit("proposição sem registro em alegacoes.csv")
    out = out.rename(columns={"parafrase_fiel": "afirmacao_resumo"})
    out["resultado_reproducao"] = out["resultado_numerico"]
    out["run_id"] = "sha256:" + hashlib.sha256("".join(_sha(q) for q in (j1, j2, panel_p, t7_p)).encode()).hexdigest()[:16]
    out["referencia"] = "tools/contraste_piloto.py"
    ins = (j1, j2, panel_p, t7_p) + ((rt_p,) if tardias is not None else ())
    out["insumos_sha256"] = "; ".join(f"{q.relative_to(root).as_posix()}={_sha(q)[:16]}" for q in ins)
    tab_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(saida, index=False)
    print(out[["claim_id", "status_conclusao"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
