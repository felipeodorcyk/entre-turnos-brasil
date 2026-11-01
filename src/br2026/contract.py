"""Carrega os contratos v1 (contracts/v1/*.json) e valida DataFrames contra eles.

A validação é estrita: colunas, tipos, nulabilidade, enumerações, padrões,
mínimos e unicidade da chave. Violações são acumuladas e levantadas juntas,
para que o erro aponte todas as divergências de uma vez.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = PROJECT_ROOT / "contracts" / "v1"
CONTRACT_VERSION = "1.2.0"
TABLES = ("votes_long", "section_turn", "section_crosswalk", "profiles", "closure",
          "municipal_context", "panel", "panel_membership")

# Colunas acrescentadas no v1.1 que admitem nulo; `status_correspondencia` não tem
# padrão e precisa ser preenchida pela frente A a partir da fonte.
_V1_1_NULLABLE_ADDITIONS = {"profiles": {"dt_referencia_cadastro": "datetime64[ns]"}}

_INT_TYPES = {"int8", "int16", "int32", "int64"}


class ContractError(ValueError):
    def __init__(self, table: str, violations: list[str]):
        self.table, self.violations = table, violations
        super().__init__(f"{table}: {len(violations)} violação(ões) do contrato v1\n  - "
                         + "\n  - ".join(violations))


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    enum: tuple | None = None
    pattern: str | None = None
    min: float | None = None
    unit: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TableContract:
    table: str
    version: str
    owner: str
    path: str
    granularity: str
    primary_key: tuple[str, ...]
    columns: tuple[Column, ...] = field(default_factory=tuple)

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def meta_schema() -> dict:
    return _load_json(CONTRACT_DIR / "_meta.schema.json")


def load_contract(table: str) -> TableContract:
    raw = _load_json(CONTRACT_DIR / f"{table}.json")
    keys = _load_json(CONTRACT_DIR / "_keys.json")["columns"]
    cols = []
    for spec in raw["columns"]:
        if "ref" in spec:
            spec = {"name": spec["ref"], **keys[spec["ref"]]}
        spec = dict(spec)
        if "enum" in spec:
            spec["enum"] = tuple(spec["enum"])
        cols.append(Column(**spec))
    return TableContract(raw["table"], raw["version"], raw["owner"], raw["path"],
                         raw["granularity"], tuple(raw["primary_key"]), tuple(cols))


def _all(values: pd.Series, pred) -> bool:
    """Predicado sobre os valores não nulos, em Python puro.

    Evita `Series.map(...).all()`, que em pandas 3 mantém o dtype textual da
    série de origem e falha na redução quando ela está vazia (achado R16-1).
    Série vazia satisfaz o predicado (vacuamente); nulabilidade é verificada à parte.
    """
    return all(pred(v) for v in values.tolist())


def _type_ok(series: pd.Series, typ: str) -> bool:
    s = series.dropna()
    if typ in _INT_TYPES:
        return pd.api.types.is_integer_dtype(series.dtype) or _all(
            s, lambda v: isinstance(v, int) and not isinstance(v, bool))
    if typ == "float64":
        return pd.api.types.is_float_dtype(series.dtype)
    if typ == "bool":
        return pd.api.types.is_bool_dtype(series.dtype) or _all(s, lambda v: isinstance(v, bool))
    if typ == "string":
        # dtype textual (pandas StringDtype ou Arrow) só guarda texto; object é conferido valor a valor.
        textual = pd.api.types.is_string_dtype(series.dtype) and not pd.api.types.is_object_dtype(series.dtype)
        return textual or _all(s, lambda v: isinstance(v, str))
    if typ == "timestamp_tz":
        return isinstance(series.dtype, pd.DatetimeTZDtype) or s.empty
    if typ == "date":
        return pd.api.types.is_datetime64_any_dtype(series.dtype) or _all(
            s, lambda v: hasattr(v, "year") and hasattr(v, "day"))
    return False


def validate(df: pd.DataFrame, table: str) -> None:
    """Levanta ContractError com todas as violações; não modifica df."""
    c = load_contract(table)
    v: list[str] = []
    missing = [n for n in c.names if n not in df.columns]
    extra = [n for n in df.columns if n not in c.names]
    if missing:
        v.append(f"colunas ausentes: {missing}")
    if extra:
        v.append(f"colunas não previstas: {extra}")
    for col in c.columns:
        if col.name not in df.columns:
            continue
        s = df[col.name]
        if not col.nullable and s.isna().any():
            v.append(f"{col.name}: {int(s.isna().sum())} nulo(s) em coluna não anulável")
        if not _type_ok(s, col.type):
            v.append(f"{col.name}: tipo {s.dtype} incompatível com {col.type}")
            continue
        nn = s.dropna()
        if col.enum is not None and len(nn):
            bad = set(nn.unique()) - set(col.enum)
            if bad:
                v.append(f"{col.name}: valores fora da enumeração {sorted(map(str, bad))[:5]}")
        if col.pattern is not None and len(nn):
            bad = ~nn.astype(str).str.fullmatch(col.pattern)
            if bad.any():
                v.append(f"{col.name}: {int(bad.sum())} valor(es) fora do padrão {col.pattern}, "
                         f"ex. {nn[bad].iloc[0]!r}")
        if col.min is not None and len(nn) and (nn < col.min).any():
            v.append(f"{col.name}: {int((nn < col.min).sum())} valor(es) abaixo de {col.min}")
    if not missing:
        dup = df.duplicated(list(c.primary_key), keep=False)
        if dup.any():
            v.append(f"chave primária {list(c.primary_key)} duplicada em {int(dup.sum())} linha(s)")
    if v:
        raise ContractError(table, v)


_PANDAS_TYPE = {"int8": "int8", "int16": "int16", "int32": "int32", "int64": "Int64",
                "float64": "float64", "bool": "boolean", "string": object}


def read_table(path: str | Path, table: str) -> pd.DataFrame:
    """Lê um Parquet (arquivo ou diretório particionado) e devolve as colunas de partição
    com o tipo do contrato, não como categoria.

    Diretório com partições por arquivo (`<UF>_T<turno>.parquet`, gravadas pelo normalize):
    cada arquivo é lido à parte e concatenado em ordem de nome, o que reproduz o arquivo único
    anterior, inclusive nas colunas inteiramente nulas (que o Parquet grava como tipo `null`
    e a leitura em conjunto não conseguiria unificar com uma partição preenchida).
    Diretório no estilo `sg_uf=/nr_turno=`: leitura do conjunto pelo pyarrow."""
    path = Path(path)
    partes = sorted(path.glob("*.parquet")) if path.is_dir() else []
    if partes:
        df = pd.concat([pd.read_parquet(p) for p in partes], ignore_index=True)
    else:
        df = pd.read_parquet(path)
    types = {c.name: c.type for c in load_contract(table).columns}
    for col in df.columns:
        if isinstance(df[col].dtype, pd.CategoricalDtype) and col in types:
            vals = df[col].astype(object)
            t = types[col]
            if t in _INT_TYPES:
                vals = pd.to_numeric(vals)
            df[col] = vals.astype(_PANDAS_TYPE.get(t, object))
    return df


def validate_parquet(path: str | Path, table: str) -> pd.DataFrame:
    """Valida e devolve a tabela lida."""
    df = read_table(path, table)
    validate(df, table)
    return df


def migrate_v1_0(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Acrescenta as colunas anuláveis do v1.1 a uma tabela gerada no v1.0.

    Não inventa valores: `section_crosswalk.status_correspondencia` continua
    ausente e a validação falha até a frente A preenchê-la a partir da fonte.
    """
    out = df.copy()
    for col, dtype in _V1_1_NULLABLE_ADDITIONS.get(table, {}).items():
        if col not in out:
            out[col] = pd.Series(pd.NaT if "datetime" in dtype else None, index=out.index, dtype=dtype)
    return out
