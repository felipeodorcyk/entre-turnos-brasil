"""A0 — inventário de fontes da frente A (não faz parte da CLI comum de B).

Subcomandos:

    local     varre SOURCE_ROOT (somente leitura), calcula hash, lista entradas de
              zip, cabeçalhos CSV/Parquet e fatos de conteúdo (UF/turno/cargo).
    remote    consulta o CKAN do TSE, faz HEAD nas URLs oficiais e grava o
              snapshot bruto de disponibilidade.
    samples   baixa amostras pequenas com timeout/retry/promoção atômica, mede
              tamanho compactado/expandido, tempo e RAM, e extrai excertos de
              cabeçalho com proveniência.
    questions responde perguntas técnicas de B com evidência determinística
              (contagens em DuckDB sobre arquivos oficiais locais) e inspeciona
              campos de encerramento/fuso.
    summary   consolida o inventário em matrizes fonte x turno x UF, contagens
              por família e estimativa de armazenamento com premissas.
    all       executa local + remote + samples + questions + summary.

Saídas (todas sob PROJECT_ROOT): docs/sources/inventory.csv,
docs/sources/local_scan.json, docs/sources/remote_snapshot.json,
docs/sources/samples/PROVENANCE.csv + *.head.txt,
docs/sources/questions_A_evidence.json, docs/sources/summary.json.

Uso:
    .venv/Scripts/python.exe src/br2026/ingest/a0_inventory.py all
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = Path(r"../election_2026")
SOURCES_DIR = PROJECT_ROOT / "docs" / "sources"
SAMPLES_DIR = SOURCES_DIR / "samples"
RAW_SAMPLES = PROJECT_ROOT / "data" / "raw" / "samples"
CKAN = "https://dadosabertos.tse.jus.br/api/3/action/"
UA = "br2026-a0-inventory/1.0 (frente A; contato: projeto nacional 2026)"

CKAN_PACKAGES = [
    "resultados-2026",
    "resultados-2026-boletim-de-urna",
    "resultados-2026-arquivos-transmitidos-para-totalizacao",
    "resultados-2026-correspondencias-esperadas-e-efetivadas-1-turno",
    "resultados-2026-correspondencias-esperadas-e-efetivadas-2-turno",
    "resultados-2026-logs-do-sistema-de-preparacao-das-urnas-eletronicas-gedai-1-turno",
    "resultados-2026-logs-do-sistema-de-preparacao-das-urnas-eletronicas-gedai-2-turno",
    "eleitorado-2026",
    "candidatos-2026",
    "comparecimento-e-abstencao-2026",
    "frequencia-de-atualizacao-dos-arquivos",
    "codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge",
    "resultados-2022",
    "resultados-2024",
]

# Amostras pequenas: finalidade explícita, sem baixar bases nacionais completas.
SAMPLES = [
    ("https://cdn.tse.jus.br/estatistica/sead/odsele/pda/tema_frequencia_atualizacao.zip",
     "especificacao oficial de frequencia de atualizacao dos arquivos do PDA"),
    ("https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/municipio_tse_ibge.zip",
     "lookup oficial de codigos UF/municipio TSE-IBGE (ano de referencia do recurso)"),
    ("https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip",
     "cadastro de candidaturas 2026 (versao publicada em 25/10/2026)"),
    ("https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_2026.zip",
     "detalhe de apuracao municipio/zona (checar turnos publicados e campos de horario)"),
    ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/correspefet/CEFT_1t_AC_051020261049.zip",
     "correspondencias efetivadas T1 (crosswalk de secoes) - amostra AC"),
    ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/correspesp/CESP_2t_AC_241020261231.zip",
     "correspondencias esperadas T2 (evidencia de publicacao do 2o turno) - amostra AC"),
    ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_1t_AC_051020261403.zip",
     "boletim de urna T1 - esquema BU e possiveis campos de horario - amostra AC"),
    ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_1t_AC_051020261403.zip.sha512",
     "hash oficial SHA-512 do ZIP de BU (verificacao de integridade pela fonte)"),
    ("https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_secao/perfil_eleitor_secao_2026_ZZ.zip",
     "perfil por secao do exterior (ZZ) - nao existe arquivo BR para este recurso"),
    ("https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_AC.zip",
     "votacao por secao T1 - esquema e turnos efetivos por UF - amostra AC"),
]

INVENTORY_FIELDS = [
    "kind", "source_id", "name", "location", "format", "bytes", "sha256",
    "remote_last_modified", "remote_status", "years", "turnos", "ufs", "cargo",
    "schema_note", "reuse_candidate", "checked_at", "notes",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def peak_rss_mb() -> float | None:
    """Pico de working set do processo (Windows). None se indisponível."""
    if os.name != "nt":
        return None
    try:
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        proc = ctypes.windll.kernel32.GetCurrentProcess()
        ok = 0
        for libname, fn in (("kernel32", "K32GetProcessMemoryInfo"),
                            ("psapi", "GetProcessMemoryInfo")):
            try:
                fnobj = getattr(ctypes.windll, libname)
                func = getattr(fnobj, fn)
                func.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
                func.restype = ctypes.c_int
                ok = func(proc, ctypes.byref(pmc), pmc.cb)
            except Exception:
                ok = 0
            if ok:
                break
        if not ok:
            return None
        return round(pmc.PeakWorkingSetSize / (1024 * 1024), 1)
    except Exception:
        return None


def http_request(url: str, method: str = "GET", timeout: int = 30,
                 headers: dict | None = None, retries: int = 3) -> tuple[int, dict, bytes]:
    """Requisição com timeout, retry limitado e status verificado."""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, method=method,
                                     headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read() if method == "GET" else b""
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body
        except urllib.error.HTTPError as exc:  # 4xx/5xx é resposta, não retry cego
            if exc.code in (404, 403) or attempt == retries:
                return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, b""
            last_err = exc
        except Exception as exc:  # timeout/DNS/reset: retry limitado
            last_err = exc
        time.sleep(min(2 * attempt, 6))
    raise RuntimeError(f"falha apos {retries} tentativas: {url} :: {last_err}")


def head(url: str, timeout: int = 20) -> dict:
    try:
        status, hdr, _ = http_request(url, method="HEAD", timeout=timeout, retries=2)
        return {"url": url, "status": status,
                "bytes": int(hdr["content-length"]) if hdr.get("content-length", "").isdigit() else None,
                "last_modified": hdr.get("last-modified"),
                "etag": hdr.get("etag"), "content_type": hdr.get("content-type"),
                "checked_at": now()}
    except Exception as exc:
        return {"url": url, "status": "ERR", "error": str(exc)[:160], "checked_at": now()}


def detect_delim(header_line: str) -> str:
    counts = {d: header_line.count(d) for d in (";", ",", "\t", "|")}
    return max(counts, key=counts.get) if max(counts.values()) else ";"


def first_line(fh, encodings=("utf-8-sig", "utf-8", "latin-1")) -> str | None:
    raw = fh.read(256 * 1024)
    for enc in encodings:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        return text.splitlines()[0] if text.splitlines() else None
    return None


def split_header(line: str) -> list[str]:
    line = line.lstrip("﻿")
    delim = detect_delim(line)
    parts = [p.strip().strip('"').strip() for p in line.split(delim)]
    return [p for p in parts if p]


def zip_entries(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        header, member = None, None
        for info in infos:
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            with zf.open(info) as fh:
                header = first_line(fh)
            member = info.filename
            break
        return {
            "n_entries": len(infos),
            "uncompressed_bytes": sum(i.file_size for i in infos),
            "compressed_bytes": sum(i.compress_size for i in infos),
            "entries": [{"name": i.filename, "bytes": i.file_size,
                         "compressed": i.compress_size} for i in infos[:60]],
            "csv_member": member,
            "header": split_header(header) if header else None,
        }


def csv_header(path: Path) -> list[str] | None:
    with path.open("rb") as fh:
        line = first_line(fh)
    if line is None:
        return None
    return split_header(line)


def duck_encoding(path: Path, sample: int = 256 * 1024) -> str:
    """TSE publica CSV em latin-1/CP1252; duckdb falha em modo estrito se assumirmos UTF-8."""
    with path.open("rb") as fh:
        chunk = fh.read(sample)
    try:
        chunk.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin1"


def duck_facts(csv_path: Path, max_bytes: int = 2_500_000_000) -> dict | None:
    """Fatos de conteúdo (linhas, UF, turno, cargo) — prova de cobertura real."""
    if csv_path.stat().st_size > max_bytes:
        return None
    try:
        import duckdb
    except ImportError:
        return None
    header = csv_header(csv_path)
    if not header:
        return None
    delim = detect_delim(";".join(header))
    enc = duck_encoding(csv_path)
    keys = [k for k in ("SG_UF", "NR_TURNO", "CD_CARGO", "DS_CARGO", "AA_ELEICAO",
                        "ANO_ELEICAO", "DS_ORIGEM_VOTO") if k in header]
    if not keys:
        return None
    con = duckdb.connect(database=":memory:")
    try:
        src = (f"read_csv('{csv_path.as_posix()}', delim='{delim}', header=true, "
               f"all_varchar=true, sample_size=-1, encoding='{enc}')")
        rows = con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]
        facts: dict = {"rows": rows, "columns_used": keys, "encoding": enc}
        for col in keys:
            vals = con.execute(
                f"SELECT {col}, COUNT(*) FROM {src} GROUP BY 1 ORDER BY 2 DESC LIMIT 40"
            ).fetchall()
            facts[col] = {("NULL" if v is None else v): int(c) for v, c in vals}
        return facts
    except Exception as exc:
        return {"error": str(exc)[:200]}
    finally:
        con.close()


# --------------------------------------------------------------------------- local
def cmd_local(args: argparse.Namespace) -> dict:
    source_root = Path(args.source_root)
    scan_root = source_root / "data"
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    scan: dict = {"source_root": str(source_root), "scanned_at": now(), "trees": {}, "files": []}

    files = sorted(p for p in scan_root.rglob("*") if p.is_file())
    # fatos de conteúdo calculados uma única vez por stem; o ZIP irmão herda o
    # mesmo dict (mesmo arquivo lógico, dois formatos), sem recontar.
    zip_stems = {p.stem for p in files if p.suffix.lower() == ".zip"}
    facts_by_stem: dict[str, dict] = {}
    if args.values:
        for p in files:
            if p.suffix.lower() != ".csv":
                continue
            if p.stem not in zip_stems and not re.search(
                    r"votacao_secao|detalhe_votacao|perfil_eleitor|eleitorado_local|consulta_cand",
                    p.name):
                continue
            t1 = time.perf_counter()
            f = duck_facts(p)
            if f:
                f["seconds"] = round(time.perf_counter() - t1, 1)
                facts_by_stem[p.stem] = f

    for path in files:
        rel = path.relative_to(source_root).as_posix()
        size = path.stat().st_size
        t0 = time.perf_counter()
        digest = sha256_file(path)
        digest_s = round(time.perf_counter() - t0, 2)
        entry: dict = {"path": rel, "bytes": size, "sha256": digest,
                       "hash_seconds": digest_s, "ext": path.suffix.lower()}
        header: list[str] | None = None
        facts = None
        if path.suffix.lower() == ".zip":
            try:
                entry["zip"] = zip_entries(path)
                header = entry["zip"]["header"]
            except Exception as exc:
                entry["zip_error"] = str(exc)[:160]
            # herda fatos de conteúdo do CSV extraído correspondente, quando existe
            facts = facts_by_stem.get(path.stem)
        elif path.suffix.lower() == ".csv":
            header = csv_header(path)
            facts = facts_by_stem.get(path.stem)
        elif path.suffix.lower() == ".parquet":
            try:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(path)
                entry["parquet"] = {"rows": pf.metadata.num_rows,
                                    "row_groups": pf.metadata.num_row_groups,
                                    "columns": [f.name for f in pf.schema_arrow]}
            except Exception as exc:
                entry["parquet_error"] = str(exc)[:160]
        if facts:
            entry["facts"] = facts
        if header:
            entry["header"] = header
        scan["files"].append(entry)

        tree = rel.split("/")[0]
        scan["trees"][tree] = scan["trees"].get(tree, {"files": 0, "bytes": 0})
        scan["trees"][tree]["files"] += 1
        scan["trees"][tree]["bytes"] += size

        reuse = "sim" if path.suffix.lower() in (".csv", ".zip", ".parquet") and tree == "data" else "nao"
        f = facts or {}
        rows.append({
            "kind": "local_file", "source_id": "", "name": path.name,
            "location": str(path), "format": path.suffix.lower().lstrip("."),
            "bytes": size, "sha256": digest, "remote_last_modified": "", "remote_status": "local",
            "years": (list(f.get("AA_ELEICAO") or f.get("ANO_ELEICAO") or {}) or [""])[0],
            "turnos": "|".join(f.get("NR_TURNO", {}) or []) or ("?" if "NR_TURNO" in str(header) else ""),
            "ufs": f"{len(f.get('SG_UF', {}))} valores" if f.get("SG_UF") else "",
            "cargo": "|".join((f.get("CD_CARGO", {}) or {}).keys()) or "",
            "schema_note": f"{len(header)} colunas" if header else "",
            "reuse_candidate": reuse, "checked_at": now(),
            "notes": ("zip: " + str(entry.get("zip", {}).get("n_entries", "?")) + " entradas, "
                      + str(entry.get("zip", {}).get("uncompressed_bytes", "?")) + " B expandidos")
                      if path.suffix.lower() == ".zip" else "",
        })

    with (SOURCES_DIR / "local_scan.json").open("w", encoding="utf-8") as fh:
        json.dump(scan, fh, ensure_ascii=False, indent=1)
    write_inventory_rows(rows, "local", SOURCES_DIR / "inventory.csv")
    return {"files": len(rows), "trees": scan["trees"],
            "out": [str(SOURCES_DIR / "local_scan.json"), str(SOURCES_DIR / "inventory.csv")]}


# --------------------------------------------------------------------------- remote
def cmd_remote(args: argparse.Namespace) -> dict:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    snapshot: dict = {"checked_at": now(), "ckan": {}, "heads": [], "notes": []}

    for pkg in CKAN_PACKAGES:
        try:
            status, _, body = http_request(f"{CKAN}package_show?id={pkg}", timeout=40)
            if status != 200:
                snapshot["ckan"][pkg] = {"error": f"HTTP {status}"}
                continue
            res = json.loads(body)["result"]
            snapshot["ckan"][pkg] = {
                "title": res.get("title"), "metadata_modified": res.get("metadata_modified"),
                "notes": (res.get("notes") or "").replace("\r", " ").replace("\n", " ")[:600],
                "n_resources": len(res.get("resources", [])),
                "resources": [{"name": r.get("name"), "format": r.get("format"), "url": r.get("url"),
                               "size": r.get("size"), "last_modified": r.get("last_modified"),
                               "created": r.get("created")} for r in res.get("resources", [])],
            }
        except Exception as exc:
            snapshot["ckan"][pkg] = {"error": str(exc)[:200]}

    # package_list pode ficar defasado em relação a package_show/search
    try:
        _, _, body = http_request(f"{CKAN}package_list", timeout=40)
        names = json.loads(body)["result"]
        snapshot["package_list_count"] = len(names)
        snapshot["package_list_2026"] = [n for n in names if "2026" in n]
        listed = set(names)
        snapshot["packages_visible_por_search_mas_ausentes_no_list"] = sorted(
            p for p in CKAN_PACKAGES if p not in listed)
    except Exception as exc:
        snapshot["package_list_error"] = str(exc)[:200]

    # HEAD em todos os recursos dos pacotes de resultados (matriz de disponibilidade)
    urls: list[str] = []
    for pkg, data in snapshot["ckan"].items():
        if pkg.startswith("resultados-2026") or pkg in (
                "eleitorado-2026", "comparecimento-e-abstencao-2026",
                "candidatos-2026", "frequencia-de-atualizacao-dos-arquivos",
                "codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge"):
            for r in data.get("resources", []):
                u = r.get("url")
                if u and u not in urls:
                    urls.append(u)
    # Amostras de conferência de padrões que o CKAN não lista (segundo turno)
    urls += [
        "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_2t_AC_261020260000.zip",
        "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/correspefet/CEFT_2t_AC_261020260000.zip",
        "https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_secao/perfil_eleitor_secao_2026_BR.zip",
    ]
    # Portal Resultados (handoff 22; nacional no handoff 26): JSON consolidado de presidente por
    # UF, exterior (zz) e Brasil (br), nos dois turnos (eleição 6257 = T1, 6258 = T2).
    # Referência independente dos CSVs de votação.
    ufs_portal = ("ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt",
                  "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp",
                  "to", "zz", "br")
    urls += [
        f"https://resultados.tse.jus.br/oficial/ele2026/{cd}/dados/{uf}/{uf}-c0001-e00{cd}-u.json"
        for cd in ("6257", "6258") for uf in ufs_portal
    ]

    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(lambda u: head(u), urls):
            snapshot["heads"].append(res)
    snapshot["head_seconds"] = round(time.perf_counter() - t0, 1)
    snapshot["head_targets"] = len(urls)
    snapshot["head_200"] = sum(1 for h in snapshot["heads"] if h["status"] == 200)
    snapshot["head_404"] = sum(1 for h in snapshot["heads"] if h["status"] == 404)
    snapshot["head_err"] = sum(1 for h in snapshot["heads"] if h["status"] == "ERR")

    with (SOURCES_DIR / "remote_snapshot.json").open("w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)

    rows = build_remote_rows(snapshot)
    write_inventory_rows(rows, "remote", SOURCES_DIR / "inventory.csv")
    return {"ckan_packages": len(snapshot["ckan"]), "heads": len(snapshot["heads"]),
            "http200": snapshot["head_200"], "http404": snapshot["head_404"],
            "head_seconds": snapshot["head_seconds"],
            "out": str(SOURCES_DIR / "remote_snapshot.json")}


def turno_from(text: str) -> str:
    low = text.lower()
    if "2t_" in low or "2-turno" in low or "2º turno" in low or "2o turno" in low:
        return "2"
    if "1t_" in low or "1-turno" in low or "1º turno" in low or "1o turno" in low:
        return "1"
    return "?"


def build_remote_rows(snapshot: dict) -> list[dict]:
    rows: list[dict] = []
    heads = {h["url"]: h for h in snapshot["heads"]}
    for pkg, data in snapshot["ckan"].items():
        for r in data.get("resources", []):
            url = r.get("url") or ""
            h = heads.get(url, {})
            fn = url.rsplit("/", 1)[-1]
            uf = ""
            m = re.search(r"_([A-Z]{2})\.(zip|csv)$", fn) or re.search(r"_([A-Z]{2})_", fn)
            if m:
                uf = m.group(1)
            rows.append({
                "kind": "remote_source", "source_id": pkg, "name": r.get("name") or fn,
                "location": url, "format": (r.get("format") or "").lower(),
                "bytes": h.get("bytes") if h.get("bytes") is not None else (r.get("size") or ""),
                "sha256": "", "remote_last_modified": h.get("last_modified") or r.get("last_modified") or "",
                "remote_status": str(h.get("status", "")),
                "years": "2026" if "2026" in pkg or "2026" in fn else "",
                "turnos": turno_from((r.get("name") or "") + " " + fn),
                "ufs": uf, "cargo": "", "schema_note": "",
                "reuse_candidate": "sim" if h.get("status") == 200 else "nao",
                "checked_at": h.get("checked_at") or snapshot["checked_at"],
                "notes": data.get("title") or "",
            })
    return rows


def write_inventory_rows(rows: list[dict], kind: str, path: Path) -> None:
    """Acumula em inventory.csv sem misturar linhas local/remote de execuções separadas."""
    prefix = "local" if kind == "local" else "remote"
    existing: list[dict] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            existing = [r for r in csv.DictReader(fh)
                        if not str(r.get("kind", "")).startswith(prefix)]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INVENTORY_FIELDS)
        w.writeheader()
        for r in existing + rows:
            w.writerow({k: r.get(k, "") for k in INVENTORY_FIELDS})


# --------------------------------------------------------------------------- samples
def _sample_one(url: str, dest_dir: Path, head_out: Path) -> dict:
    """Executa em subprocesso isolado: pico de RAM por amostra é confiável."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    head_out.parent.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[-1]
    dest = dest_dir / name
    tmp = dest.with_suffix(dest.suffix + ".part")
    out: dict = {"url": url, "name": name, "started_at": now()}

    t0 = time.perf_counter()
    status, hdr, _ = http_request(url, method="HEAD", timeout=30, retries=2)
    out["head_status"] = status
    out["head_bytes"] = hdr.get("content-length")
    out["head_last_modified"] = hdr.get("last-modified")

    t1 = time.perf_counter()
    for attempt in range(1, 4):
        try:
            status, hdr, body = http_request(url, timeout=120, retries=1)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            expect = hdr.get("content-length")
            if expect and int(expect) != len(body):
                raise RuntimeError(f"conteudo incompleto: {len(body)} de {expect}")
            tmp.write_bytes(body)
            os.replace(tmp, dest)  # promoção atômica só após integridade básica
            break
        except Exception as exc:
            out[f"attempt_{attempt}_error"] = str(exc)[:160]
            if attempt == 3:
                raise
            time.sleep(3 * attempt)
    out["download_seconds"] = round(time.perf_counter() - t1, 2)
    out["bytes"] = dest.stat().st_size
    out["throughput_kbps"] = round(out["bytes"] / 1024 / max(out["download_seconds"], 0.001))
    t2 = time.perf_counter()
    out["sha256"] = sha256_file(dest)
    out["hash_seconds"] = round(time.perf_counter() - t2, 2)

    if dest.suffix.lower() == ".zip":
        t3 = time.perf_counter()
        try:
            info = zip_entries(dest)
            out.update({"entries": info["n_entries"],
                        "uncompressed_bytes": info["uncompressed_bytes"],
                        "csv_member": info["csv_member"]})
            out["zip_read_seconds"] = round(time.perf_counter() - t3, 2)
            # descompactação em fluxo do maior membro CSV: tamanho/tempo/RAM expandidos
            with zipfile.ZipFile(dest) as zf:
                csvs = [i for i in zf.infolist()
                        if not i.is_dir() and i.filename.lower().endswith(".csv")]
                if csvs:
                    big = max(csvs, key=lambda i: i.file_size)
                    t4 = time.perf_counter()
                    n = 0
                    with zf.open(big) as member:
                        while True:
                            chunk = member.read(4 * 1024 * 1024)
                            if not chunk:
                                break
                            n += len(chunk)
                    out["stream_member"] = big.filename
                    out["stream_uncompressed_bytes"] = n
                    out["stream_seconds"] = round(time.perf_counter() - t4, 2)
                    out["stream_mbps"] = round(
                        n / 1024 / 1024 / max(out["stream_seconds"], 0.001), 1)
            # excerto de cabeçalho com proveniência (primeiras 6 linhas de cada CSV)
            with zipfile.ZipFile(dest) as zf, head_out.open("w", encoding="utf-8") as fh:
                fh.write(f"# fonte: {url}\n# obtido_em: {out['started_at']}\n"
                         f"# sha256_zip: {out['sha256']}\n# bytes_zip: {out['bytes']}\n")
                for info_i in zf.infolist():
                    if info_i.is_dir() or not info_i.filename.lower().endswith((".csv", ".txt")):
                        continue
                    fh.write(f"# membro: {info_i.filename} ({info_i.file_size} B)\n")
                    with zf.open(info_i) as member:
                        for i, line in enumerate(member):
                            if i >= 6:
                                break
                            fh.write(line.decode("utf-8", "replace"))
            out["excerpt"] = str(head_out)
        except Exception as exc:
            out["zip_error"] = str(exc)[:200]
    else:
        head_out.write_text(f"# fonte: {url}\n# obtido_em: {out['started_at']}\n"
                            f"# sha256: {out['sha256']}\n# bytes: {out['bytes']}\n"
                            + dest.read_bytes()[:4000].decode("utf-8", "replace"),
                            encoding="utf-8")
        out["excerpt"] = str(head_out)

    out["peak_rss_mb"] = peak_rss_mb()
    out["total_seconds"] = round(time.perf_counter() - t0, 2)
    return out


def cmd_samples(args: argparse.Namespace) -> dict:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    RAW_SAMPLES.mkdir(parents=True, exist_ok=True)
    prov_path = SAMPLES_DIR / "PROVENANCE.csv"
    records: list[dict] = []
    sample_filter = getattr(args, "sample_filter", "") or ""
    for url, purpose in SAMPLES:
        if sample_filter and sample_filter not in url:
            continue
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "_sample_one", url,
             str(RAW_SAMPLES), str(SAMPLES_DIR / (url.rsplit("/", 1)[-1] + ".head.txt"))],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            records.append({"url": url, "name": url.rsplit("/", 1)[-1], "purpose": purpose,
                            "error": (proc.stderr or proc.stdout)[-300:], "checked_at": now()})
            continue
        rec = json.loads(proc.stdout.strip().splitlines()[-1])
        rec["purpose"] = purpose
        records.append(rec)

    fields = ["name", "url", "purpose", "head_status", "head_bytes", "head_last_modified",
              "bytes", "sha256", "download_seconds", "throughput_kbps", "hash_seconds",
              "entries", "uncompressed_bytes", "zip_read_seconds", "stream_member",
              "stream_uncompressed_bytes", "stream_seconds", "stream_mbps", "peak_rss_mb",
              "total_seconds", "excerpt", "started_at", "error",
              "attempt_1_error", "attempt_2_error", "attempt_3_error"]
    existing: list[dict] = []
    if prov_path.exists():
        with prov_path.open(encoding="utf-8", newline="") as fh:
            old = {r.get("url"): r for r in csv.DictReader(fh)}
        old.update({r["url"]: r for r in records})
        existing = list(old.values())
    else:
        existing = records
    with prov_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in existing:
            w.writerow({k: r.get(k, "") for k in fields})
    ok = [r for r in records if not r.get("error")]
    return {"downloaded": len(ok), "failed": len(records) - len(ok),
            "bytes": sum(int(r.get("bytes") or 0) for r in ok),
            "out": str(prov_path)}


# --------------------------------------------------------------------------- questions
def zip_dir_by_range(url: str, timeout: int = 60) -> list[dict]:
    """Lista o diretório central de um ZIP remoto via HTTP Range (sem baixar tudo)."""
    status, hdr, _ = http_request(url, method="HEAD", timeout=timeout, retries=2)
    total = int(hdr["content-length"])
    tail_start = max(0, total - 70000)
    _, _, tail = http_request(url, headers={"Range": f"bytes={tail_start}-{total - 1}"}, timeout=timeout)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise RuntimeError("EOCD nao encontrado no fim do arquivo")
    import struct
    n_entries, cd_size, cd_off = struct.unpack("<HII", tail[eocd + 10:eocd + 20])
    _, _, cd = http_request(url, headers={"Range": f"bytes={cd_off}-{cd_off + cd_size - 1}"},
                            timeout=timeout)
    entries, pos = [], 0
    while pos + 46 <= len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
        csize, usize = struct.unpack("<II", cd[pos + 20:pos + 28])
        nlen, xlen, clen = struct.unpack("<HHH", cd[pos + 28:pos + 34])
        lho = struct.unpack("<I", cd[pos + 42:pos + 46])[0]
        name = cd[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
        entries.append({"name": name, "compressed": csize, "bytes": usize, "local_offset": lho})
        pos += 46 + nlen + xlen + clen
    if len(entries) != n_entries:
        raise RuntimeError(f"dir central incompleto: {len(entries)} de {n_entries}")
    return entries


def zip_member_by_range(url: str, entry: dict, timeout: int = 60) -> bytes:
    import struct
    off = entry["local_offset"]
    _, _, hdrb = http_request(url, headers={"Range": f"bytes={off}-{off + 29}"}, timeout=timeout)
    if hdrb[:4] != b"PK\x03\x04":
        raise RuntimeError("cabecalho local invalido")
    nlen, xlen = struct.unpack("<HH", hdrb[26:30])
    data_start = off + 30 + nlen + xlen
    data_end = data_start + entry["compressed"] - 1
    _, _, data = http_request(url, headers={"Range": f"bytes={data_start}-{data_end}"}, timeout=timeout)
    method = struct.unpack("<H", hdrb[8:10])[0]
    if method == 8:
        return zlib.decompress(data, -15)
    if method == 0:
        return data
    raise RuntimeError(f"metodo de compressao nao suportado: {method}")


def cmd_questions(args: argparse.Namespace) -> dict:
    """Responde Q1–Q6 de B com evidência determinística (só agregados/contagens)."""
    source_root = Path(args.source_root)
    raw = source_root / "data" / "01_raw"
    ev: dict = {"answered_at": now(), "source_root": str(source_root), "q": {}}

    # Q6 — data de geração efetiva do perfil por seção 2026
    ev["q"]["Q6"] = {}
    for name in ("perfil_eleitor_secao_2026_RS.csv", "perfil_eleitor_secao_2022_RS.csv"):
        p = raw / name
        if not p.exists():
            ev["q"]["Q6"][name] = {"ausente": True}
            continue
        try:
            import duckdb
            con = duckdb.connect()
            src = (f"read_csv('{p.as_posix()}', delim=';', header=true, "
                   f"all_varchar=true, sample_size=-1, encoding='{duck_encoding(p)}')")
            cols = [r[0] for r in con.execute(f"SELECT * FROM {src} LIMIT 0").description]
            gen = [c for c in cols if c in ("DT_GERACAO", "HH_GERACAO", "AA_ELEICAO", "ANO_ELEICAO")]
            ev["q"]["Q6"][name] = {
                "linhas": con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0],
                "datas_geracao": [list(r) for r in con.execute(
                    f"SELECT DT_GERACAO, COUNT(*) FROM {src} GROUP BY 1 ORDER BY 2 DESC LIMIT 5").fetchall()],
                "horas_geracao_min_max": [list(r) for r in con.execute(
                    f"SELECT MIN(HH_GERACAO), MAX(HH_GERACAO) FROM {src}").fetchall()],
                "ano_de_referencia": [list(r) for r in con.execute(
                    f"SELECT {next(c for c in ('AA_ELEICAO', 'ANO_ELEICAO') if c in cols)}, COUNT(*) "
                    f"FROM {src} GROUP BY 1").fetchall()]
                if any(c in cols for c in ("AA_ELEICAO", "ANO_ELEICAO")) else [],
                "colunas_de_tempo": gen,
            }
            con.close()
        except Exception as exc:
            ev["q"]["Q6"][name] = {"erro": str(exc)[:1500]}

    # Q2/Q3/Q5 — contagens no detalhe de apuração (presidente, T1 nacional)
    det = raw / "detalhe_votacao_secao_2026_BR.csv"
    if det.exists():
        try:
            import duckdb
            con = duckdb.connect()
            src = (f"read_csv('{det.as_posix()}', delim=';', header=true, "
                   f"all_varchar=true, sample_size=-1, encoding='{duck_encoding(det)}')")
            q = lambda sql: [list(r) for r in con.execute(sql).fetchall()]
            ev["q"]["Q2"] = {
                "arquivo": det.name,
                "soma_nacional_QT_VOTOS_ANULADOS_APU_SEP": q(
                    f"SELECT SUM(CAST(NULLIF(QT_VOTOS_ANULADOS_APU_SEP,'') AS BIGINT)) FROM {src}")[0][0],
                "linhas_com_anulados_maior_zero": q(
                    f"SELECT COUNT(*) FROM {src} WHERE TRY_CAST(QT_VOTOS_ANULADOS_APU_SEP AS BIGINT) > 0")[0][0],
                "linhas_por_origem": q(
                    f"SELECT COALESCE(DS_ORIGEM_VOTO,'(nulo)'), COUNT(*) FROM {src} GROUP BY 1 ORDER BY 2 DESC"),
            }
            ev["q"]["Q3"] = {
                "definicao": "linhas do detalhe (presidente, T1) em que "
                             "QT_APTOS <> QT_COMPARECIMENTO + QT_ABSTENCOES",
                "linhas_sem_QT_APTOS": q(
                    f"SELECT COUNT(*) FROM {src} WHERE QT_APTOS IS NULL OR TRIM(QT_APTOS)=''")[0][0],
                "falhas_por_origem_e_instalacao": q(
                    f"SELECT COALESCE(DS_ORIGEM_VOTO,'(nulo)'), COALESCE(ST_SECAO_INSTALADA,'(nulo)'), "
                    f"COUNT(*), SUM(TRY_CAST(QT_APTOS AS BIGINT)), "
                    f"SUM(TRY_CAST(QT_COMPARECIMENTO AS BIGINT)), SUM(TRY_CAST(QT_ABSTENCOES AS BIGINT)) "
                    f"FROM {src} WHERE TRY_CAST(QT_APTOS AS BIGINT) IS DISTINCT FROM "
                    f"TRY_CAST(QT_COMPARECIMENTO AS BIGINT) + TRY_CAST(QT_ABSTENCOES AS BIGINT) "
                    f"GROUP BY 1,2 ORDER BY 3 DESC"),
                "st_secao_anulada_nas_falhas": q(
                    f"SELECT COALESCE(ST_SECAO_ANULADA,'(nulo)'), COUNT(*) FROM {src} "
                    f"WHERE TRY_CAST(QT_APTOS AS BIGINT) IS DISTINCT FROM "
                    f"TRY_CAST(QT_COMPARECIMENTO AS BIGINT) + TRY_CAST(QT_ABSTENCOES AS BIGINT) "
                    f"GROUP BY 1 ORDER BY 2 DESC"),
            }
            ev["q"]["Q5"] = {
                "por_origem_voto": q(
                    f"SELECT COALESCE(DS_ORIGEM_VOTO,'(nulo)'), COUNT(*) FROM {src} GROUP BY 1 ORDER BY 2 DESC"),
                "secoes_com_mais_de_uma_linha_de_origem": q(
                    f"SELECT COUNT(*) FROM (SELECT SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO FROM {src} "
                    f"GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT DS_ORIGEM_VOTO) > 1)"),
            }
            con.close()
        except Exception as exc:
            ev["q"]["Q2/Q3/Q5"] = {"erro": str(exc)[:1500]}

    # Q1 — campos de encerramento: detalhe local + BU baixada + diretorio remoto do log
    det_head = csv_header(det) if det.exists() else None
    q1: dict = {"campos_tempo_no_detalhe": [c for c in (det_head or [])
                                            if "HOR" in c or "DT_" in c]}

    bu = RAW_SAMPLES / "bweb_1t_AC_051020261403.zip"
    if bu.exists():
        try:
            info = zip_entries(bu)
            q1["bweb_membro"] = info["csv_member"]
            q1["bweb_colunas"] = info["header"]
            q1["bweb_entradas"] = [e["name"] for e in info["entries"]]
            # extrai o CSV da BU e mede só agregados: granularidade e formato dos horários
            import duckdb
            with zipfile.ZipFile(bu) as zf:
                target = RAW_SAMPLES / "_extracted" / Path(info["csv_member"]).name
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info["csv_member"]) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 4 * 1024 * 1024)
            con = duckdb.connect()
            s = (f"read_csv('{target.as_posix()}', delim=';', header=true, "
                 f"all_varchar=true, sample_size=-1, encoding='{duck_encoding(target)}')")
            f0 = lambda sql: [list(r) for r in con.execute(sql).fetchall()]
            q1["bweb_fatos"] = {
                "linhas": f0(f"SELECT COUNT(*) FROM {s}")[0][0],
                "por_turno": f0(f"SELECT NR_TURNO, COUNT(*) FROM {s} GROUP BY 1"),
                "secoes_distintas": f0(
                    f"SELECT COUNT(*) FROM (SELECT DISTINCT SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO FROM {s})")[0][0],
                "registros_de_tempo_por_secao": {
                    "max_registros_DT_ENCERRAMENTO_por_secao": f0(
                        f"SELECT MAX(c) FROM (SELECT COUNT(*) c FROM {s} "
                        f"GROUP BY SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO, DT_ENCERRAMENTO)")[0][0],
                    "secoes_com_mais_de_um_encerramento": f0(
                        f"SELECT COUNT(*) FROM (SELECT SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO FROM {s} "
                        f"WHERE DT_ENCERRAMENTO IS NOT NULL AND TRIM(DT_ENCERRAMENTO)<>'' "
                        f"GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT DT_ENCERRAMENTO) > 1)")[0][0],
                    "secoes_sem_encerramento": f0(
                        f"SELECT COUNT(*) FROM (SELECT SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO FROM {s} "
                        f"GROUP BY 1,2,3,4 HAVING COUNT(*) FILTER (WHERE DT_ENCERRAMENTO IS NOT NULL "
                        f"AND TRIM(DT_ENCERRAMENTO)<>'') = 0)")[0][0],
                },
                "valores": {
                    col: {
                        "distintos": f0(f"SELECT COUNT(DISTINCT {col}) FROM {s}")[0][0],
                        "nulos_ou_vazios": f0(
                            f"SELECT COUNT(*) FROM {s} WHERE {col} IS NULL OR TRIM({col})=''")[0][0],
                        "min": f0(f"SELECT MIN({col}) FROM {s}")[0][0],
                        "max": f0(f"SELECT MAX({col}) FROM {s}")[0][0],
                        "exemplos": [r[0] for r in f0(
                            f"SELECT DISTINCT {col} FROM {s} WHERE {col} IS NOT NULL "
                            f"AND TRIM({col})<>'' ORDER BY 1 LIMIT 4")],
                    } for col in ("DT_ABERTURA", "DT_ENCERRAMENTO", "DT_EMISSAO_BU",
                                  "DT_BU_RECEBIDO", "DT_GERACAO", "HH_GERACAO")
                    if col in (info["header"] or [])
                },
                # distribuição factual (sem interpretação) para B estudar 17h/19h
                "encerramento_por_hora_local_do_arquivo": f0(
                    f"SELECT SUBSTRING(DT_ENCERRAMENTO, 12, 2) AS hora, "
                    f"COUNT(DISTINCT SG_UF || '/' || CD_MUNICIPIO || '/' || NR_ZONA || '/' || NR_SECAO) "
                    f"FROM {s} GROUP BY 1 ORDER BY 1"),
                "urnas_e_secoes_agregadas": {
                    "urnas_distintas": f0(
                        f"SELECT COUNT(DISTINCT NR_URNA_EFETIVADA) FROM {s}")[0][0],
                    "secoes_com_agregacao_declarada": f0(
                        f"SELECT COUNT(*) FROM (SELECT SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO FROM {s} "
                        f"WHERE DS_SECOES_AGREGADAS IS NOT NULL AND TRIM(DS_SECOES_AGREGADAS)<>'' "
                        f"AND DS_SECOES_AGREGADAS <> '#NULO#' GROUP BY 1,2,3,4)")[0][0],
                },
            }
            con.close()
            q1["bweb_arquivo_extraido"] = str(target)
        except Exception as exc:
            q1["bweb_erro"] = str(exc)[:600]

    arq = ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/"
           "bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip")
    try:
        t0 = time.perf_counter()
        entries = zip_dir_by_range(arq)
        interesting = [e for e in entries if re.search(r"log|rdv|encerr|hora|txt|json", e["name"], re.I)]
        q1["arqurnatot"] = {
            "url": arq, "metodo": "HTTP Range (diretorio central, sem download completo)",
            "entradas": len(entries), "segundos": round(time.perf_counter() - t0, 1),
            "por_extensao": {},
            "documentos": [e["name"] for e in entries
                           if e["name"].lower().endswith((".pdf", ".txt", ".doc", ".docx"))][:10],
            "exemplos": [e["name"] for e in interesting[:25]],
        }
        by_ext: dict = {}
        for e in entries:
            ext = Path(e["name"]).suffix.lower() or "(sem)"
            d = by_ext.setdefault(ext, {"n": 0, "bytes_min": None, "bytes_max": 0})
            d["n"] += 1
            d["bytes_min"] = e["bytes"] if d["bytes_min"] is None else min(d["bytes_min"], e["bytes"])
            d["bytes_max"] = max(d["bytes_max"], e["bytes"])
        q1["arqurnatot"]["por_extensao"] = dict(
            sorted(by_ext.items(), key=lambda kv: -kv[1]["n"])[:12])
        # extrai entradas representativas (RDV .dat e log .jez) e procura campos de tempo
        cand = [e for e in entries if e["bytes"] < 400_000
                and e["name"].lower().endswith((".txt", ".log", ".csv", ".json",
                                                ".xml", ".dat", ".jez"))]
        small = []
        for ext in (".dat", ".jez", ".txt", ".csv", ".json", ".xml", ".log"):
            small += sorted([e for e in cand if e["name"].lower().endswith(ext)],
                            key=lambda e: e["bytes"])[:2]
        time_re = re.compile(rb"\d{2}:\d{2}:\d{2}|\d{2}/\d{2}/\d{4}|encerr|abertur|emissao|"
                             rb"receb|fuso|utc|brt|horario|hora\b", re.I)
        excerpts = []
        for e in small:
            data = zip_member_by_range(arq, e)
            strings = re.findall(rb"[\x20-\x7e]{5,}", data)[:400]
            hits = [s.decode("latin-1") for s in strings if time_re.search(s)][:10]
            text = data.decode("utf-8", "replace")
            line_hits = [ln for ln in text.splitlines() if re.search(
                r"encerr|fechamento|hora|horário|horario|fuso|utc|\d{2}:\d{2}:\d{2}", ln, re.I)][:8]
            SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
            out = SAMPLES_DIR / (Path(e["name"]).name + ".range_excerpt.txt")
            out.write_text(f"# fonte: {arq}\n# membro: {e['name']} ({e['bytes']} B) via HTTP Range\n"
                           f"# obtido_em: {now()}\n"
                           f"# strings_ascii_com_indicio_de_tempo: {len(hits)}\n"
                           + b"\n".join(strings[:80]).decode("latin-1") + "\n",
                           encoding="utf-8")
            excerpts.append({"membro": e["name"], "bytes": e["bytes"],
                             "formato": "provavelmente binario (RDV) " if not line_hits else "texto",
                             "strings_com_indicio_de_tempo": hits[:6],
                             "linhas_com_indicio_de_tempo": line_hits[:6],
                             "arquivo": str(out)})
        q1["arqurnatot"]["amostras_extraidas"] = excerpts
        # documento oficial do pacote (leiame) extraído via Range, para leitura de dicionário
        try:
            pdfs = [e for e in entries if e["name"].lower().endswith(".pdf")]
            if pdfs:
                pdf_entry = pdfs[0]
                data = zip_member_by_range(arq, pdf_entry)
                target_pdf = RAW_SAMPLES / "_extracted" / Path(pdf_entry["name"]).name
                target_pdf.parent.mkdir(parents=True, exist_ok=True)
                target_pdf.write_bytes(data)
                q1["arqurnatot"]["leiame"] = {"membro": pdf_entry["name"],
                                              "bytes": len(data),
                                              "arquivo": str(target_pdf)}
        except Exception as exc:
            q1["arqurnatot"]["leiame_erro"] = str(exc)[:300]
    except Exception as exc:
        q1["arqurnatot"] = {"url": arq, "erro": str(exc)[:300]}
    ev["q"]["Q1"] = q1

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SOURCES_DIR / "questions_A_evidence.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    return {"out": str(out_path), "perguntas": sorted(ev["q"])}


# --------------------------------------------------------------------------- summary
FAMILY_BY_DIR = {
    "votacao_secao": "votacao_secao", "detalhe_votacao_secao": "detalhe_votacao_secao",
    "detalhe_votacao_munzona": "detalhe_votacao_munzona",
    "votacao_candidato_munzona": "votacao_candidato_munzona",
    "votacao_partido_munzona": "votacao_partido_munzona",
    "buweb": "bweb_bu", "correspesp": "corresp_esperadas", "correspefet": "corresp_efetivadas",
    "arqurnatot": "arquivos_transmitidos", "logsgedai": "logs_gedai",
    "perfil_eleitor_secao": "perfil_secao", "perfil_eleitorado": "perfil_geral",
    "eleitorado_locais_votacao": "eleitorado_local_votacao",
    "perfil_comparecimento_abstencao": "comparecimento_abstencao",
    "consulta_cand": "cadastro_candidatos", "municipio_tse_ibge": "lookup_municipios",
    "pda": "doc_frequencia_pda",
    "relatorio_resultado_totalizacao": "relatorio_totalizacao",
    "perfil_eleitor_deficiente": "perfil_deficiencia", "perfil_eleitor_tte": "transferencia_temporaria",
    "historico_candidatura": "historico_candidatura", "consulta_cand_complementar": "cand_complementar",
    "bem_candidato": "bens_candidatos", "consulta_coligacao": "coligacoes",
    "consulta_vagas": "vagas", "motivo_cassacao": "motivo_cassacao",
    "fotos": "fotos_candidatos", "proposta_governo": "propostas", "certidao_criminal": "certidoes",
}
CORE_FAMILIES = {
    "votacao_secao", "detalhe_votacao_secao", "detalhe_votacao_munzona",
    "votacao_candidato_munzona", "votacao_partido_munzona", "bweb_bu",
    "corresp_esperadas", "corresp_efetivadas", "perfil_secao",
    "eleitorado_local_votacao", "comparecimento_abstencao", "cadastro_candidatos",
    "lookup_municipios", "doc_frequencia_pda",
}
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
       "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]


def cmd_summary(args: argparse.Namespace) -> dict:
    snap = json.loads((SOURCES_DIR / "remote_snapshot.json").read_text(encoding="utf-8"))
    local = json.loads((SOURCES_DIR / "local_scan.json").read_text(encoding="utf-8"))
    fams: dict = {}
    for h in snap["heads"]:
        url = h["url"]
        parts = url.rstrip("/").split("/")
        folder, fname = parts[-2], parts[-1]
        fam = FAMILY_BY_DIR.get(folder, folder)
        d = fams.setdefault(fam, {"arquivos": 0, "bytes": 0, "status": {}, "turnos": {},
                                  "ufs_presentes": set(), "ufs_ausentes": set(),
                                  "last_modified_min": None, "last_modified_max": None,
                                  "exemplos_404": []})
        d["arquivos"] += 1
        st = str(h.get("status"))
        d["status"][st] = d["status"].get(st, 0) + 1
        if st == "200":
            d["bytes"] += int(h.get("bytes") or 0)
        elif len(d["exemplos_404"]) < 5:
            d["exemplos_404"].append(url)
        t = turno_from(fname + " " + url)
        d["turnos"][t] = d["turnos"].get(t, 0) + 1
        m = re.search(r"_([A-Z]{2})\.(zip|csv|sha512)$", fname) or re.search(r"_([A-Z]{2})_", fname)
        uf = m.group(1) if m else ("BR" if "_BR." in fname or fname.endswith("_BR.zip") else "")
        if uf in UFS and st == "200":
            d["ufs_presentes"].add(uf)
        lm = h.get("last_modified")
        if lm:
            d["last_modified_min"] = lm if not d["last_modified_min"] else min(d["last_modified_min"], lm)
            d["last_modified_max"] = lm if not d["last_modified_max"] else max(d["last_modified_max"], lm)
    for fam, d in fams.items():
        d["ufs_presentes"] = sorted(d["ufs_presentes"])
        d["ufs_ausentes"] = sorted(set(UFS) - set(d["ufs_presentes"]))
        d["cobertura_uf"] = f"{len(d['ufs_presentes'])}/{len(UFS)}"

    core = {f: d for f, d in fams.items() if f in CORE_FAMILIES}
    # comparação de versões: arquivo local x HEAD remoto (mesmo nome de arquivo)
    local_by_name = {Path(e["path"]).name: e for e in local["files"]}
    version_check = []
    for h in snap["heads"]:
        fname = h["url"].rstrip("/").split("/")[-1]
        e = local_by_name.get(fname)
        if e and h.get("status") == 200 and h.get("bytes"):
            version_check.append({"arquivo": fname, "local_bytes": e["bytes"],
                                  "remoto_bytes": h["bytes"],
                                  "identico_por_tamanho": e["bytes"] == h["bytes"],
                                  "remoto_lm": h.get("last_modified")})
    summary = {
        "gerado_em": now(),
        "fonte_snapshot": str(SOURCES_DIR / "remote_snapshot.json"),
        "familias": fams,
        "armazenamento": {
            "core_bytes": sum(d["bytes"] for d in core.values()),
            "core_familias": sorted(core),
            "total_medido_bytes": sum(d["bytes"] for d in fams.values()),
            "premissas": ("soma dos content-length respondidos por HEAD em "
                          + str(len(snap["heads"])) + " URLs; exclui famílias não listadas no "
                          "CKAN e não mede ZIPs gerados por reprocessamento oficial"),
        },
        "versoes_local_x_remoto": version_check,
        "ausencias_http_404": [h["url"] for h in snap["heads"] if h.get("status") == 404],
        "erros_de_rede": [h["url"] for h in snap["heads"] if h.get("status") == "ERR"],
    }
    out_path = SOURCES_DIR / "summary.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1, default=list)
    return {"out": str(out_path),
            "core_bytes": summary["armazenamento"]["core_bytes"],
            "familias": len(fams)}


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_local = sub.add_parser("local")
    p_local.add_argument("--values", action="store_true",
                         help="calcula UF/turno/cargo distintos via DuckDB (mais lento)")
    sub.add_parser("remote")
    p_samp = sub.add_parser("samples")
    p_samp.add_argument("--sample-filter", default="")
    sub.add_parser("questions")
    sub.add_parser("summary")
    sub.add_parser("all")
    p_one = sub.add_parser("_sample_one")
    p_one.add_argument("url"); p_one.add_argument("dest"); p_one.add_argument("head_out")
    args = ap.parse_args(argv)

    if args.cmd == "_sample_one":
        rec = _sample_one(args.url, Path(args.dest), Path(args.head_out))
        print(json.dumps(rec, ensure_ascii=False))
        return 0

    t0 = time.perf_counter()
    result: dict = {}
    if args.cmd in ("local", "all"):
        a = argparse.Namespace(source_root=args.source_root, values=True)
        result["local"] = cmd_local(a)
    if args.cmd in ("remote", "all"):
        result["remote"] = cmd_remote(args)
    if args.cmd in ("samples", "all"):
        result["samples"] = cmd_samples(args)
    if args.cmd in ("questions", "all"):
        result["questions"] = cmd_questions(args)
    if args.cmd in ("summary", "all"):
        result["summary"] = cmd_summary(args)
    result["elapsed_seconds"] = round(time.perf_counter() - t0, 1)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
