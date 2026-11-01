"""Logs de urna das seções tardias (handoff 29): eventos de encerramento e votos após as 17h.

Escopo delimitado: (1) as seções cujo encerramento ou emissão do BU (censo do portal, convertidos
para Brasília pelo deslocamento municipal validado) é >= 18h, onde estão as seções prorrogadas e a
fronteira dos critérios externos (UOL/Tatu pelo encerramento, TSE pela emissão); (2) uma amostra
aleatória simples (semente fixa) das demais seções, só para validar os campos por seção da Tatu
fora da cauda. Não é coleta nacional de logs; o total nacional de votos após as 17h vem da Tatu,
validada nessas duas partes (ver `reconciliar_tardias.py`).

Para cada seção, a partir do `log.jez` oficial (zip com `logd.dat`, uma linha por evento, hora
local da urna), só eventos do dia da eleição do turno:
- `pedido_encerramento_primeiro` / `_ultimo`: "Operador selecionou: Encerrar votação";
- `encerramento_confirmado_ultimo`: "Procedimento de encerramento confirmado";
- `inicio_encerramento`: "Inicio do Encerramento";
- `cancelamentos_encerramento`: pedidos de encerramento sem confirmação antes do pedido seguinte;
- `votos_apos_17h`, `votos_17_18`, `votos_18_19`, `votos_apos_19h`: "O voto do eleitor foi
  computado" com hora (convertida para Brasília) nas faixas; `ultimo_voto`.

Cadeia de urnas (R30-1): quando a urna da seção foi trocada, o pacote traz o log da urna final e, em
`.jez` aninhados, os das urnas anteriores. Os eventos saem da cadeia completa (linhas de todos os
logs, sem repetição, em ordem de hora); os do log final sozinho ficam em colunas `_final`, porque
é o que uma leitura só do `logd.dat` externo vê. A conferência contra o comparecimento oficial é
feita em `reconciliar_tardias.py`. `--reprocessar` relê os pacotes já baixados, sem rede.

Sigilo: o log registra o título do mesário no encerramento e a sequência de eventos; nada disso
sai daqui. Saem só horários de eventos de operação e contagens por seção. Logs brutos ficam em
`data/raw/bu_portal/logs_{pleito}/` (não versionado), com SHA-256.

Uso: python tools/logs_tardias.py [--desde 18:00] [--amostra 1000] [--paralelo 6]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tools"))

from censo_bu import CAMINHO, Cliente, Ritmo  # noqa: E402

DIA = {3221: "25/10/2026", 3220: "04/10/2026"}
EV_PEDIDO = "Operador selecionou: Encerrar vota"
EV_CONFIRMADO = "Procedimento de encerramento confirmado"
EV_INICIO = "Inicio do Encerramento"
EV_VOTO = "O voto do eleitor foi computado"


def eventos(logd: str, dia: str, offset_h: float) -> dict:
    """Horários (Brasília) e contagens do dia da eleição; `offset_h` soma-se à hora local."""
    def hb(hhmmss: str) -> float:
        h, m, s = (int(x) for x in hhmmss.split(":"))
        return h * 3600 + m * 60 + s + offset_h * 3600

    def fmt(seg: float | None) -> str | None:
        if seg is None:
            return None
        seg = int(round(seg))
        return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"

    pedidos, confirmados, inicios, votos = [], [], [], []
    for linha in logd.splitlines():
        if not linha.startswith(dia):
            continue
        p = linha.split("\t")
        if len(p) < 5:
            continue
        t, msg = hb(p[0][11:19]), p[4]
        if msg.startswith(EV_VOTO):
            votos.append(t)
        elif msg.startswith(EV_PEDIDO):
            pedidos.append(t)
        elif msg.startswith(EV_CONFIRMADO):
            confirmados.append(t)
        elif msg.startswith(EV_INICIO):
            inicios.append(t)
    # pedido cancelado: não seguido de confirmação antes do próximo pedido
    canc = 0
    for i, t in enumerate(pedidos):
        prox = pedidos[i + 1] if i + 1 < len(pedidos) else float("inf")
        if not any(t <= c < prox for c in confirmados):
            canc += 1
    h17, h18, h19 = 17 * 3600, 18 * 3600, 19 * 3600
    return {"pedido_encerramento_primeiro": fmt(min(pedidos) if pedidos else None),
            "pedido_encerramento_ultimo": fmt(max(pedidos) if pedidos else None),
            "encerramento_confirmado_ultimo": fmt(max(confirmados) if confirmados else None),
            "inicio_encerramento": fmt(max(inicios) if inicios else None),
            "n_pedidos_encerramento": len(pedidos), "cancelamentos_encerramento": canc,
            "votos_dia": len(votos), "ultimo_voto": fmt(max(votos) if votos else None),
            "votos_apos_17h": sum(t >= h17 for t in votos),
            "votos_17_18": sum(h17 <= t < h18 for t in votos),
            "votos_18_19": sum(h18 <= t < h19 for t in votos),
            "votos_apos_19h": sum(t >= h19 for t in votos)}


def deslocamentos(turno: int) -> pd.Series:
    """Deslocamento (h) local → Brasília por município: inferido no turno, senão no 1º turno, senão o legal."""
    from validar_fuso import legal
    off = pd.read_csv(RAIZ / "data" / "analytics" / "closure_tz_offsets.csv", dtype={"cd_municipio_tse": str})
    off = off[off.offset_h.notna()]
    t1 = off[off.nr_turno == 1].set_index(["sg_uf", "cd_municipio_tse"]).offset_h
    tt = off[off.nr_turno == turno].set_index(["sg_uf", "cd_municipio_tse"]).offset_h
    return tt.combine_first(t1), legal


def horarios_censo(pleito: int = 3221) -> pd.DataFrame:
    """Seções OK do censo (território) com abertura, encerramento e emissão do BU em Brasília."""
    import duckdb
    arq = (RAIZ / "data" / "raw" / "bu_portal" / f"censo_{pleito}" / "resultados.jsonl").as_posix()
    r = duckdb.sql(f"""select sg_uf, cd_municipio_tse, nr_zona, nr_secao, bu_abertura, bu_encerramento, bu_emissao
        from (select *, row_number() over (partition by sg_uf, cd_municipio_tse, nr_zona, nr_secao
                                           order by coletado_em desc) k
              from read_json_auto('{arq}', format='newline_delimited'))
        where k = 1 and status = 'OK' and sg_uf <> 'ZZ'""").df()
    off, legal = deslocamentos(2 if pleito == 3221 else 1)
    chave = list(zip(r.sg_uf, r.cd_municipio_tse))
    r["offset_h"] = [off.get(c) if c in off.index else (lambda v: v if isinstance(v, (int, float)) else None)(legal(*c)[1])
                     for c in chave]
    r["fonte_offset"] = ["INFERIDO" if c in off.index else "LEGAL" for c in chave]
    r["offset_h"] = pd.to_numeric(r.offset_h, errors="coerce")   # AM sem inferência (ambíguo) fica nulo
    for c, n in (("bu_abertura", "abertura_br"), ("bu_encerramento", "encerramento_br"), ("bu_emissao", "emissao_br")):
        r[n] = pd.to_datetime(r[c], format="%Y%m%dT%H%M%S") + pd.to_timedelta(r.offset_h, unit="h")
    return r


def ler_logd(jez: bytes) -> str:
    """Só o log da urna final (o `logd.dat` do pacote externo)."""
    with zipfile.ZipFile(io.BytesIO(jez)) as z:
        return z.read("logd.dat").decode("latin-1")


def ler_cadeia(jez: bytes) -> list[str]:
    """Todos os `logd.dat` do pacote: o da urna final e os de urnas anteriores da mesma seção, que
    vêm em `.jez` aninhados (R30-1). Ordem: externo primeiro, depois os aninhados, em profundidade."""
    out = []
    with zipfile.ZipFile(io.BytesIO(jez)) as z:
        nomes = z.namelist()
        if "logd.dat" in nomes:
            out.append(z.read("logd.dat").decode("latin-1"))
        for n in nomes:
            if n.lower().endswith(".jez"):
                out += ler_cadeia(z.read(n))
    return out


def _quando(linha: str) -> str:
    """'dd/mm/aaaa hh:mm:ss…' → 'aaaammdd hh:mm:ss' para ordenar."""
    return f"{linha[6:10]}{linha[3:5]}{linha[:2]} {linha[11:19]}"


def eventos_cadeia(jez: bytes, dia: str, offset_h: float) -> dict:
    """Eventos da cadeia completa (linhas de todas as urnas, sem repetição, em ordem de hora) e, com
    sufixo `_final`, os do log da urna final sozinho, que é o que a leitura ingênua vê."""
    logs = ler_cadeia(jez)
    if not logs:
        raise KeyError("logd.dat")
    linhas = sorted({l for lg in logs for l in lg.splitlines() if l.strip()}, key=_quando)
    ev = eventos("\n".join(linhas), dia, offset_h)
    fin = eventos(logs[0], dia, offset_h)
    ev.update({"n_logs": len(logs), "votos_dia_final": fin["votos_dia"],
               "votos_apos_17h_final": fin["votos_apos_17h"],
               "pedido_encerramento_primeiro_final": fin["pedido_encerramento_primeiro"]})
    return ev


def escolher_hash(aux: dict | None) -> dict | None:
    """Pacote da seção: o 'Totalizado' tem prioridade sobre o 'Recebido'; entre iguais, o último."""
    hs = [h for h in (aux or {}).get("hashes", []) if h.get("st") in ("Totalizado", "Recebido")]
    tot = [h for h in hs if h.get("st") == "Totalizado"]
    return (tot or hs or [None])[-1]


def reprocessar(pasta: Path, dia: str) -> dict:
    """Relê os pacotes já baixados (sem rede) com a cadeia completa e reescreve `resultados.jsonl`;
    a versão anterior fica em `resultados_so_log_final.jsonl`."""
    res = pasta / "resultados.jsonl"
    linhas = [json.loads(l) for l in res.read_text(encoding="utf-8").splitlines() if l.strip()]
    zips: dict[str, zipfile.ZipFile] = {}
    novas, mudou = [], 0
    for r in linhas:
        if r.get("status") != "OK":
            novas.append(r)
            continue
        uf = r["sg_uf"]
        z = zips.setdefault(uf, zipfile.ZipFile(pasta / f"logs_{uf}.zip"))
        ev = eventos_cadeia(z.read(r["arquivo"]), dia, float(r["offset_h"]))
        mudou += int(ev["votos_dia"] != r.get("votos_dia")
                     or ev["pedido_encerramento_primeiro"] != r.get("pedido_encerramento_primeiro"))
        novas.append({**r, **ev, "leitura": "CADEIA_COMPLETA"})
    for z in zips.values():
        z.close()
    antigo = pasta / "resultados_so_log_final.jsonl"
    if not antigo.exists():
        res.replace(antigo)
    res.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in novas), encoding="utf-8")
    return {"secoes": len(novas), "alteradas": mudou,
            "com_logs_aninhados": sum(int(r.get("n_logs", 1) > 1) for r in novas)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", type=int, default=3221)
    ap.add_argument("--desde", default="18:00", help="encerramento do BU (Brasília) a partir do qual baixar o log")
    ap.add_argument("--amostra", type=int, default=1000, help="seções regulares sorteadas para validação")
    ap.add_argument("--paralelo", type=int, default=6)
    ap.add_argument("--max-req-s", type=float, default=15.0)
    ap.add_argument("--reprocessar", action="store_true",
                    help="relê os pacotes já baixados com a cadeia completa, sem rede")
    a = ap.parse_args(argv)
    pasta_censo = RAIZ / "data" / "raw" / "bu_portal" / f"censo_{a.pleito}"
    pasta = RAIZ / "data" / "raw" / "bu_portal" / f"logs_{a.pleito}"
    pasta.mkdir(parents=True, exist_ok=True)
    if a.reprocessar:
        print(json.dumps(reprocessar(pasta, DIA[a.pleito])), flush=True)
        return 0
    # seleção: encerramento ou emissão do BU (Brasília) >= --desde, mais a amostra das demais
    cs = horarios_censo(a.pleito)
    lim = pd.Timestamp(cs.encerramento_br.dropna().iloc[0].date()) + pd.Timedelta(a.desde + ":00")
    tarde = (cs.encerramento_br >= lim) | (cs.emissao_br >= lim)
    K = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
    resto = cs[~tarde & cs.encerramento_br.notna()]
    amostra = resto.sample(n=min(a.amostra, len(resto)), random_state=20261028) if a.amostra else resto.iloc[:0]
    sel = pd.concat([cs[tarde].assign(estrato="TARDIA"), amostra.assign(estrato="AMOSTRA")])
    estrato = {tuple(x[:4]): x[4] for x in sel[K + ["estrato"]].itertuples(index=False, name=None)}
    off = cs.set_index(["sg_uf", "cd_municipio_tse"]).offset_h.groupby(level=[0, 1]).first()
    # hash do pacote da seção: aux.json guardado pelo censo (lido só para as selecionadas)
    aux: dict[tuple, dict] = {}
    for uf, g in sel.groupby("sg_uf"):
        with zipfile.ZipFile(pasta_censo / f"bu_{uf}.zip") as z:
            nomes = set(z.namelist())
            for m, zn, s_ in g[["cd_municipio_tse", "nr_zona", "nr_secao"]].itertuples(index=False, name=None):
                n = f"aux/{m}-{zn}-{s_}.json"
                if n in nomes:
                    aux[(uf, m, zn, s_)] = json.loads(z.read(n))
    res_path = pasta / "resultados.jsonl"
    feitas = set()
    if res_path.exists():
        for l in res_path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("status") in ("OK", "SEM_LOG", "LOG_404", "LOG_INVALIDO"):
                feitas.add((r["sg_uf"], r["cd_municipio_tse"], r["nr_zona"], r["nr_secao"]))
    pend = [t for t in sel[K].itertuples(index=False, name=None) if t not in feitas]
    print(f"seleção {len(sel)} ({int(tarde.sum())} com encerramento/emissão BU >= {a.desde}; "
          f"amostra {len(amostra)}); pendentes {len(pend)}", flush=True)
    cli = Cliente(Ritmo(a.max_req_s))
    t0 = time.perf_counter()

    def uma(t):
        uf, m, z, s = t
        r = {"pleito": a.pleito, "sg_uf": uf, "cd_municipio_tse": m, "nr_zona": z, "nr_secao": s,
             "estrato": estrato[t]}
        h = escolher_hash(aux.get((uf, m, z, s)))
        nm = next((x["nm"] for x in (h["arq"] if h else []) if x.get("tp") == "log"), None)
        if nm is None:
            return {**r, "status": "SEM_LOG"}, None
        base = CAMINHO.format(p=a.pleito, uf=uf.lower(), m=m, z=z, s=s)
        st, jez = cli.get(f"{base}/{h['hash']}/{nm}")
        if st == 0:
            return {**r, "status": "ERRO_REDE"}, None
        if jez is None:
            return {**r, "status": "LOG_404"}, None
        try:
            ev = eventos_cadeia(jez, DIA[a.pleito], float(off.get((uf, m), float("nan"))))
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            return {**r, "status": "LOG_INVALIDO", "obs": type(e).__name__, "sha256": hashlib.sha256(jez).hexdigest()}, jez
        return {**r, "status": "OK", "arquivo": nm, "sha256": hashlib.sha256(jez).hexdigest(), "bytes": len(jez),
                "offset_h": float(off.get((uf, m), float("nan"))), "leitura": "CADEIA_COMPLETA", **ev}, jez

    n = 0
    with cf.ThreadPoolExecutor(max_workers=a.paralelo) as ex, res_path.open("a", encoding="utf-8") as fh:
        zips: dict[str, zipfile.ZipFile] = {}
        for r, jez in ex.map(uma, pend):
            if jez is not None:
                uf = r["sg_uf"]
                if uf not in zips:
                    zips[uf] = zipfile.ZipFile(pasta / f"logs_{uf}.zip", "a", compression=zipfile.ZIP_STORED)
                zips[uf].writestr(r.get("arquivo") or f"{r['cd_municipio_tse']}-{r['nr_zona']}-{r['nr_secao']}.jez", jez)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
            if n % 500 == 0:
                print(f"{n}/{len(pend)} em {time.perf_counter() - t0:.0f} s; {cli.requisicoes} req", flush=True)
        for zf in zips.values():
            zf.close()
    resumo = {"pleito": a.pleito, "desde": a.desde, "selecao": len(sel), "tardias": int(tarde.sum()),
              "amostra": len(amostra), "nesta_execucao": len(pend),
              "segundos": round(time.perf_counter() - t0, 1), "requisicoes": cli.requisicoes}
    with (pasta / "execucoes.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(resumo) + "\n")
    print(json.dumps(resumo), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
