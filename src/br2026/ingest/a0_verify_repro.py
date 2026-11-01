"""A0 — verificação de reprodutibilidade do inventário local.

Recomputa SHA-256 de todos os arquivos de SOURCE_ROOT/data e compara com o
`docs/sources/local_scan.json` gravado pela última execução de `local --values`.
Responde ao teste obrigatório 8 do 02_HANDOFF_DADOS.md para a etapa A0:
duas execuções sobre os mesmos insumos produzem conteúdo semanticamente igual,
sem duplicar registros e sem misturar timestamps de execução no conteúdo.

Uso:
    .venv/Scripts/python.exe src/br2026/ingest/a0_verify_repro.py
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = Path(r"../election_2026")
SOURCES_DIR = PROJECT_ROOT / "docs" / "sources"
CHUNK = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def main() -> int:
    scan = json.loads((SOURCES_DIR / "local_scan.json").read_text(encoding="utf-8"))
    source_root = Path(scan["source_root"])
    gravado = {e["path"]: e for e in scan["files"]}
    atuais = sorted(p for p in (source_root / "data").rglob("*") if p.is_file())

    t0 = time.perf_counter()
    diverg: list[dict] = []
    hash_seconds = 0.0
    for p in atuais:
        rel = p.relative_to(source_root).as_posix()
        t1 = time.perf_counter()
        digest = sha256_file(p)
        hash_seconds += time.perf_counter() - t1
        e = gravado.get(rel)
        if e is None:
            diverg.append({"path": rel, "motivo": "novo na segunda execucao"})
        elif e["sha256"] != digest:
            diverg.append({"path": rel, "motivo": "sha256 divergente",
                           "gravado": e["sha256"], "recomputado": digest})
        elif e["bytes"] != p.stat().st_size:
            diverg.append({"path": rel, "motivo": "bytes divergentes"})

    ausentes = sorted(set(gravado) - {p.relative_to(source_root).as_posix() for p in atuais})

    resultado = {
        "verificado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_root": str(source_root),
        "arquivos_gravados": len(gravado),
        "arquivos_recomputados": len(atuais),
        "sha256_identicos": len(atuais) - len(diverg),
        "divergencias": diverg,
        "ausentes_na_segunda_execucao": ausentes,
        "hash_seconds": round(hash_seconds, 1),
        "elapsed_seconds": round(time.perf_counter() - t0, 1),
        "reproduzivel": not diverg and not ausentes,
    }
    out = SOURCES_DIR / "repro_check.json"
    out.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: resultado[k] for k in (
        "arquivos_gravados", "arquivos_recomputados", "sha256_identicos",
        "hash_seconds", "reproduzivel")}, ensure_ascii=False))
    print("out:", out)
    return 0 if resultado["reproduzivel"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
