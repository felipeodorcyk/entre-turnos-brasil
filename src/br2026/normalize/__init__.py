"""Normalização para staging (frente A, marco M3) — contrato v1.1.

Produz, a partir dos brutos adquiridos pelo M2 (`data/raw/` + manifesto), as
tabelas de staging `votes_long`, `section_turn` e — desde o ciclo do piloto
AC/RS/MG (26/10/2026) — as três auxiliares do v1.1: `profiles`, `closure` e
`section_crosswalk`. Cada tabela é validada por `br2026.contract.validate`
antes de virar Parquet (tmp + promoção atômica). `municipal_context` continua
fora do escopo: aguarda B listar as variáveis em `config/analysis.toml [context]`.

Regras derivadas dos dados reais (26/10/2026, piloto AC/RS/MG, presidente/T1):

- **Escopo**: só `CD_CARGO=1` (presidente). Identificadores são preenchidos com
  zeros à esquerda (`NR_ZONA`/`NR_SECAO` → 4, `CD_MUNICIPIO` → 5), conforme
  `_keys.json`.
- **`tipo_votavel`**: `NR_VOTAVEL` 95 → `BRANCO`, 96 → `NULO`, demais → `NOMINAL`.
  Não há voto de legenda para presidente em 2026/T1 (verificado: zero grupos com
  `SQ_CANDIDATO` vazio fora de 95/96).
- **`sq_candidato`**: sentinela bruta `-1` (e `''`) em branco/nulo vira **nulo**;
  para nominal, dígitos de `SQ_CANDIDATO`.
- **`cd_eleicao`** vem do conteúdo (`6257` em T1), nunca do nome do arquivo.
- **`section_turn`**: booleanos `Sim`/`Não` → True/False (nulo se vazio).
  `flag_identidade_comparecimento` fica **nula** quando
  `qt_votos_anulados_apu_sep > 0` (indeterminada, conforme `nota_v1_1` do
  contrato); `flag_identidade_aptos` é nula se algum termo ausente. Linhas que
  violam identidade são **mantidas e marcadas**, nunca removidas.
- **`source_id`** = SHA-256 do bruto registrado no manifesto (`data/raw/manifest.json`).

Tabelas auxiliares v1.1 (regras fechadas com os dados do piloto):

- **`profiles`**: perfil cadastral dos APTOS em formato longo — cada uma das
  cinco dimensões (gênero, faixa etária, grau de escolaridade, estado civil,
  raça/cor) vira uma marginal separada; dimensões nunca são somadas entre si.
  `dt_geracao` é a data de GERAÇÃO do arquivo; `dt_referencia_cadastro` fica
  **nula** (não documentada no bruto — QB-A1-02). Categoria `-1` /
  NÃO INFORMADO é preservada com `flag_desconhecido=True`.
- **`closure`**: uma linha por campo de tempo × seção, com `ts_bruto`
  preservado exatamente. Sem fuso horário documentado para os campos do BU web
  e do detalhe, `ts_brasilia` fica nula com `motivo_ausencia =
  FUSO_NAO_DOCUMENTADO` (QB-A1-01; nunca inferir fuso pela UF). Reemissões e
  substituições de urna são preservadas (múltiplas linhas) e marcadas por
  flags; nada é descartado silenciosamente.
- **`section_crosswalk`**: `EFETIVADA` vem do BU web
  (`DS_SECOES_AGREGADAS`: `#NULO#` = própria; a linha da seção apuradora lista
  as agregadas nela — verificado: 2.131/2.131 aderentes em MG entre o bweb e
  o eleitorado); `ESPERADA` vem do eleitorado local de votação
  (`CD_TIPO_SECAO_AGREGADA` 1 = própria, 2 = agregada com
  `NR_SECAO_PRINCIPAL`). Sem distribuição proporcional de votos.

`run(uf, turno)` acumula por UF/turno no Parquet único do contrato, de modo
idempotente: reprocessar a mesma UF substitui apenas as linhas dela. Turno 2 sem
bruto correspondente vira bloqueio explícito, nunca dado inventado.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import duckdb
import pandas as pd

from br2026.contract import PROJECT_ROOT, validate
from br2026.interfaces import StageResult

RAW_REL = Path("data") / "raw"
STAGING_REL = Path("data") / "staging"
MANIFEST_REL = RAW_REL / "manifest.json"

CARGO_PRESIDENTE = 1
ANO = 2026

# stem no manifesto -> membro CSV dentro do ZIP
_FONTE_VOTOS = ("votacao_secao_2026_BR", "votacao_secao_2026_BR.csv")
_FONTE_DETALHE = ("detalhe_votacao_secao_2026", "detalhe_votacao_secao_2026_BR.csv")

_COLS_VOTOS = ("CD_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
               "NR_SECAO", "CD_CARGO", "NR_VOTAVEL", "SQ_CANDIDATO", "QT_VOTOS")
_COLS_DETALHE = ("CD_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
                 "NR_SECAO", "CD_CARGO", "QT_APTOS", "QT_COMPARECIMENTO",
                 "QT_ABSTENCOES", "QT_VOTOS_NOMINAIS", "QT_VOTOS_LEGENDA",
                 "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS", "QT_VOTOS_ANULADOS_APU_SEP",
                 "NR_LOCAL_VOTACAO", "ST_SECAO_INSTALADA", "ST_SECAO_ANULADA",
                 "DS_ORIGEM_VOTO")

# --------------------------------------------------------------------------- #
# brutos das tabelas auxiliares v1.1 (piloto AC/RS/MG, 26/10/2026)             #
# --------------------------------------------------------------------------- #

# stems no manifesto (o bweb/CESP/CEFT vêm de URLs com data de snapshot no nome)
_FONTE_PERFIL = ("perfil_eleitor_secao_2026_{uf}", "perfil_eleitor_secao_2026_{uf}.csv")
_FONTE_BWEB = ("bweb_1t_{uf}_051020261403", "bweb_1t_{uf}_051020261403.csv")
_FONTE_ELEITORADO = ("eleitorado_local_votacao_2026", "eleitorado_local_votacao_2026_{uf}.csv")

_COLS_PERFIL = ("AA_ELEICAO", "DT_GERACAO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
                "NR_SECAO", "CD_GENERO", "DS_GENERO", "CD_FAIXA_ETARIA",
                "DS_FAIXA_ETARIA", "CD_GRAU_ESCOLARIDADE", "DS_GRAU_ESCOLARIDADE",
                "CD_ESTADO_CIVIL", "DS_ESTADO_CIVIL", "CD_RACA_COR", "DS_RACA_COR",
                "QT_ELEITORES")

_COLS_BWEB = ("ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
              "NR_SECAO", "DT_ABERTURA", "DT_ENCERRAMENTO", "DT_EMISSAO_BU",
              "DT_BU_RECEBIDO", "DS_SECOES_AGREGADAS", "NR_URNA_EFETIVADA",
              "CD_CARGO_PERGUNTA")

_COLS_DETALHE_TEMPO = ("CD_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO",
                       "NR_ZONA", "NR_SECAO", "CD_CARGO",
                       "DT_RECEBIMENTO_BU_HOR_TSE", "DT_PRIM_TOT_PARCIAL_HOR_TSE")

_COLS_ELEITORADO = ("NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                    "CD_TIPO_SECAO_AGREGADA", "NR_SECAO_PRINCIPAL",
                    "NR_LOCAL_VOTACAO", "NR_LOCAL_VOTACAO_ORIGINAL")

# dimensões do perfil em formato longo: (dimensao, coluna CD, coluna DS)
_DIMENSOES_PERFIL = (
    ("GENERO", "CD_GENERO", "DS_GENERO"),
    ("FAIXA_ETARIA", "CD_FAIXA_ETARIA", "DS_FAIXA_ETARIA"),
    ("GRAU_ESCOLARIDADE", "CD_GRAU_ESCOLARIDADE", "DS_GRAU_ESCOLARIDADE"),
    ("ESTADO_CIVIL", "CD_ESTADO_CIVIL", "DS_ESTADO_CIVIL"),
    ("RACA_COR", "CD_RACA_COR", "DS_RACA_COR"),
)

# bweb: coluna de tempo -> semântica do contrato de closure
_SEMANTICAS_BWEB = (
    ("DT_ABERTURA", "ABERTURA_URNA"),
    ("DT_ENCERRAMENTO", "ENCERRAMENTO_URNA"),
    ("DT_EMISSAO_BU", "EMISSAO_BU"),
    ("DT_BU_RECEBIDO", "RECEBIMENTO_BU_TSE"),
)
# detalhe de apuração: recebimento no TSE e primeira totalização (v1.1)
_SEMANTICAS_DETALHE = (
    ("DT_RECEBIMENTO_BU_HOR_TSE", "RECEBIMENTO_BU_TSE"),
    ("DT_PRIM_TOT_PARCIAL_HOR_TSE", "PRIMEIRA_TOTALIZACAO_TSE"),
)

_SENTINELA_AGREGADAS = "#NULO#"      # bweb: seção apurou em urna própria
_SENTINELA_PRINCIPAL = "-1"          # eleitorado: sem seção principal
_SEPARADOR_AGREGADAS = " / "         # bweb MG/RS: "96 / 100" (lista sem padding)
_PADRAO_BWEB = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
_PADRAO_DETALHE = r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}"
# BU por seção do portal Resultados (handoff 29): censo de `tools/censo_bu.py`, registrado no
# manifesto como `bu_portal_censo_{pleito}`; horários do bloco dadosSecao e da emissão do BU
_PADRAO_BU_PORTAL = r"\d{8}T\d{6}"
_SEMANTICAS_BU_PORTAL = (
    ("DT_ABERTURA", "ABERTURA_URNA"),
    ("DT_ENCERRAMENTO", "ENCERRAMENTO_URNA"),
    ("DT_EMISSAO_BU", "EMISSAO_BU"),
)
_PLEITO_BU_PORTAL = {1: 3220, 2: 3221}

_SENTINELAS_SQ = {"", "-1", "#NULO", "#NE"}


class NormalizeError(RuntimeError):
    """Falha de normalização com causa legível (entra em `StageResult.bloqueios`)."""


# --------------------------------------------------------------------------- #
# manifesto e extração do bruto                                                #
# --------------------------------------------------------------------------- #


def _carregar_manifesto(raiz: Path) -> dict:
    caminho = raiz / MANIFEST_REL
    if not caminho.exists():
        raise NormalizeError(f"manifesto ausente: {caminho} (rodar br2026 ingest antes)")
    import json
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise NormalizeError(f"manifesto ilegível ({e}): {caminho}")


def _source_id(manifesto: dict, stem: str, raiz: Path) -> str:
    reg = manifesto["registros"].get(stem)
    if reg is None:
        raise NormalizeError(f"{stem} sem registro no manifesto (rodar br2026 ingest)")
    caminho = raiz / RAW_REL / reg["arquivo"]
    if not caminho.exists():
        raise NormalizeError(f"bruto registrado ausente: {caminho} (rodar br2026 ingest --force)")
    return reg["sha256"]


def _extrair_membro(raiz: Path, stem: str, membro: str, sha: str) -> Path:
    """Extrai o membro CSV do ZIP para um cache estável em `data/raw/.tmp/`.

    O caminho é indexado pelo SHA-256 do bruto: reprocessar não reextrai, e
    trocar o bruto invalida o cache automaticamente.
    """
    reg = _registro_arquivo(raiz, stem)
    # o mesmo ZIP pode ter um membro por UF (eleitorado é nacional); o membro
    # entra na chave do cache, senão a UF seguinte leria o CSV da anterior
    destino = (raiz / RAW_REL / ".tmp"
               / f"{Path(reg).stem}__{Path(membro).stem}__{sha[:12]}.csv")
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    zp = raiz / RAW_REL / reg
    tmp = destino.with_suffix(".parcial")
    with zipfile.ZipFile(zp) as z, z.open(membro) as src, open(tmp, "wb") as out:
        shutil.copyfileobj(src, out, length=1 << 20)
    os.replace(tmp, destino)
    return destino


def _registro_arquivo(raiz: Path, stem: str) -> str:
    manifesto = _carregar_manifesto(raiz)
    return manifesto["registros"][stem]["arquivo"]


# --------------------------------------------------------------------------- #
# leitura com DuckDB                                                           #
# --------------------------------------------------------------------------- #


def _colunas_do_csv(caminho: Path) -> set[str]:
    """Nomes de coluna do cabeçalho do CSV (Latin-1, ';'), sem carregar o arquivo."""
    import csv
    with open(caminho, encoding="latin-1", newline="") as fh:
        primeira = fh.readline()
    return {c.strip().strip('"') for c in primeira.split(";")}


def _duck(caminho: Path, ordem: bool = True) -> duckdb.DuckDBPyConnection:
    """Conexão com teto de memória e transbordo em disco (`BR2026_DUCKDB_MEMORIA`, padrão 4GB).

    Sem teto o DuckDB usa até 80% da RAM nas somas do perfil; com o teto, o excesso vai para
    um diretório temporário ao lado do CSV, e o resultado não muda. `ordem=False` só onde a
    ordem das linhas não importa (somas re-agrupadas depois).
    """
    tmp = Path(caminho).parent / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(config={
        "memory_limit": os.environ.get("BR2026_DUCKDB_MEMORIA", "4GB"),
        "temp_directory": str(tmp),
        "preserve_insertion_order": ordem,
    })


def _ler_csv(caminho: Path, cols: tuple[str, ...], uf: str, turno: int | None,
             col_cargo: str = "CD_CARGO") -> pd.DataFrame:
    """Lê só as colunas necessárias, filtrando presidente/UF/turno, em Latin-1.

    `col_cargo` nomeia a coluna do cargo na fonte (bweb usa
    `CD_CARGO_PERGUNTA`); `turno=None` para fontes sem coluna de turno
    (perfil eleitoral é cadastral). Quando `uf="BR"` não filtra UF (arquivo
    nacional).
    """
    selecao = ", ".join(cols)
    filtros = []
    if col_cargo is not None:
        filtros.append(f"{col_cargo} = '{CARGO_PRESIDENTE}'")
    if turno is not None:
        filtros.append(f"NR_TURNO = '{turno}'")
    if uf != "BR":
        filtros.append(f"SG_UF = '{uf}'")
    where = " AND ".join(filtros) or "TRUE"
    sql = (f"SELECT {selecao} FROM read_csv('{caminho}', encoding='latin1', header=true, "
           f"delim=';', all_varchar=true) WHERE {where}")
    con = _duck(caminho)
    try:
        return con.execute(sql).df()
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# conversões de tipo (bruto -> contrato v1)                                    #
# --------------------------------------------------------------------------- #


def _zera(col: pd.Series, largura: int) -> pd.Series:
    return col.astype("string").str.strip().str.zfill(largura)


def _inteiros(col: pd.Series) -> pd.Series:
    return pd.to_numeric(col, errors="coerce").astype("Int64")


def _boleanos(col: pd.Series) -> pd.Series:
    m = col.astype("string").str.strip().str.lower()
    return m.map({"sim": True, "não": False, "nao": False}).astype("boolean")


def _construir_votes_long(bruto: pd.DataFrame, source_id: str) -> pd.DataFrame:
    df = bruto.copy()
    nr_votavel = pd.to_numeric(df["NR_VOTAVEL"], errors="coerce").astype("int32")
    tipo = nr_votavel.map({95: "BRANCO", 96: "NULO"}).fillna("NOMINAL").astype(object)

    sq = df["SQ_CANDIDATO"].astype("string").str.strip()
    sq = sq.mask(sq.isin(_SENTINELAS_SQ) | sq.isna(), None)
    sq = sq.where(pd.Series(tipo == "NOMINAL", index=df.index), None)

    out = pd.DataFrame({
        "ano": pd.Series(ANO, index=df.index, dtype="int16"),
        "cd_eleicao": df["CD_ELEICAO"].astype("string").str.strip(),
        "nr_turno": pd.to_numeric(df["NR_TURNO"], errors="coerce").astype("int8"),
        "sg_uf": df["SG_UF"].astype("string").str.strip(),
        "cd_municipio_tse": _zera(df["CD_MUNICIPIO"], 5),
        "nr_zona": _zera(df["NR_ZONA"], 4),
        "nr_secao": _zera(df["NR_SECAO"], 4),
        "cd_cargo": pd.to_numeric(df["CD_CARGO"], errors="coerce").astype("int16"),
        "nr_votavel": nr_votavel,
        "tipo_votavel": pd.Series(tipo, index=df.index, dtype="string"),
        "sq_candidato": sq.astype("string"),
        "qt_votos": pd.to_numeric(df["QT_VOTOS"], errors="coerce").astype("Int64"),
        "source_id": pd.Series(source_id, index=df.index, dtype="string"),
    })
    return out


def _hash_id(*partes: object) -> str:
    """Identificador estável e determinístico (SHA-256 hex) a partir de partes."""
    texto = "|".join("" if p is None else str(p) for p in partes)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _zera_ou_nulo(col: pd.Series, largura: int) -> pd.Series:
    """Zeros à esquerda; sentinelas (`-1`, vazio, `#NULO#`) viram nulo."""
    s = col.astype("string").str.strip()
    s = s.mask(s.isin({"", "-1", "#NULO#", "#NE", "None", "nan"}), None)
    return s.str.zfill(largura)


def _normaliza(ds: pd.Series) -> pd.Series:
    """Texto de categoria sem espaços, preservando o valor original."""
    return ds.astype("string").str.strip()


# --------------------------------------------------------------------------- #
# tabelas auxiliares v1.1: profiles, closure, section_crosswalk                #
# --------------------------------------------------------------------------- #


def _ler_perfil_agregado(caminho: Path, uf: str) -> pd.DataFrame:
    """Perfil bruto já em formato longo e somado por (seção, dimensão, categoria), no DuckDB.

    O bruto é um cruzamento de dezenas de dimensões (MG: 9,7 milhões de linhas); carregá-lo
    inteiro no pandas levava o normalize a 15 GB. Aqui as chaves ficam como texto bruto, sem
    limpeza, e `_construir_profiles` aplica a mesma limpeza de antes e soma de novo: o
    resultado é idêntico ao da leitura completa. `QT_INVALIDOS` conta valores não inteiros.
    Uma leitura por dimensão: um UNION ALL sobre a mesma CTE a materializa inteira.
    """
    chaves = "AA_ELEICAO, DT_GERACAO, SG_UF, CD_MUNICIPIO, NR_ZONA, NR_SECAO"
    filtro = "TRUE" if uf == "BR" else f"SG_UF = '{uf}'"
    con = _duck(caminho, ordem=False)
    try:
        partes = [con.execute(
            f"SELECT {chaves}, '{dim}' AS DIMENSAO, {cd} AS CD_CATEGORIA, {ds} AS DS_CATEGORIA, "
            "SUM(TRY_CAST(QT_ELEITORES AS BIGINT)) AS QT_ELEITORES, "
            "COUNT(*) FILTER (WHERE TRY_CAST(QT_ELEITORES AS BIGINT) IS NULL) AS QT_INVALIDOS "
            f"FROM read_csv('{caminho}', encoding='latin1', header=true, delim=';', "
            f"all_varchar=true) WHERE {filtro} GROUP BY ALL").df()
            for dim, cd, ds in _DIMENSOES_PERFIL]
    finally:
        con.close()
    return pd.concat(partes, ignore_index=True)


def _construir_profiles(bruto: pd.DataFrame, source_id: str) -> pd.DataFrame:
    """Perfil cadastral dos aptos em formato longo (uma linha por dimensão).

    Recebe a saída de `_ler_perfil_agregado`. Cinco marginais independentes por
    seção; as dimensões não são somadas entre si. `dt_geracao` é a data de
    GERAÇÃO do arquivo e `dt_referencia_cadastro` fica nula (não documentada no bruto).
    """
    if bruto.empty:
        raise NormalizeError("profiles: perfil eleitoral vazio para a UF/turno")
    dt_geracao = pd.to_datetime(bruto["DT_GERACAO"].astype("string").str.strip(),
                                format="%d/%m/%Y", errors="coerce")
    if dt_geracao.isna().any():
        raise NormalizeError(
            f"profiles: {int(dt_geracao.isna().sum())} DT_GERACAO inválida(s) no bruto")
    n_inv = int(pd.to_numeric(bruto["QT_INVALIDOS"]).sum())
    if n_inv:
        raise NormalizeError(f"profiles: {n_inv} QT_ELEITORES inválido(s) no bruto")
    qt = pd.to_numeric(bruto["QT_ELEITORES"], errors="coerce").astype("Int64")
    ano = pd.to_numeric(bruto["AA_ELEICAO"], errors="coerce").astype("int16")
    base = pd.DataFrame({
        "ano_referencia": ano,
        "dt_geracao": dt_geracao,
        "dt_referencia_cadastro": pd.Series(pd.NaT, index=bruto.index,
                                            dtype="datetime64[ns]"),
        "sg_uf": _normaliza(bruto["SG_UF"]),
        "cd_municipio_tse": _zera(bruto["CD_MUNICIPIO"], 5),
        "nr_zona": _zera(bruto["NR_ZONA"], 4),
        "nr_secao": _zera(bruto["NR_SECAO"], 4),
        "qt_eleitores": qt,
        "source_id": pd.Series(source_id, index=bruto.index, dtype="string"),
    })
    out = base
    out["dimensao"] = bruto["DIMENSAO"].astype("string")
    out["cd_categoria"] = _normaliza(bruto["CD_CATEGORIA"]).fillna("")
    out["ds_categoria"] = _normaliza(bruto["DS_CATEGORIA"]).fillna("")
    # o bruto é um cruzamento com dimensões adicionais (identidade de gênero,
    # quilombola, libras etc.); somar por (seção, dimensão, categoria) produz a
    # marginal do contrato — verificado: as cinco marginais fecham no total da
    # seção e o total por seção = eleitorado (AC 2.411/2.411).
    chave = ["ano_referencia", "dt_geracao", "dt_referencia_cadastro", "sg_uf",
             "cd_municipio_tse", "nr_zona", "nr_secao", "dimensao", "cd_categoria",
             "ds_categoria", "source_id"]
    out = (out.groupby(chave, dropna=False, observed=True, as_index=False)
           ["qt_eleitores"].sum())
    cd_num = pd.to_numeric(out["cd_categoria"], errors="coerce")
    out["flag_desconhecido"] = (
        (cd_num == -1) | (out["cd_categoria"] == "")
        | out["ds_categoria"].str.upper().str.contains("NÃO INFORMADO", na=False)
    ).astype("boolean")
    return out[["ano_referencia", "dt_geracao", "dt_referencia_cadastro", "sg_uf",
                "cd_municipio_tse", "nr_zona", "nr_secao", "dimensao",
                "cd_categoria", "ds_categoria", "flag_desconhecido",
                "qt_eleitores", "source_id"]]


def _ts_vazio(n: int) -> pd.Series:
    """Série `timestamp_tz` vazia (NaT) para colunas sem fuso documentado."""
    return pd.Series(pd.NaT, index=range(n),
                     dtype=pd.DatetimeTZDtype(tz="America/Sao_Paulo"))


def _linhas_horario(df: pd.DataFrame, semantica_por_coluna: tuple[tuple[str, str], ...],
                    fonte: str, source_id: str, uf: str, turno: int,
                    padrao: str, urnas_por_secao: dict | None) -> pd.DataFrame:
    """Uma linha por (seção, campo de tempo), preservando todas as emissões.

    `ts_bruto` fica exatamente como na fonte. Sem documentação de fuso, a
    normalização para America/Sao_Paulo fica nula com
    `motivo_ausencia=FUSO_NAO_DOCUMENTADO` — nunca inferida pela UF.
    """
    if df.empty:
        return pd.DataFrame()
    base = df.copy()
    base["NR_ZONA"] = _zera(base["NR_ZONA"], 4)
    base["NR_SECAO"] = _zera(base["NR_SECAO"], 4)
    if "NR_URNA_EFETIVADA" in base.columns:
        urna_da_linha = base["NR_URNA_EFETIVADA"].astype("string")
    else:
        urna_da_linha = pd.Series(None, index=base.index, dtype="string")
    base["NR_URNA_EFETIVADA"] = urna_da_linha
    blocos = []
    for coluna, semantica in semantica_por_coluna:
        bloco = base[["NR_ZONA", "NR_SECAO", "NR_URNA_EFETIVADA", "CD_MUNICIPIO",
                      coluna]].copy()
        bloco = bloco.rename(columns={coluna: "ts_bruto"})
        bloco["semantica"] = semantica
        bloco["fonte"] = fonte
        blocos.append(bloco)
    out = pd.concat(blocos, ignore_index=True)
    out["ts_bruto"] = out["ts_bruto"].astype("string").str.strip()
    out["ts_bruto"] = out["ts_bruto"].mask(out["ts_bruto"].isin({""}), None)
    out = out.drop_duplicates(subset=["NR_ZONA", "NR_SECAO", "semantica", "ts_bruto",
                                      "NR_URNA_EFETIVADA"]).reset_index(drop=True)

    # reemissão: mais de um horário distinto para o mesmo campo na mesma seção
    chave = ["NR_ZONA", "NR_SECAO", "semantica"]
    distintos = out.groupby(chave)["ts_bruto"].transform(
        lambda s: s.dropna().nunique())
    out["flag_reemissao"] = (distintos > 1).astype("boolean")

    if urnas_por_secao is not None:
        out["flag_substituicao_urna"] = [
            urnas_por_secao.get((z, s), 1) > 1
            for z, s in zip(out["NR_ZONA"], out["NR_SECAO"], strict=True)]
    else:
        out["flag_substituicao_urna"] = pd.Series(False, index=out.index,
                                                 dtype="boolean")

    valido = out["ts_bruto"].notna()
    casam = out["ts_bruto"].fillna("").str.fullmatch(padrao)
    out["flag_anomalia"] = (valido & ~casam).astype("boolean")

    out["id_registro"] = [
        _hash_id(uf, turno, z, s, sem, fonte, ts, urna, seq)
        for z, s, sem, ts, urna, seq in zip(
            out["NR_ZONA"], out["NR_SECAO"], out["semantica"], out["ts_bruto"],
            out["NR_URNA_EFETIVADA"],
            out.groupby(["NR_ZONA", "NR_SECAO", "semantica", "ts_bruto"],
                        dropna=False).cumcount(),
            strict=True)]
    out["motivo_ausencia"] = [
        ("SEM_REGISTRO" if ts is None else
         ("BRUTO_INVALIDO" if anomalo else "FUSO_NAO_DOCUMENTADO"))
        for ts, anomalo in zip(out["ts_bruto"], out["flag_anomalia"], strict=True)]
    return pd.DataFrame({
        "ano": pd.Series(ANO, index=out.index, dtype="int16"),
        "nr_turno": pd.Series(turno, index=out.index, dtype="int8"),
        "sg_uf": pd.Series(uf, index=out.index, dtype="string"),
        "cd_municipio_tse": _zera(out["CD_MUNICIPIO"], 5),
        "nr_zona": out["NR_ZONA"],
        "nr_secao": out["NR_SECAO"],
        "id_registro": out["id_registro"].astype("string"),
        "id_bu": pd.Series(None, index=out.index, dtype=object),
        "id_urna": out["NR_URNA_EFETIVADA"],
        "semantica": out["semantica"].astype("string"),
        "ts_bruto": out["ts_bruto"],
        "fuso_documentado": pd.Series(None, index=out.index, dtype=object),
        "fonte_fuso": pd.Series(None, index=out.index, dtype=object),
        "ts_brasilia": _ts_vazio(len(out)),
        "motivo_ausencia": out["motivo_ausencia"].astype("string"),
        "flag_reemissao": out["flag_reemissao"],
        "flag_substituicao_urna": out["flag_substituicao_urna"],
        "flag_anomalia": out["flag_anomalia"],
        "source_id": pd.Series(source_id, index=out.index, dtype="string"),
    })


def _construir_closure(bweb: pd.DataFrame, detalhe: pd.DataFrame, sha_bweb: str,
                       sha_detalhe: str, uf: str, turno: int) -> pd.DataFrame:
    """Registros de horário do BU web (4 campos) + detalhe (recebimento e 1ª totalização)."""
    urnas: dict[tuple[str, str], int] = {}
    if not bweb.empty:
        b = bweb.copy()
        b["NR_ZONA"] = _zera(b["NR_ZONA"], 4)
        b["NR_SECAO"] = _zera(b["NR_SECAO"], 4)
        urnas = (b.groupby(["NR_ZONA", "NR_SECAO"])["NR_URNA_EFETIVADA"]
                 .nunique(dropna=True).to_dict())
        bweb = b
    partes = []
    if not bweb.empty:
        partes.append(_linhas_horario(bweb, _SEMANTICAS_BWEB, "bweb", sha_bweb, uf,
                                      turno, _PADRAO_BWEB, urnas))
    if not detalhe.empty:
        partes.append(_linhas_horario(detalhe, _SEMANTICAS_DETALHE, "detalhe_votacao_secao",
                                      sha_detalhe, uf, turno, _PADRAO_DETALHE, urnas))
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


def _ler_bu_portal(raiz: Path, manifesto: dict, uf: str, turno: int) -> tuple[pd.DataFrame, str | None, dict]:
    """Horários do censo de BU do portal para a UF/turno: (linhas OK, SHA do resultado, contagens).

    Só entram seções com status OK (BU decodificado e identificação igual à pedida). As demais
    ficam contadas por status e fora do closure: BU de outra seção não pode dar horário a esta.
    """
    stem = f"bu_portal_censo_{_PLEITO_BU_PORTAL[turno]}"
    reg = manifesto["registros"].get(stem)
    if reg is None:
        return pd.DataFrame(), None, {}
    sha = _source_id(manifesto, stem, raiz)
    caminho = raiz / RAW_REL / reg["arquivo"]
    con = duckdb.connect()
    try:
        r = con.execute(
            f"SELECT * FROM read_json_auto('{caminho}', format='newline_delimited', union_by_name=true) "
            f"WHERE sg_uf = '{uf}'").df()
    finally:
        con.close()
    if r.empty:
        return pd.DataFrame(), sha, {}
    # retomadas podem repetir a seção (erro de rede e depois OK): vale a última tentativa terminal
    r = r.drop_duplicates(["cd_municipio_tse", "nr_zona", "nr_secao"], keep="last")
    contagem = r["status"].value_counts().to_dict()
    ok = r[r["status"] == "OK"]
    out = pd.DataFrame({
        "CD_MUNICIPIO": ok["cd_municipio_tse"].astype("string"),
        "NR_ZONA": ok["nr_zona"].astype("string"),
        "NR_SECAO": ok["nr_secao"].astype("string"),
        "DT_ABERTURA": ok["bu_abertura"].astype("string"),
        "DT_ENCERRAMENTO": ok["bu_encerramento"].astype("string"),
        "DT_EMISSAO_BU": ok["bu_emissao"].astype("string"),
        "SHA256_BU": ok["sha256"].astype("string"),
    })
    return out.reset_index(drop=True), sha, contagem


def _construir_closure_bu_portal(bu: pd.DataFrame, sha: str, uf: str, turno: int) -> pd.DataFrame:
    """Linhas de closure do BU do portal; `id_bu` = SHA-256 do bu.dat de cada seção."""
    if bu.empty:
        return pd.DataFrame()
    cl = _linhas_horario(bu, _SEMANTICAS_BU_PORTAL, "bu_portal", sha, uf, turno, _PADRAO_BU_PORTAL, None)
    ids = bu.assign(NR_ZONA=_zera(bu["NR_ZONA"], 4), NR_SECAO=_zera(bu["NR_SECAO"], 4)) \
        .set_index(["NR_ZONA", "NR_SECAO"])["SHA256_BU"]
    cl["id_bu"] = [ids.get((z, s)) for z, s in zip(cl["nr_zona"], cl["nr_secao"], strict=True)]
    return cl


def _construir_crosswalk(eleitorado: pd.DataFrame, bweb: pd.DataFrame, sha_el: str,
                         sha_bw: str, uf: str, turno: int,
                         cs_json: dict | None = None, sha_cs: str = "",
                         ceft_df: pd.DataFrame | None = None, sha_ceft: str = "",
                         detalhe_df: pd.DataFrame | None = None, sha_det: str = "") -> pd.DataFrame:
    """Correspondência seção de origem → seção apuradora (ESPERADA e EFETIVADA).

    Sem distribuição proporcional de votos: só o vínculo de apuração.

    - EFETIVADA:
      1) BU web (`bweb:DS_SECOES_AGREGADAS`): `#NULO#` = a própria seção apurou;
         uma linha com lista (`96 / 100`) é a seção apuradora e as seções listadas
         são agregadas nela. Seção listada por mais de uma apuradora vira `AMBIGUA`.
      2) presença das apuradoras no turno + eleitorado, só sem BU web: pela CEFT do turno
         (`ceft+eleitorado_local_votacao`) ou, sem ela, pelo detalhe de votação do turno
         (`detalhe+eleitorado_local_votacao`, decisão D-T2-01 do contrato v1.2.0). A agregada
         esperada só vira EFETIVADA se não tem apuração própria no turno e a principal
         esperada tem; agregada com apuração própria é conflito e vira `AMBIGUA`. Seção sem
         registro no turno não ganha linha EFETIVADA (o painel a exclui).
    - ESPERADA (eleitorado): `CD_TIPO_SECAO_AGREGADA` 1 = própria,
      2 = agregada com `NR_SECAO_PRINCIPAL`. Seção sem registro de apuração
      no turno e não listada vira `SEM_APURACAO` (nada é inferido).
    """
    linhas: list[dict] = []
    if bweb.empty and eleitorado.empty and (ceft_df is None or ceft_df.empty):
        return pd.DataFrame()

    # município e locais por (zona, seção), vindos do eleitorado
    municipio: dict[tuple[str, str], str] = {}
    locais: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    if not eleitorado.empty:
        for z, s, m, lv, lo in zip(
                _zera(eleitorado["NR_ZONA"], 4), _zera(eleitorado["NR_SECAO"], 4),
                eleitorado["CD_MUNICIPIO"].astype("string").str.strip().str.zfill(5),
                _zera_ou_nulo(eleitorado["NR_LOCAL_VOTACAO"], 4),
                _zera_ou_nulo(eleitorado["NR_LOCAL_VOTACAO_ORIGINAL"], 4), strict=True):
            municipio[(z, s)] = m
            locais[(z, s)] = (lv, lo)

    def _municipio_de(z: str, s: str) -> str:
        m = municipio.get((z, s))
        if m is None:
            raise NormalizeError(
                f"section_crosswalk: seção {z}/{s} sem município no eleitorado")
        return m

    listadas: dict[tuple[str, str], set[str]] = {}
    vistos: set[tuple[str, str]] = set()

    # ---------------- EFETIVADA (BU web) ---------------- #
    if not bweb.empty:
        b = bweb.copy()
        b["NR_ZONA"] = _zera(b["NR_ZONA"], 4)
        b["NR_SECAO"] = _zera(b["NR_SECAO"], 4)
        b["lista"] = b["DS_SECOES_AGREGADAS"].astype("string").str.strip()
        b = b.drop_duplicates(subset=["NR_ZONA", "NR_SECAO", "lista"])
        vistos = set(zip(b["NR_ZONA"], b["NR_SECAO"], strict=False))
        for z, s, lista in zip(b["NR_ZONA"], b["NR_SECAO"], b["lista"], strict=True):
            if lista is None or lista in ("", _SENTINELA_AGREGADAS):
                continue
            for item in lista.split(_SEPARADOR_AGREGADAS):
                item = item.strip().zfill(4)
                listadas.setdefault((z, item), set()).add(s)
        ambiguas: set[tuple[str, str]] = set()
        for z, s, lista in zip(b["NR_ZONA"], b["NR_SECAO"], b["lista"], strict=True):
            lv, lo = locais.get((z, s), (None, None))
            if lista is None or lista in ("", _SENTINELA_AGREGADAS):
                linhas.append(dict(
                    ano=ANO, nr_turno=turno, sg_uf=uf, cd_municipio_tse=_municipio_de(z, s),
                    nr_zona=z, nr_secao=s, nr_secao_apuradora=s,
                    nr_local_votacao=lv, nr_local_votacao_original=lo,
                    tipo_correspondencia="PROPRIA", status_correspondencia="EFETIVADA",
                    fonte="bweb:DS_SECOES_AGREGADAS", justificativa=None,
                    flag_ambigua=False, source_id=sha_bw))
                continue
            linhas.append(dict(
                ano=ANO, nr_turno=turno, sg_uf=uf, cd_municipio_tse=_municipio_de(z, s),
                nr_zona=z, nr_secao=s, nr_secao_apuradora=s,
                nr_local_votacao=lv, nr_local_votacao_original=lo,
                tipo_correspondencia="PRINCIPAL_COM_AGREGADAS",
                status_correspondencia="EFETIVADA", fonte="bweb:DS_SECOES_AGREGADAS",
                justificativa=f"seções agregadas: {lista}", flag_ambigua=False,
                source_id=sha_bw))
            for item in lista.split(_SEPARADOR_AGREGADAS):
                item = item.strip().zfill(4)
                candidatas = sorted(listadas.get((z, item), set()))
                if len(candidatas) > 1:
                    # ambígua: uma única linha por seção, emitida depois do laço
                    ambiguas.add((z, item))
                else:
                    iv, io = locais.get((z, item), (None, None))
                    linhas.append(dict(
                        ano=ANO, nr_turno=turno, sg_uf=uf,
                        cd_municipio_tse=_municipio_de(z, item), nr_zona=z,
                        nr_secao=item, nr_secao_apuradora=s,
                        nr_local_votacao=iv, nr_local_votacao_original=io,
                        tipo_correspondencia="AGREGADA_EM_OUTRA",
                        status_correspondencia="EFETIVADA",
                        fonte="bweb:DS_SECOES_AGREGADAS",
                        justificativa=f"agregada na seção {s}", flag_ambigua=False,
                        source_id=sha_bw))
        for z, item in sorted(ambiguas):
            candidatas = sorted(listadas[(z, item)])
            iv, io = locais.get((z, item), (None, None))
            linhas.append(dict(
                ano=ANO, nr_turno=turno, sg_uf=uf,
                cd_municipio_tse=_municipio_de(z, item), nr_zona=z, nr_secao=item,
                nr_secao_apuradora=None, nr_local_votacao=iv,
                nr_local_votacao_original=io, tipo_correspondencia="AMBIGUA",
                status_correspondencia="EFETIVADA",
                fonte="bweb:DS_SECOES_AGREGADAS",
                justificativa="listada por: " + ", ".join(candidatas),
                flag_ambigua=True, source_id=sha_bw))
    elif not eleitorado.empty and ((ceft_df is not None and not ceft_df.empty)
                                   or (detalhe_df is not None and not detalhe_df.empty)):
        usa_ceft = ceft_df is not None and not ceft_df.empty
        c_df = (ceft_df if usa_ceft else detalhe_df).copy()
        fonte_pres = "ceft+eleitorado_local_votacao" if usa_ceft else "detalhe+eleitorado_local_votacao"
        sha_pres = sha_ceft if usa_ceft else sha_det
        c_df["NR_ZONA"] = _zera(c_df["NR_ZONA"], 4)
        c_df["NR_SECAO"] = _zera(c_df["NR_SECAO"], 4)
        vistos = set(zip(c_df["NR_ZONA"], c_df["NR_SECAO"], strict=False))
        e_tmp = eleitorado.copy()
        e_tmp["NR_ZONA"] = _zera(e_tmp["NR_ZONA"], 4)
        e_tmp["NR_SECAO"] = _zera(e_tmp["NR_SECAO"], 4)
        agregadas_por_princ: dict[tuple[str, str], list[str]] = {}
        for z, s, tipo, principal in zip(
                e_tmp["NR_ZONA"], e_tmp["NR_SECAO"],
                e_tmp["CD_TIPO_SECAO_AGREGADA"].astype("string").str.strip(),
                _zera_ou_nulo(e_tmp["NR_SECAO_PRINCIPAL"], 4), strict=True):
            if tipo == "2" and principal:
                listadas.setdefault((z, s), set()).add(principal)
                agregadas_por_princ.setdefault((z, principal), []).append(s)
        for z, s, tipo, principal in zip(
                e_tmp["NR_ZONA"], e_tmp["NR_SECAO"],
                e_tmp["CD_TIPO_SECAO_AGREGADA"].astype("string").str.strip(),
                _zera_ou_nulo(e_tmp["NR_SECAO_PRINCIPAL"], 4), strict=True):
            lv, lo = locais.get((z, s), (None, None))
            base = dict(ano=ANO, nr_turno=turno, sg_uf=uf, cd_municipio_tse=_municipio_de(z, s),
                        nr_zona=z, nr_secao=s, nr_local_votacao=lv, nr_local_votacao_original=lo,
                        status_correspondencia="EFETIVADA", fonte=fonte_pres, source_id=sha_pres)
            if tipo == "2" and (z, s) in vistos:
                linhas.append({**base, "nr_secao_apuradora": None, "tipo_correspondencia": "AMBIGUA",
                               "justificativa": (f"agregação esperada em {principal} mas a seção tem "
                                                 "apuração própria no turno"),
                               "flag_ambigua": True})
            elif tipo == "2" and principal and (z, principal) in vistos:
                linhas.append({**base, "nr_secao_apuradora": principal,
                               "tipo_correspondencia": "AGREGADA_EM_OUTRA",
                               "justificativa": (f"agregada na seção {principal}: sem apuração própria "
                                                 "no turno e principal esperada apurada"),
                               "flag_ambigua": False})
            elif (z, s) in vistos:
                ags = sorted(agregadas_por_princ.get((z, s), []))
                linhas.append({**base, "nr_secao_apuradora": s,
                               "tipo_correspondencia": "PRINCIPAL_COM_AGREGADAS" if ags else "PROPRIA",
                               "justificativa": ("seções agregadas: " + " / ".join(ags)) if ags else None,
                               "flag_ambigua": False})

    # ---------------- ESPERADA (eleitorado) ---------------- #
    if not eleitorado.empty:
        e = eleitorado.copy()
        e["NR_ZONA"] = _zera(e["NR_ZONA"], 4)
        e["NR_SECAO"] = _zera(e["NR_SECAO"], 4)
        for z, s, tipo, principal in zip(
                e["NR_ZONA"], e["NR_SECAO"],
                e["CD_TIPO_SECAO_AGREGADA"].astype("string").str.strip(),
                _zera_ou_nulo(e["NR_SECAO_PRINCIPAL"], 4), strict=True):
            lv, lo = locais.get((z, s), (None, None))
            base = dict(ano=ANO, nr_turno=turno, sg_uf=uf,
                        cd_municipio_tse=_municipio_de(z, s), nr_zona=z, nr_secao=s,
                        nr_local_votacao=lv, nr_local_votacao_original=lo,
                        status_correspondencia="ESPERADA",
                        fonte="eleitorado_local_votacao:CD_TIPO_SECAO_AGREGADA",
                        source_id=sha_el)
            if tipo == "1":
                if (z, s) in vistos or (z, s) in listadas:
                    linhas.append({**base, "nr_secao_apuradora": s,
                                   "tipo_correspondencia": "PROPRIA",
                                   "justificativa": None, "flag_ambigua": False})
                else:
                    linhas.append({**base, "nr_secao_apuradora": None,
                                   "tipo_correspondencia": "SEM_APURACAO",
                                   "justificativa": "sem registro de apuração no BU web do turno",
                                   "flag_ambigua": False})
            elif tipo == "2":
                linhas.append({**base, "nr_secao_apuradora": principal,
                               "tipo_correspondencia": "AGREGADA_EM_OUTRA",
                               "justificativa": (f"NR_SECAO_PRINCIPAL={principal}"
                                                 if principal else
                                                 "NR_SECAO_PRINCIPAL ausente no eleitorado"),
                               "flag_ambigua": False})
            else:
                raise NormalizeError(
                    f"section_crosswalk: CD_TIPO_SECAO_AGREGADA={tipo!r} "
                    f"na seção {z}/{s} de {uf} fora do esperado (1/2)")
    out = pd.DataFrame(linhas)
    # colunas anuláveis podem ficar 100% vazias em algumas UFs (ex.: sem local de
    # votação); dtype object evita o caso degenerado do validador com string vazia
    for coluna in ("nr_secao_apuradora", "nr_local_votacao",
                   "nr_local_votacao_original", "justificativa"):
        if coluna in out.columns:
            out[coluna] = out[coluna].astype(object)
    return out


def _construir_section_turn(bruto: pd.DataFrame, source_id: str) -> pd.DataFrame:
    df = bruto.copy()
    qt_aptos = _inteiros(df["QT_APTOS"])
    qt_comp = _inteiros(df["QT_COMPARECIMENTO"])
    qt_abst = _inteiros(df["QT_ABSTENCOES"])
    qt_nom = _inteiros(df["QT_VOTOS_NOMINAIS"])
    qt_leg = _inteiros(df["QT_VOTOS_LEGENDA"])
    qt_bra = _inteiros(df["QT_VOTOS_BRANCOS"])
    qt_nul = _inteiros(df["QT_VOTOS_NULOS"])
    qt_anul = _inteiros(df["QT_VOTOS_ANULADOS_APU_SEP"])

    flag_aptos = (qt_aptos == qt_comp + qt_abst).astype("boolean")
    flag_comp = (qt_comp == qt_nom + qt_leg + qt_bra + qt_nul).astype("boolean")
    # v1.1: com anulados separados > 0 e sem regra documentada, a identidade de
    # comparecimento é indeterminada -> flag nula (nunca True/False por conveniência).
    flag_comp = flag_comp.where(qt_anul == 0, pd.NA)

    out = pd.DataFrame({
        "ano": pd.Series(ANO, index=df.index, dtype="int16"),
        "cd_eleicao": df["CD_ELEICAO"].astype("string").str.strip(),
        "nr_turno": pd.to_numeric(df["NR_TURNO"], errors="coerce").astype("int8"),
        "sg_uf": df["SG_UF"].astype("string").str.strip(),
        "cd_municipio_tse": _zera(df["CD_MUNICIPIO"], 5),
        "nr_zona": _zera(df["NR_ZONA"], 4),
        "nr_secao": _zera(df["NR_SECAO"], 4),
        "cd_cargo": pd.to_numeric(df["CD_CARGO"], errors="coerce").astype("int16"),
        "qt_aptos": qt_aptos,
        "qt_comparecimento": qt_comp,
        "qt_abstencoes": qt_abst,
        "qt_votos_nominais": qt_nom,
        "qt_votos_legenda": qt_leg,
        "qt_votos_brancos": qt_bra,
        "qt_votos_nulos": qt_nul,
        "qt_votos_anulados_apu_sep": qt_anul,
        "nr_local_votacao": _zera(df["NR_LOCAL_VOTACAO"], 4),
        "st_secao_instalada": _boleanos(df["ST_SECAO_INSTALADA"]),
        "st_secao_anulada": _boleanos(df["ST_SECAO_ANULADA"]),
        "ds_origem_voto": df["DS_ORIGEM_VOTO"].astype("string").str.strip(),
        "flag_identidade_aptos": flag_aptos,
        "flag_identidade_comparecimento": flag_comp,
        "source_id": pd.Series(source_id, index=df.index, dtype="string"),
    })
    return out


# --------------------------------------------------------------------------- #
# gravação idempotente por UF/turno                                            #
# --------------------------------------------------------------------------- #


def _particao(caminho: Path, uf: str, turno: int | None) -> Path:
    return caminho.parent / caminho.stem / (f"{uf}.parquet" if turno is None else f"{uf}_T{turno}.parquet")


def _migrar_arquivo_unico(caminho: Path) -> None:
    """Divide um staging de arquivo único (layout anterior) em partições UF × turno.

    Cada partição recebe exatamente as linhas que tinha no arquivo, na mesma ordem; o arquivo
    único só é removido depois de todas as partições gravadas.
    """
    existente = pd.read_parquet(caminho)
    chaves = ["sg_uf", "nr_turno"] if "nr_turno" in existente.columns else ["sg_uf"]
    for valores, parte in existente.groupby(chaves, sort=True):
        valores = valores if isinstance(valores, tuple) else (valores,)
        destino = _particao(caminho, valores[0], int(valores[1]) if len(valores) > 1 else None)
        _gravar_particao(parte.reset_index(drop=True), destino, caminho.stem)
    caminho.unlink()


def _particao_vigente(caminho: Path, uf: str, turno: int | None, source_id: str) -> bool:
    """A partição da UF/turno existe e veio inteira do bruto `source_id`."""
    import pyarrow.parquet as pq
    p = _particao(caminho, uf, turno)
    if caminho.exists() or not p.exists():
        return False
    ids = pq.read_table(p, columns=["source_id"]).column("source_id").unique().to_pylist()
    return ids == [source_id]


def _gravar_particao(df: pd.DataFrame, destino: Path, tabela: str) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, destino)


def _gravar_mesa(df: pd.DataFrame, caminho: Path, uf: str, turno: int | None = None,
                 ordenar_por: tuple[str, ...] | None = None) -> int:
    """Grava as linhas da UF/turno na partição própria; não toca as demais.

    `caminho` é o nome lógico da tabela (`<staging>/<tabela>.parquet`); os dados ficam em
    `<staging>/<tabela>/<UF>_T<turno>.parquet`, ou `<UF>.parquet` com `turno=None` (tabelas sem
    `nr_turno`, ex.: `profiles`). Cada gravação lê só a fatia nova, o que mantém a memória
    constante com o número de UFs. Um arquivo único do layout anterior é migrado na primeira
    gravação. Gravação atômica (tmp + os.replace). Devolve o total de linhas da tabela.
    """
    import pyarrow.parquet as pq
    ordenar = tuple(ordenar_por or ("sg_uf", "nr_turno", "cd_municipio_tse",
                                    "nr_zona", "nr_secao", "cd_cargo"))
    if caminho.exists():
        _migrar_arquivo_unico(caminho)
    if turno is not None and "nr_turno" in df.columns and not (df["nr_turno"] == turno).all():
        raise NormalizeError(f"{caminho.stem}: linhas de outro turno na gravação de {uf}/T{turno}")
    if not (df["sg_uf"] == uf).all():
        raise NormalizeError(f"{caminho.stem}: linhas de outra UF na gravação de {uf}")
    df = df.sort_values(list(ordenar), kind="stable").reset_index(drop=True)
    _gravar_particao(df, _particao(caminho, uf, turno), caminho.stem)
    pasta = caminho.parent / caminho.stem
    return sum(pq.read_metadata(p).num_rows for p in sorted(pasta.glob("*.parquet")))


# --------------------------------------------------------------------------- #
# run                                                                          #
# --------------------------------------------------------------------------- #


def run(uf: str, turno: int, project_root: Path) -> StageResult:
    """Produz `votes_long` e `section_turn` para `uf`/`turno` (presidente).

    Lê os brutos do manifesto, normaliza, valida pelo contrato v1 e grava em
    `data/staging/`. Turnos sem bruto declarado viram bloqueio explícito.
    """
    raiz = Path(project_root)
    uf = str(uf).strip().upper()
    turno = int(turno)
    if turno not in (1, 2):
        raise NormalizeError(f"turno inválido: {turno!r} (esperado 1 ou 2)")

    avisos: list[str] = []
    bloqueios: list[str] = []
    staging = raiz / STAGING_REL

    manifesto = _carregar_manifesto(raiz)

    arquivos: list[Path] = []
    linhas: dict[str, int] = {}

    # ---- votes_long e section_turn ----------------------------------------- #
    stem_v, membro_v = _FONTE_VOTOS
    sha_v = _source_id(manifesto, stem_v, raiz)
    csv_v = _extrair_membro(raiz, stem_v, membro_v, sha_v)
    bruto_v = _ler_csv(csv_v, _COLS_VOTOS, uf, turno)

    stem_d, membro_d = _FONTE_DETALHE
    sha_d = _source_id(manifesto, stem_d, raiz)
    csv_d = _extrair_membro(raiz, stem_d, membro_d, sha_d)
    bruto_d = _ler_csv(csv_d, _COLS_DETALHE, uf, turno)

    if turno == 2 and bruto_v.empty and bruto_d.empty:
        bloqueios.append(
            "votes_long/section_turn: 2º turno de votação/detalhe não anunciado no catálogo CKAN "
            "(AUSENTE_EM_26_10); sem bruto para normalizar — revalidar package_show antes de G2")
        return StageResult(etapa="normalize", arquivos=(), linhas={},
                           avisos=tuple(avisos), bloqueios=tuple(bloqueios))

    if bruto_v.empty:
        bloqueios.append(f"votes_long: nenhum voto de presidente em {uf}/T{turno} no bruto {stem_v}")
    else:
        vl = _construir_votes_long(bruto_v, sha_v)
        validate(vl, "votes_long")                     # contrato v1 estrito
        total_vl = _gravar_mesa(vl, staging / "votes_long.parquet", uf, turno)
        arquivos.append(staging / "votes_long.parquet")
        linhas["votes_long_novas"] = len(vl)
        linhas["votes_long_total"] = total_vl

    if bruto_d.empty:
        bloqueios.append(f"section_turn: nenhum total de presidente em {uf}/T{turno} no bruto {stem_d}")
    else:
        st = _construir_section_turn(bruto_d, sha_d)
        validate(st, "section_turn")
        total_st = _gravar_mesa(st, staging / "section_turn.parquet", uf, turno)
        arquivos.append(staging / "section_turn.parquet")
        linhas["section_turn_novas"] = len(st)
        linhas["section_turn_total"] = total_st
        # avisos de integridade: identidades que não fecham (mantidas e marcadas)
        n_aptos_off = int((st["flag_identidade_aptos"] == False).sum())
        n_comp_off = int((st["flag_identidade_comparecimento"] == False).sum())
        n_comp_na = int(st["flag_identidade_comparecimento"].isna().sum())
        if n_aptos_off:
            avisos.append(f"section_turn: {n_aptos_off} linha(s) com identidade de aptos violada "
                          "(mantidas e marcadas, nunca removidas)")
        if n_comp_off:
            avisos.append(f"section_turn: {n_comp_off} linha(s) com identidade de comparecimento "
                          "violada (mantidas e marcadas)")
        if n_comp_na:
            avisos.append(f"section_turn: {n_comp_na} linha(s) com comparecimento indeterminado "
                          "(qt_votos_anulados_apu_sep > 0; flag nula, QB-A1-03)")

    # ---- profiles (perfil cadastral dos aptos) ----------------------------- #
    stem_p = _FONTE_PERFIL[0].format(uf=uf)
    membro_p = _FONTE_PERFIL[1].format(uf=uf)
    if stem_p not in manifesto["registros"]:
        avisos.append(f"profiles: {stem_p} ausente do manifesto; tabela não produzida "
                      "neste ciclo (sem inferência)")
    elif turno == 2 and _particao_vigente(staging / "profiles.parquet", uf, None,
                                          _source_id(manifesto, stem_p, raiz)):
        # o perfil é cadastral, sem turno: o 1º turno sempre o regrava; no 2º, a partição
        # já gravada do mesmo bruto é a mesma tabela
        avisos.append(f"profiles: partição de {uf} já gravada a partir do mesmo bruto; reaproveitada")
    else:
        sha_p = _source_id(manifesto, stem_p, raiz)
        csv_p = _extrair_membro(raiz, stem_p, membro_p, sha_p)
        bruto_p = _ler_perfil_agregado(csv_p, uf)
        if bruto_p.empty:
            bloqueios.append(f"profiles: nenhum perfil eleitoral em {uf} no bruto {stem_p}")
        else:
            pr = _construir_profiles(bruto_p, sha_p)
            validate(pr, "profiles")
            total_pr = _gravar_mesa(pr, staging / "profiles.parquet", uf,
                                    ordenar_por=("sg_uf", "cd_municipio_tse", "nr_zona",
                                                 "nr_secao", "dimensao", "cd_categoria"))
            arquivos.append(staging / "profiles.parquet")
            linhas["profiles_novas"] = len(pr)
            linhas["profiles_total"] = total_pr
            # marginal por dimensão deve fechar no mesmo total da seção
            marginais = (pr.groupby(["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao",
                                     "dimensao"], observed=True)["qt_eleitores"].sum()
                         .unstack("dimensao"))
            if marginais.notna().all(axis=1).any():
                discordantes = (marginais.max(axis=1) != marginais.min(axis=1)).sum()
                if discordantes:
                    avisos.append(f"profiles: {discordantes} seção(ões) com marginais de "
                                  "dimensões diferentes (preservadas; verificar cadastro)")
            n_desc = int(pr["flag_desconhecido"].sum())
            if n_desc:
                avisos.append(f"profiles: {n_desc} categoria(s) desconhecida(s) preservada(s) "
                              "com flag_desconhecido (nunca remanejadas)")

    # ---- closure (horários do BU web + detalhe) ---------------------------- #
    stem_b = _FONTE_BWEB[0].format(uf=uf) if turno == 1 else f"bweb_{turno}t_{uf}"
    membro_b = _FONTE_BWEB[1].format(uf=uf) if turno == 1 else f"bweb_{turno}t_{uf}.csv"
    for k_reg, v_reg in manifesto["registros"].items():
        if not isinstance(v_reg, dict):
            continue
        if k_reg.startswith(f"bweb_{turno}t_{uf}_"):
            stem_b = k_reg
            membro_b = (v_reg.get("conteudo") or {}).get("membro_validado") or f"{k_reg}.csv"
            break
        turnos_v = {int(t) for t in (v_reg.get("turnos") or []) if str(t).isdigit()}
        turnos_obs_v = {int(t) for t in ((v_reg.get("conteudo") or {}).get("turnos_observados") or []) if str(t).isdigit()}
        if (v_reg.get("fonte") == "bweb" and str(v_reg.get("uf") or "").upper() == uf
                and turno in (turnos_v | turnos_obs_v)):
            stem_b = k_reg
            membro_b = (v_reg.get("conteudo") or {}).get("membro_validado") or f"{k_reg}.csv"
            break
    bweb = pd.DataFrame()
    sha_b = None
    if stem_b not in manifesto["registros"]:
        avisos.append(f"closure: {stem_b} ausente do manifesto; sem horários do BU web "
                      "neste ciclo (sem inferência)")
    else:
        sha_b = _source_id(manifesto, stem_b, raiz)
        csv_b = _extrair_membro(raiz, stem_b, membro_b, sha_b)
        bweb = _ler_csv(csv_b, _COLS_BWEB, uf, turno, col_cargo="CD_CARGO_PERGUNTA")
    detalhe_tempo = pd.DataFrame()
    disponiveis = _colunas_do_csv(csv_d)
    tempos = [c for c, _ in _SEMANTICAS_DETALHE]
    if all(c in disponiveis for c in tempos):
        detalhe_tempo = _ler_csv(csv_d, _COLS_DETALHE_TEMPO, uf, turno)
    else:
        avisos.append(f"closure: {stem_d} sem as colunas {tempos}; recebimento/primeira "
                      "totalização ausentes do detalhe — sem inferência")
    cl = _construir_closure(bweb, detalhe_tempo, sha_b or "", sha_d, uf, turno)
    bu_portal, sha_bp, cont_bp = _ler_bu_portal(raiz, manifesto, uf, turno)
    if sha_bp is not None:
        cl_bp = _construir_closure_bu_portal(bu_portal, sha_bp, uf, turno)
        if not cl_bp.empty:
            cl = pd.concat([cl, cl_bp], ignore_index=True) if not cl.empty else cl_bp
        linhas["bu_portal_secoes"] = len(bu_portal)
        avisos.append(f"closure: BU do portal (censo) em {uf}/T{turno}: {cont_bp}; só OK entra")
    if cl.empty:
        if stem_b in manifesto["registros"] or not detalhe_tempo.empty:
            bloqueios.append(f"closure: sem registros de horário em {uf}/T{turno} "
                             f"({stem_b} e {stem_d})")
        else:
            avisos.append(f"closure: sem fonte de horário registrada para {uf}/T{turno} "
                          f"({stem_b} ausente do manifesto e {stem_d} sem as colunas de "
                          "tempo); tabela não produzida neste ciclo")
    else:
        validate(cl, "closure")
        total_cl = _gravar_mesa(cl, staging / "closure.parquet", uf, turno,
                                ordenar_por=("sg_uf", "nr_turno", "cd_municipio_tse",
                                             "nr_zona", "nr_secao", "semantica",
                                             "id_registro"))
        arquivos.append(staging / "closure.parquet")
        linhas["closure_novas"] = len(cl)
        linhas["closure_total"] = total_cl
        n_reem = int(cl["flag_reemissao"].sum())
        n_sub = int(cl["flag_substituicao_urna"].sum())
        n_anom = int(cl["flag_anomalia"].sum())
        n_sem = int((cl["motivo_ausencia"] == "SEM_REGISTRO").sum())
        avisos.append(f"closure: {len(cl)} registros; fuso não documentado em "
                      f"{int((cl['motivo_ausencia'] == 'FUSO_NAO_DOCUMENTADO').sum())} "
                      "(ts_brasilia nula, QB-A1-01)")
        if n_reem:
            avisos.append(f"closure: {n_reem} registro(s) de reemissão preservados "
                          "(múltiplos horários por campo, flag_reemissao)")
        if n_sub:
            avisos.append(f"closure: {n_sub} registro(s) em seção(ões) com mais de uma "
                          "urna efetiva (flag_substituicao_urna)")
        if n_anom:
            avisos.append(f"closure: {n_anom} horário(s) fora do padrão da fonte "
                          "(ts_bruto preservado, motivo BRUTO_INVALIDO)")
        if n_sem:
            avisos.append(f"closure: {n_sem} campo(s) sem registro na fonte "
                          "(motivo SEM_REGISTRO)")

    # ---- section_crosswalk (ESPERADA x EFETIVADA) -------------------------- #
    stem_e = _FONTE_ELEITORADO[0]
    membro_e = _FONTE_ELEITORADO[1].format(uf=uf)
    if stem_e not in manifesto["registros"]:
        avisos.append(f"section_crosswalk: {stem_e} ausente do manifesto; tabela não "
                      "produzida neste ciclo (sem inferência)")
    else:
        sha_e = _source_id(manifesto, stem_e, raiz)
        csv_e = _extrair_membro(raiz, stem_e, membro_e, sha_e)
        eleitorado = _ler_csv(csv_e, _COLS_ELEITORADO, uf, turno, col_cargo=None)
        cs_json = None
        sha_cs = ""
        ceft_df = None
        sha_ceft = ""
        if bweb.empty:
            import json as _json_mod
            if True:
                for k_reg, v_reg in manifesto["registros"].items():
                    if not isinstance(v_reg, dict):
                        continue
                    turnos_v = {int(t) for t in (v_reg.get("turnos") or []) if str(t).isdigit()}
                    turnos_obs_v = {int(t) for t in ((v_reg.get("conteudo") or {}).get("turnos_observados") or []) if str(t).isdigit()}
                    if (v_reg.get("fonte") == "correspondencia_efetivada"
                            and str(v_reg.get("uf") or "").upper() == uf
                            and (k_reg.startswith(f"CEFT_{turno}t_{uf}_") or turno in (turnos_v | turnos_obs_v))):
                        arq_c = str(v_reg.get("arquivo") or "")
                        if arq_c.lower().endswith(".zip"):
                            sha_ceft = _source_id(manifesto, k_reg, raiz)
                            membro_c = (v_reg.get("conteudo") or {}).get("membro_validado") or f"ceft_{turno}t_{uf}.csv"
                            csv_c = _extrair_membro(raiz, k_reg, membro_c, sha_ceft)
                            ceft_df = _ler_csv(csv_c, ("SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_URNA_EFETIVADA"),
                                               uf, turno=None, col_cargo=None)
                        break
        cw = _construir_crosswalk(
            eleitorado, bweb, sha_e, sha_b or "", uf, turno,
            cs_json=cs_json, sha_cs=sha_cs, ceft_df=ceft_df, sha_ceft=sha_ceft,
            detalhe_df=bruto_d if bweb.empty else None, sha_det=sha_d,
        )
        if cw.empty:
            bloqueios.append(f"section_crosswalk: sem correspondência em {uf}/T{turno} "
                             f"({stem_e} e {stem_b})")
        else:
            validate(cw, "section_crosswalk")
            total_cw = _gravar_mesa(cw, staging / "section_crosswalk.parquet", uf, turno,
                                    ordenar_por=("sg_uf", "nr_turno", "cd_municipio_tse",
                                                 "nr_zona", "nr_secao",
                                                 "status_correspondencia",
                                                 "tipo_correspondencia"))
            arquivos.append(staging / "section_crosswalk.parquet")
            linhas["section_crosswalk_novas"] = len(cw)
            linhas["section_crosswalk_total"] = total_cw
            por_tipo = cw.groupby(["status_correspondencia", "tipo_correspondencia"],
                                  observed=True).size()
            avisos.append("section_crosswalk: " + "; ".join(
                f"{k[1]}/{k[0]}={v}" for k, v in por_tipo.items()))
            n_amb = int(cw["flag_ambigua"].sum())
            if n_amb:
                avisos.append(f"section_crosswalk: {n_amb} linha(s) ambígua(s) preservada(s) "
                              "para revisão (nunca resolvida por conveniência)")

    linhas["pico_memoria_kb"] = _pico_memoria_kb()
    return StageResult(etapa="normalize", arquivos=tuple(arquivos), linhas=linhas,
                       avisos=tuple(avisos), bloqueios=tuple(bloqueios))


def _pico_memoria_kb() -> int:
    import sys
    if sys.platform == "win32":
        from ctypes import wintypes
        import ctypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return int(c.PeakWorkingSetSize // 1024)
        return 0
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if sys.platform == "darwin" else rss // 1024)
