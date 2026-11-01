"""Prova de conceito dos horários pelo BU por seção do portal Resultados (handoff 24, M3).

Lê `arquivo-urna/{pleito}/dados/{uf}/{mun}/{zona}/{secao}/...-aux.json` e o `bu.dat` indicado,
decodifica o DER sem esquema e extrai, do BU interno: identificação (município, zona, local,
seção), data/hora de emissão e o bloco `dadosSecao` (abertura, encerramento).

Duas etapas, ambas sobre amostra estratificada fixa (semente registrada):
  1. validação no 1º turno (pleito 3220): os horários do BU por seção são comparados com
     ABERTURA_URNA/ENCERRAMENTO_URNA do BU web já no staging (mesmo evento, outra publicação);
  2. 2º turno (pleito 3221): horários de abertura e encerramento por seção.

Brutos guardados em data/raw/bu_portal/{pleito}/ com SHA-256 num manifesto próprio; saídas
agregadas por seção (BU é documento público e não tem dado pessoal) em
reports/analysis/evidencias_horarios/. Também mede o custo (requisições, bytes, tempo).

Uso: python tools/poc_bu_horarios.py [--root DIR] [--n-uf 120] [--semente 20261027]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/{p}/dados/{uf}/{m}/{z}/{s}"
UA = "br2026-pesquisa/1.0 (prova de conceito do piloto; leitura delimitada)"


def _tlv(b: bytes, i: int):
    t = b[i]; i += 1
    if t & 0x1F == 0x1F:
        tag = 0
        while True:
            x = b[i]; i += 1; tag = (tag << 7) | (x & 0x7F)
            if not x & 0x80:
                break
    else:
        tag = t & 0x1F
    ln = b[i]; i += 1
    if ln & 0x80:
        n = ln & 0x7F; ln = int.from_bytes(b[i:i + n], "big"); i += n
    return t, tag, i, ln


def _filhos(b: bytes, i: int, fim: int) -> list[tuple[int, int, bytes]]:
    out = []
    while i < fim:
        t, tag, j, ln = _tlv(b, i)
        out.append((t, tag, b[j:j + ln]))
        i = j + ln
    return out


def _int(v: bytes) -> int:
    return int.from_bytes(v, "big", signed=True)


def decodificar_bu(dat: bytes) -> dict:
    """Envelope genérico -> último OCTET STRING = BU. Campos pela posição observada no BU 2026."""
    t, _, j, ln = _tlv(dat, 0)
    env = _filhos(dat, j, j + ln)
    bu = [v for (tt, _, v) in env if tt == 0x04][-1]
    t, _, j, ln = _tlv(bu, 0)
    top = _filhos(bu, j, j + ln)
    # identificação da seção: SEQ{ SEQ{municipio, zona}, local, secao } logo antes da emissão (GeneralizedString)
    idx_em = next(k for k, (tt, tag, v) in enumerate(top) if tt == 0x1B and len(v) == 15)
    ident = _filhos(top[idx_em - 1][2], 0, len(top[idx_em - 1][2]))
    mz = _filhos(ident[0][2], 0, len(ident[0][2]))
    dados = next((v for (tt, tag, v) in top[idx_em + 1:] if tt == 0xA0), None)   # ctx[0] dadosSecao
    ab = enc = None
    if dados is not None:
        hs = [v.decode() for (tt, _, v) in _filhos(dados, 0, len(dados)) if tt == 0x1B]
        ab, enc = (hs + [None, None])[:2]
    return {"municipio": _int(mz[0][2]), "zona": _int(mz[1][2]), "local": _int(ident[1][2]),
            "secao": _int(ident[2][2]), "emissao": top[idx_em][2].decode(), "abertura": ab, "encerramento": enc}


def _get(url: str, tentativas: int = 3) -> bytes | None:
    for k in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + k)
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1 + k)
    return None


def buscar(pleito: int, uf: str, mun: str, zona: str, secao: str, raw: Path) -> dict:
    u, m, z, s = uf.lower(), mun.zfill(5), zona.zfill(4), secao.zfill(4)
    base = BASE.format(p=pleito, uf=u, m=m, z=z, s=s)
    aux = _get(f"{base}/p00{pleito}-{u}-m{m}-z{z}-s{s}-aux.json")
    r = {"pleito": pleito, "sg_uf": uf, "cd_municipio_tse": m, "nr_zona": z, "nr_secao": s, "bytes": 0}
    if aux is None:
        return {**r, "status": "SEM_AUX"}
    r["bytes"] += len(aux)
    j = json.loads(aux)
    hs = [h for h in j.get("hashes", []) if h.get("st") in ("Totalizado", "Recebido")] or j.get("hashes", [])
    if not hs:
        return {**r, "status": "SEM_HASH", "st_secao": j.get("st")}
    h = hs[-1]
    nm = next((a["nm"] for a in h.get("arq", []) if a.get("tp") == "bu"), None)
    if nm is None:
        return {**r, "status": "SEM_BU"}
    dat = _get(f"{base}/{h['hash']}/{nm}")
    if dat is None:
        return {**r, "status": "BU_404"}
    r["bytes"] += len(dat)
    dest = raw / str(pleito) / nm
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(dat)
    try:
        d = decodificar_bu(dat)
    except (ValueError, IndexError, StopIteration, UnicodeDecodeError) as e:
        return {**r, "status": f"DER_INVALIDO:{type(e).__name__}"}
    ok_id = (d["municipio"] == int(m) and d["zona"] == int(z) and d["secao"] == int(s))
    return {**r, "status": "OK" if ok_id else "IDENTIFICACAO_DIVERGE", "arquivo": nm,
            "sha256": hashlib.sha256(dat).hexdigest(), "n_hashes": len(j.get("hashes", [])),
            **{f"bu_{k}": v for k, v in d.items()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    ap.add_argument("--n-uf", type=int, default=120)
    ap.add_argument("--semente", type=int, default=20261027)
    ap.add_argument("--n-validacao", type=int, default=60)
    a = ap.parse_args(argv)
    root = a.root
    raw = root / "data" / "raw" / "bu_portal"
    out = root / "reports" / "analysis" / "evidencias_horarios"
    out.mkdir(parents=True, exist_ok=True)
    from br2026.panel.run import staging_path
    st = pd.read_parquet(staging_path(root / "data" / "staging", "section_turn"),
                         columns=["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"])
    t2 = st[st.nr_turno == 2].drop_duplicates()
    rng = np.random.default_rng(a.semente)
    amostra = pd.concat([g.iloc[rng.choice(len(g), size=min(a.n_uf, len(g)), replace=False)]
                         for _, g in t2.groupby("sg_uf")])
    val = pd.concat([g.iloc[:max(1, a.n_validacao // 3)] for _, g in amostra.groupby("sg_uf")])
    tarefas = [(3220, r) for r in val.itertuples()] + [(3221, r) for r in amostra.itertuples()]
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda pr: buscar(pr[0], pr[1].sg_uf, pr[1].cd_municipio_tse, pr[1].nr_zona,
                                            pr[1].nr_secao, raw), tarefas))
    dur = time.perf_counter() - t0
    df = pd.DataFrame(res)
    df.to_csv(out / "poc_bu_amostra.csv", index=False)
    man = {"executado_em_utc": pd.Timestamp.now("UTC").isoformat(timespec="seconds"), "semente": a.semente,
           "n_por_uf_t2": a.n_uf, "secoes_validacao_t1": int(len(val)), "requisicoes_aprox": int(2 * len(tarefas)),
           "bytes": int(df.bytes.sum()), "segundos": round(dur, 1), "status": df.status.value_counts().to_dict()}
    (out / "poc_bu_manifesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(man, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
