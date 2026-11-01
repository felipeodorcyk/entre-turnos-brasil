"""Exportador do release web municipal (P0).

Lê artefatos analíticos congelados sem modificá-los e escreve um release
imutável consumível pelo app React. Ver docs/webapp/CONTRACT.md.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import os
import tempfile
import uuid
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

SCHEMA_VERSION = "webapp-p0/1.0.0"
EXPORT_VERSION = "1.0.1"
SOCIO_FIELDS = [
    "renda_pc",
    "baixa_renda",
    "desocupacao",
    "vinculos",
    "pbf",
    "urbana",
]
COUNT_FIELDS = [
    "qt_aptos_t1",
    "qt_aptos_t2",
    "qt_comparecimento_t1",
    "qt_comparecimento_t2",
    "qt_abstencoes_t1",
    "qt_abstencoes_t2",
    "qt_votos_validos_t1",
    "qt_votos_validos_t2",
    "qt_votos_brancos_t1",
    "qt_votos_brancos_t2",
    "qt_votos_nulos_t1",
    "qt_votos_nulos_t2",
    "qt_lula_t1",
    "qt_lula_t2",
    "qt_flavio_t1",
    "qt_flavio_t2",
]
MUNICIPIO_FIELDS = [
    "cd_tse",
    "cd_ibge",
    "sg_uf",
    "nome",
    "regiao",
    "cd_regiao_imediata",
    "n_unidades",
    *COUNT_FIELDS,
    *SOCIO_FIELDS,
    "tem_geometria",
    "tem_contexto",
]
CORE_FIELDS = [field for field in MUNICIPIO_FIELDS if field not in SOCIO_FIELDS]
FIELD_DEFS: dict[str, dict[str, Any]] = {
    "cd_tse": {"tipo": "string", "rotulo": "Código TSE do município", "agregacao": "chave"},
    "cd_ibge": {"tipo": "string", "rotulo": "Código IBGE do município", "agregacao": "chave"},
    "sg_uf": {"tipo": "string", "rotulo": "UF", "agregacao": "dimensao"},
    "nome": {"tipo": "string", "rotulo": "Município", "agregacao": "dimensao"},
    "regiao": {"tipo": "string", "rotulo": "Grande região", "agregacao": "dimensao"},
    "cd_regiao_imediata": {"tipo": "string", "rotulo": "Região imediata IBGE", "agregacao": "dimensao"},
    "n_unidades": {"tipo": "int", "rotulo": "Unidades eleitorais pareadas", "agregacao": "soma_descritiva"},
    **{
        f: {"tipo": "int", "rotulo": f.replace("qt_", "").replace("_t", " T"), "agregacao": "soma"}
        for f in COUNT_FIELDS
    },
    "renda_pc": {
        "tipo": "float|null",
        "rotulo": "Renda domiciliar per capita média (R$ de 2022)",
        "unidade": "R$/mês",
        "ano_referencia": "2022",
        "fonte": "IBGE, Censo 2022, SIDRA 10295",
        "agregacao": "nao_agregavel",
    },
    "baixa_renda": {
        "tipo": "float|null",
        "rotulo": "Pessoas com até ½ salário mínimo (%)",
        "unidade": "%",
        "ano_referencia": "2022",
        "fonte": "IBGE, Censo 2022, SIDRA 10296",
        "agregacao": "nao_agregavel",
    },
    "desocupacao": {
        "tipo": "float|null",
        "rotulo": "Taxa de desocupação (%)",
        "unidade": "%",
        "ano_referencia": "2022",
        "fonte": "IBGE, Censo 2022, SIDRA 6580",
        "agregacao": "nao_agregavel",
    },
    "vinculos": {
        "tipo": "float|null",
        "rotulo": "Vínculos formais por mil habitantes",
        "unidade": "vínculos/1.000 hab.",
        "ano_referencia": "2025-12-31",
        "fonte": "MTE, RAIS 2025",
        "agregacao": "nao_agregavel",
        "nota": "Vínculo é do estabelecimento, não pessoa única.",
    },
    "pbf": {
        "tipo": "float|null",
        "rotulo": "Registros do Bolsa Família por 100 domicílios",
        "unidade": "registros/100 domicílios",
        "ano_referencia": "2026-08",
        "fonte": "MDS/PBF, folha 08/2026",
        "agregacao": "nao_agregavel",
        "nota": "Registro de pagamento não é família única.",
    },
    "urbana": {
        "tipo": "float|null",
        "rotulo": "População urbana (%)",
        "unidade": "%",
        "ano_referencia": "2022",
        "fonte": "IBGE, Censo 2022, SIDRA 9923",
        "agregacao": "nao_agregavel",
    },
    "tem_geometria": {"tipo": "0|1", "rotulo": "Tem geometria municipal 2022", "agregacao": "cobertura"},
    "tem_contexto": {"tipo": "0|1", "rotulo": "Tem todos os indicadores socioeconômicos", "agregacao": "cobertura"},
}

DERIVED_DEFS = {
    "participacao_lula_t1": "qt_lula_t1 / qt_votos_validos_t1",
    "participacao_lula_t2": "qt_lula_t2 / qt_votos_validos_t2",
    "participacao_flavio_t1": "qt_flavio_t1 / qt_votos_validos_t1",
    "participacao_flavio_t2": "qt_flavio_t2 / qt_votos_validos_t2",
    "comparecimento_t1": "qt_comparecimento_t1 / qt_aptos_t1",
    "comparecimento_t2": "qt_comparecimento_t2 / qt_aptos_t2",
    "delta_participacao_lula_pp": "100 * (participacao_lula_t2 - participacao_lula_t1)",
    "delta_participacao_flavio_pp": "100 * (participacao_flavio_t2 - participacao_flavio_t1)",
    "delta_comparecimento_pp": "100 * (comparecimento_t2 - comparecimento_t1)",
    "delta_margem_pp": "100 * ((Lula_t2 - Flavio_t2)/validos_t2 - (Lula_t1 - Flavio_t1)/validos_t1)",
    "delta_margem_votos": "(Lula_t2 - Flavio_t2) - (Lula_t1 - Flavio_t1)",
}


@dataclass
class Inputs:
    root: Path
    metrics_municipio: Path
    metrics_uf: Path
    metrics_aggregate: Path
    painel_socio: Path
    coverage_municipio: Path
    faixas_nacional: Path
    crosswalk: Path
    localidades: Path
    referencia_oficial: Path
    analysis_manifest: Path
    malha: Path

    @classmethod
    def default(cls, root: Path) -> "Inputs":
        return cls(
            root=root,
            metrics_municipio=root / "data/analytics/metrics_municipio.csv",
            metrics_uf=root / "data/analytics/metrics_uf.csv",
            metrics_aggregate=root / "data/analytics/metrics_aggregate.csv",
            painel_socio=root / "data/analytics/socio/painel_municipal_socio.parquet",
            coverage_municipio=root / "data/analytics/coverage_municipio.csv",
            faixas_nacional=root / "data/analytics/socio/faixas_nacional.csv",
            crosswalk=root / "data/raw/ibge_setores/municipio_tse_ibge.zip",
            localidades=root / "data/raw/ibge_localidades/municipios.json",
            referencia_oficial=root / "reports/analysis/evidencias_nacional/referencia_m1_m2_uf.csv",
            analysis_manifest=root / "data/analytics/analysis_manifest.json",
            malha=root / "web/public/geo/municipios_2022_intermediaria.geojson",
        )


@dataclass
class ExportResult:
    release_id: str
    out_dir: Path
    manifest: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(type(value))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"), default=_json_default)
        fh.write("\n")


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"cd_municipio_tse": str, "sg_uf": str}, **kwargs)


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return _read_csv(path)


def _read_crosswalk(path: Path) -> pd.DataFrame:
    if path.suffix == ".zip":
        import zipfile

        with zipfile.ZipFile(path) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(member) as fh:
                return pd.read_csv(fh, sep=";", encoding="latin-1", dtype=str)
    return pd.read_csv(path, dtype=str)


def _normalise_crosswalk(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "CD_MUNICIPIO_TSE": "cd_municipio_tse",
        "CD_MUNICIPIO_IBGE": "cd_municipio_ibge",
        "SG_UF": "sg_uf",
        "NM_MUNICIPIO_TSE": "nome_tse",
        "NM_MUNICIPIO_IBGE": "nome_ibge",
        "NM_UF": "nome_uf",
    }
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns}).copy()
    out["cd_municipio_tse"] = out["cd_municipio_tse"].str.zfill(5)
    out["cd_municipio_ibge"] = out["cd_municipio_ibge"].str.zfill(7)
    return out.drop_duplicates(["sg_uf", "cd_municipio_tse"])


def _localidades_index(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    municipios: dict[str, dict[str, Any]] = {}
    ufs: dict[str, dict[str, Any]] = {}
    for item in data:
        ri = item.get("regiao-imediata") or {}
        ri_uf = (ri.get("regiao-intermediaria") or {}).get("UF") or {}
        micro_uf = ((item.get("microrregiao") or {}).get("mesorregiao") or {}).get("UF") or {}
        uf = ri_uf or micro_uf
        code = str(item["id"]).zfill(7)
        municipios[code] = {
            "nome": item["nome"],
            "sg_uf": uf.get("sigla"),
            "nome_uf": uf.get("nome"),
            "regiao": (uf.get("regiao") or {}).get("nome"),
            "cd_regiao_imediata": str(ri.get("id")).zfill(6) if ri.get("id") else None,
        }
        if uf.get("sigla"):
            ufs[uf["sigla"]] = {"nome_uf": uf.get("nome"), "regiao": (uf.get("regiao") or {}).get("nome")}
    return municipios, ufs


def _geo_codes(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        code = props.get("codarea") or props.get("CD_MUN") or props.get("cd_municipio_ibge")
        if code is not None:
            codes.add(str(code).zfill(7))
    return codes


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _safe_int(value: Any) -> int:
    if value is None or pd.isna(value):
        raise ValueError("contagem ausente inesperada")
    return int(value)


def _release_id(input_hashes: dict[str, str], source_commit: str) -> str:
    payload = json.dumps(
        {"schema": SCHEMA_VERSION, "export": EXPORT_VERSION, "hashes": input_hashes},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return f"p0-{source_commit[:7]}-{hashlib.sha256(payload).hexdigest()[:10]}"


def _official_block(reference: pd.DataFrame) -> dict[str, Any]:
    required_order = (
        "qt_aptos",
        "qt_comparecimento",
        "qt_abstencoes",
        "qt_votos_brancos",
        "qt_votos_nulos",
        "qt_lula",
        "qt_flavio",
    )
    required = set(required_order)
    metrics = set(reference["metrica"].unique())
    missing = required - metrics
    if missing:
        raise ValueError(f"referência oficial sem métricas: {sorted(missing)}")
    if int(reference["dif"].abs().max()) != 0:
        raise ValueError("referência oficial com diferença não zero")
    names = {1: "t1", 2: "t2"}
    totals: dict[str, Any] = {}
    for turn, label in names.items():
        part = reference[reference["nr_turno"] == turn].groupby("metrica")["valor_referencia"].sum()
        totals[label] = {k.replace("qt_", ""): int(part[k]) for k in required_order}
        totals[label]["validos_t2"] = None
        if turn == 2:
            totals[label]["validos_t2"] = int(part["qt_lula"] + part["qt_flavio"])
    por_uf = []
    for uf, part in reference.groupby("sg_uf"):
        row: dict[str, Any] = {"sg_uf": uf}
        for turn, label in names.items():
            values = part[part["nr_turno"] == turn].set_index("metrica")["valor_referencia"]
            row[label] = {k.replace("qt_", ""): int(values[k]) for k in required_order}
        por_uf.append(row)
    # 423 aptos sem comparecimento nem abstenção (41 seções não instaladas do exterior).
    excecao = {
        "aptos_sem_comparecimento_abstencao_t1": int(
            totals["t1"]["aptos"] - totals["t1"]["comparecimento"] - totals["t1"]["abstencoes"]
        ),
        "aptos_sem_comparecimento_abstencao_t2": int(
            totals["t2"]["aptos"] - totals["t2"]["comparecimento"] - totals["t2"]["abstencoes"]
        ),
        "unidades_sem_apuracao_nenhum_turno": 42,
        "aptos_unidades_sem_apuracao": 495,
    }
    urls = sorted(set(reference["url"].dropna().astype(str))) if "url" in reference else []
    return {
        "fonte": "TSE — Relatório de Resultado da Totalização 2026",
        "unidades": int(reference["sg_uf"].nunique()),
        "inclui_exterior": "ZZ" in set(reference["sg_uf"]),
        "metricas_por_unidade_turno": int(len(reference)),
        "diferencas_nao_zero": int((reference["dif"] != 0).sum()),
        "totais": totals,
        "por_uf": sorted(por_uf, key=lambda r: r["sg_uf"]),
        "excecoes": excecao,
        "urls": urls,
    }


def _faixas_block(faixas: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for indicador, part in faixas.groupby("indicador", sort=False):
        part = part.sort_values("faixa")
        out[str(indicador)] = [
            {
                "faixa": int(row.faixa),
                "corte_inferior": _safe_float(row.corte_inferior),
                "corte_superior": _safe_float(row.corte_superior),
                "valor_min": _safe_float(row.valor_min),
                "valor_max": _safe_float(row.valor_max),
                "municipios": int(row.municipios),
                "municipios_sem_indicador": int(row.municipios_sem_indicador),
            }
            for row in part.itertuples()
        ]
    return {
        "metodo": "quintis nacionais sem peso, uma vez, empates juntos; não recalculados ao filtrar",
        "fonte": "data/analytics/socio/faixas_nacional.csv",
        "indicadores": out,
    }


def _validate_municipios(
    rows: list[list[Any]], metrics: pd.DataFrame, metrics_uf: pd.DataFrame, warnings: list[str]
) -> dict[str, Any]:
    idx = {name: i for i, name in enumerate(MUNICIPIO_FIELDS)}
    if len(rows) != len(metrics):
        raise ValueError(f"linhas exportadas {len(rows)} != métricas {len(metrics)}")
    seen = set()
    for row in rows:
        key = row[idx["cd_ibge"]]
        if key in seen:
            raise ValueError(f"chave duplicada: {key}")
        seen.add(key)
    total = metrics_uf[metrics_uf["sg_uf"] == "TOTAL"].iloc[0]
    for field_name in COUNT_FIELDS:
        exported = sum(int(row[idx[field_name]]) for row in rows)
        expected = int(total[field_name])
        if exported != expected:
            raise ValueError(f"soma de {field_name} divergente: {exported} != {expected}")
    per_uf = metrics.groupby("sg_uf")[COUNT_FIELDS].sum()
    for uf, part in per_uf.iterrows():
        ref = metrics_uf[metrics_uf["sg_uf"] == uf]
        if ref.empty:
            warnings.append(f"UF {uf} sem linha em metrics_uf")
            continue
        for field_name in ("qt_aptos_t2", "qt_comparecimento_t2", "qt_votos_validos_t2", "qt_lula_t2", "qt_flavio_t2"):
            if int(part[field_name]) != int(ref.iloc[0][field_name]):
                raise ValueError(f"{uf}/{field_name}: {int(part[field_name])} != {int(ref.iloc[0][field_name])}")
    return {"chaves_unicas": len(seen), "somas_reconciliadas": True, "ufs": int(per_uf.shape[0])}


def export_release(
    inputs: Inputs,
    out_root: Path,
    *,
    write_pointer: bool = True,
) -> ExportResult:
    warnings: list[str] = []
    for path in [
        inputs.metrics_municipio,
        inputs.metrics_uf,
        inputs.metrics_aggregate,
        inputs.painel_socio,
        inputs.coverage_municipio,
        inputs.faixas_nacional,
        inputs.crosswalk,
        inputs.localidades,
        inputs.referencia_oficial,
        inputs.analysis_manifest,
        inputs.malha,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    metrics = _read_csv(inputs.metrics_municipio)
    metrics["cd_municipio_tse"] = metrics["cd_municipio_tse"].str.zfill(5)
    metrics_uf = _read_csv(inputs.metrics_uf)
    painel = _read_table(inputs.painel_socio)
    painel["cd_municipio_tse"] = painel["cd_municipio_tse"].str.zfill(5)
    cross = _normalise_crosswalk(_read_crosswalk(inputs.crosswalk))
    muns_ibge, ufs_ibge = _localidades_index(inputs.localidades)
    faixas = _read_csv(inputs.faixas_nacional)
    reference = pd.read_csv(inputs.referencia_oficial)
    analysis_manifest = json.loads(inputs.analysis_manifest.read_text(encoding="utf-8"))
    geo_codes = _geo_codes(inputs.malha)

    # Junta nomes por código IBGE, nunca por nome.
    base = metrics.merge(
        cross[["sg_uf", "cd_municipio_tse", "cd_municipio_ibge", "nome_tse"]],
        on=["sg_uf", "cd_municipio_tse"],
        how="left",
        validate="one_to_one",
    )
    if base["cd_municipio_ibge"].isna().any():
        missing = base[base["cd_municipio_ibge"].isna()][["sg_uf", "cd_municipio_tse"]]
        raise ValueError(f"municípios sem código IBGE: {missing.to_dict('records')}")

    socio_cols = ["sg_uf", "cd_municipio_tse", *SOCIO_FIELDS]
    socio = painel[socio_cols].copy()
    base = base.merge(socio, on=["sg_uf", "cd_municipio_tse"], how="left", validate="one_to_one")
    if len(base) != len(metrics):
        raise ValueError("join socioeconômico alterou o número de linhas")

    for col in COUNT_FIELDS + ["n_unidades"]:
        base[col] = base[col].astype("int64")

    rows: list[list[Any]] = []
    missing_geo: list[str] = []
    missing_context: list[str] = []
    for row in base.itertuples(index=False):
        ibge = str(row.cd_municipio_ibge).zfill(7)
        local = muns_ibge.get(ibge, {})
        nome = local.get("nome") or str(row.nome_tse).title()
        regiao = local.get("regiao") or (painel.loc[painel["cd_municipio_tse"] == row.cd_municipio_tse, "regiao"].iloc[0] if "regiao" in painel else None)
        cd_ri = local.get("cd_regiao_imediata")
        if not cd_ri and "cd_regiao_imediata" in painel:
            cd_ri = painel.loc[painel["cd_municipio_tse"] == row.cd_municipio_tse, "cd_regiao_imediata"].iloc[0]
        tem_geo = 1 if ibge in geo_codes else 0
        if not tem_geo:
            missing_geo.append(ibge)
        has_ctx = all(_safe_float(getattr(row, f)) is not None for f in SOCIO_FIELDS)
        if not has_ctx:
            missing_context.append(ibge)
        record = {
            "cd_tse": str(row.cd_municipio_tse).zfill(5),
            "cd_ibge": ibge,
            "sg_uf": row.sg_uf,
            "nome": nome,
            "regiao": regiao,
            "cd_regiao_imediata": cd_ri,
            "n_unidades": int(row.n_unidades),
            **{f: _safe_int(getattr(row, f)) for f in COUNT_FIELDS},
            **{f: _safe_float(getattr(row, f)) for f in SOCIO_FIELDS},
            "tem_geometria": tem_geo,
            "tem_contexto": 1 if has_ctx else 0,
        }
        rows.append([record[f] for f in MUNICIPIO_FIELDS])

    validacoes = _validate_municipios(rows, metrics, metrics_uf, warnings)
    municipios_geo = set(base["cd_municipio_ibge"].astype(str))
    malha_sem_municipio = sorted(geo_codes - municipios_geo)
    chaves_metricas = set(zip(base["sg_uf"], base["cd_municipio_tse"]))
    crosswalk_sem_metrics = sorted(set(zip(cross["sg_uf"], cross["cd_municipio_tse"])) - chaves_metricas)
    validacoes["malha_sem_municipio"] = len(malha_sem_municipio)
    validacoes["crosswalk_sem_metrics"] = len(crosswalk_sem_metrics)
    if malha_sem_municipio:
        warnings.append(f"{len(malha_sem_municipio)} feição(ões) da malha sem município no painel.")
    if crosswalk_sem_metrics:
        warnings.append(f"{len(crosswalk_sem_metrics)} chave(s) do lookup sem métrica municipal.")

    # UF: contagens territoriais + nomes/regiões; a linha TOTAL não é UF.
    uf_rows: list[dict[str, Any]] = []
    uf_counts = metrics_uf[metrics_uf["sg_uf"] != "TOTAL"].copy()
    for row in uf_counts.itertuples(index=False):
        uf_rows.append(
            {
                "sg_uf": row.sg_uf,
                "nome_uf": ufs_ibge.get(row.sg_uf, {}).get("nome_uf", row.sg_uf),
                "regiao": ufs_ibge.get(row.sg_uf, {}).get("regiao"),
                "n_municipios": int((metrics["sg_uf"] == row.sg_uf).sum()),
                **{f: int(getattr(row, f)) for f in COUNT_FIELDS},
            }
        )
    uf_rows.sort(key=lambda r: r["sg_uf"])

    official = _official_block(reference)
    faixas_out = _faixas_block(faixas)

    dicionario = {
        "schema_version": SCHEMA_VERSION,
        "grão": "município do território brasileiro",
        "universo": "pareado_territorial",
        "campos": FIELD_DEFS,
        "derivados": DERIVED_DEFS,
        "fontes": {
            "eleitoral": "TSE — votação por seção 2026, painel pareado do projeto presidenciais_2026_br",
            "oficial": "TSE — Relatório de Resultado da Totalização 2026",
            "nomes": "IBGE — API de localidades, municípios 2022",
            "malha": "IBGE — API de malhas, município 2022, qualidade intermediária",
            "socio": "IBGE Censo 2022; MTE RAIS 2025; MDS/PBF 08/2026",
        },
        "nao_agregaveis": SOCIO_FIELDS,
        "politica_nulos": "ausente é null; não satisfaz intervalo; nunca imputado como zero",
        "notas": [
            "Contagens por turno são inteiros; razões são calculadas a partir de somas.",
            "Indicadores socioeconômicos são atributos do município e não são agregados.",
            "Boa Esperança do Norte/MT (5101837) não tem contexto nem geometria 2022.",
        ],
    }

    input_paths = {
        "metrics_municipio": inputs.metrics_municipio,
        "metrics_uf": inputs.metrics_uf,
        "metrics_aggregate": inputs.metrics_aggregate,
        "painel_socio": inputs.painel_socio,
        "coverage_municipio": inputs.coverage_municipio,
        "faixas_nacional": inputs.faixas_nacional,
        "crosswalk": inputs.crosswalk,
        "localidades": inputs.localidades,
        "referencia_oficial": inputs.referencia_oficial,
        "analysis_manifest": inputs.analysis_manifest,
        "malha": inputs.malha,
    }
    input_hashes = {name: _sha256(path) for name, path in input_paths.items()}
    input_hashes["exporter_code"] = _sha256(Path(__file__))
    source_commit = str(analysis_manifest.get("git_commit", "sem-commit"))
    release_id = _release_id(input_hashes, source_commit)
    out_dir = out_root / release_id

    payloads: dict[str, Any] = {
        "municipios.json": {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "grao": "municipio",
            "universo": "pareado_territorial",
            "fields": MUNICIPIO_FIELDS,
            "rows": rows,
        },
        "uf.json": {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "fields": ["sg_uf", "nome_uf", "regiao", "n_municipios", *COUNT_FIELDS],
            "rows": [
                [r["sg_uf"], r["nome_uf"], r["regiao"], r["n_municipios"], *[r[f] for f in COUNT_FIELDS]]
                for r in uf_rows
            ],
        },
        "nacional.json": {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            **official,
        },
        "faixas.json": {"schema_version": SCHEMA_VERSION, "release_id": release_id, **faixas_out},
        "dicionario.json": {"schema_version": SCHEMA_VERSION, "release_id": release_id, **dicionario},
    }
    # Um único arquivo para o carregamento inicial do app (sem os indicadores
    # socioeconômicos, que chegam em `socio.json` logo depois). Os arquivos
    # separados continuam existindo para verificação e download.
    core_index = [MUNICIPIO_FIELDS.index(field) for field in CORE_FIELDS]
    socio_index = {field: MUNICIPIO_FIELDS.index(field) for field in ("cd_ibge", *SOCIO_FIELDS)}
    payloads["bundle.json"] = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "municipios": {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "fields": CORE_FIELDS,
            "rows": [[row[i] for i in core_index] for row in rows],
        },
        "uf": payloads["uf.json"],
        "nacional": payloads["nacional.json"],
        "faixas": payloads["faixas.json"],
        "dicionario": payloads["dicionario.json"],
    }
    payloads["socio.json"] = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "fields": ["cd_ibge", *SOCIO_FIELDS],
        "rows": [[row[socio_index[field]] for field in ("cd_ibge", *SOCIO_FIELDS)] for row in rows],
    }

    # Escrita atômica dentro do diretório do release.
    out_root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{release_id}-", dir=out_root))
    for name, payload in payloads.items():
        _write_json(tmp / name, payload)

    output_hashes = {name: _sha256(tmp / name) for name in payloads}
    output_sizes = {name: (tmp / name).stat().st_size for name in payloads}

    manifest = {
        "release_id": release_id,
        "schema_version": SCHEMA_VERSION,
        "export_version": EXPORT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origem": {
            "projeto": inputs.root.name,
            "commit_analitico_manifesto": source_commit,
            "codigo_com_alteracoes_nao_commitadas": analysis_manifest.get(
                "codigo_com_alteracoes_nao_commitadas"
            ),
            "contract_version": analysis_manifest.get("contract_version"),
        },
        "universos": {
            "municipal": "pareado_territorial",
            "municipios": int(len(rows)),
            "ufs": int(len(uf_rows)),
            "unidades_eleitorais": int(metrics["n_unidades"].sum()),
            "exterior": "fora do mapa/tabela municipal; incluído apenas no card oficial",
        },
        "cobertura": {
            "com_geometria": int(len(rows) - len(missing_geo)),
            "sem_geometria": missing_geo,
            "com_contexto": int(len(rows) - len(missing_context)),
            "sem_contexto": missing_context,
            "municipios_sem_indicador_por_campo": {
                f: int(sum(1 for r in rows if r[MUNICIPIO_FIELDS.index(f)] is None))
                for f in SOCIO_FIELDS
            },
            "malha_sem_municipio": malha_sem_municipio,
            "crosswalk_sem_metrics": len(crosswalk_sem_metrics),
        },
        "excecoes": official["excecoes"],
        "fontes": {
            "eleitoral": "TSE, votação por seção 2026; painel do projeto",
            "oficial": "TSE, Relatório de Resultado da Totalização 2026",
            "malha": {
                "produto": "IBGE — API v3 de malhas, municípios 2022, qualidade intermediária",
                "url": "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=intermediaria&intrarregiao=municipio",
                "acesso": "2026-10-30",
                "licenca": "dados abertos IBGE; atribuição obrigatória. Confirmar termos de hospedagem pública (decisão pendente do Sol).",
                "features": len(geo_codes),
            },
            "socio": dicionario["fontes"]["socio"],
            "nomes": dicionario["fontes"]["nomes"],
        },
        "hashes_entrada": input_hashes,
        "hashes_saida": output_hashes,
        "tamanhos_bytes": output_sizes,
        "validacoes": validacoes,
        "particoes": {
            "municipios": "arquivo único; 5.571 linhas; sem partição no P0",
            "mapa": "malha nacional simplificada, carregada sob demanda",
        },
        "raio": None,
        "decisoes_pendentes_sol": [
            "card nacional oficial vs pareado_total",
            "licença/atribuição da malha para hospedagem pública",
            "política para nomes divergentes TSE/IBGE",
            "indicadores socioeconômicos não agregáveis",
            "nomenclatura das faixas congeladas",
        ],
        "avisos": warnings,
    }
    _write_json(tmp / "manifest.json", manifest)
    if out_dir.exists():
        previous = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        if previous["hashes_saida"] != output_hashes or any(
            _sha256(out_dir / name) != digest for name, digest in output_hashes.items()
        ):
            raise ValueError(f"Release collision: {release_id}; existing release preserved")
        manifest = previous
        # Only this invocation's private staging directory is removed.
        shutil.rmtree(tmp)
    else:
        tmp.rename(out_dir)
    if write_pointer:
        pointer_tmp = out_root / f".pointer-{uuid.uuid4().hex}.json"
        _write_json(
            pointer_tmp,
            {
                "release_id": release_id,
                "schema_version": SCHEMA_VERSION,
                "manifest": f"{release_id}/manifest.json",
            },
        )
        os.replace(pointer_tmp, out_root / "current.json")
    return ExportResult(release_id=release_id, out_dir=out_dir, manifest=manifest, warnings=warnings)


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Exporta o release web municipal P0.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, default=None, help="diretório de releases (default: web/public/release)")
    parser.add_argument("--malha", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = args.root.resolve()
    inputs = Inputs.default(root)
    if args.malha:
        inputs.malha = args.malha
    out_root = args.out or (root / "web/public/release")
    result = export_release(inputs, out_root)
    print(f"release: {result.release_id}")
    print(f"saida:   {result.out_dir}")
    print(f"manifesto: {result.out_dir / 'manifest.json'}")
    for warning in result.warnings:
        print(f"aviso: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
