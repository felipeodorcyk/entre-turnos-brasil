"""Inventário do pacote de staging publicado: uma linha por partição, com SHA-256 (R30-2).

Desde o handoff 26 o staging é particionado (`<tabela>/<UF>_T<turno>.parquet`; `profiles/<UF>.parquet`).
O inventário substitui a lista de arquivos únicos da entrega do piloto: `conferir` aponta partição
alterada, ausente ou a mais, e o teste de integração do pacote (`test_live_cli_validate_published_package`)
usa essa conferência antes de validar cada tabela no contrato.

Uso:
    python tools/inventario_staging.py            # grava reports/data/PACOTE_STAGING.json
    python tools/inventario_staging.py --conferir # compara o disco com o inventário gravado
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
TABELAS = ("votes_long", "section_turn", "profiles", "closure", "section_crosswalk")
# produtos socioeconômicos (handoff 37): cada arquivo publicado é uma "partição"; _cache fica de fora
SOCIO = ("socio_ibge", "socio_rais", "socio_pbf", "entorno_local")
INVENTARIO = Path("reports") / "data" / "PACOTE_STAGING.json"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def inventariar(staging: Path, tabelas: tuple[str, ...] = TABELAS) -> dict[str, dict[str, str]]:
    """{tabela: {partição: sha256}}; tabela em arquivo único entra como partição '' (layout antigo)."""
    inv = {}
    for t in tabelas:
        unico = staging / f"{t}.parquet"
        if unico.exists():
            inv[t] = {"": _sha(unico)}
        elif (staging / t).is_dir():
            arqs = sorted((staging / t).glob("*.parquet")) if t in TABELAS else sorted(
                q for q in (staging / t).iterdir() if q.is_file() and q.suffix in (".parquet", ".json", ".csv"))
            inv[t] = {q.name: _sha(q) for q in arqs}
    return inv


def conferir(staging: Path, esperado: dict[str, dict[str, str]],
             tabelas: tuple[str, ...] = TABELAS) -> list[str]:
    """Problemas entre o disco e o inventário: tabela ou partição ausente, a mais ou com hash diferente."""
    atual = inventariar(staging, tabelas)
    prob = []
    for t in sorted(set(esperado) | set(atual)):
        e, a = esperado.get(t), atual.get(t)
        if e is None:
            prob.append(f"{t}: tabela fora do inventário")
            continue
        if a is None:
            prob.append(f"{t}: tabela ausente do staging")
            continue
        for p in sorted(set(e) - set(a)):
            prob.append(f"{t}/{p}: partição ausente")
        for p in sorted(set(a) - set(e)):
            prob.append(f"{t}/{p}: partição fora do inventário")
        for p in sorted(set(e) & set(a)):
            if e[p] != a[p]:
                prob.append(f"{t}/{p}: hash difere do inventário")
    return prob


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=RAIZ)
    ap.add_argument("--conferir", action="store_true")
    a = ap.parse_args(argv)
    staging, alvo = a.root / "data" / "staging", a.root / INVENTARIO
    if a.conferir:
        js = json.loads(alvo.read_text(encoding="utf-8"))
        prob = conferir(staging, js["particoes"])
        if "particoes_socio" in js:
            prob += conferir(staging, js["particoes_socio"], SOCIO)
        print("\n".join(prob) or "PASS")
        return 1 if prob else 0
    inv = inventariar(staging)
    inv_s = inventariar(staging, SOCIO)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(json.dumps({"layout": "particionado <tabela>/<UF>_T<turno>.parquet; profiles/<UF>.parquet",
                                "n_particoes": {t: len(v) for t, v in inv.items()}, "particoes": inv,
                                "n_particoes_socio": {t: len(v) for t, v in inv_s.items()},
                                "particoes_socio": inv_s},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print({t: len(v) for t, v in inv.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
