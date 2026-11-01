"""Contexto municipal oficial (IBGE SIDRA) → staging `municipal_context` (handoff 17, O-R6).

Escrito pela frente B após a transferência das frentes (handoff 17). Variáveis e
tabelas definidas em `config/analysis.toml [context]`, conferidas nos metadados
da API em 26/10/2026:

    tabela 4714 (Censo 2022): var 93 população residente; var 6318 área (km²)
    tabela 5938 (PIB dos Municípios): var 37 PIB a preços correntes (mil R$)

O JSON bruto de cada consulta é gravado em `data/raw/ibge/` com SHA-256 e
promoção atômica, e registrado em `data/raw/ibge/manifest.json`. O código IBGE
de 7 dígitos é ligado ao código TSE pelo arquivo oficial `municipio_tse_ibge`.
Valores não numéricos do SIDRA ("-", "...", "X") viram ausentes, nunca zero.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

API = "https://servicodados.ibge.gov.br/api/v3/agregados"
UF_IBGE = {"RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22,
           "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32,
           "RJ": 33, "SP": 35, "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53}
# (tabela, período, variável IBGE) → (variável do contrato, unidade)
CONSULTAS = {
    (4714, 2022, 93): ("populacao_residente", "pessoas"),
    (4714, 2022, 6318): ("area_territorial_km2", "km2"),
    (5938, 2022, 37): ("pib_mil_reais", "mil reais"),
}


def query_url(tabela: int, periodo: int, variaveis: list[int], uf: str) -> str:
    vs = "|".join(str(v) for v in variaveis)
    return f"{API}/{tabela}/periodos/{periodo}/variaveis/{vs}?localidades=N6[N3[{UF_IBGE[uf]}]]"


def _fetch(url: str, timeout: int = 120, tentativas: int = 4) -> bytes:
    """GET com novas tentativas (espera de 5, 15 e 45 s): a API do SIDRA falha de forma
    intermitente (27/10/2026, timeout na consulta nacional)."""
    import time
    req = urllib.request.Request(url, headers={"User-Agent": "br2026/1.0", "Accept-Encoding": "gzip"})
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise OSError(f"HTTP {r.status} em {url}")
                b = r.read()
            return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b
        except OSError:
            if i == tentativas - 1:
                raise
            time.sleep(5 * 3 ** i)
    raise AssertionError("inalcançável")


def _atomic_write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return hashlib.sha256(data).hexdigest()


def parse_sidra(payload: bytes, tabela: int, periodo: int, url: str, source_id: str) -> pd.DataFrame:
    """JSON da API v3 de agregados → linhas (cd_municipio_ibge, variavel, valor, unidade, ano)."""
    rows = []
    for var in json.loads(payload.decode("utf-8")):
        key = (tabela, periodo, int(var["id"]))
        if key not in CONSULTAS:
            continue
        nome, unidade = CONSULTAS[key]
        for res in var.get("resultados", []):
            for s in res.get("series", []):
                raw = s.get("serie", {}).get(str(periodo))
                valor = pd.to_numeric(raw, errors="coerce")  # "-", "...", "X" → NaN
                rows.append({"cd_municipio_ibge": str(s["localidade"]["id"]), "variavel": nome,
                             "valor": float(valor) if pd.notna(valor) else float("nan"),
                             "unidade": unidade, "ano_referencia": periodo, "fonte_url": url,
                             "source_id": source_id})
    return pd.DataFrame(rows)


def tse_ibge_map(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", encoding="latin-1", dtype=str)
    return pd.DataFrame({"sg_uf": df.SG_UF, "cd_municipio_tse": df.CD_MUNICIPIO_TSE.str.zfill(5),
                         "cd_municipio_ibge": df.CD_MUNICIPIO_IBGE.str.zfill(7)})


def build_context(parsed: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    m = parsed.merge(mapping, on="cd_municipio_ibge", how="left", validate="many_to_one")
    if m.cd_municipio_tse.isna().any():
        bad = sorted(m.loc[m.cd_municipio_tse.isna(), "cd_municipio_ibge"].unique())[:5]
        raise ValueError(f"município IBGE sem correspondência TSE: {bad}")
    out = m[["sg_uf", "cd_municipio_tse", "cd_municipio_ibge", "variavel", "valor", "unidade",
             "ano_referencia", "fonte_url", "source_id"]].copy()
    out["ano_referencia"] = out.ano_referencia.astype("int16")
    return out.sort_values(["sg_uf", "cd_municipio_tse", "variavel"]).reset_index(drop=True)


def run(ufs: list[str], project_root: Path, mapping_zip: Path, fetch=_fetch) -> dict:
    """Consulta, grava brutos versionados e publica data/staging/municipal_context.parquet."""
    from br2026.contract import validate
    root = Path(project_root)
    raw_dir = root / "data" / "raw" / "ibge"
    manifest_path = raw_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"registros": {}}
    parts = []
    for uf in ufs:
        for (tabela, periodo), vars_ in _group_queries().items():
            url = query_url(tabela, periodo, vars_, uf)
            payload = fetch(url)
            name = f"sidra_{tabela}_{periodo}_{'-'.join(map(str, vars_))}_{uf}.json"
            sha = _atomic_write(raw_dir / name, payload)
            manifest["registros"][name] = {"url": url, "sha256": sha, "bytes": len(payload),
                                           "obtido_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            parts.append(parse_sidra(payload, tabela, periodo, url, sha))
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    ctx = build_context(pd.concat(parts, ignore_index=True), tse_ibge_map(mapping_zip))
    validate(ctx, "municipal_context")
    out = root / "data" / "staging" / "municipal_context.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    ctx.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    return {"linhas": len(ctx), "municipios": int(ctx.cd_municipio_tse.nunique()),
            "ausentes": int(ctx.valor.isna().sum()), "arquivos_brutos": len(parts)}


def _group_queries() -> dict:
    g: dict = {}
    for tabela, periodo, var in CONSULTAS:
        g.setdefault((tabela, periodo), []).append(var)
    return g
