"""Entorno socioespacial dos locais de votação — frente C (handoff 36).

Entrega **delimitada**: inventário nacional dos locais/coordenadas, vínculo
seção–local T1/T2, aquisição versionada das malhas/agregados IBGE 2022,
consolidação de setores, buffer geodésico de 1 km com interpolação areal e
piloto em RS/AC/SE. A expansão nacional depende de revisão de Opus
(`reports/analysis/PLANO_ENTORNO_36.md`).

Decisões de método (registradas antes de olhar resultados eleitorais):

- **Buffer geodésico** de 1 km (WGS84, 64 vértices), não UTM fixa.
- **Áreas** em projeção Sinusoidal equal-area (`+proj=sinu +lon_0=-52`), com
  validação independente pela área geodésica do mesmo polígono.
- **Interpolação areal** sob hipótese de distribuição uniforme:
  ``w_i = area(S_i ∩ buffer) / area(S_i)``, truncada em [0, 1].
- **Renda** = V06004 (média do rendimento nominal mensal das pessoas
  responsáveis **com rendimentos** por domicílios particulares permanentes
  ocupados), ponderada por domicílios com renda válida. Não é renda per
  capita. A média ponderada das medianas setoriais (V06006) recebe nome
  próprio; nunca é chamada de "mediana do círculo".
- **Coordenada ausente, fora do município/UF ou conflitante** não gera
  entorno válido; centroide imputado nunca recebe renda. Ausência não vira
  zero: métricas ficam nulas com motivo.
- **Halo** de UFs vizinhas para não truncar círculos na fronteira.
- **Nenhum voto é redistribuído**; o vínculo seção–local é diagnóstico.

Uso:
    python -m br2026.ingest.entorno_nacional --ufs RS,AC,SE
    python -m br2026.ingest.entorno_nacional --ufs RS --raio 1000 --sensibilidades 500,3000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import CRS, Geod, Transformer
from shapely.geometry import Point, Polygon, box

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / "data" / "raw" / "ibge_setores"
STAGING_DIR = PROJECT_ROOT / "data" / "staging" / "entorno_local"
CACHE_STAGING = STAGING_DIR / "_cache"
MANIFEST_INSUMOS = CACHE_DIR / "manifest.json"
MANIFEST_SAIDAS = STAGING_DIR / "manifest.json"
VOTOS_GLOB = str(PROJECT_ROOT / "data" / "staging" / "votes_long" / "*.parquet")
MUNICIPAL_CONTEXT = PROJECT_ROOT / "data" / "staging" / "municipal_context.parquet"

URL_MALHA = ("https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
             "malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022/"
             "setores/gpkg/UF/{uf}/{uf}_setores_CD2022.gpkg")
URL_BASICO = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
              "Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/"
              "Agregados_por_setores_basico_BR_20260520.zip")
URL_RENDA = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
             "Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/"
             "Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip")
URL_DIC_BASICO = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
                  "Agregados_por_Setores_Censitarios/"
                  "dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx")
URL_DIC_RENDA = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
                 "Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/"
                 "dicionario_de_dados_renda_responsavel_20260508.xlsx")
URL_LOOKUP = ("https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/"
              "municipio_tse_ibge.zip")
URL_LOCAIS = "data/raw/eleitorado_local_votacao_2026.zip"

USER_AGENT = "br2026-entorno/1.0 (pesquisa; frente C)"
GEOD = Geod(ellps="WGS84")
SINU = CRS.from_proj4("+proj=sinu +lon_0=-52 +datum=WGS84 +units=m +no_defs")
_TO_SINU = Transformer.from_crs("EPSG:4674", SINU, always_xy=True)
_DE_SINU = Transformer.from_crs(SINU, "EPSG:4674", always_xy=True)

# Vizinhança estadual (fronteiras terrestres; usada só para o halo geométrico).
VIZINHOS: dict[str, tuple[str, ...]] = {
    "AC": ("AM", "RO"), "AL": ("PE", "SE", "BA"), "AM": ("AC", "RO", "MT", "PA", "RR"),
    "AP": ("PA",), "BA": ("AL", "SE", "PE", "PI", "TO", "GO", "MG", "ES"),
    "CE": ("PI", "PE", "RN", "PB"), "DF": ("GO", "MG"),
    "ES": ("BA", "MG", "RJ"), "GO": ("DF", "MG", "BA", "TO", "MT", "MS"),
    "MA": ("PI", "TO", "PA"), "MG": ("BA", "ES", "RJ", "SP", "MS", "GO", "DF"),
    "MS": ("MT", "GO", "MG", "SP", "PR"), "MT": ("AM", "PA", "TO", "GO", "MS", "RO"),
    "PA": ("AP", "MA", "TO", "MT", "AM", "RR"), "PB": ("RN", "CE", "PE"),
    "PE": ("AL", "BA", "PI", "CE", "PB"), "PI": ("MA", "TO", "BA", "PE", "CE"),
    "PR": ("SP", "MS", "SC"), "RJ": ("ES", "MG", "SP"), "RN": ("CE", "PB"),
    "RO": ("AC", "AM", "MT"), "RR": ("AM", "PA"), "RS": ("SC",),
    "SC": ("RS", "PR"), "SE": ("AL", "BA"), "SP": ("MG", "MS", "PR", "RJ"),
    "TO": ("MA", "PI", "BA", "GO", "MT", "PA"), "ZZ": (),
}

COLS_LOCAIS = (
    "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
    "NR_LOCAL_VOTACAO", "NR_LOCAL_VOTACAO_ORIGINAL", "NM_LOCAL_VOTACAO",
    "DS_ENDERECO", "NM_BAIRRO", "NR_CEP", "NR_LATITUDE", "NR_LONGITUDE",
    "CD_SITU_LOCAL_VOTACAO", "CD_TIPO_SECAO_AGREGADA", "NR_SECAO_PRINCIPAL",
    "QT_ELEITOR_SECAO",
)
COLS_MALHA = ("CD_SETOR", "SITUACAO", "CD_SIT", "CD_FCU", "CD_MUN", "CD_UF",
              "AREA_KM2")
COLS_BASICO = ("CD_SETOR", "SITUACAO", "CD_SIT", "CD_FCU", "CD_MUN", "CD_UF",
               "AREA_KM2", "v0001", "v0002", "v0005", "v0007")
COLS_RENDA = ("CD_SETOR", "V06001", "V06004", "V06006")


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 22), b""):
            h.update(bloco)
    return h.hexdigest()


def _baixar(url: str, destino: Path, timeout: int = 300, tentativas: int = 3) -> dict:
    """Download atômico com tentativas; devolve cabeçalhos remotos."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    ultimo: Exception | None = None
    for tent in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r, open(parcial, "wb") as out:
                shutil.copyfileobj(r, out, length=1 << 22)
                headers = {
                    "last_modified": r.headers.get("Last-Modified"),
                    "etag": r.headers.get("ETag"),
                    "content_length": r.headers.get("Content-Length"),
                    "status": r.status,
                }
            os.replace(parcial, destino)
            return headers
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo = e
            time.sleep(2 * tent)
    parcial.unlink(missing_ok=True)
    raise RuntimeError(f"falha ao baixar {url}: {type(ultimo).__name__}: {ultimo}")


def _carregar_manifesto() -> dict:
    if MANIFEST_INSUMOS.exists():
        return json.loads(MANIFEST_INSUMOS.read_text(encoding="utf-8"))
    return {"manifest_version": "1.0", "criado_em": _agora(), "fontes": {}}


def _gravar_json_atomico(obj: dict, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, caminho)


def adquirir(ufs: tuple[str, ...], project_root: Path = PROJECT_ROOT,
             force: bool = False) -> dict:
    """Baixa/valida malhas por UF e agregados nacionais; grava manifesto próprio."""
    cache = Path(project_root) / "data" / "raw" / "ibge_setores"
    cache.mkdir(parents=True, exist_ok=True)
    manifesto = _carregar_manifesto()

    itens: list[tuple[str, str, str]] = []
    for uf in sorted(set(ufs)):
        itens.append((f"malha_{uf}", URL_MALHA.format(uf=uf),
                      f"{uf}_setores_CD2022.gpkg"))
    itens += [
        ("basico", URL_BASICO, "Agregados_por_setores_basico_BR_20260520.zip"),
        ("renda", URL_RENDA, "Agregados_por_setores_renda_responsavel_BR_20260508.zip"),
        ("dicionario_basico", URL_DIC_BASICO,
         "dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx"),
        ("dicionario_renda", URL_DIC_RENDA,
         "dicionario_de_dados_renda_responsavel_20260508.xlsx"),
        ("lookup_municipio", URL_LOOKUP, "municipio_tse_ibge.zip"),
    ]
    for chave, url, nome in itens:
        destino = cache / nome
        headers: dict = {}
        if force or not destino.exists() or destino.stat().st_size == 0:
            headers = _baixar(url, destino)
        registro = manifesto["fontes"].get(chave, {})
        registro.update({
            "url": url, "arquivo": nome, "bytes": destino.stat().st_size,
            "sha256": _sha256(destino), "baixado_em": registro.get("baixado_em", _agora()),
            "verificado_em": _agora(), "origem": "remoto" if headers else "cache",
        })
        if headers.get("last_modified"):
            registro["last_modified"] = headers["last_modified"]
        if headers.get("etag"):
            registro["etag"] = headers["etag"]
        manifesto["fontes"][chave] = registro
    manifesto["ufs_malha"] = sorted(set(ufs))
    manifesto["atualizado_em"] = _agora()
    _gravar_json_atomico(manifesto, Path(project_root) / "data" / "raw" /
                         "ibge_setores" / "manifest.json")
    return manifesto


def ler_lookup(project_root: Path = PROJECT_ROOT) -> pd.DataFrame:
    """Lookup TSE→IBGE (5.570 municípios + exterior), validado."""
    zp = Path(project_root) / "data" / "raw" / "ibge_setores" / "municipio_tse_ibge.zip"
    with zipfile.ZipFile(zp) as z:
        membro = next(m for m in z.namelist() if m.lower().endswith(".csv"))
        with z.open(membro) as fh:
            df = pd.read_csv(fh, sep=";", encoding="latin-1", dtype=str,
                             keep_default_na=False)
    df.columns = [c.strip().strip('"') for c in df.columns]
    for col in ("CD_MUNICIPIO_TSE", "CD_MUNICIPIO_IBGE", "CD_UF_IBGE", "SG_UF"):
        df[col] = df[col].astype(str).str.strip()
    df["CD_MUNICIPIO_TSE"] = df["CD_MUNICIPIO_TSE"].str.zfill(5)
    df["CD_MUNICIPIO_IBGE"] = df["CD_MUNICIPIO_IBGE"].str.zfill(7)
    df["CD_UF_IBGE"] = df["CD_UF_IBGE"].str.zfill(2)
    dup = df.duplicated(["CD_MUNICIPIO_TSE"], keep=False)
    if dup.any():
        raise ValueError(f"lookup TSE→IBGE com {int(dup.sum())} códigos TSE duplicados")
    return df[["SG_UF", "CD_MUNICIPIO_TSE", "CD_MUNICIPIO_IBGE", "CD_UF_IBGE",
               "NM_MUNICIPIO_TSE", "NM_MUNICIPIO_IBGE"]]


def _csv_do_zip(caminho: Path, colunas: tuple[str, ...] | None = None) -> pd.DataFrame:
    with zipfile.ZipFile(caminho) as z:
        membro = next(m for m in z.namelist() if m.lower().endswith(".csv"))
        with z.open(membro) as fh:
            df = pd.read_csv(fh, sep=";", encoding="latin-1", dtype=str,
                             usecols=colunas, keep_default_na=False)
    df.columns = [c.strip().strip('"') for c in df.columns]
    return df


def _num(serie: pd.Series, zero_simbolos: bool = False,
         decimal: bool = False) -> pd.Series:
    """Converte texto TSE/IBGE; símbolos de supressão → nulo.

    `decimal=True` para renda/área/média (ponto ou vírgula decimal); `False`
    para contagens (ponto de milhar). Quando há vírgula, o ponto é milhar.
    """
    s = serie.astype(str).str.strip()
    if zero_simbolos:
        s = s.where(~s.isin({"-", ""}), "0")
    s = s.where(~s.isin({"", "-", "...", "..", "X", "x", "NA", "N/A"}), None)
    if decimal:
        s = s.where(~s.str.contains(",", regex=False, na=False),
                    s.str.replace(".", "", regex=False))
        s = s.str.replace(",", ".", regex=False)
    else:
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def ler_agregados(project_root: Path = PROJECT_ROOT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agregados básicos (população/domicílios) e de renda do responsável."""
    cache = Path(project_root) / "data" / "raw" / "ibge_setores"
    basico = _csv_do_zip(cache / "Agregados_por_setores_basico_BR_20260520.zip",
                         COLS_BASICO)
    basico["CD_SETOR"] = basico["CD_SETOR"].astype(str).str.strip().str.zfill(15)
    for col, zero, dec in (("v0001", True, False), ("v0002", True, False),
                           ("v0005", False, True), ("v0007", True, False)):
        basico[col] = _num(basico[col], zero_simbolos=zero, decimal=dec)
    basico["AREA_KM2"] = _num(basico["AREA_KM2"], decimal=True)
    basico = basico.rename(columns={"v0001": "pop", "v0002": "dom",
                                    "v0005": "mor_med", "v0007": "dom_ocup"})
    basico = basico[["CD_SETOR", "SITUACAO", "CD_SIT", "CD_FCU", "CD_MUN",
                     "CD_UF", "AREA_KM2", "pop", "dom", "mor_med", "dom_ocup"]]

    renda = _csv_do_zip(cache / "Agregados_por_setores_renda_responsavel_BR_20260508.zip",
                        COLS_RENDA)
    renda["CD_SETOR"] = renda["CD_SETOR"].astype(str).str.strip().str.zfill(15)
    renda["V06001"] = _num(renda["V06001"], zero_simbolos=True, decimal=False)
    renda["V06004"] = _num(renda["V06004"], decimal=True)
    renda["V06006"] = _num(renda["V06006"], decimal=True)
    renda = renda.rename(columns={"V06001": "resp_renda", "V06004": "renda_media",
                                  "V06006": "renda_mediana"})
    return basico, renda


# --------------------------------------------------------------------------- #
# geometria                                                                   #
# --------------------------------------------------------------------------- #


def _coords_sinu(coords: np.ndarray) -> np.ndarray:
    x, y = _TO_SINU.transform(coords[:, 0], coords[:, 1])
    return np.column_stack([x, y])


def area_m2(geom) -> float:
    """Área em m² na projeção equal-area (Sinusoidal)."""
    if geom is None or geom.is_empty:
        return 0.0
    return float(shapely.area(shapely.transform(geom, _coords_sinu)))


def area_geodesica_m2(geom) -> float:
    """Área geodésica (WGS84) — usada na validação independente."""
    if geom is None or geom.is_empty:
        return 0.0
    return float(abs(GEOD.geometry_area_perimeter(geom)[0]))


def buffer_geodesico(lon: float, lat: float, raio_m: float, vertices: int = 128) -> Polygon:
    """Círculo geodésico de raio `raio_m` em torno de (lon, lat), em EPSG:4674."""
    azimutes = np.linspace(0.0, 360.0, vertices, endpoint=False)
    lons, lats, _ = GEOD.fwd(np.full(vertices, float(lon)),
                             np.full(vertices, float(lat)),
                             azimutes, np.full(vertices, float(raio_m)))
    return Polygon(np.column_stack([lons, lats]))


def consolidar_setores(malha: gpd.GeoDataFrame, basico: pd.DataFrame,
                       renda: pd.DataFrame) -> gpd.GeoDataFrame:
    """Uma geometria e um conjunto de atributos por CD_SETOR.

    Partes repetidas idênticas são dissolvidas; atributos conflitantes bloqueiam
    o setor (`flag_conflito=True`) e ele não entra na interpolação. População e
    domicílios nunca são somados entre partes (o atributo é único por setor).
    """
    if malha.crs is None:
        malha = malha.set_crs("EPSG:4674")
    malha = malha.to_crs("EPSG:4674")
    malha["CD_SETOR"] = malha["CD_SETOR"].astype(str).str.strip().str.zfill(15)
    malha["CD_MUN"] = malha["CD_MUN"].astype(str).str.strip().str.zfill(7)
    malha["CD_UF"] = malha["CD_UF"].astype(str).str.strip().str.zfill(2)
    malha["AREA_KM2"] = pd.to_numeric(malha["AREA_KM2"], errors="coerce")
    malha["SITUACAO"] = malha["SITUACAO"].astype(str).str.strip()
    malha["CD_SIT"] = malha["CD_SIT"].astype(str).str.strip()
    malha["CD_FCU"] = malha["CD_FCU"].astype(str).str.strip()
    invalida = ~shapely.is_valid(malha.geometry.values)
    malha["geometry"] = shapely.make_valid(malha.geometry.values)
    malha["flag_geom_invalida"] = invalida
    malha = malha[~malha.geometry.is_empty & malha.geometry.notna()].copy()

    base = basico.copy()
    base["CD_SETOR"] = base["CD_SETOR"].astype(str).str.strip().str.zfill(15)
    conflito_base = (base.groupby("CD_SETOR")[["pop", "dom", "mor_med", "dom_ocup"]]
                     .nunique(dropna=False).gt(1).any(axis=1)
                     .rename("flag_conflito_basico"))
    base = base.drop_duplicates("CD_SETOR")
    rnd = renda.copy()
    rnd["CD_SETOR"] = rnd["CD_SETOR"].astype(str).str.strip().str.zfill(15)
    conflito_renda = (rnd.groupby("CD_SETOR")[["renda_media", "renda_mediana"]]
                      .nunique(dropna=False).gt(1).any(axis=1)
                      .rename("flag_conflito_renda"))
    rnd = rnd.drop_duplicates("CD_SETOR")
    df = malha.drop(columns=[c for c in ("pop", "dom", "mor_med", "dom_ocup",
                                         "renda_media", "renda_mediana",
                                         "resp_renda") if c in malha.columns])
    df = df.merge(base[["CD_SETOR", "pop", "dom", "mor_med", "dom_ocup"]],
                  on="CD_SETOR", how="left", validate="many_to_one")
    df = df.merge(rnd[["CD_SETOR", "resp_renda", "renda_media", "renda_mediana"]],
                  on="CD_SETOR", how="left", validate="many_to_one")
    df = df.merge(conflito_base, on="CD_SETOR", how="left")
    df = df.merge(conflito_renda, on="CD_SETOR", how="left")
    df["flag_conflito_basico"] = df["flag_conflito_basico"].fillna(False).astype(bool)
    df["flag_conflito_renda"] = df["flag_conflito_renda"].fillna(False).astype(bool)
    df["flag_sem_basico"] = df["pop"].isna()
    df["flag_sem_renda"] = df["renda_media"].isna()
    df["flag_urbano"] = df["SITUACAO"].eq("Urbana")
    fcu = df["CD_FCU"].str.fullmatch(r"\d+").fillna(False)
    df["flag_favela"] = fcu & ~df["CD_FCU"].str.fullmatch(r"0+").fillna(False)
    df["flag_agua"] = df["CD_SIT"].eq("9")

    attrs = ["SITUACAO", "CD_FCU", "CD_MUN", "pop", "dom", "dom_ocup",
             "renda_media", "renda_mediana"]
    conflito = (df.groupby("CD_SETOR")[attrs].nunique(dropna=False).gt(1)
                .any(axis=1))
    df["flag_conflito_atributos"] = (
        df["CD_SETOR"].map(conflito).fillna(False)
        | df["flag_conflito_basico"] | df["flag_conflito_renda"]
    )

    agregacao = {c: "first" for c in df.columns if c not in ("CD_SETOR", "geometry")}
    agregacao["flag_conflito_atributos"] = "max"
    agregacao["flag_geom_invalida"] = "max"
    out = df.dissolve(by="CD_SETOR", aggfunc=agregacao, as_index=False)
    out["geometry"] = shapely.make_valid(out.geometry.values)
    out["area_m2"] = shapely.area(shapely.transform(out.geometry.values, _coords_sinu))
    out["area_km2_calc"] = out["area_m2"] / 1e6
    out["flag_area_divergente"] = (
        (out["AREA_KM2"].notna())
        & ((out["area_km2_calc"] - out["AREA_KM2"]).abs()
           / out["AREA_KM2"].replace(0, np.nan) > 0.10)
    )
    out["flag_area_zero"] = out["area_m2"] <= 0
    out["flag_elegivel"] = (
        ~out["flag_conflito_atributos"]
        & ~out["flag_sem_basico"]
        & ~out["flag_area_zero"]
        & ~out["flag_geom_invalida"]
        & out["geometry"].notna()
    )
    return gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4674")


def preparar_setores(setores: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, np.ndarray,
                                                        shapely.STRtree, dict]:
    """Projeta setores, monta a árvore espacial e os vetores de atributos."""
    if len(setores) == 0:
        return setores, np.array([], dtype=object), None, {}
    proj = setores.to_crs(SINU)
    geoms = proj.geometry.values
    areas = shapely.area(geoms).astype(float)
    arr = {
        "area": areas,
        "pop": setores["pop"].fillna(0).to_numpy(dtype=float),
        "dom": setores["dom"].fillna(0).to_numpy(dtype=float),
        "dom_ocup": setores["dom_ocup"].fillna(0).to_numpy(dtype=float),
        "mor_med": setores["mor_med"].fillna(0).to_numpy(dtype=float),
        # responsáveis em DPP ocupados (V06001): universo da renda média V06004 (decisão D37-E4)
        # sem fallback: setores consolidados sem a coluna vêm de regra antiga e devem falhar (R38-2)
        "resp": setores["resp_renda"].to_numpy(dtype=float),
        "renda_media": setores["renda_media"].to_numpy(dtype=float),
        "renda_mediana": setores["renda_mediana"].to_numpy(dtype=float),
        "urbano": setores["flag_urbano"].to_numpy(dtype=bool),
        "favela": setores["flag_favela"].to_numpy(dtype=bool),
        "elegivel": setores["flag_elegivel"].to_numpy(dtype=bool),
    }
    tree = shapely.STRtree(setores.geometry.values)
    return proj, geoms, tree, arr


def interpolar(buffer: Polygon, geoms, tree: shapely.STRtree, arr: dict,
               buffer_area_m2: float, raio_m: int) -> dict:
    """Interpolação areal de um buffer sobre os setores (árvore em lon/lat)."""
    vazio = {
        "setores_n": 0, "cobertura_area": 0.0,
        "populacao_estimada": np.nan, "domicilios_estimados": np.nan,
        "domicilios_ocupados_estimados": np.nan, "moradores_por_domicilio": np.nan,
        "densidade_hab_km2": np.nan, "pct_pop_urbana": np.nan,
        "pct_pop_favela": np.nan, "renda_media_responsavel": np.nan,
        "renda_media_responsavel_peso_domicilios": np.nan,
        "renda_mediana_responsavel_setores": np.nan, "cobertura_renda": np.nan,
    }
    if tree is None:
        return vazio
    idx = tree.query(buffer)
    if len(idx) == 0:
        return vazio
    buf_proj = shapely.transform(buffer, _coords_sinu)
    inter = shapely.intersection(buf_proj, geoms[idx])
    areas_i = shapely.area(inter)
    areas_s = arr["area"][idx]
    frac = np.clip(np.divide(areas_i, areas_s, out=np.zeros_like(areas_i),
                             where=areas_s > 0), 0.0, 1.0)
    eleg = arr["elegivel"][idx] & (areas_i > 1e-6)
    cobertura = float(np.clip(areas_i.sum() / buffer_area_m2, 0.0, 1.0))
    if not eleg.any():
        return {**vazio, "cobertura_area": cobertura}

    f = frac[eleg]
    pop = float((f * arr["pop"][idx][eleg]).sum())
    dom = float((f * arr["dom"][idx][eleg]).sum())
    docu = float((f * arr["dom_ocup"][idx][eleg]).sum())
    mor = float((f * arr["dom_ocup"][idx][eleg] * arr["mor_med"][idx][eleg]).sum())
    pop_urb = float((f * arr["pop"][idx][eleg] * arr["urbano"][idx][eleg]).sum())
    pop_fav = float((f * arr["pop"][idx][eleg] * arr["favela"][idx][eleg]).sum())

    # renda (D37-E4): peso principal = responsáveis em DPP ocupados estimados (V06001 × fração),
    # o universo de V06004; sensibilidade = domicílios totais estimados (V0002), a fórmula da base
    # RS. Setor sem renda válida fica fora do numerador e do denominador (ausente não é zero), e a
    # cobertura de renda é medida na mesma base do peso.
    rm, rmed = arr["renda_media"][idx][eleg], arr["renda_mediana"][idx][eleg]
    resp = arr["resp"][idx][eleg] if "resp" in arr else np.full(len(f), np.nan)
    base_resp = np.where(np.isfinite(resp), f * resp, 0.0)
    ok_m, ok_med = np.isfinite(rm) & (rm > 0), np.isfinite(rmed) & (rmed > 0)
    peso = np.where(ok_m, base_resp, 0.0)
    peso_med = np.where(ok_med, base_resp, 0.0)
    peso_dom = np.where(ok_m, f * arr["dom"][idx][eleg], 0.0)
    peso_total, peso_med_total, peso_dom_total = float(peso.sum()), float(peso_med.sum()), float(peso_dom.sum())
    renda = float((np.where(ok_m, rm, 0.0) * peso).sum() / peso_total) if peso_total > 0 else np.nan
    renda_med = (float((np.where(ok_med, rmed, 0.0) * peso_med).sum() / peso_med_total)
                 if peso_med_total > 0 else np.nan)
    renda_dom = (float((np.where(ok_m, rm, 0.0) * peso_dom).sum() / peso_dom_total)
                 if peso_dom_total > 0 else np.nan)
    base_total = float(base_resp.sum())
    cobertura_renda = (peso_total / base_total) if base_total > 0 else np.nan

    area_km2 = math.pi * (raio_m / 1000.0) ** 2
    return {
        "setores_n": int(eleg.sum()),
        "cobertura_area": cobertura,
        "populacao_estimada": pop,
        "domicilios_estimados": dom,
        "domicilios_ocupados_estimados": docu,
        "moradores_por_domicilio": (mor / docu) if docu > 0 else np.nan,
        "densidade_hab_km2": (pop / area_km2) if area_km2 > 0 else np.nan,
        "pct_pop_urbana": (100.0 * pop_urb / pop) if pop > 0 else np.nan,
        "pct_pop_favela": (100.0 * pop_fav / pop) if pop > 0 else np.nan,
        "renda_media_responsavel": renda,
        "renda_media_responsavel_peso_domicilios": renda_dom,
        "renda_mediana_responsavel_setores": renda_med,
        "cobertura_renda": cobertura_renda,
    }


def _coord(serie: pd.Series) -> pd.Series:
    """Latitude/longitude TSE: vírgula decimal, sem separador de milhar."""
    s = serie.astype(str).str.strip().str.replace(",", ".", regex=False)
    s = s.where(~s.isin({"", "-1", "0", "0.0", "-1.0", "nan", "None"}), None)
    return pd.to_numeric(s, errors="coerce")


def inventariar_locais(ufs: tuple[str, ...] | None = None,
                       project_root: Path = PROJECT_ROOT) -> pd.DataFrame:
    """Cadastro nacional de locais/seções T1/T2, com coordenadas normalizadas."""
    zp = Path(project_root) / URL_LOCAIS
    alvo = {u.upper() for u in ufs} if ufs else None
    partes: list[pd.DataFrame] = []
    with zipfile.ZipFile(zp) as z:
        membros = [m for m in z.namelist()
                   if m.lower().endswith(".csv")
                   and "eleitorado_local_votacao_2026_" in m
                   and not m.lower().endswith("_brasil.csv")]
        for membro in sorted(membros):
            uf = membro.rsplit("_", 1)[-1].split(".")[0].upper()
            if alvo is not None and uf not in alvo:
                continue
            with z.open(membro) as fh:
                df = pd.read_csv(fh, sep=";", encoding="latin-1", dtype=str,
                                 usecols=list(COLS_LOCAIS), keep_default_na=False)
            df.columns = [c.strip().strip('"') for c in df.columns]
            for col in ("NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO",
                        "NR_LOCAL_VOTACAO_ORIGINAL", "NR_SECAO_PRINCIPAL"):
                if col in df.columns:
                    df[col] = df[col].astype(str).str.strip()
            df["SG_UF"] = df["SG_UF"].astype(str).str.strip().str.upper()
            df["CD_MUNICIPIO"] = df["CD_MUNICIPIO"].astype(str).str.strip().str.zfill(5)
            df["NR_ZONA"] = df["NR_ZONA"].str.zfill(4)
            df["NR_SECAO"] = df["NR_SECAO"].str.zfill(4)
            local = df["NR_LOCAL_VOTACAO"].where(
                ~df["NR_LOCAL_VOTACAO"].isin({"-1", "", "0"}), df["NR_LOCAL_VOTACAO_ORIGINAL"])
            local = local.where(~local.isin({"-1", "", "0"}), None)
            df["NR_LOCAL_ADOTADO"] = local.str.zfill(4) if local.notna().any() else local
            df["id_local"] = np.where(
                df["NR_LOCAL_ADOTADO"].notna(),
                df["SG_UF"] + "_" + df["CD_MUNICIPIO"] + "_" + df["NR_ZONA"] + "_"
                + df["NR_LOCAL_ADOTADO"], None)
            df["id_secao"] = (df["SG_UF"] + "_" + df["CD_MUNICIPIO"] + "_"
                              + df["NR_ZONA"] + "_" + df["NR_SECAO"])
            df["nr_turno"] = pd.to_numeric(df["NR_TURNO"], errors="coerce").astype("int8")
            df["lat"] = _coord(df["NR_LATITUDE"])
            df["lon"] = _coord(df["NR_LONGITUDE"])
            df["coord_valida_bruta"] = (
                df["lat"].between(-34.0, 6.0) & df["lon"].between(-74.0, -32.0)
                & df["lat"].notna() & df["lon"].notna()
            )
            df["qt_eleitor"] = _num(df["QT_ELEITOR_SECAO"], zero_simbolos=True)
            df["flag_ativo"] = df["CD_SITU_LOCAL_VOTACAO"].astype(str).str.strip().eq("1")
            df["flag_agregada"] = df["CD_TIPO_SECAO_AGREGADA"].astype(str).str.strip().eq("2")
            df["nr_secao_principal"] = df["NR_SECAO_PRINCIPAL"].str.zfill(4)
            df.loc[~df["flag_agregada"], "nr_secao_principal"] = None
            df["nm_local"] = df["NM_LOCAL_VOTACAO"].astype(str).str.strip()
            df["ds_endereco"] = df["DS_ENDERECO"].astype(str).str.strip()
            df["nm_bairro"] = df["NM_BAIRRO"].astype(str).str.strip()
            df["nr_cep"] = df["NR_CEP"].astype(str).str.strip()
            partes.append(df[["SG_UF", "CD_MUNICIPIO", "nr_turno", "NR_ZONA",
                              "NR_SECAO", "NR_LOCAL_ADOTADO", "id_local", "id_secao",
                              "nm_local", "ds_endereco", "nm_bairro", "nr_cep",
                              "lat", "lon", "coord_valida_bruta", "qt_eleitor",
                              "flag_ativo", "flag_agregada", "nr_secao_principal"]])
    if not partes:
        return pd.DataFrame()
    out = pd.concat(partes, ignore_index=True)
    lookup = ler_lookup(project_root)
    out = out.merge(lookup[["SG_UF", "CD_MUNICIPIO_TSE", "CD_MUNICIPIO_IBGE",
                            "CD_UF_IBGE"]],
                    left_on=["SG_UF", "CD_MUNICIPIO"], right_on=["SG_UF", "CD_MUNICIPIO_TSE"],
                    how="left", validate="many_to_one")
    out = out.rename(columns={"CD_MUNICIPIO": "cd_municipio_tse",
                              "CD_MUNICIPIO_IBGE": "cd_municipio_ibge"})
    dup = out.duplicated(["id_secao", "nr_turno"], keep=False)
    if dup.any():
        raise ValueError(f"inventário com {int(dup.sum())} seções duplicadas por turno")
    return out


def consolidar_locais(locais: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (turno, id_local), com coordenada modal e flags de qualidade."""
    df = locais[locais["id_local"].notna()].copy()
    if df.empty:
        return pd.DataFrame()
    df["lat_r"] = df["lat"].round(7)
    df["lon_r"] = df["lon"].round(7)
    coords = df.dropna(subset=["lat_r", "lon_r"])
    contagem = (coords.groupby(["nr_turno", "id_local", "lat_r", "lon_r"], dropna=False)
                .size().reset_index(name="n_coord"))
    contagem = contagem.sort_values(["nr_turno", "id_local", "n_coord"],
                                    ascending=[True, True, False])
    primeira = contagem.drop_duplicates(["nr_turno", "id_local"])
    maximo = contagem.groupby(["nr_turno", "id_local"])["n_coord"].transform("max")
    empate = (contagem.assign(maximo=maximo)
              .groupby(["nr_turno", "id_local"])["n_coord"]
              .apply(lambda s: int((s == s.max()).sum() > 1)).rename("empate"))
    n_coords = (contagem.groupby(["nr_turno", "id_local"])["lat_r"]
                .size().rename("n_coords"))

    base = (df.sort_values(["nr_turno", "id_local"])
            .drop_duplicates(["nr_turno", "id_local"])
            [["nr_turno", "id_local", "SG_UF", "cd_municipio_tse", "cd_municipio_ibge",
              "NR_ZONA", "NR_LOCAL_ADOTADO", "nm_local", "ds_endereco", "nm_bairro",
              "nr_cep", "flag_ativo", "coord_valida_bruta"]])
    base = base.merge(primeira[["nr_turno", "id_local", "lat_r", "lon_r", "n_coord"]],
                      on=["nr_turno", "id_local"], how="left")
    base = base.merge(n_coords, on=["nr_turno", "id_local"], how="left")
    base = base.merge(empate.reset_index(), on=["nr_turno", "id_local"], how="left")
    base["flag_coord_conflitante"] = base["n_coords"].fillna(0).gt(1)
    base["flag_coord_ambigua"] = (
        base["flag_coord_conflitante"] & base["empate"].fillna(0).astype(bool)
    )
    base["coord_valida"] = (
        base["coord_valida_bruta"] & base["lat_r"].notna() & base["lon_r"].notna()
        & ~base["flag_coord_ambigua"]
    )
    # seções e aptos do local, por turno
    agg = (df.groupby(["nr_turno", "id_local"])
           .agg(n_secoes=("id_secao", "nunique"),
                aptos=("qt_eleitor", "sum"))
           .reset_index())
    base = base.merge(agg, on=["nr_turno", "id_local"], how="left")
    # pontos repetidos: mesma coordenada em locais distintos (pode ser legítimo)
    rep = (base.dropna(subset=["lat_r", "lon_r"])
           .groupby(["nr_turno", "SG_UF", "lat_r", "lon_r"]).size()
           .rename("n_locais_ponto"))
    base = base.merge(rep.reset_index(), on=["nr_turno", "SG_UF", "lat_r", "lon_r"],
                      how="left")
    base["flag_ponto_repetido"] = base["n_locais_ponto"].fillna(1).gt(1)
    return base.reset_index(drop=True)


def auditar_coordenadas(locais: pd.DataFrame,
                        setores_uf: gpd.GeoDataFrame,
                        tolerancia_municipio_m: float = 100.0) -> pd.DataFrame:
    """Point-in-polygon contra município e UF; flags sem descartar linhas.

    Coordenada fora do município por até `tolerancia_municipio_m` é tratada
    como precisão de limite (`flag_coord_limite_municipio`), não como erro
    grosseiro; fora da UF é inválida. A tolerância é registrada e pode ser
    revista por Opus.
    """
    if locais.empty:
        return locais
    out = locais.copy()
    out["flag_coord_fora_municipio"] = False
    out["flag_coord_fora_uf"] = False
    out["flag_coord_limite_municipio"] = False
    out["dist_municipio_m"] = np.nan
    out["municipio_contido"] = None
    validos = out["coord_valida"].fillna(False) & out["lat_r"].notna()
    if not validos.any():
        return out
    municipios = setores_uf.dissolve(by="CD_MUN", as_index=False)[["CD_MUN", "geometry"]]
    municipios_proj = municipios.to_crs(SINU)
    uf_geom = shapely.union_all(municipios.geometry.values)
    pontos = gpd.GeoDataFrame(
        out.loc[validos, ["id_local", "nr_turno", "cd_municipio_ibge", "lat_r", "lon_r"]].copy(),
        geometry=gpd.points_from_xy(out.loc[validos, "lon_r"], out.loc[validos, "lat_r"]),
        crs="EPSG:4674")
    junta = gpd.sjoin(pontos, municipios.rename(columns={"CD_MUN": "mun_contido"}),
                      how="left", predicate="intersects")
    junta["esperado"] = junta["cd_municipio_ibge"].astype(str) == junta["mun_contido"].astype(str)
    melhor = (junta.sort_values(["id_local", "nr_turno", "esperado"],
                                ascending=[True, True, False])
              .drop_duplicates(["id_local", "nr_turno"]))
    mapa = melhor.set_index(["id_local", "nr_turno"])[["mun_contido", "esperado"]]
    pontos_proj = pontos.to_crs(SINU)
    for pos, (idx, row) in enumerate(out.loc[validos].iterrows()):
        chave = (row["id_local"], row["nr_turno"])
        if chave in mapa.index:
            mun = mapa.loc[chave, "mun_contido"]
            esperado = bool(mapa.loc[chave, "esperado"])
            out.at[idx, "municipio_contido"] = mun
            out.at[idx, "flag_coord_fora_municipio"] = not esperado
            if not esperado:
                esp = municipios_proj[municipios_proj["CD_MUN"]
                                      == str(row["cd_municipio_ibge"]).zfill(7)]
                if len(esp):
                    dist = float(esp.geometry.distance(pontos_proj.geometry.iloc[pos]).iloc[0])
                    out.at[idx, "dist_municipio_m"] = dist
                    if dist <= tolerancia_municipio_m:
                        out.at[idx, "flag_coord_limite_municipio"] = True
        else:
            out.at[idx, "flag_coord_fora_municipio"] = True
    dentro_uf = shapely.intersects(uf_geom, pontos.geometry.values)
    for idx, ok in zip(out.loc[validos].index, dentro_uf, strict=True):
        out.at[idx, "flag_coord_fora_uf"] = not bool(ok)
    out["flag_coord_valida"] = (
        out["coord_valida"].fillna(False)
        & ~out["flag_coord_fora_uf"]
        & (~out["flag_coord_fora_municipio"] | out["flag_coord_limite_municipio"])
    )
    return out


def vincular_secoes(inventario: pd.DataFrame, uf: str) -> pd.DataFrame:
    """Tabela seção–local por turno, com apuradora e mudanças T1/T2."""
    sec = inventario[inventario["SG_UF"] == uf].copy()
    if sec.empty:
        return pd.DataFrame()
    sec = sec.drop_duplicates(["id_secao", "nr_turno"])
    # local apurador: para seção agregada, o local da seção principal no mesmo turno
    principal = sec[["nr_turno", "cd_municipio_tse", "NR_ZONA", "NR_SECAO",
                     "id_local", "lat", "lon", "flag_agregada"]].rename(
        columns={"NR_SECAO": "nr_secao_principal", "id_local": "id_local_apurador",
                 "lat": "lat_apurador", "lon": "lon_apurador",
                 "flag_agregada": "flag_agregada_apuradora"})
    sec = sec.merge(principal, on=["nr_turno", "cd_municipio_tse", "NR_ZONA",
                                   "nr_secao_principal"], how="left",
                    suffixes=("", "_p"))
    sec["flag_local_apurador_ausente"] = sec["flag_agregada"] & sec["id_local_apurador"].isna()
    sec.loc[~sec["flag_agregada"], "id_local_apurador"] = sec.loc[
        ~sec["flag_agregada"], "id_local"]

    # mudanças T1/T2
    t1 = sec[sec["nr_turno"] == 1].set_index("id_secao")
    t2 = sec[sec["nr_turno"] == 2].set_index("id_secao")
    mudou = (t1["id_local"].reindex(t2.index).notna()
             & t2["id_local"].notna()
             & (t1["id_local"].reindex(t2.index) != t2["id_local"]))
    novo = t2.index.difference(t1.index)
    ausente = t1.index.difference(t2.index)
    sec["flag_mudou_local"] = sec["id_secao"].map(mudou).fillna(False)
    sec["flag_novo_t2"] = sec["id_secao"].isin(novo)
    sec["flag_ausente_t2"] = sec["id_secao"].isin(ausente)
    return sec[[
        "SG_UF", "cd_municipio_tse", "cd_municipio_ibge", "nr_turno", "NR_ZONA",
        "NR_SECAO", "id_secao", "id_local", "id_local_apurador", "nr_secao_principal",
        "flag_agregada", "flag_local_apurador_ausente", "flag_ativo",
        "coord_valida_bruta", "lat", "lon", "flag_mudou_local", "flag_novo_t2",
        "flag_ausente_t2",
    ]].rename(columns={"SG_UF": "sg_uf", "NR_ZONA": "nr_zona", "NR_SECAO": "nr_secao"})


# Versão das regras de `consolidar_setores`/`COLS_*`: mudar quando a consolidação mudar, para invalidar os
# caches feitos com a regra antiga (R38-2).
VERSAO_CONSOLIDACAO = "2026-10-28.1"
_SHA_MEMO: dict[tuple, str] = {}


def _sha256_memo(caminho: Path) -> str:
    """SHA-256 do arquivo, memorizado por (caminho, tamanho, mtime) dentro do processo."""
    st = caminho.stat()
    k = (str(caminho.resolve()), st.st_size, st.st_mtime_ns)
    if k not in _SHA_MEMO:
        _SHA_MEMO[k] = _sha256(caminho)
    return _SHA_MEMO[k]


def _hash_frame(df: pd.DataFrame) -> str:
    """Hash do conteúdo (independente da ordem das linhas) de um recorte de agregados."""
    s = df.sort_values("CD_SETOR", kind="mergesort").reset_index(drop=True)
    h = hashlib.sha256("|".join(map(str, s.columns)).encode("utf-8"))
    h.update(pd.util.hash_pandas_object(s, index=False).to_numpy().tobytes())
    return h.hexdigest()


def chave_cache_setores(uf: str, malha_path: Path, b: pd.DataFrame, r: pd.DataFrame) -> dict:
    """Tudo de que o cache consolidado da UF depende: conteúdo da malha, dos agregados básicos e da renda
    da UF, e a versão da consolidação. O cache só é reutilizado se a chave gravada for idêntica."""
    partes = {"uf": uf, "versao_consolidacao": VERSAO_CONSOLIDACAO,
              "malha_sha256": _sha256_memo(malha_path),
              "basico_hash": _hash_frame(b), "renda_hash": _hash_frame(r)}
    return {**partes, "chave": _hash_texto(*partes.values())}


def _recortes_uf(uf: str, basico: pd.DataFrame, renda: pd.DataFrame,
                 project_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    lookup = ler_lookup(project_root)
    uf_ibge = lookup.loc[lookup["SG_UF"] == uf, "CD_UF_IBGE"]
    if uf_ibge.empty:
        raise ValueError(f"UF {uf} ausente do lookup TSE→IBGE")
    uf_ibge = uf_ibge.iloc[0]
    return (basico[basico["CD_SETOR"].str[:2] == uf_ibge],
            renda[renda["CD_SETOR"].str[:2] == uf_ibge])


def _consolidar_uf(malha_path: Path, b: pd.DataFrame, r: pd.DataFrame) -> gpd.GeoDataFrame:
    malha = pyogrio.read_dataframe(malha_path, columns=list(COLS_MALHA))
    malha.columns = [str(c) for c in malha.columns]
    return consolidar_setores(malha, b, r)


def _gravar_cache(setores: gpd.GeoDataFrame, destino: Path, chave: dict, **extra) -> None:
    meta = destino.with_suffix(".chave.json")
    meta.unlink(missing_ok=True)  # parquet novo sem chave nunca passa por válido
    tmp = destino.with_suffix(".parquet.tmp")
    setores.to_parquet(tmp, index=False)
    os.replace(tmp, destino)
    _gravar_json_atomico({**chave, "gerado_em": _agora(), **extra}, meta)


def carregar_setores(uf: str, basico: pd.DataFrame, renda: pd.DataFrame,
                     project_root: Path = PROJECT_ROOT,
                     force: bool = False, chaves: dict | None = None) -> gpd.GeoDataFrame:
    """Malha consolidada da UF (cache GeoParquet), com agregados e renda.

    O cache traz ao lado um `.chave.json` com a chave de `chave_cache_setores`; sem chave, ou com chave
    diferente da dos insumos atuais, ele é refeito (R38-2). Vale igualmente para UFs vizinhas do halo.
    `chaves`, se dado, recebe a chave efetivamente usada, para a proveniência das saídas."""
    cache = Path(project_root) / "data" / "staging" / "entorno_local" / "_cache"
    cache.mkdir(parents=True, exist_ok=True)
    destino = cache / f"setores_{uf}.parquet"
    meta = destino.with_suffix(".chave.json")
    malha_path = (Path(project_root) / "data" / "raw" / "ibge_setores"
                  / f"{uf}_setores_CD2022.gpkg")
    if not malha_path.exists():
        raise FileNotFoundError(malha_path)
    b, r = _recortes_uf(uf, basico, renda, project_root)
    chave = chave_cache_setores(uf, malha_path, b, r)
    if chaves is not None:
        chaves[uf] = chave["chave"]
    if destino.exists() and meta.exists() and not force:
        if json.loads(meta.read_text(encoding="utf-8")).get("chave") == chave["chave"]:
            return gpd.read_parquet(destino)
        print(f"  [cache] setores_{uf}: chave diverge dos insumos atuais; refazendo")
    setores = _consolidar_uf(malha_path, b, r)
    _gravar_cache(setores, destino, chave)
    return setores


def validar_cache_setores(uf: str, basico: pd.DataFrame, renda: pd.DataFrame,
                          project_root: Path = PROJECT_ROOT) -> str:
    """Confere um cache sem chave (anterior a R38-2) refazendo a consolidação em memória: se o conteúdo for
    idêntico, grava a chave atual (`IDENTICO`); se não, substitui o cache (`REFEITO`) e os consumidores
    precisam ser refeitos. Com a chave já igual à dos insumos, `CHAVE_OK`."""
    destino = Path(project_root) / "data" / "staging" / "entorno_local" / "_cache" / f"setores_{uf}.parquet"
    meta = destino.with_suffix(".chave.json")
    malha_path = (Path(project_root) / "data" / "raw" / "ibge_setores"
                  / f"{uf}_setores_CD2022.gpkg")
    b, r = _recortes_uf(uf, basico, renda, project_root)
    chave = chave_cache_setores(uf, malha_path, b, r)
    if meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("chave") == chave["chave"]:
        return "CHAVE_OK"
    novo = _consolidar_uf(malha_path, b, r)
    if destino.exists():
        antigo = gpd.read_parquet(destino)
        if (list(antigo.columns) == list(novo.columns) and len(antigo) == len(novo)
                and pd.DataFrame(antigo.drop(columns="geometry")).equals(pd.DataFrame(novo.drop(columns="geometry")))
                and bool(np.array_equal(shapely.to_wkb(antigo.geometry.values),
                                        shapely.to_wkb(novo.geometry.values)))):
            _gravar_json_atomico({**chave, "gerado_em": _agora(), "validado_por": "reconsolidacao"}, meta)
            return "IDENTICO"
        # guarda o cache substituído para auditar a diferença
        os.replace(destino, destino.with_suffix(".substituido.parquet"))
    _gravar_cache(novo, destino, chave)
    return "REFEITO"


def _halo(setores_uf: gpd.GeoDataFrame, vizinhos: list[gpd.GeoDataFrame],
          margem_graus: float = 0.05) -> gpd.GeoDataFrame:
    if not vizinhos:
        return setores_uf
    minx, miny, maxx, maxy = setores_uf.total_bounds
    caixa = box(minx - margem_graus, miny - margem_graus,
                maxx + margem_graus, maxy + margem_graus)
    partes = [setores_uf]
    for v in vizinhos:
        if v is None or v.empty:
            continue
        partes.append(v[v.geometry.intersects(caixa)])
    return pd.concat(partes, ignore_index=True)


def calcular_uf(uf: str, locais: pd.DataFrame, setores_uf: gpd.GeoDataFrame,
                vizinhos: list[gpd.GeoDataFrame], raio: int = 1000,
                sensibilidades: tuple[int, ...] = (),
                cobertura_min: float = 0.90,
                renda_min: float = 0.75,
                tolerancia_municipio_m: float = 100.0,
                source_id: str = "") -> tuple[pd.DataFrame, dict]:
    """Calcula o entorno dos locais da UF (1 km principal + sensibilidades)."""
    halo = _halo(setores_uf, vizinhos)
    _, geoms, tree, arr = preparar_setores(halo)
    loc = auditar_coordenadas(locais, setores_uf,
                              tolerancia_municipio_m=tolerancia_municipio_m)
    registros: list[dict] = []
    for _, row in loc.iterrows():
        validade = bool(row["flag_coord_valida"])
        base = {
            "nr_turno": int(row["nr_turno"]), "id_local": row["id_local"],
            "sg_uf": row["SG_UF"], "cd_municipio_tse": row["cd_municipio_tse"],
            "cd_municipio_ibge": row["cd_municipio_ibge"], "nr_zona": row["NR_ZONA"],
            "nr_local": row["NR_LOCAL_ADOTADO"], "nm_local": row["nm_local"],
            "lat": row["lat_r"], "lon": row["lon_r"],
            "n_secoes": int(row["n_secoes"]) if pd.notna(row["n_secoes"]) else 0,
            "aptos": float(row["aptos"]) if pd.notna(row["aptos"]) else np.nan,
            "flag_coord_valida": validade,
            "flag_coord_conflitante": bool(row["flag_coord_conflitante"]),
            "flag_coord_fora_municipio": bool(row["flag_coord_fora_municipio"]),
            "flag_coord_limite_municipio": bool(row["flag_coord_limite_municipio"]),
            "dist_municipio_m": (float(row["dist_municipio_m"])
                                 if pd.notna(row["dist_municipio_m"]) else np.nan),
            "flag_coord_fora_uf": bool(row["flag_coord_fora_uf"]),
            "flag_ponto_repetido": bool(row["flag_ponto_repetido"]),
        }
        if validade:
            base["tipo_coordenada"] = "ORIGINAL_2026"
            buf = buffer_geodesico(float(row["lon_r"]), float(row["lat_r"]), raio)
            met = interpolar(buf, geoms, tree, arr, math.pi * raio ** 2, raio)
            base.update({k: met[k] for k in met})
            base["flag_entorno_valido"] = bool(
                met["setores_n"] > 0 and met["cobertura_area"] >= cobertura_min
                and pd.notna(met["populacao_estimada"]))
            if not base["flag_entorno_valido"]:
                base["motivo_ausencia"] = ("SEM_SETOR" if met["setores_n"] == 0
                                           else "COBERTURA_INSUFICIENTE")
            else:
                base["motivo_ausencia"] = None
            base["flag_renda_valida"] = bool(
                pd.notna(met["renda_media_responsavel"])
                and pd.notna(met["cobertura_renda"])
                and met["cobertura_renda"] >= renda_min)
            if not base["flag_renda_valida"]:
                base["motivo_renda"] = ("SEM_RENDA" if pd.isna(met["renda_media_responsavel"])
                                        else "COBERTURA_RENDA_INSUFICIENTE")
            else:
                base["motivo_renda"] = None
            for r in sensibilidades:
                if int(r) == raio:
                    continue
                b = buffer_geodesico(float(row["lon_r"]), float(row["lat_r"]), int(r))
                m = interpolar(b, geoms, tree, arr, math.pi * int(r) ** 2, int(r))
                for k in ("setores_n", "cobertura_area", "populacao_estimada",
                          "domicilios_estimados", "densidade_hab_km2",
                          "pct_pop_urbana", "pct_pop_favela",
                          "renda_media_responsavel", "cobertura_renda"):
                    base[f"{k}_{r}"] = m[k]
        else:
            base["tipo_coordenada"] = ("SEM_COORDENADA" if not bool(row["coord_valida_bruta"])
                                       else "COORD_INVALIDA")
            base["setores_n"] = 0
            base["cobertura_area"] = 0.0
            for k in ("populacao_estimada", "domicilios_estimados",
                      "domicilios_ocupados_estimados", "moradores_por_domicilio",
                      "densidade_hab_km2", "pct_pop_urbana", "pct_pop_favela",
                      "renda_media_responsavel", "renda_mediana_responsavel_setores",
                      "cobertura_renda"):
                base[k] = np.nan
            if row["flag_coord_conflitante"]:
                base["motivo_ausencia"] = "COORD_CONFLITANTE"
            elif row["flag_coord_fora_uf"]:
                base["motivo_ausencia"] = "COORD_FORA_UF"
            elif row["flag_coord_fora_municipio"]:
                base["motivo_ausencia"] = "COORD_FORA_MUNICIPIO"
            else:
                base["motivo_ausencia"] = "SEM_COORDENADA"
            base["flag_entorno_valido"] = False
            base["flag_renda_valida"] = False
            base["motivo_renda"] = "SEM_ENTORNO"
        base["source_id"] = source_id
        registros.append(base)
    out = pd.DataFrame(registros)
    diag = {
        "uf": uf, "locais": int(len(out)),
        "coordenada_valida": int(out["flag_coord_valida"].sum()),
        "coordenada_ausente": int((out["tipo_coordenada"] == "SEM_COORDENADA").sum()),
        "fora_municipio": int(out["flag_coord_fora_municipio"].sum()),
        "fora_uf": int(out["flag_coord_fora_uf"].sum()),
        "conflito_coordenada": int(out["flag_coord_conflitante"].sum()),
        "ponto_repetido": int(out["flag_ponto_repetido"].sum()),
        "entorno_valido": int(out["flag_entorno_valido"].sum()),
        "entorno_invalido": int((~out["flag_entorno_valido"]).sum()),
        "renda_valida": int(out["flag_renda_valida"].sum()),
        "cobertura_area": {
            "p10": round(float(out["cobertura_area"].quantile(0.10)), 4),
            "p50": round(float(out["cobertura_area"].median()), 4),
            "p90": round(float(out["cobertura_area"].quantile(0.90)), 4),
        },
        "cobertura_renda": {
            "p10": round(float(out["cobertura_renda"].quantile(0.10)), 4),
            "p50": round(float(out["cobertura_renda"].median()), 4),
            "p90": round(float(out["cobertura_renda"].quantile(0.90)), 4),
        },
        "cobertura_area_limiares": {
            str(t): int((out["cobertura_area"] >= t).sum()) for t in (0.75, 0.90, 0.95)
        },
        "cobertura_renda_limiares": {
            str(t): int((out["cobertura_renda"] >= t).sum()) for t in (0.50, 0.75, 0.90)
        },
        "setores_conflito": int(setores_uf["flag_conflito_atributos"].sum()),
        "setores_sem_basico": int(setores_uf["flag_sem_basico"].sum()),
        "setores_sem_renda": int(setores_uf["flag_sem_renda"].sum()),
        "setores_area_divergente": int(setores_uf["flag_area_divergente"].sum()),
        "setores_total": int(len(setores_uf)),
    }
    return out, diag


def cobertura_votos(uf: str, secoes: pd.DataFrame) -> dict:
    """Confere que o vínculo seção–local não multiplica nem perde votos."""
    if secoes.empty:
        return {"votos_total": 0, "votos_vinculados": 0, "secoes_com_voto": 0}
    import duckdb

    con = duckdb.connect()
    try:
        votos = con.execute(f"""
            SELECT sg_uf, cd_municipio_tse, nr_zona, nr_secao, nr_turno,
                   sum(qt_votos) AS qt_votos
            FROM read_parquet('{VOTOS_GLOB}')
            WHERE cd_cargo = 1 AND sg_uf = ?
            GROUP BY 1,2,3,4,5
        """, [uf]).df()
    finally:
        con.close()
    junta = secoes.merge(votos, on=["sg_uf", "cd_municipio_tse", "nr_zona",
                                    "nr_secao", "nr_turno"], how="left",
                         validate="one_to_one", indicator=True)
    if len(junta) != len(secoes):
        raise ValueError(f"{uf}: join de votos multiplicou linhas ({len(secoes)} → {len(junta)})")
    vinculados = junta[junta["_merge"] == "both"]
    chaves = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao", "nr_turno"]
    faltantes = votos.merge(secoes[chaves].drop_duplicates(), on=chaves, how="left",
                            indicator=True)
    sem_secao = faltantes[faltantes["_merge"] == "left_only"]
    return {
        "votos_total": int(votos["qt_votos"].sum()),
        "votos_vinculados": int(vinculados["qt_votos"].sum()),
        "votos_sem_secao_local": int(sem_secao["qt_votos"].sum()),
        "secoes_com_voto": int(len(votos)),
        "secoes_com_voto_sem_local": int(len(sem_secao)),
        "join_um_para_um": True,
    }


def urbanizacao_municipal(setores: list[gpd.GeoDataFrame],
                          project_root: Path = PROJECT_ROOT) -> pd.DataFrame:
    """Urbanização municipal por soma de setores (não pela média dos entornos)."""
    if not setores:
        return pd.DataFrame()
    partes = []
    for s in setores:
        d = s.copy()
        d["pop_urbana"] = d["pop"].fillna(0) * d["flag_urbano"].astype(int)
        g = (d.groupby("CD_MUN", as_index=False)
             .agg(pop_total=("pop", "sum"), pop_urbana=("pop_urbana", "sum"),
                  dom_total=("dom", "sum"), area_km2=("area_km2_calc", "sum"),
                  setores=("CD_SETOR", "nunique"),
                  setores_sem_pop=("flag_sem_basico", "sum")))
        partes.append(g)
    out = pd.concat(partes, ignore_index=True).groupby("CD_MUN", as_index=False).sum(numeric_only=True)
    out = out.rename(columns={"CD_MUN": "cd_municipio_ibge"})
    out["pct_urbana"] = 100.0 * out["pop_urbana"] / out["pop_total"].replace(0, np.nan)
    lookup = ler_lookup(project_root)
    out = out.merge(lookup[["CD_MUNICIPIO_IBGE", "SG_UF", "CD_MUNICIPIO_TSE"]],
                    left_on="cd_municipio_ibge", right_on="CD_MUNICIPIO_IBGE", how="left")
    out = out.drop(columns=["CD_MUNICIPIO_IBGE"]).rename(
        columns={"SG_UF": "sg_uf", "CD_MUNICIPIO_TSE": "cd_municipio_tse"})
    ctx_path = Path(project_root) / "data" / "staging" / "municipal_context.parquet"
    if ctx_path.exists():
        ctx = pd.read_parquet(ctx_path)
        pop = (ctx[ctx["variavel"] == "populacao_residente"]
               [["cd_municipio_ibge", "valor"]]
               .rename(columns={"valor": "pop_sidra"}))
        out = out.merge(pop, left_on="cd_municipio_ibge", right_on="cd_municipio_ibge",
                        how="left")
        out["pop_diferenca"] = out["pop_total"] - out["pop_sidra"]
        out["pop_diferenca_pct"] = 100.0 * out["pop_diferenca"] / out["pop_sidra"].replace(0, np.nan)
    return out


def diagnostico_saidas(locais: pd.DataFrame, secoes: pd.DataFrame,
                       votos: dict, uf: str) -> dict:
    mudou = int(secoes["flag_mudou_local"].sum())
    return {
        "uf": uf,
        "secoes": int(len(secoes)),
        "secoes_t1": int((secoes["nr_turno"] == 1).sum()),
        "secoes_t2": int((secoes["nr_turno"] == 2).sum()),
        "secoes_agregadas": int(secoes["flag_agregada"].sum()),
        "secoes_sem_local": int(secoes["id_local"].isna().sum()),
        "secoes_apurador_ausente": int(secoes["flag_local_apurador_ausente"].sum()),
        "secoes_mudaram_local_t1_t2": mudou,
        "secoes_novas_t2": int(secoes["flag_novo_t2"].sum()),
        "secoes_ausentes_t2": int(secoes["flag_ausente_t2"].sum()),
        "locais": int(len(locais)),
        "locais_coord_fora_municipio": int(locais["flag_coord_fora_municipio"].sum()),
        "locais_coord_limite_municipio": int(locais["flag_coord_limite_municipio"].sum()),
        "dist_municipio_m": {
            "p50": round(float(locais["dist_municipio_m"].median()), 1),
            "p90": round(float(locais["dist_municipio_m"].quantile(0.90)), 1),
            "max": round(float(locais["dist_municipio_m"].max()), 1),
        } if locais["dist_municipio_m"].notna().any() else None,
        "votos": votos,
    }


def _fonte_locais(project_root: Path = PROJECT_ROOT) -> dict:
    """Registro do cadastro TSE de locais no manifesto de brutos."""
    p = Path(project_root) / "data" / "raw" / "manifest.json"
    if not p.exists():
        return {}
    reg = json.loads(p.read_text(encoding="utf-8")).get("registros", {}).get(
        "eleitorado_local_votacao_2026", {})
    return {k: reg.get(k) for k in ("arquivo", "sha256", "url", "bytes")}


def inventario_nacional(project_root: Path = PROJECT_ROOT,
                        ufs: tuple[str, ...] | None = None) -> dict:
    """Inventário nacional de locais/seções T1/T2 e vínculos, sem entorno espacial.

    Não depende de malhas: cobre coordenadas brutas, conflitos, repetição,
    seções agregadas e mudanças T1/T2. A auditoria fora do município/UF e o
    entorno ficam no piloto até a revisão de Opus.
    """
    ufs = tuple(ufs) if ufs else tuple(sorted(VIZINHOS))
    inventario = inventariar_locais(ufs, project_root)
    locais = consolidar_locais(inventario)
    secoes = pd.concat([vincular_secoes(inventario, uf) for uf in ufs
                        if (inventario["SG_UF"] == uf).any()], ignore_index=True)
    diag_uf: dict[str, dict] = {}
    for uf in ufs:
        s = secoes[secoes["sg_uf"] == uf] if not secoes.empty else pd.DataFrame()
        l = locais[locais["SG_UF"] == uf] if not locais.empty else pd.DataFrame()
        if s.empty:
            continue
        votos = cobertura_votos(uf, s)
        diag_uf[uf] = {
            "uf": uf,
            "secoes": int(len(s)),
            "secoes_t1": int((s["nr_turno"] == 1).sum()),
            "secoes_t2": int((s["nr_turno"] == 2).sum()),
            "secoes_agregadas": int(s["flag_agregada"].sum()),
            "secoes_sem_local": int(s["id_local"].isna().sum()),
            "secoes_apurador_ausente": int(s["flag_local_apurador_ausente"].sum()),
            "secoes_mudaram_local_t1_t2": int(s["flag_mudou_local"].sum()),
            "secoes_novas_t2": int(s["flag_novo_t2"].sum()),
            "secoes_ausentes_t2": int(s["flag_ausente_t2"].sum()),
            "locais": int(len(l)),
            "locais_coord_ausente": int((~l["coord_valida_bruta"]).sum()),
            "locais_ponto_repetido": int(l["flag_ponto_repetido"].sum()),
            "votos": votos,
        }
    saida = Path(project_root) / "data" / "staging" / "entorno_local"
    _gravar_parquet(inventario, saida / "inventario_locais.parquet")
    _gravar_parquet(locais, saida / "inventario_locais_agregado.parquet")
    _gravar_parquet(secoes, saida / "inventario_secoes_local.parquet")
    manifesto = {
        "gerado_em": _agora(), "manifest_version": "1.0",
        "tipo": "inventario_nacional", "ufs": list(ufs),
        "linhas_inventario": int(len(inventario)),
        "locais": int(len(locais)), "secoes": int(len(secoes)),
        "pico_memoria_kb": _pico_memoria_kb(),
        "diagnostico_por_uf": diag_uf,
        "fonte_locais": _fonte_locais(project_root),
        "nota": ("Auditoria fora do município/UF e entorno espacial dependem das "
                 "malhas e da revisão de Opus; este inventário não é cobertura nacional "
                 "do entorno."),
    }
    _gravar_json_atomico(manifesto, saida / "diagnostico_inventario_nacional.json")
    return manifesto


def urbanizacao_nacional(project_root: Path = PROJECT_ROOT,
                         force: bool = False) -> dict:
    """Urbanização municipal nacional por soma de setores (sem buffers).

    Independe das decisões de buffer/cobertura do entorno; usa a mesma malha e
    agregados já validados no piloto. O exterior (ZZ) fica fora (sem malha).
    """
    ufs = tuple(sorted(u for u in VIZINHOS if u != "ZZ"))
    adquirir(ufs, project_root, force=force)
    basico, renda = ler_agregados(project_root)
    insumos = _carregar_manifesto()["fontes"]
    lista = []
    diag_uf: dict[str, dict] = {}
    for uf in ufs:
        print(f"  setores {uf}...", flush=True)
        s = carregar_setores(uf, basico, renda, project_root, force=False)
        lista.append(s)
        diag_uf[uf] = {
            "setores": int(len(s)),
            "pop_total": int(s["pop"].fillna(0).sum()),
            "setores_sem_basico": int(s["flag_sem_basico"].sum()),
            "setores_sem_renda": int(s["flag_sem_renda"].sum()),
            "setores_conflito": int(s["flag_conflito_atributos"].sum()),
            "setores_area_divergente": int(s["flag_area_divergente"].sum()),
        }
    urb = urbanizacao_municipal(lista, project_root)
    mapa_fonte = {
        uf: _hash_texto(uf, insumos.get(f"malha_{uf}", {}).get("sha256", ""),
                        insumos.get("basico", {}).get("sha256", ""),
                        insumos.get("renda", {}).get("sha256", ""))
        for uf in ufs
    }
    urb["source_id"] = urb["sg_uf"].map(mapa_fonte)
    saida = Path(project_root) / "data" / "staging" / "entorno_local"
    destino = saida / "urbanizacao_municipal_nacional.parquet"
    _gravar_parquet(urb, destino)
    manifesto = {
        "gerado_em": _agora(), "manifest_version": "1.0",
        "tipo": "urbanizacao_municipal_nacional",
        "ufs": list(ufs), "municipios": int(len(urb)),
        "pop_total": int(urb["pop_total"].sum()),
        "pop_urbana": int(urb["pop_urbana"].sum()),
        "pct_urbana": round(100 * urb["pop_urbana"].sum() / urb["pop_total"].sum(), 4),
        "pop_sidra": float(urb["pop_sidra"].sum()),
        "diferenca_pct_mediana": float(urb["pop_diferenca_pct"].median()),
        "diferenca_pct_p95_abs": float(urb["pop_diferenca_pct"].abs().quantile(0.95)),
        "pico_memoria_kb": _pico_memoria_kb(),
        "diagnostico_por_uf": diag_uf,
        "sha256": _sha256(destino),
        "insumos": {k: {"url": v.get("url"), "sha256": v.get("sha256")}
                    for k, v in insumos.items()
                    if k.startswith(("malha_", "basico", "renda"))},
    }
    _gravar_json_atomico(manifesto, saida / "diagnostico_urbanizacao_nacional.json")
    return manifesto


def _hash_texto(*partes: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in partes)
                          .encode("utf-8")).hexdigest()


def _pico_memoria_kb() -> int:
    """Pico de RSS do processo (Windows/psapi; POSIX/resource)."""
    import sys
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC),
                                               wintypes.DWORD]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return int(c.PeakWorkingSetSize // 1024)
        return 0
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if sys.platform == "darwin" else rss // 1024)


def _gravar_parquet(df: pd.DataFrame, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, caminho)


def run(ufs: tuple[str, ...], project_root: Path = PROJECT_ROOT,
        raio: int = 1000, sensibilidades: tuple[int, ...] = (),
        cobertura_min: float = 0.90, renda_min: float = 0.75,
        tolerancia_municipio_m: float = 100.0,
        force: bool = False) -> dict:
    """Executa o entorno para as UFs pedidas (piloto ou lote nacional)."""
    ufs = tuple(u.upper() for u in ufs)
    desconhecidas = [u for u in ufs if u not in VIZINHOS]
    if desconhecidas:
        raise ValueError(f"UF(s) desconhecida(s): {desconhecidas}")
    vizinhos = sorted({v for u in ufs for v in VIZINHOS[u]})
    adquirir(tuple(sorted(set(ufs) | set(vizinhos))), project_root, force=force)
    inventario = inventariar_locais(ufs, project_root)
    basico, renda = ler_agregados(project_root)
    insumos = _carregar_manifesto()["fontes"]
    fonte_basico = insumos.get("basico", {}).get("sha256", "")
    fonte_renda = insumos.get("renda", {}).get("sha256", "")
    saidas: dict[str, dict] = {}
    urbanizacoes: list[gpd.GeoDataFrame] = []
    for uf in ufs:
        print(f"\n== {uf} ==")
        chaves: dict[str, str] = {}
        setores = carregar_setores(uf, basico, renda, project_root, force=force, chaves=chaves)
        viz = []
        for v in VIZINHOS[uf]:
            try:
                # sem force: a chave do cache já obriga a refazer vizinho com insumo ou versão diferente
                viz.append(carregar_setores(v, basico, renda, project_root, chaves=chaves))
            except FileNotFoundError:
                print(f"  [aviso] malha vizinha {v} ausente; halo parcial")
        sha_malha = insumos.get(f"malha_{uf}", {}).get("sha256", "")
        source_id = _hash_texto(uf, sha_malha, fonte_basico, fonte_renda)
        locais_uf = consolidar_locais(inventario[inventario["SG_UF"] == uf])
        print(f"  locais: {len(locais_uf):,} | setores: {len(setores):,}")
        locais, diag = calcular_uf(uf, locais_uf, setores, viz, raio=raio,
                                   sensibilidades=sensibilidades,
                                   cobertura_min=cobertura_min, renda_min=renda_min,
                                   tolerancia_municipio_m=tolerancia_municipio_m,
                                   source_id=source_id)
        secoes = vincular_secoes(inventario, uf)
        metricas = locais[["nr_turno", "id_local", "flag_entorno_valido",
                           "cobertura_area", "populacao_estimada",
                           "renda_media_responsavel", "flag_renda_valida"]]
        secoes = secoes.merge(metricas, on=["nr_turno", "id_local"], how="left")
        apurador = metricas.rename(columns={
            "id_local": "id_local_apurador", "flag_entorno_valido": "flag_entorno_valido_apurador",
            "cobertura_area": "cobertura_area_apurador",
            "populacao_estimada": "populacao_estimada_apurador",
            "renda_media_responsavel": "renda_media_responsavel_apurador",
            "flag_renda_valida": "flag_renda_valida_apurador"})
        secoes = secoes.merge(apurador, on=["nr_turno", "id_local_apurador"], how="left")
        secoes["source_id_entorno"] = source_id
        votos = cobertura_votos(uf, secoes)
        diag.update(diagnostico_saidas(locais, secoes, votos, uf))
        diag["insumos"] = {"malha": sha_malha, "basico": fonte_basico,
                           "renda": fonte_renda, "source_id": source_id,
                           "chaves_cache_setores": chaves}
        diag["parametros"] = {"raio_m": raio, "sensibilidades": list(sensibilidades),
                              "cobertura_min": cobertura_min, "renda_min": renda_min,
                              "tolerancia_municipio_m": tolerancia_municipio_m}
        _gravar_parquet(locais, Path(project_root) / "data" / "staging" /
                        "entorno_local" / f"locais_{uf}.parquet")
        _gravar_parquet(secoes, Path(project_root) / "data" / "staging" /
                        "entorno_local" / f"secoes_{uf}.parquet")
        _gravar_json_atomico(diag, Path(project_root) / "data" / "staging" /
                             "entorno_local" / f"diagnostico_{uf}.json")
        urbanizacoes.append(setores)
        saidas[uf] = {
            "locais": int(len(locais)), "secoes": int(len(secoes)),
            "entorno_valido": int(locais["flag_entorno_valido"].sum()),
            "votos_vinculados": votos["votos_vinculados"],
            "votos_total": votos["votos_total"],
            "arquivos": {
                "locais": f"locais_{uf}.parquet",
                "secoes": f"secoes_{uf}.parquet",
                "diagnostico": f"diagnostico_{uf}.json",
            },
            "sha256": {
                "locais": _sha256(Path(project_root) / "data" / "staging" /
                                  "entorno_local" / f"locais_{uf}.parquet"),
                "secoes": _sha256(Path(project_root) / "data" / "staging" /
                                  "entorno_local" / f"secoes_{uf}.parquet"),
            },
        }
        print(f"  entorno válido: {saidas[uf]['entorno_valido']:,} | "
              f"votos vinculados: {votos['votos_vinculados']:,}/{votos['votos_total']:,}")

    urb = urbanizacao_municipal(urbanizacoes, project_root)
    mapa_fonte = {
        u: _hash_texto(u, insumos.get(f"malha_{u}", {}).get("sha256", ""),
                       insumos.get("basico", {}).get("sha256", ""),
                       insumos.get("renda", {}).get("sha256", ""))
        for u in ufs
    }
    urb["source_id"] = urb["sg_uf"].map(mapa_fonte)
    _gravar_parquet(urb, Path(project_root) / "data" / "staging" /
                    "entorno_local" / "urbanizacao_municipal.parquet")
    manifesto = {
        "gerado_em": _agora(), "manifest_version": "1.0",
        "ufs": list(ufs), "raio_m": raio, "sensibilidades": list(sensibilidades),
        "cobertura_min": cobertura_min, "renda_min": renda_min,
        "tolerancia_municipio_m": tolerancia_municipio_m,
        "pico_memoria_kb": _pico_memoria_kb(),
        "insumos": {k: {"url": v.get("url"), "sha256": v.get("sha256"),
                        "bytes": v.get("bytes"), "last_modified": v.get("last_modified")}
                    for k, v in insumos.items() if k.startswith(("malha_", "basico", "renda"))},
        "fonte_locais": _fonte_locais(project_root),
        "saidas": saidas,
        "urbanizacao_municipal": {
            "arquivo": "urbanizacao_municipal.parquet", "linhas": int(len(urb)),
            "sha256": _sha256(Path(project_root) / "data" / "staging" /
                              "entorno_local" / "urbanizacao_municipal.parquet"),
        },
    }
    _gravar_json_atomico(manifesto, Path(project_root) / "data" / "staging" /
                         "entorno_local" / "manifest.json")
    return manifesto


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Entorno socioespacial dos locais de votação")
    ap.add_argument("--ufs", default="", help="UFs separadas por vírgula (ex.: RS,AC,SE)")
    ap.add_argument("--inventario-nacional", action="store_true",
                    help="só inventário/vínculos nacionais, sem entorno espacial")
    ap.add_argument("--urbanizacao-nacional", action="store_true",
                    help="urbanização municipal nacional por soma de setores (sem buffers)")
    ap.add_argument("--validar-cache", action="store_true",
                    help="confere os caches de setores contra os insumos atuais (R38-2)")
    ap.add_argument("--raio", type=int, default=1000)
    ap.add_argument("--sensibilidades", default="", help="ex.: 500,3000")
    ap.add_argument("--cobertura-min", type=float, default=0.90)
    ap.add_argument("--renda-min", type=float, default=0.75)
    ap.add_argument("--tolerancia-municipio-m", type=float, default=100.0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    if args.inventario_nacional:
        m = inventario_nacional()
        print(json.dumps({"tipo": m["tipo"], "ufs": len(m["ufs"]),
                          "locais": m["locais"], "secoes": m["secoes"],
                          "pico_memoria_kb": m["pico_memoria_kb"]},
                         ensure_ascii=False, indent=2))
        return 0
    if args.validar_cache:
        basico, renda = ler_agregados()
        ufs = tuple(sorted(u for u in VIZINHOS if u != "ZZ"))
        res = {}
        for u in ufs:
            res[u] = validar_cache_setores(u, basico, renda)
            print(f"  {u}: {res[u]}", flush=True)
        _gravar_json_atomico({"gerado_em": _agora(), "versao_consolidacao": VERSAO_CONSOLIDACAO,
                              "resultado": res}, STAGING_DIR / "_cache" / "validacao_cache.json")
        return 0
    if args.urbanizacao_nacional:
        m = urbanizacao_nacional(force=args.force)
        print(json.dumps({"tipo": m["tipo"], "ufs": len(m["ufs"]),
                          "municipios": m["municipios"],
                          "pop_total": m["pop_total"], "pop_urbana": m["pop_urbana"],
                          "pct_urbana": m["pct_urbana"],
                          "diferenca_pct_p95_abs": m["diferenca_pct_p95_abs"]},
                         ensure_ascii=False, indent=2))
        return 0
    if not args.ufs:
        ap.error("--ufs é obrigatório fora do inventário nacional")
    ufs = tuple(x.strip().upper() for x in args.ufs.split(",") if x.strip())
    sens = tuple(int(x) for x in args.sensibilidades.split(",") if x.strip())
    manifesto = run(ufs, raio=args.raio, sensibilidades=sens,
                    cobertura_min=args.cobertura_min, renda_min=args.renda_min,
                    tolerancia_municipio_m=args.tolerancia_municipio_m,
                    force=args.force)
    print(json.dumps({"ufs": manifesto["ufs"], "raio_m": manifesto["raio_m"],
                      "saidas": {u: {"locais": v["locais"], "secoes": v["secoes"],
                                     "entorno_valido": v["entorno_valido"]}
                                 for u, v in manifesto["saidas"].items()}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
