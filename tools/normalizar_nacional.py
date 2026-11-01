"""Normalize das 28 unidades nos dois turnos, em paralelo e retomável (handoff 26).

Cada tarefa é um `python -m br2026 normalize --uf X --turno T` em processo próprio, para que
o pico de memória de uma UF não se some ao das outras. O 1º turno de cada UF roda antes do
2º (o perfil, sem turno, é gravado no 1º e reaproveitado no 2º). Uma UF/turno é pulada quando
todas as suas partições já existem e vieram dos brutos vigentes no manifesto; `--refazer`
ignora isso.

Saída: `reports/analysis/evidencias_nacional/normalize_log.jsonl` (uma linha por tarefa:
tempo, pico de memória, linhas, avisos, bloqueios, código de saída).

Uso:
    python tools/normalizar_nacional.py [--ufs AC,RS] [--paralelo 3] [--refazer] [--turnos 2]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from br2026.normalize import _migrar_arquivo_unico  # noqa: E402

UNIDADES = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
            "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ")
# tabelas por turno; o perfil é por UF (sem turno)
TABELAS_TURNO = ("votes_long", "section_turn", "closure", "section_crosswalk")
LOG_REL = Path("reports") / "analysis" / "evidencias_nacional" / "normalize_log.jsonl"


def _vigente(staging: Path, uf: str, turno: int, shas: set[str]) -> bool:
    partes = [staging / t / f"{uf}_T{turno}.parquet" for t in TABELAS_TURNO]
    partes.append(staging / "profiles" / f"{uf}.parquet")
    if turno == 2:
        # o 2º turno não tem bweb nem CEFT: closure e crosswalk do T2 podem não existir
        partes = [p for p in partes if p.parent.name in ("votes_long", "section_turn")]
    for p in partes:
        if not p.exists():
            return False
        ids = set(pq.read_table(p, columns=["source_id"]).column("source_id").unique().to_pylist())
        if not ids <= shas:
            return False
    return True


def _uma(uf: str, turno: int) -> dict:
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, "-m", "br2026", "--root", str(RAIZ), "normalize",
                        "--uf", uf, "--turno", str(turno)],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(RAIZ))
    saida = {}
    for linha in r.stdout.splitlines()[::-1]:
        if linha.startswith("{"):
            saida = json.loads(linha)
            break
    return {"uf": uf, "turno": turno, "codigo_saida": r.returncode,
            "tempo_s": round(time.perf_counter() - t0, 1),
            "pico_memoria_gb": round((saida.get("linhas") or {}).get("pico_memoria_kb", 0) / 1e6, 2),
            "linhas": saida.get("linhas"), "avisos": saida.get("avisos"),
            "bloqueios": saida.get("bloqueios"), "erro": r.stderr.strip()[-2000:] or None,
            "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _uf_completa(uf: str, staging: Path, shas: set[str], refazer: bool,
                 turnos: tuple[int, ...] = (1, 2)) -> list[dict]:
    res = []
    for turno in turnos:
        if not refazer and _vigente(staging, uf, turno, shas):
            res.append({"uf": uf, "turno": turno, "codigo_saida": None, "pulado": "partições vigentes"})
            continue
        r = _uma(uf, turno)
        res.append(r)
        if turno == 1 and r["codigo_saida"] not in (0,):
            break   # sem o 1º turno, o 2º não tem perfil nem base de comparação
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ufs", default=",".join(UNIDADES))
    ap.add_argument("--paralelo", type=int, default=3)
    ap.add_argument("--refazer", action="store_true")
    ap.add_argument("--turnos", default="1,2", help="ex.: 2 para refazer só o 2º turno (perfil do 1º reaproveitado)")
    a = ap.parse_args()
    turnos = tuple(int(t) for t in a.turnos.split(","))
    ufs = [u.strip().upper() for u in a.ufs.split(",") if u.strip()]
    staging = RAIZ / "data" / "staging"
    # migração do layout de arquivo único antes de qualquer processo paralelo
    for t in TABELAS_TURNO + ("profiles",):
        if (staging / f"{t}.parquet").exists():
            _migrar_arquivo_unico(staging / f"{t}.parquet")
    manifesto = json.loads((RAIZ / "data" / "raw" / "manifest.json").read_text(encoding="utf-8"))
    shas = {r["sha256"] for r in manifesto["registros"].values() if isinstance(r, dict) and "sha256" in r}
    log = RAIZ / LOG_REL
    log.parent.mkdir(parents=True, exist_ok=True)
    # as maiores primeiro, para o paralelismo não terminar esperando SP
    ordem = sorted(ufs, key=lambda u: (u not in ("SP", "MG", "RJ", "BA", "RS", "PR"), u))
    falhas = 0
    with cf.ThreadPoolExecutor(max_workers=a.paralelo) as ex, open(log, "a", encoding="utf-8") as fh:
        for res in ex.map(lambda u: _uf_completa(u, staging, shas, a.refazer, turnos), ordem):
            for r in res:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
                estado = r.get("pulado") or f"saída {r['codigo_saida']}, {r.get('tempo_s')} s, {r.get('pico_memoria_gb')} GB"
                print(f"{r['uf']}/T{r['turno']}: {estado}", flush=True)
                # saída 4 (BLOCKED) é esperada no 2º turno: sem bweb_2t/CEFT_2t
                if r["codigo_saida"] not in (None, 0, 4):
                    falhas += 1
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
