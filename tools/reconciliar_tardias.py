"""Reconciliação das contagens externas de seções tardias e votos após as 17h (handoff 29).

Compara, número a número, o que UOL/Agência Tatu e o TSE publicaram com o que sai das nossas
fontes primárias: o censo dos BUs do portal (horários de abertura, encerramento e emissão, em
Brasília pelo deslocamento municipal validado) e os logs oficiais das seções tardias mais uma
amostra aleatória das demais (`logs_tardias.py`). Para cada número, testa as definições
plausíveis (evento e corte) e registra a mais próxima, a diferença e o que a explica. Nenhum
corte daqui entra na análise principal por faixas, cujas faixas foram pré-registradas.

Saídas (agregadas; nenhuma linha por seção é versionada):
- `reports/analysis/evidencias_horarios/reconciliacao_tardias.csv` (tabela de reprodução);
- `reports/analysis/evidencias_horarios/reconciliacao_tardias.json` (o mesmo, mais as
  validações dos campos por seção da Tatu e a estimativa nacional de votos após as 17h);
- `reports/analysis/evidencias_horarios/reconciliacao_secoes.parquet` (não versionado).

Uso: python tools/reconciliar_tardias.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tools"))

from logs_tardias import horarios_censo  # noqa: E402

K = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
OUT = RAIZ / "reports" / "analysis" / "evidencias_horarios"
TATU = RAIZ / "data" / "raw" / "externo" / "tatu_votacao_apos_17h"
# TSE, nota de 27/10/2026 (reproduzida por Gazeta do Povo, InfoMoney e outros; ver CONTRASTE)
TSE = {"secoes_apos_17h10": 24268, "secoes_ate_17h10": 473065, "secoes_apos_19h": 6766,
       "votos_apos_17h_nas_apos_19h": 4773, "votos_17_18_nas_apos_19h": 2837,
       "votos_18_19_nas_apos_19h": 1923, "votos_apos_19h_nas_apos_19h": 13, "votos_apos_17h_pais": 34393}


def _seg(t: pd.Series) -> pd.Series:
    """Segundos desde a meia-noite (Brasília)."""
    return t.dt.hour * 3600 + t.dt.minute * 60 + t.dt.second


def _hms(x: pd.Series) -> pd.Series:
    """'HH:MM[:SS]' → segundos; nulos ficam nulos."""
    p = x.astype("string").replace("", pd.NA).str.split(":", expand=True)
    num = lambda c: pd.to_numeric(p[c], errors="coerce")
    seg = num(0) * 3600 + num(1) * 60
    return seg + (num(2).fillna(0) if p.shape[1] > 2 else 0)


def _linha(fonte, item, publicado, definicao, nosso, explicacao, natureza="CONTAGEM_PROPRIA", status=None):
    """`natureza`: CONTAGEM_PROPRIA (fontes primárias), EXTERNO_VALIDADO (dado de terceiro conferido por
    amostra), LISTA_PUBLICA_PARCIAL ou RECORTE (nosso valor cobre só parte do universo publicado)."""
    dif = None if nosso is None or publicado is None else int(nosso) - int(publicado)
    if status is not None:
        pass
    elif dif is None:
        status = "NAO_REPRODUZIVEL"
    elif dif == 0:
        status = "EXATO"
    elif abs(dif) <= max(5, 0.005 * abs(publicado)):
        status = "APROXIMADO"
    else:
        status = "DIVERGE"
    return {"fonte": fonte, "item": item, "publicado": publicado, "definicao_testada": definicao,
            "nosso_valor": None if nosso is None else int(nosso), "diferenca": dif, "status": status,
            "natureza": natureza, "explicacao": explicacao}


def _melhor(publicado: int, candidatos: dict[str, pd.Series]) -> tuple[str, pd.Series]:
    """Definição (nome e máscara de seções) cuja contagem fica mais perto do número publicado. A máscara
    devolvida é a mesma usada na contagem, para que as somas seguintes apliquem exatamente o critério
    escolhido (R30-3). Proximidade não identifica o método da fonte: é só compatibilidade."""
    return min(candidatos.items(), key=lambda kv: abs(int(kv[1].sum()) - publicado))


def _comparecimento_t2() -> pd.DataFrame:
    from br2026.contract import read_table
    from br2026.panel.run import staging_path
    st = read_table(staging_path(RAIZ / "data" / "staging", "section_turn"), "section_turn")
    return st[(st.nr_turno == 2) & (st.cd_cargo == 1)][K + ["qt_comparecimento"]]


def main() -> int:
    cs = horarios_censo(3221)
    enc, emi = _seg(cs.encerramento_br), _seg(cs.emissao_br)
    meta = json.loads((TATU / "meta.json").read_text(encoding="utf-8"))
    tatu = pd.read_parquet(OUT / "tatu_secoes.parquet")
    rep_tatu = json.loads((OUT / "tatu_reproducao.json").read_text(encoding="utf-8"))
    lg = pd.read_json(RAIZ / "data" / "raw" / "bu_portal" / "logs_3221" / "resultados.jsonl", lines=True,
                      dtype={"cd_municipio_tse": str, "nr_zona": str, "nr_secao": str})
    lg = lg.drop_duplicates(K, keep="last")
    status_logs = lg.status.value_counts().to_dict()
    lg = lg[lg.status == "OK"]
    d = cs.merge(lg.drop(columns=["pleito", "status", "offset_h"], errors="ignore"), on=K, how="left")
    d = d.merge(tatu[K + ["encerramento_tatu", "ultimo_voto_tatu", "votos_apos17_tatu", "u19_tatu", "tarde_tatu",
                          "campo5_tatu"]], on=K, how="left")
    d["enc_s"], d["emi_s"] = enc.values, emi.values
    for c in ("pedido_encerramento_primeiro", "pedido_encerramento_ultimo", "encerramento_confirmado_ultimo",
              "ultimo_voto", "pedido_encerramento_primeiro_final"):
        d[c + "_s"] = _hms(d[c]) if c in d else pd.Series(float("nan"), index=d.index)
    # R30-1: o log só vale como evidência se os votos do dia (cadeia completa) igualam o comparecimento
    d = d.merge(_comparecimento_t2(), on=K, how="left")
    com_log = d.estrato.notna() & d.votos_dia.notna()
    d["reconciliada"] = com_log & (d.votos_dia == d.qt_comparecimento)
    ok = d.reconciliada
    rec = {"secoes_com_log": int(com_log.sum()), "reconciliadas": int(ok.sum()),
           "divergentes": d.loc[com_log & ~ok, K + ["votos_dia", "qt_comparecimento"]].to_dict("records"),
           "com_logs_aninhados": int((d.n_logs > 1).sum()) if "n_logs" in d else None,
           "divergentes_so_log_final": int((com_log & (d.votos_dia_final != d.qt_comparecimento)).sum())
           if "votos_dia_final" in d else None}
    tardia = d.estrato.eq("TARDIA")
    H17, H1710, H18, H19 = 17 * 3600, 17 * 3600 + 600, 18 * 3600, 19 * 3600
    linhas = []

    # ---- UOL/Agência Tatu ----
    linhas.append(_linha("UOL/Tatu", "seções no universo (território)", meta["n_secoes_total"],
                         "seções com BU no censo do portal, fora do exterior", len(cs),
                         "mesmo universo: as 70 seções sem BU publicado são todas do exterior"))
    c19 = meta["criterios19"]
    # os critérios por pedido de encerramento dependem do log; todas as seções com pedido >= 19h têm
    # encerramento ou emissão do BU >= 18h e portanto estão no recorte dos logs
    pf, pu = d.pedido_encerramento_primeiro_s, d.pedido_encerramento_ultimo_s
    pff = d.pedido_encerramento_primeiro_final_s
    crit = {"bu": ("bu", "encerramento do BU >= 19:00:00", d.enc_s >= H19, "horário de encerramento gravado no BU"),
            "pedido": ("pedido", "último 'Encerrar votação' do log >= 19:00:00", pu >= H19,
                       "pedido do mesário no log; inclui seções com pedido anterior cancelado"),
            "pedido1": ("pedido1", "primeiro 'Encerrar votação' >= 19:00:00, cadeia completa de urnas", pf >= H19,
                        "critério publicado (5.330), lido em todos os logs da seção, inclusive de urnas "
                        "substituídas; uma urna anterior pode ter pedido o encerramento antes das 19h"),
            "pedido1, só log final": ("pedido1", "primeiro 'Encerrar votação' >= 19:00:00, só o log da urna final",
                                      pff >= H19, "leitura só do log externo do pacote, aparentemente a da fonte "
                                                  "(a lista pública tem o mesmo número)")}
    for c, (cm, defin, msk, expl) in crit.items():
        linhas.append(_linha("UOL/Tatu", f"seções 'até 19h', critério {c}", c19[cm]["secoes"], defin, int(msk.sum()), expl))
        linhas.append(_linha("UOL/Tatu", f"votos após 17h, critério {c}", c19[cm]["votos17"],
                             f"'voto computado' no log >= 17:00, seções com {defin}",
                             int(d.loc[msk & ok, "votos_apos_17h"].sum()),
                             f"log reconciliado em {int((msk & ok).sum()):,} de {int(msk.sum()):,} seções".replace(",", ".")))
    for k, nome in (("lula_t2", "votos de Lula nas seções 'até 19h'"), ("flavio_t2", "votos de Flávio nas seções 'até 19h'"),
                    ("comparecimento_t2", "comparecimento nas seções 'até 19h'")):
        ch = k.replace("_t2", "")
        linhas.append(_linha("UOL/Tatu", nome, rep_tatu["publicado"][ch], "soma do staging T2 nas seções marcadas da lista pública",
                             rep_tatu[k], "a lista pública tem 5.329 das 5.330 seções; a que falta explica a diferença"))
    linhas.append(_linha("UOL/Tatu", "votos após 17h no país", meta["votos17_total_parcial"],
                         "soma do campo por seção da lista pública", int(tatu.votos_apos17_tatu.sum()),
                         f"a Tatu leu {meta['secoes_com_log']:,} logs; a lista pública cobre {len(tatu):,} das "
                         f"{meta['n_secoes_total']:,} seções".replace(",", "."), "LISTA_PUBLICA_PARCIAL", "LISTA_PARCIAL"))
    linhas.append(_linha("UOL/Tatu", "cancelamentos de encerramento", meta["cancelamentos_encerramento"],
                         "pedidos sem confirmação, só nas seções com log baixado",
                         int(d.loc[com_log, "cancelamentos_encerramento"].sum()),
                         "contagem nacional exige todos os logs; o nosso valor cobre só o recorte", "RECORTE",
                         "FORA_DO_RECORTE"))

    # ---- TSE (nota de 27/10) ----
    cand = {"emissão do BU > 17:10:00": emi > H1710, "emissão do BU >= 17:11:00": emi >= H1710 + 60,
            "encerramento do BU > 17:10:00": enc > H1710, "encerramento do BU >= 17:11:00": enc >= H1710 + 60}
    df_, m_ = _melhor(TSE["secoes_apos_17h10"], cand)
    linhas.append(_linha("TSE", "seções encerradas após 17h10", TSE["secoes_apos_17h10"], df_, int(m_.sum()),
                         "o TSE não publicou a definição; a emissão do BU é a testada mais próxima, o que é "
                         "compatível com ela, não prova de que foi usada "
                         f"(encerramento > 17:10 daria {int(cand['encerramento do BU > 17:10:00'].sum()):,})".replace(",", ".")))
    linhas.append(_linha("TSE", "seções encerradas até 17h10", TSE["secoes_ate_17h10"], "emissão do BU <= 17:10:00",
                         int((emi <= H1710).sum()),
                         f"a soma publicada ({TSE['secoes_ate_17h10'] + TSE['secoes_apos_17h10']:,}) é menor que o "
                         f"universo ({len(cs):,}); a diferença deve ser de seções fora do recorte do TSE".replace(",", ".")))
    cand = {"emissão do BU >= 19:00:00": emi >= H19, "emissão do BU > 19:00:59": emi >= H19 + 60,
            "encerramento do BU >= 19:00:00": enc >= H19}
    df19, m19 = _melhor(TSE["secoes_apos_19h"], cand)
    linhas.append(_linha("TSE", "seções encerradas após 19h", TSE["secoes_apos_19h"], df19, int(m19.sum()),
                         "a emissão do BU é a definição testada mais próxima (compatível, não comprovada); o "
                         "encerramento >= 19h dá o critério 'bu' da Tatu"))
    sub = d[m19.values & ok.values]
    for k, col, nome in (("votos_apos_17h_nas_apos_19h", "votos_apos_17h", "votos após 17h nessas seções"),
                         ("votos_17_18_nas_apos_19h", "votos_17_18", "votos entre 17h e 18h nessas seções"),
                         ("votos_18_19_nas_apos_19h", "votos_18_19", "votos entre 18h e 19h nessas seções"),
                         ("votos_apos_19h_nas_apos_19h", "votos_apos_19h", "votos após 19h nessas seções")):
        linhas.append(_linha("TSE", nome, TSE[k], f"'voto computado' no log, em seções com {df19}",
                             int(sub[col].sum()),
                             f"log baixado em {len(sub):,} de {int(m19.sum()):,} seções".replace(",", ".")
                             + ("; a diferença está entre 17h e 18h e nenhum conjunto testado (emissão a partir de "
                                "18h50, 18h55 ou 19h; encerramento a partir de 19h) a reproduz; o TSE não publicou a "
                                "definição" if col in ("votos_apos_17h", "votos_17_18") else "")))

    # ---- validação dos campos por seção da Tatu contra os logs ----
    val = {}
    for est in ("TARDIA", "AMOSTRA"):
        g = d[(d.estrato == est) & ok & d.votos_apos17_tatu.notna()]
        pv = (g.pedido_encerramento_primeiro_final_s // 60).astype("Int64")
        et = (_hms(g.encerramento_tatu) // 60).astype("Int64")
        uv = (g.ultimo_voto_s // 60).astype("Int64")
        ut = (_hms(g.ultimo_voto_tatu) // 60).astype("Int64")
        val[est] = {"secoes": int(len(g)),
                    "votos_apos17_iguais": float((g.votos_apos_17h == g.votos_apos17_tatu).mean()),
                    "soma_votos_apos17_log": int(g.votos_apos_17h.sum()),
                    "soma_votos_apos17_tatu": int(g.votos_apos17_tatu.sum()),
                    "encerramento_tatu_igual_primeiro_pedido_hhmm": float((pv == et).mean()),
                    "ultimo_voto_igual_hhmm": float((uv == ut).mean()),
                    "u19_igual_primeiro_pedido_19h_so_log_final": float(
                        ((g.pedido_encerramento_primeiro_final_s >= H19) == g.u19_tatu).mean()),
                    "u19_igual_primeiro_pedido_19h_cadeia": float(
                        ((g.pedido_encerramento_primeiro_s >= H19) == g.u19_tatu).mean())}
    # total nacional: só a Tatu leu todos os logs; o campo dela é validado acima na cauda e na amostra
    log_ok = ok
    v17 = meta["panorama"]["pais"]["votos17"]
    expl = (f"nosso valor é o da Tatu ({meta['secoes_com_log']:,} logs), cujo campo por seção confere com os nossos "
            f"logs em {100 * val['TARDIA']['votos_apos17_iguais']:.2f}% das seções tardias e "
            f"{100 * val['AMOSTRA']['votos_apos17_iguais']:.2f}% da amostra").replace(",", "X").replace(".", ",").replace("X", ".")
    linhas.append(_linha("TSE", "votos após 17h no país", TSE["votos_apos_17h_pais"], "total da Tatu (todos os logs)",
                         v17, expl + "; a diferença não se explica com os dados públicos", "EXTERNO_VALIDADO"))
    linhas.append(_linha("Congresso em Foco; CNN/Setup (C11)", "votos após 17h no país", 34330,
                         "total da Tatu (todos os logs)", v17, expl, "EXTERNO_VALIDADO"))
    tab = pd.DataFrame(linhas)
    OUT.mkdir(parents=True, exist_ok=True)
    tab.to_csv(OUT / "reconciliacao_tardias.csv", index=False, encoding="utf-8")
    # contagens por faixa de horário (Brasília), três eventos, para o capítulo temporal
    faixas = [0, H17, H17 + 900, H18, H19, 24 * 3600]
    rot = ["antes_17h", "17h00_17h15", "17h15_18h", "18h_19h", "a_partir_19h"]
    contagem = {nome: pd.cut(s, faixas, right=False, labels=rot).value_counts().reindex(rot).astype(int).to_dict()
                for nome, s in (("encerramento_bu", d.enc_s), ("emissao_bu", d.emi_s),
                                ("primeiro_pedido_log", d.pedido_encerramento_primeiro_s))}
    contagem["primeiro_pedido_log"]["observacao"] = "só nas seções com log baixado (recorte + amostra)"
    # custos medidos da coleta (execuções registradas pelas duas ferramentas)
    bp = RAIZ / "data" / "raw" / "bu_portal"
    ce = [json.loads(x) for x in (bp / "censo_3221" / "execucoes.jsonl").read_text(encoding="utf-8").splitlines() if x]
    le = [json.loads(x) for x in (bp / "logs_3221" / "execucoes.jsonl").read_text(encoding="utf-8").splitlines() if x]
    custos = {"censo_bu": {"secoes": sum(e["nesta_execucao"] for e in ce), "requisicoes": sum(e["requisicoes"] for e in ce),
                           "bytes": sum(e["bytes"] for e in ce), "segundos": round(sum(e["segundos"] for e in ce), 1),
                           "pausas_por_limitacao": sum(e["pausas_por_limitacao"] for e in ce)},
              "logs": {"secoes": sum(e["nesta_execucao"] for e in le), "requisicoes": sum(e["requisicoes"] for e in le),
                       "bytes": sum(z.stat().st_size for z in (bp / "logs_3221").glob("logs_*.zip")),
                       "segundos": round(sum(e["segundos"] for e in le), 1)}}
    custos["logs_nacional_estimado"] = {
        "secoes": len(cs), "requisicoes": len(cs),
        "bytes": round(custos["logs"]["bytes"] / max(custos["logs"]["secoes"], 1) * len(cs))}
    (OUT / "custos_coleta.json").write_text(json.dumps(custos, ensure_ascii=False, indent=2), encoding="utf-8")
    js = {"reproducao": linhas, "custos": custos, "reconciliacao_logs": rec, "validacao_campos_tatu": val, "status_logs": status_logs,
          "logs": {"tardias": int(tardia.sum()), "amostra": int(d.estrato.eq("AMOSTRA").sum()),
                   "com_log_ok": int(log_ok.sum())},
          "secoes_por_faixa": contagem,
          "votos_apos_17h_pais": {"tatu_todos_logs": v17, "tse": TSE["votos_apos_17h_pais"],
                                  "congresso_em_foco_cnn": 34330,
                                  "nossa_contagem_na_cauda": int(d[tardia & log_ok].votos_apos_17h.sum()),
                                  "secoes_na_cauda": int(tardia.sum()),
                                  "observacao": "contagem nacional própria exigiria os 497 mil logs (não coletados)"}}
    (OUT / "reconciliacao_tardias.json").write_text(json.dumps(js, ensure_ascii=False, indent=2, default=str),
                                                    encoding="utf-8")
    cols = K + ["estrato", "abertura_br", "encerramento_br", "emissao_br", "offset_h", "fonte_offset",
                "pedido_encerramento_primeiro", "pedido_encerramento_ultimo", "n_pedidos_encerramento",
                "cancelamentos_encerramento", "votos_dia", "votos_apos_17h", "votos_17_18", "votos_18_19",
                "votos_apos_19h", "ultimo_voto", "encerramento_tatu", "votos_apos17_tatu", "u19_tatu",
                "n_logs", "votos_dia_final", "votos_apos_17h_final", "pedido_encerramento_primeiro_final",
                "qt_comparecimento", "reconciliada"]
    d[cols].to_parquet(OUT / "reconciliacao_secoes.parquet", index=False)
    with pd.option_context("display.width", 250, "display.max_colwidth", 60):
        print(tab[["fonte", "item", "publicado", "nosso_valor", "diferenca", "status"]].to_string(index=False))
    print(json.dumps({"reconciliacao_logs": {k: v for k, v in rec.items() if k != "divergentes"},
                      "divergentes": len(rec["divergentes"]), "validacao": val, "votos_17h_pais": js["votos_apos_17h_pais"], "faixas": contagem},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
