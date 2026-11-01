"""Ingestão e harmonização dos dados da RAIS (MTE) — Frente B (Handoff 35).

Fonte oficial: Ministério do Trabalho e Emprego (MTE) / PDET
Microdados de Estabelecimentos (RAIS Estabelecimentos 2023)
Servidor FTP oficial: ftp://ftp.mtps.gov.br/pdet/microdados/RAIS/2023/RAIS_ESTAB_PUB.7z

Variáveis extraídas:
- vinculos_formais_total: Estoque de vínculos ativos em 31/12/2023 no município do estabelecimento.
- vinculos_formais_por_mil_hab: Razão administrativa de vínculos formais ativos por 1.000 habitantes
  residentes no Censo 2022 (IBGE).
- vinculos_clt_total: Estoque de vínculos ativos regidos pela CLT em 31/12/2023.
- vinculos_estatutarios_total: Estoque de vínculos ativos regidos por estatuto público em 31/12/2023.

Regras metodológicas (Plano 33 / Handoff 35):
1. Vínculos não são trabalhadores únicos e emprego no estabelecimento não mede emprego dos residentes.
2. Desocupação não é derivada desta fonte (vem da frente A / Censo 2022).
3. Formato longo comum unificado: (sg_uf, cd_municipio_ibge, indicador, periodo_referencia).
4. Reconciliação com referência histórica do RS documentada.
"""
from __future__ import annotations

import csv
import ftplib
import hashlib
import io
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

import numpy as np
import pandas as pd

VERSION_TRANSFORMACAO = "1.0.0"
FTP_HOST = "ftp.mtps.gov.br"
FTP_PATH_2023 = "pdet/microdados/RAIS/2023/RAIS_ESTAB_PUB.7z"
FONTE_URL_OFICIAL = "ftp://ftp.mtps.gov.br/pdet/microdados/RAIS/2023/RAIS_ESTAB_PUB.7z"
# Referência principal da integração (frente 37, decisão D37-T2): estoque de 31/12/2025, a RAIS mais
# recente publicada antes da eleição (MTE, 13/05/2026). 2023 fica como auditoria contra a base RS.
ANO_PADRAO = 2025


def ftp_path(ano: int) -> str:
    return f"pdet/microdados/RAIS/{ano}/RAIS_ESTAB_PUB.7z"


def fonte_url(ano: int) -> str:
    return f"ftp://{FTP_HOST}/{ftp_path(ano)}"

EXPECTED_COLUMNS = [
    "sg_uf",
    "cd_municipio_ibge",
    "cd_municipio_tse",
    "indicador",
    "valor",
    "unidade",
    "numerador",
    "denominador",
    "universo",
    "periodo_referencia",
    "motivo_ausencia",
    "source_id",
    "versao_transformacao",
]


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def load_tse_ibge_mapping(mapping_path: Path | str) -> pd.DataFrame:
    """Carrega correspondência oficial entre códigos IBGE (7 dígitos) e TSE (5 dígitos)."""
    mapping_path = Path(mapping_path)
    if mapping_path.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(mapping_path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", encoding="latin-1", dtype=str)
    else:
        df = pd.read_csv(mapping_path, sep=";", encoding="latin-1", dtype=str)

    clean = pd.DataFrame({
        "sg_uf": df["SG_UF"].str.strip(),
        "cd_municipio_tse": df["CD_MUNICIPIO_TSE"].astype(str).str.strip().str.zfill(5),
        "cd_municipio_ibge": df["CD_MUNICIPIO_IBGE"].astype(str).str.strip().str.zfill(7),
        "nm_municipio": df["NM_MUNICIPIO_IBGE"].str.strip(),
    })
    clean["cd_municipio_ibge_6"] = clean["cd_municipio_ibge"].str[:6]
    return clean


def parse_rais_stream(
    stream: Iterable[str],
) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
    """Lê linhas do arquivo de estabelecimentos da RAIS e agrega por código municipal de 6 dígitos.

    Aceita qualquer iterador de linhas em texto (delimitado por vírgula ou ponto-e-vírgula).
    Não grava nem emite identificadores individuais.
    """
    reader = csv.reader(stream)
    header = next(reader)
    h_norm = [h.strip().replace('"', "") for h in header]

    def find_col(patterns: list[str]) -> int:
        for p in patterns:
            for idx, col in enumerate(h_norm):
                if re.search(p, col, re.IGNORECASE):
                    return idx
        raise ValueError(f"Coluna compatível não encontrada para padrões: {patterns} em {h_norm}")

    mun_idx = find_col([r"^munic[ií]pio", r"munic[ií]pio - c[oó]digo"])
    vinc_idx = find_col([r"qtd v[ií]nculos ativos", r"v[ií]nculos ativos"])

    clt_idx = None
    try:
        clt_idx = find_col([r"qtd v[ií]nculos clt", r"v[ií]nculos clt"])
    except ValueError:
        pass

    estat_idx = None
    try:
        estat_idx = find_col([r"qtd v[ií]nculos estatut[aá]rios", r"v[ií]nculos estatut[aá]rios"])
    except ValueError:
        pass

    uf_idx = None
    try:
        uf_idx = find_col([r"^uf", r"^uf - c[oó]digo"])
    except ValueError:
        pass

    totals: dict[str, dict[str, int]] = {}
    total_linhas = 0
    linhas_com_vinc = 0
    vinc_acumulado = 0
    clt_acumulado = 0
    estat_acumulado = 0

    for row in reader:
        if not row:
            continue
        total_linhas += 1
        mun_raw = row[mun_idx].strip()
        if not mun_raw or not mun_raw.isdigit():
            continue
        mun6 = mun_raw.zfill(6)

        try:
            vinc = int(row[vinc_idx].strip() or 0)
        except (ValueError, TypeError):
            vinc = 0

        clt = 0
        if clt_idx is not None:
            try:
                clt = int(row[clt_idx].strip() or 0)
            except (ValueError, TypeError):
                clt = 0

        estat = 0
        if estat_idx is not None:
            try:
                estat = int(row[estat_idx].strip() or 0)
            except (ValueError, TypeError):
                estat = 0

        if mun6 not in totals:
            totals[mun6] = {
                "vinculos_formais_total": 0,
                "vinculos_clt_total": 0,
                "vinculos_estatutarios_total": 0,
                "estabelecimentos_total": 0,
            }

        rec = totals[mun6]
        rec["vinculos_formais_total"] += vinc
        rec["vinculos_clt_total"] += clt
        rec["vinculos_estatutarios_total"] += estat
        rec["estabelecimentos_total"] += 1

        vinc_acumulado += vinc
        clt_acumulado += clt
        estat_acumulado += estat
        if vinc > 0:
            linhas_com_vinc += 1

    audit = {
        "cabecalho": h_norm,
        "linhas_processadas": total_linhas,
        "estabelecimentos_com_vinculos_ativos": linhas_com_vinc,
        "vinculos_formais_total_brasil": vinc_acumulado,
        "vinculos_clt_total_brasil": clt_acumulado,
        "vinculos_estatutarios_total_brasil": estat_acumulado,
        "municipios_com_estabelecimentos": len(totals),
        "ano_referencia": 2023,
        "data_referencia": "2023-12-31",
        "fonte": FONTE_URL_OFICIAL,
    }

    return totals, audit


def extract_rais_archive(archive_path: Path | str) -> tuple[dict[str, dict[str, int]], dict[str, Any]]:
    """Extrai e processa em stream RAIS_ESTAB_PUB.7z sem descompactar em disco."""
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Arquivo RAIS não encontrado: {archive_path}")

    cmd = ["tar", "-xOf", str(archive_path), "RAIS_ESTAB_PUB.COMT"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.stdout is None:
        raise RuntimeError("Falha ao abrir stream do tar para RAIS")

    stream = io.TextIOWrapper(proc.stdout, encoding="latin-1")
    totals, audit = parse_rais_stream(stream)
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read().decode("latin-1", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"Erro do comando tar ao extrair RAIS: {err}")

    audit["archive_sha256"] = sha256_file(archive_path)
    audit["archive_bytes"] = archive_path.stat().st_size
    return totals, audit


def build_rais_long_contract(
    totals: dict[str, dict[str, int]],
    mapping_df: pd.DataFrame,
    pop_df: pd.DataFrame | None,
    source_id: str,
    periodo: str = "2023-12-31",
) -> pd.DataFrame:
    """Monta o DataFrame no formato municipal longo comum especificado no Plano 33."""
    mapping = mapping_df.copy()
    if "cd_municipio_ibge_6" not in mapping.columns:
        mapping["cd_municipio_ibge_6"] = mapping["cd_municipio_ibge"].astype(str).str.zfill(7).str[:6]

    pop_map: dict[str, float] = {}
    if pop_df is not None and not pop_df.empty:
        # Se contiver a coluna 'variavel' == 'populacao_residente', filtra
        if "variavel" in pop_df.columns:
            p_sub = pop_df[pop_df["variavel"] == "populacao_residente"]
            pop_map = dict(zip(p_sub["cd_municipio_ibge"].astype(str).str.zfill(7), p_sub["valor"].astype(float)))
        elif "populacao_residente" in pop_df.columns:
            pop_map = dict(zip(pop_df["cd_municipio_ibge"].astype(str).str.zfill(7), pop_df["populacao_residente"].astype(float)))
        elif "valor" in pop_df.columns and "cd_municipio_ibge" in pop_df.columns:
            pop_map = dict(zip(pop_df["cd_municipio_ibge"].astype(str).str.zfill(7), pop_df["valor"].astype(float)))

    rows = []
    ano = periodo[:4]
    data_br = f"{periodo[8:10]}/{periodo[5:7]}/{ano}"
    universo_base = f"Estoque de vínculos empregatícios ativos em {data_br} por município do estabelecimento (MTE/RAIS {ano})"
    universo_taxa = f"Razão administrativa entre vínculos formais no estabelecimento (RAIS {ano}) e população residente (Censo 2022); vínculos não são trabalhadores únicos e não medem emprego dos residentes"
    universo_clt = f"Estoque de vínculos ativos regidos pela CLT em {data_br} (MTE/RAIS {ano})"
    universo_estat = f"Estoque de vínculos ativos regidos por estatuto público em {data_br} (MTE/RAIS {ano})"

    for _, map_row in mapping.iterrows():
        sg_uf = map_row["sg_uf"]
        ibge7 = map_row["cd_municipio_ibge"]
        ibge6 = map_row["cd_municipio_ibge_6"]
        tse_cd = map_row["cd_municipio_tse"]

        rec = totals.get(ibge6)
        if rec is None:
            # Município ausente na RAIS (ex: Boa Esperança do Norte 5101837 criado pós-2023)
            motivo = (f"municipio_instalado_pos_{ano}" if ibge7 == "5101837" else "sem_declaracao_rais")
            for ind, uni, udesc in [
                ("vinculos_formais_total", "vinculos", universo_base),
                ("vinculos_formais_por_mil_hab", "vinculos_por_mil_hab", universo_taxa),
                ("vinculos_clt_total", "vinculos", universo_clt),
                ("vinculos_estatutarios_total", "vinculos", universo_estat),
            ]:
                rows.append({
                    "sg_uf": sg_uf,
                    "cd_municipio_ibge": ibge7,
                    "cd_municipio_tse": tse_cd,
                    "indicador": ind,
                    "valor": np.nan,
                    "unidade": uni,
                    "numerador": np.nan,
                    "denominador": np.nan,
                    "universo": udesc,
                    "periodo_referencia": periodo,
                    "motivo_ausencia": motivo,
                    "source_id": source_id,
                    "versao_transformacao": VERSION_TRANSFORMACAO,
                })
            continue

        vinc_tot = float(rec["vinculos_formais_total"])
        clt_tot = float(rec["vinculos_clt_total"])
        estat_tot = float(rec["vinculos_estatutarios_total"])

        # 1. vinculos_formais_total
        rows.append({
            "sg_uf": sg_uf,
            "cd_municipio_ibge": ibge7,
            "cd_municipio_tse": tse_cd,
            "indicador": "vinculos_formais_total",
            "valor": vinc_tot,
            "unidade": "vinculos",
            "numerador": np.nan,
            "denominador": np.nan,
            "universo": universo_base,
            "periodo_referencia": periodo,
            "motivo_ausencia": None,
            "source_id": source_id,
            "versao_transformacao": VERSION_TRANSFORMACAO,
        })

        # 2. vinculos_clt_total
        rows.append({
            "sg_uf": sg_uf,
            "cd_municipio_ibge": ibge7,
            "cd_municipio_tse": tse_cd,
            "indicador": "vinculos_clt_total",
            "valor": clt_tot,
            "unidade": "vinculos",
            "numerador": np.nan,
            "denominador": np.nan,
            "universo": universo_clt,
            "periodo_referencia": periodo,
            "motivo_ausencia": None,
            "source_id": source_id,
            "versao_transformacao": VERSION_TRANSFORMACAO,
        })

        # 3. vinculos_estatutarios_total
        rows.append({
            "sg_uf": sg_uf,
            "cd_municipio_ibge": ibge7,
            "cd_municipio_tse": tse_cd,
            "indicador": "vinculos_estatutarios_total",
            "valor": estat_tot,
            "unidade": "vinculos",
            "numerador": np.nan,
            "denominador": np.nan,
            "universo": universo_estat,
            "periodo_referencia": periodo,
            "motivo_ausencia": None,
            "source_id": source_id,
            "versao_transformacao": VERSION_TRANSFORMACAO,
        })

        # 4. vinculos_formais_por_mil_hab
        pop_val = pop_map.get(ibge7)
        if pop_val is not None and not np.isnan(pop_val) and pop_val > 0:
            taxa = round(1000.0 * vinc_tot / pop_val, 4)
            rows.append({
                "sg_uf": sg_uf,
                "cd_municipio_ibge": ibge7,
                "cd_municipio_tse": tse_cd,
                "indicador": "vinculos_formais_por_mil_hab",
                "valor": taxa,
                "unidade": "vinculos_por_mil_hab",
                "numerador": vinc_tot,
                "denominador": float(pop_val),
                "universo": universo_taxa,
                "periodo_referencia": periodo,
                "motivo_ausencia": None,
                "source_id": source_id,
                "versao_transformacao": VERSION_TRANSFORMACAO,
            })
        else:
            rows.append({
                "sg_uf": sg_uf,
                "cd_municipio_ibge": ibge7,
                "cd_municipio_tse": tse_cd,
                "indicador": "vinculos_formais_por_mil_hab",
                "valor": np.nan,
                "unidade": "vinculos_por_mil_hab",
                "numerador": vinc_tot,
                "denominador": np.nan,
                "universo": universo_taxa,
                "periodo_referencia": periodo,
                "motivo_ausencia": "denominador_populacao_ausente",
                "source_id": source_id,
                "versao_transformacao": VERSION_TRANSFORMACAO,
            })

    out = pd.DataFrame(rows)[EXPECTED_COLUMNS]
    out["valor"] = pd.to_numeric(out["valor"], errors="coerce")
    out["numerador"] = pd.to_numeric(out["numerador"], errors="coerce")
    out["denominador"] = pd.to_numeric(out["denominador"], errors="coerce")
    return out.sort_values(["sg_uf", "cd_municipio_ibge", "indicador"]).reset_index(drop=True)


def validate_socio_contract(df: pd.DataFrame) -> None:
    """Valida aderência estrita ao contrato comum longo de socioeconomia."""
    missing_cols = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Colunas ausentes no contrato longo: {sorted(missing_cols)}")

    # Unicidade da chave primária
    pk = ["sg_uf", "cd_municipio_ibge", "indicador", "periodo_referencia"]
    dup = df.duplicated(subset=pk, keep=False)
    if dup.any():
        sample = df.loc[dup, pk].head(5).to_dict(orient="records")
        raise ValueError(f"Violação de unicidade da chave primária {pk}: {sample}")

    # Formatos de código
    if not df["sg_uf"].str.match(r"^[A-Z]{2}$").all():
        raise ValueError("Valores inválidos encontrados na coluna sg_uf")
    if not df["cd_municipio_ibge"].str.match(r"^[0-9]{7}$").all():
        raise ValueError("Valores inválidos encontrados na coluna cd_municipio_ibge")

    # Ausentes sem motivo
    ausentes_sem_motivo = df["valor"].isna() & df["motivo_ausencia"].isna()
    if ausentes_sem_motivo.any():
        bad = df.loc[ausentes_sem_motivo, pk].head(5).to_dict(orient="records")
        raise ValueError(f"Valores nulos sem motivo_ausencia especificado: {bad}")


def reconcile_rs_against_legacy(
    df_rais_long: pd.DataFrame,
    legacy_staging_path: Path | str,
) -> dict[str, Any]:
    """Compara os totais municipais de vínculos com a entrega histórica do RS."""
    legacy_staging_path = Path(legacy_staging_path)
    if not legacy_staging_path.exists():
        return {"status": "AVISO", "motivo": f"Arquivo legado não encontrado em {legacy_staging_path}"}

    legacy = pd.read_parquet(legacy_staging_path)
    leg_map = dict(zip(legacy["id_municipio_ibge"].astype(str), legacy["vinculos_formais_total"].astype(float)))

    rais_rs = df_rais_long[
        (df_rais_long["sg_uf"] == "RS") & (df_rais_long["indicador"] == "vinculos_formais_total")
    ]
    cur_map = dict(zip(rais_rs["cd_municipio_ibge"].astype(str), rais_rs["valor"].astype(float)))

    comuns = [m for m in leg_map if m in cur_map and not np.isnan(cur_map[m])]
    x = np.array([leg_map[m] for m in comuns])
    y = np.array([cur_map[m] for m in comuns])

    corr = float(np.corrcoef(x, y)[0, 1]) if len(comuns) > 1 else 1.0
    tot_leg = float(np.sum(x))
    tot_cur = float(np.sum(y))
    diff_rel = float((tot_cur - tot_leg) / tot_leg) if tot_leg > 0 else 0.0

    return {
        "status": "CONCILIADO_COM_DIVERGENCIA_DOCUMENTADA",
        "municipios_comparados": len(comuns),
        "total_rs_legado_dee": tot_leg,
        "total_rs_nacional_rais_estab": tot_cur,
        "diferenca_absoluta": tot_cur - tot_leg,
        "diferenca_percentual": round(diff_rel * 100, 4),
        "correlacao_linear": round(corr, 6),
        "nota_metodologica": (
            "Diferença não explicada (revisão 37). A base RS soma os vínculos por sexo publicados pelo "
            "DEE-RS a partir de uma liberação anterior da RAIS 2023; aqui se lê o arquivo de "
            "estabelecimentos republicado pelo MTE em 18/05/2026. Versão da liberação e arquivo "
            "(estabelecimentos x vínculos) são hipóteses não testadas."
        ),
    }


def run_socio_rais(
    project_root: Path | str,
    raw_archive: Path | str | None = None,
    mapping_zip: Path | str | None = None,
    context_parquet: Path | str | None = None,
    legacy_rs_parquet: Path | str | None = None,
    force: bool = False,
    ano: int = ANO_PADRAO,
) -> dict[str, Any]:
    """Pipeline completo de ingestão, validação, publicação em staging e auditoria da RAIS.

    Um arquivo por ano de referência (`socio_rais_<ano>.parquet`); a reconciliação com a base RS
    só se aplica a 2023, o ano daquela base."""
    root = Path(project_root)
    raw_dir = root / "data" / "raw" / "socio_rais"
    staging_dir = root / "data" / "staging" / "socio_rais"
    raw_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    archive_path = Path(raw_archive) if raw_archive else raw_dir / f"RAIS_ESTAB_PUB_{ano}.7z"
    manifest_path = raw_dir / "manifest.json"
    staging_parquet = staging_dir / f"socio_rais_{ano}.parquet"
    audit_path = staging_dir / f"rais_auditoria_{ano}.json"
    periodo = f"{ano}-12-31"

    mapping_path = Path(mapping_zip) if mapping_zip else root / "data" / "raw" / "samples" / "municipio_tse_ibge.zip"
    if not mapping_path.exists():
        alt = root / "data" / "raw" / "ibge_setores" / "municipio_tse_ibge.zip"
        if alt.exists():
            mapping_path = alt

    ctx_path = Path(context_parquet) if context_parquet else root / "data" / "staging" / "municipal_context.parquet"

    # Se raw_archive não existe, tenta baixar do FTP oficial
    if not archive_path.exists():
        print(f"Baixando RAIS Estabelecimentos {ano} de {FTP_HOST}/{ftp_path(ano)}...")
        ftp = ftplib.FTP(FTP_HOST, timeout=60)
        ftp.login()
        tmp_download = archive_path.with_suffix(".tmp")
        with open(tmp_download, "wb") as f:
            ftp.retrbinary(f"RETR {ftp_path(ano)}", f.write)
        ftp.quit()
        os.replace(tmp_download, archive_path)
        print(f"Download concluído: {archive_path.stat().st_size} bytes")

    source_sha = sha256_file(archive_path)

    # Verifica cache idempotente
    if not force and staging_parquet.exists() and manifest_path.exists() and audit_path.exists():
        man = json.loads(manifest_path.read_text(encoding="utf-8"))
        if man.get("registros", {}).get(archive_path.name, {}).get("sha256") == source_sha:
            print("Staging RAIS atualizado e verificado por hash de entrada; reutilizando cache.")
            return json.loads(audit_path.read_text(encoding="utf-8"))

    # Extrai e agrega os dados
    print("Processando estabelecimentos da RAIS em stream...")
    totals, audit = extract_rais_archive(archive_path)
    audit.update({"ano_referencia": ano, "data_referencia": periodo, "fonte": fonte_url(ano)})

    # Carrega lookups e população
    mapping_df = load_tse_ibge_mapping(mapping_path)
    pop_df = pd.read_parquet(ctx_path) if ctx_path.exists() else None

    # Constrói contrato longo
    df_long = build_rais_long_contract(totals, mapping_df, pop_df, source_id=source_sha, periodo=periodo)
    validate_socio_contract(df_long)

    # Reconciliação RS
    if ano != 2023:
        rec_rs = {"status": "NAO_APLICAVEL", "motivo": f"a base RS de referência é a RAIS 2023; esta é {ano}"}
    elif legacy_rs_parquet:
        rec_rs = reconcile_rs_against_legacy(df_long, legacy_rs_parquet)
    else:
        legacy_cand = Path("../election_2026/data/02_staging/socioeconomico_municipal_rs.parquet")
        rec_rs = reconcile_rs_against_legacy(df_long, legacy_cand) if legacy_cand.exists() else {}
    audit["reconciliacao_rs"] = rec_rs

    # Salva staging atômico
    tmp_out = staging_parquet.with_suffix(".parquet.tmp")
    df_long.to_parquet(tmp_out, index=False)
    os.replace(tmp_out, staging_parquet)

    # Salva manifesto (um registro por arquivo bruto; anos anteriores preservados)
    manifest_data = (json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists()
                     else {"versao_manifesto": "1.0", "registros": {}})
    manifest_data["gerado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest_data.setdefault("registros", {})[archive_path.name] = {
        "url": fonte_url(ano),
        "sha256": source_sha,
        "bytes": archive_path.stat().st_size,
        "periodo_referencia": periodo,
        "versao_transformacao": VERSION_TRANSFORMACAO,
    }
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Salva auditoria
    audit["arquivo_staging"] = str(staging_parquet.relative_to(root))
    audit["staging_sha256"] = sha256_file(staging_parquet)
    audit["total_linhas_staging"] = len(df_long)
    audit["municipios_tse_cobertos"] = int(df_long["cd_municipio_tse"].nunique())
    audit["municipios_ibge_cobertos"] = int(df_long["cd_municipio_ibge"].nunique())
    audit["cobertura_ufs"] = sorted(df_long["sg_uf"].unique())

    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Staging RAIS gerado com sucesso: {len(df_long)} linhas em {staging_parquet}")
    return audit


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="RAIS estabelecimentos -> contrato municipal longo")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--ano", type=int, default=ANO_PADRAO)
    ap.add_argument("--arquivo", default=None, help="RAIS_ESTAB_PUB.7z local (offline)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    run_socio_rais(a.project_root, raw_archive=a.arquivo, force=a.force, ano=a.ano)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
