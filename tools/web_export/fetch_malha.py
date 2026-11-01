"""Baixa e congela a malha municipal e as UFs usadas pelo mapa.

Fonte: API v3 de malhas do IBGE (municípios 2022, qualidade intermediária).
A resposta vem comprimida em gzip. A simplificação usa mapshaper quando
disponível (preserva topologia entre municípios) e cai para arredondamento
de precisão quando não está. O resultado e o hash entram no manifesto do
release; a malha não é editada à mão.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

BASE = "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo%2Bjson&qualidade=intermediaria&intrarregiao={}"
CACHE = Path(__file__).resolve().parents[2] / "data/raw/malha_web"
OUT = Path(__file__).resolve().parents[2] / "web/public/geo"


def _download(url: str, dest: Path) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "presidenciais-2026-web-export/1.0"})
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read()
    dest.write_bytes(raw)
    return raw


def _decompress(raw: bytes) -> bytes:
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


def _round_coords(obj, decimals: int = 5):
    if isinstance(obj, list):
        if obj and all(isinstance(x, (int, float)) for x in obj):
            return [round(float(x), decimals) for x in obj]
        return [_round_coords(x, decimals) for x in obj]
    return obj


def _simplify_with_mapshaper(src: Path, dst: Path) -> bool:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        return False
    cmd = [
        npx,
        "--yes",
        "mapshaper@0.6.102",
        str(src),
        "-simplify",
        "25%",
        "keep-shapes",
        "-o",
        "format=geojson",
        "precision=0.00001",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception:
        return False
    if proc.returncode != 0 or not dst.exists():
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:], file=sys.stderr)
        return False
    return True


def _write_geojson(raw: bytes, dst: Path, simplify: bool) -> dict:
    data = json.loads(raw)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if simplify:
        with tempfile.TemporaryDirectory(prefix="malha-web-") as tmp:
            src = Path(tmp) / "raw.geojson"
            tmp_out = Path(tmp) / "out.geojson"
            src.write_bytes(raw)
            if _simplify_with_mapshaper(src, tmp_out):
                data = json.loads(tmp_out.read_text(encoding="utf-8"))
            else:
                for feature in data.get("features", []):
                    geom = feature.get("geometry") or {}
                    if "coordinates" in geom:
                        geom["coordinates"] = _round_coords(geom["coordinates"])
    else:
        for feature in data.get("features", []):
            geom = feature.get("geometry") or {}
            if "coordinates" in geom:
                geom["coordinates"] = _round_coords(geom["coordinates"], 4)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    dst.write_text(text, encoding="utf-8")
    return {
        "arquivo": dst.name,
        "bytes": dst.stat().st_size,
        "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
        "features": len(data.get("features", [])),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    resultados = []
    for kind, simplify in (("municipio", True), ("UF", False)):
        raw_path = CACHE / f"malha_{kind}_raw.gz"
        raw = _download(BASE.format(kind), raw_path)
        plain = _decompress(raw)
        (CACHE / f"malha_{kind}_raw.geojson").write_bytes(plain)
        dest = OUT / ("municipios_2022_intermediaria.geojson" if kind == "municipio" else "ufs_2022.geojson")
        info = _write_geojson(plain, dest, simplify=simplify)
        info["fonte_url"] = BASE.format(kind)
        info["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        resultados.append(info)
        print(f"{kind}: {info['features']} feições, {info['bytes']} bytes -> {dest}")
    meta = {"acesso": "2026-10-30", "fonte": "IBGE API v3 malhas", "resultados": resultados}
    (OUT / "malha_manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
