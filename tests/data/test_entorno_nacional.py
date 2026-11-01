"""Testes offline do entorno nacional (handoff 36) â€” geometria, setores, vÃ­nculos.

Sem rede e sem dados reais: geometrias sintÃ©ticas em EPSG:4674, ZIPs mÃ­nimos no
formato TSE/IBGE e um Parquet de votos temporÃ¡rio. Cobrem as decisÃµes crÃ­ticas
do handoff: interseÃ§Ã£o conhecida, multipartes/duplicatas, conflito de atributos,
Ã¡rea zero/invÃ¡lida, renda ausente, fronteira entre UFs, coordenadas fora do
municÃ­pio/UF, mudanÃ§a de local T1/T2, agregaÃ§Ã£o e preservaÃ§Ã£o de votos.
"""
from __future__ import annotations

import csv
import io
import math
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "data"))

pytest.importorskip("geopandas")
import br2026.ingest.entorno_nacional as e  # noqa: E402
from shapely.geometry import Point, Polygon, box  # noqa: E402


def _setores(rows, crs="EPSG:4674") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=crs)


# --------------------------------------------------------------------------- #
# geometria e buffer                                                           #
# --------------------------------------------------------------------------- #


def test_area_equal_area_confere_com_geodesica():
    for lat in (0.0, -20.0, -30.0):
        g = box(-50.0, lat, -49.99, lat + 0.01)
        aeq = e.area_m2(g)
        ageo = e.area_geodesica_m2(g)
        assert aeq > 0 and ageo > 0
        assert abs(aeq - ageo) / ageo < 1e-6


def test_buffer_geodesico_em_latitudes_distintas():
    for lat in (-5.0, -20.0, -30.0):
        b = e.buffer_geodesico(-50.0, lat, 1000.0)
        aeq = e.area_m2(b)
        ageo = e.area_geodesica_m2(b)
        # 128 vÃ©rtices: erro de aproximaÃ§Ã£o < 0,2% em relaÃ§Ã£o a pi RÂ²
        assert abs(aeq - math.pi * 1e6) / (math.pi * 1e6) < 0.002
        assert abs(aeq - ageo) / ageo < 1e-6


# --------------------------------------------------------------------------- #
# consolidaÃ§Ã£o de setores                                                      #
# --------------------------------------------------------------------------- #


def test_multipartes_identicas_nao_multiplicam_populacao():
    s = box(-50.0, -20.0, -49.99, -19.99)
    partes = [s.intersection(box(-50.0, -20.0, -49.995, -19.99)),
              s.intersection(box(-49.995, -20.0, -49.99, -19.99))]
    malha = _setores([
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s) / 1e6, "geometry": p} for p in partes
    ])
    b = pd.DataFrame({
        "CD_SETOR": ["110001505000001"], "SITUACAO": ["Urbana"], "CD_SIT": ["1"],
        "CD_FCU": ["."], "CD_MUN": ["1100015"], "CD_UF": ["11"],
        "AREA_KM2": [e.area_m2(s) / 1e6], "pop": [100], "dom": [40],
        "mor_med": [2.5], "dom_ocup": [38],
    })
    r = pd.DataFrame({"CD_SETOR": ["110001505000001"], "resp_renda": [40],
                      "renda_media": [1000.0], "renda_mediana": [800.0]})
    out = e.consolidar_setores(malha, b, r)
    assert len(out) == 1
    assert int(out["pop"].iloc[0]) == 100          # nÃ£o 200
    assert not bool(out.flag_conflito_atributos.iloc[0])
    assert abs(out.area_m2.iloc[0] - e.area_m2(s)) / e.area_m2(s) < 1e-6


def test_atributos_conflitantes_bloqueiam_setor():
    s = box(-50.0, -20.0, -49.99, -19.99)
    malha = _setores([
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s) / 1e6, "geometry": s},
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s) / 1e6, "geometry": s},
    ])
    b = pd.DataFrame({
        "CD_SETOR": ["110001505000001", "110001505000001"],
        "SITUACAO": ["Urbana", "Urbana"], "CD_SIT": ["1", "1"], "CD_FCU": [".", "."],
        "CD_MUN": ["1100015", "1100015"], "CD_UF": ["11", "11"],
        "AREA_KM2": [1.0, 1.0], "pop": [100, 200], "dom": [40, 80],
        "mor_med": [2.5, 2.5], "dom_ocup": [38, 76],
    })
    r = pd.DataFrame({"CD_SETOR": ["110001505000001"], "resp_renda": [1],
                      "renda_media": [1000.0], "renda_mediana": [800.0]})
    out = e.consolidar_setores(malha, b, r)
    assert len(out) == 1
    assert bool(out.flag_conflito_atributos.iloc[0])
    assert not bool(out.flag_elegivel.iloc[0])


def test_geometria_invalida_e_area_zero():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    linha = Polygon([(0, 0), (0.001, 0), (0.002, 0), (0, 0)])
    malha = _setores([
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": 1.0, "geometry": bowtie},
        {"CD_SETOR": "110001505000002", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": 0.0, "geometry": linha},
    ])
    b = pd.DataFrame({
        "CD_SETOR": ["110001505000001", "110001505000002"],
        "SITUACAO": ["Urbana", "Urbana"], "CD_SIT": ["1", "1"], "CD_FCU": [".", "."],
        "CD_MUN": ["1100015", "1100015"], "CD_UF": ["11", "11"],
        "AREA_KM2": [1.0, 0.0], "pop": [10, 20], "dom": [4, 8],
        "mor_med": [2.5, 2.5], "dom_ocup": [4, 8],
    })
    r = pd.DataFrame({"CD_SETOR": ["110001505000001", "110001505000002"],
                      "resp_renda": [1, 1], "renda_media": [1000.0, 1000.0],
                      "renda_mediana": [800.0, 800.0]})
    out = e.consolidar_setores(malha, b, r)
    inval = out[out.CD_SETOR == "110001505000001"].iloc[0]
    zero = out[out.CD_SETOR == "110001505000002"].iloc[0]
    assert bool(inval.flag_geom_invalida)
    assert not bool(inval.flag_elegivel)
    assert bool(zero.flag_area_zero)
    assert not bool(zero.flag_elegivel)


def test_setor_sem_renda_nao_vira_zero():
    s = box(-50.0, -20.0, -49.99, -19.99)
    malha = _setores([{"CD_SETOR": "110001505000001", "SITUACAO": "Urbana",
                       "CD_SIT": "1", "CD_FCU": ".", "CD_MUN": "1100015",
                       "CD_UF": "11", "AREA_KM2": e.area_m2(s) / 1e6,
                       "geometry": s}])
    b = pd.DataFrame({"CD_SETOR": ["110001505000001"], "SITUACAO": ["Urbana"],
                      "CD_SIT": ["1"], "CD_FCU": ["."], "CD_MUN": ["1100015"],
                      "CD_UF": ["11"], "AREA_KM2": [1.0], "pop": [100],
                      "dom": [40], "mor_med": [2.5], "dom_ocup": [38]})
    r = pd.DataFrame({"CD_SETOR": ["110001505000001"], "resp_renda": [np.nan],
                      "renda_media": [np.nan], "renda_mediana": [np.nan]})
    out = e.consolidar_setores(malha, b, r)
    assert bool(out.flag_sem_renda.iloc[0])
    assert pd.isna(out.renda_media.iloc[0])


# --------------------------------------------------------------------------- #
# interpolaÃ§Ã£o                                                                 #
# --------------------------------------------------------------------------- #


def test_interpolacao_setor_inteiro_e_parcial():
    lon0, lat0 = -50.0, -20.0
    s1 = box(lon0 - 0.002, lat0 - 0.002, lon0 + 0.002, lat0 + 0.002)
    s2 = box(lon0 + 0.0089, lat0 - 0.002, lon0 + 0.0129, lat0 + 0.002)
    malha = _setores([
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s1) / 1e6, "geometry": s1},
        {"CD_SETOR": "110001505000002", "SITUACAO": "Rural", "CD_SIT": "8",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s2) / 1e6, "geometry": s2},
    ])
    b = pd.DataFrame({
        "CD_SETOR": ["110001505000001", "110001505000002"],
        "SITUACAO": ["Urbana", "Rural"], "CD_SIT": ["1", "8"], "CD_FCU": [".", "."],
        "CD_MUN": ["1100015", "1100015"], "CD_UF": ["11", "11"],
        "AREA_KM2": [e.area_m2(s1) / 1e6, e.area_m2(s2) / 1e6],
        "pop": [100, 200], "dom": [40, 80], "mor_med": [2.5, 2.5],
        "dom_ocup": [38, 76],
    })
    r = pd.DataFrame({"CD_SETOR": ["110001505000001", "110001505000002"],
                      "resp_renda": [40, 80], "renda_media": [1000.0, 3000.0],
                      "renda_mediana": [800.0, 2500.0]})
    setores = e.consolidar_setores(malha, b, r)
    _, geoms, tree, arr = e.preparar_setores(setores)
    met = e.interpolar(e.buffer_geodesico(lon0, lat0, 1000.0), geoms, tree, arr,
                       math.pi * 1e6, 1000)
    assert met["setores_n"] == 2
    assert 100 < met["populacao_estimada"] < 300
    assert 0 < met["cobertura_area"] < 1
    assert 0 <= met["pct_pop_urbana"] <= 100
    assert met["cobertura_renda"] == pytest.approx(1.0, abs=0.01)


def test_interpolacao_invariante_a_divisao_do_setor():
    s = box(-50.002, -20.002, -49.998, -19.998)
    b = pd.DataFrame({"CD_SETOR": ["110001505000001"], "SITUACAO": ["Urbana"],
                      "CD_SIT": ["1"], "CD_FCU": ["."], "CD_MUN": ["1100015"],
                      "CD_UF": ["11"], "AREA_KM2": [e.area_m2(s) / 1e6],
                      "pop": [100], "dom": [40], "mor_med": [2.5], "dom_ocup": [38]})
    r = pd.DataFrame({"CD_SETOR": ["110001505000001"], "resp_renda": [40],
                      "renda_media": [1000.0], "renda_mediana": [800.0]})
    inteiro = _setores([{"CD_SETOR": "110001505000001", "SITUACAO": "Urbana",
                         "CD_SIT": "1", "CD_FCU": ".", "CD_MUN": "1100015",
                         "CD_UF": "11", "AREA_KM2": e.area_m2(s) / 1e6,
                         "geometry": s}])
    partes = _setores([
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s) / 1e6, "geometry": s.intersection(
             box(-50.002, -20.002, -50.0, -19.998))},
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s) / 1e6, "geometry": s.intersection(
             box(-50.0, -20.002, -49.998, -19.998))},
    ])
    met = []
    for malha in (inteiro, partes):
        setores = e.consolidar_setores(malha, b, r)
        _, geoms, tree, arr = e.preparar_setores(setores)
        met.append(e.interpolar(e.buffer_geodesico(-50.0, -20.0, 1000.0),
                                geoms, tree, arr, math.pi * 1e6, 1000))
    assert met[0]["populacao_estimada"] == pytest.approx(met[1]["populacao_estimada"], rel=1e-9)
    assert met[0]["cobertura_area"] == pytest.approx(met[1]["cobertura_area"], rel=1e-9)


def test_sem_setor_nao_e_populacao_zero():
    vazio = gpd.GeoDataFrame({"CD_SETOR": [], "geometry": []}, crs="EPSG:4674")
    _, geoms, tree, arr = e.preparar_setores(vazio)
    met = e.interpolar(e.buffer_geodesico(-50.0, -20.0, 1000.0), geoms, tree, arr,
                       math.pi * 1e6, 1000)
    assert met["setores_n"] == 0
    assert np.isnan(met["populacao_estimada"])
    assert met["cobertura_area"] == 0


def test_fronteira_com_halo():
    # dois setores grandes adjacentes, um em cada UF; ponto na divisa
    s1 = box(-50.0, -20.0, -49.97, -19.97)
    s2 = box(-49.97, -20.0, -49.94, -19.97)
    malha = _setores([
        {"CD_SETOR": "110001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1100015", "CD_UF": "11",
         "AREA_KM2": e.area_m2(s1) / 1e6, "geometry": s1},
        {"CD_SETOR": "120001505000001", "SITUACAO": "Urbana", "CD_SIT": "1",
         "CD_FCU": ".", "CD_MUN": "1200015", "CD_UF": "12",
         "AREA_KM2": e.area_m2(s2) / 1e6, "geometry": s2},
    ])
    b = pd.DataFrame({
        "CD_SETOR": ["110001505000001", "120001505000001"],
        "SITUACAO": ["Urbana", "Urbana"], "CD_SIT": ["1", "1"], "CD_FCU": [".", "."],
        "CD_MUN": ["1100015", "1200015"], "CD_UF": ["11", "12"],
        "AREA_KM2": [e.area_m2(s1) / 1e6, e.area_m2(s2) / 1e6],
        "pop": [100, 200], "dom": [40, 80], "mor_med": [2.5, 2.5],
        "dom_ocup": [38, 76],
    })
    r = pd.DataFrame({"CD_SETOR": ["110001505000001", "120001505000001"],
                      "resp_renda": [40, 80], "renda_media": [1000.0, 2000.0],
                      "renda_mediana": [800.0, 1500.0]})
    setores = e.consolidar_setores(malha, b, r)
    _, geoms, tree, arr = e.preparar_setores(setores)
    met = e.interpolar(e.buffer_geodesico(-49.97, -19.985, 1000.0),
                       geoms, tree, arr, math.pi * 1e6, 1000)
    assert met["setores_n"] == 2
    assert met["cobertura_area"] > 0.95


# --------------------------------------------------------------------------- #
# auditoria de coordenadas                                                     #
# --------------------------------------------------------------------------- #


def test_auditoria_fora_municipio_fora_uf_e_tolerancia():
    s1 = box(0.0, 0.0, 1.0, 1.0)      # municÃ­pio 1100015
    s2 = box(1.0, 0.0, 2.0, 1.0)      # municÃ­pio 1200015
    setores = _setores([
        {"CD_SETOR": "110001505000001", "CD_MUN": "1100015", "geometry": s1},
        {"CD_SETOR": "120001505000001", "CD_MUN": "1200015", "geometry": s2},
    ])
    locais = pd.DataFrame({
        "id_local": ["A", "B", "C", "D"], "nr_turno": [1, 1, 1, 1],
        "cd_municipio_ibge": ["1100015", "1100015", "1100015", "1100015"],
        "lat_r": [0.5, 0.5, 0.5, 0.5], "lon_r": [0.5, 1.5, 1.0005, 3.0],
        "coord_valida": [True, True, True, True],
    })
    out = e.auditar_coordenadas(locais, setores, tolerancia_municipio_m=500.0)
    assert bool(out.loc[out.id_local == "A", "flag_coord_valida"].iloc[0])
    assert bool(out.loc[out.id_local == "B", "flag_coord_fora_municipio"].iloc[0])
    assert not bool(out.loc[out.id_local == "B", "flag_coord_valida"].iloc[0])
    assert bool(out.loc[out.id_local == "C", "flag_coord_limite_municipio"].iloc[0])
    assert bool(out.loc[out.id_local == "C", "flag_coord_valida"].iloc[0])
    assert bool(out.loc[out.id_local == "D", "flag_coord_fora_uf"].iloc[0])
    assert not bool(out.loc[out.id_local == "D", "flag_coord_valida"].iloc[0])


def test_consolidar_locais_conflito_e_empate():
    base = {
        "SG_UF": "AC", "cd_municipio_tse": "01015", "cd_municipio_ibge": "1200179",
        "NR_ZONA": "0001", "NR_LOCAL_ADOTADO": "1001", "nm_local": "X",
        "ds_endereco": "", "nm_bairro": "", "nr_cep": "", "flag_ativo": True,
        "coord_valida_bruta": True, "qt_eleitor": 10, "flag_agregada": False,
        "nr_secao_principal": None,
    }
    rows = []
    # local A: trÃªs seÃ§Ãµes, duas com a mesma coordenada (modal) e uma diferente
    for sec, lat in (("0001", -10.0), ("0002", -10.0), ("0003", -10.1)):
        rows.append({**base, "id_local": "AC_01015_0001_1001",
                     "id_secao": f"AC_01015_0001_{sec}", "nr_turno": 1,
                     "lat": lat, "lon": -67.0})
    # local B: empate (duas coordenadas, uma cada)
    for sec, lat in (("0004", -11.0), ("0005", -11.1)):
        rows.append({**base, "id_local": "AC_01015_0001_1002",
                     "id_secao": f"AC_01015_0001_{sec}", "nr_turno": 1,
                     "lat": lat, "lon": -67.0})
    out = e.consolidar_locais(pd.DataFrame(rows))
    a = out[out.id_local == "AC_01015_0001_1001"].iloc[0]
    b = out[out.id_local == "AC_01015_0001_1002"].iloc[0]
    assert bool(a.flag_coord_conflitante) and not bool(a.flag_coord_ambigua)
    assert a.lat_r == pytest.approx(-10.0) and bool(a.coord_valida)
    assert bool(b.flag_coord_conflitante) and bool(b.flag_coord_ambigua)
    assert not bool(b.coord_valida)


# --------------------------------------------------------------------------- #
# vÃ­nculos seÃ§Ã£oâ€“local                                                         #
# --------------------------------------------------------------------------- #


def test_vincular_secoes_mudanca_e_agregacao():
    base = {
        "SG_UF": "AC", "cd_municipio_tse": "01015", "cd_municipio_ibge": "1200179",
        "NR_ZONA": "0001", "lat": -10.0, "lon": -67.0, "flag_ativo": True,
        "coord_valida_bruta": True,
    }
    inv = pd.DataFrame([
        {**base, "nr_turno": 1, "NR_SECAO": "0010", "id_secao": "AC_01015_0001_0010",
         "id_local": "AC_01015_0001_1001", "flag_agregada": False,
         "nr_secao_principal": None},
        {**base, "nr_turno": 2, "NR_SECAO": "0010", "id_secao": "AC_01015_0001_0010",
         "id_local": "AC_01015_0001_2002", "flag_agregada": False,
         "nr_secao_principal": None},
        {**base, "nr_turno": 1, "NR_SECAO": "0020", "id_secao": "AC_01015_0001_0020",
         "id_local": "AC_01015_0001_3003", "flag_agregada": True,
         "nr_secao_principal": "0010"},
        {**base, "nr_turno": 2, "NR_SECAO": "0020", "id_secao": "AC_01015_0001_0020",
         "id_local": "AC_01015_0001_3003", "flag_agregada": True,
         "nr_secao_principal": "0010"},
    ])
    out = e.vincular_secoes(inv, "AC")
    sec10 = out[out.id_secao == "AC_01015_0001_0010"]
    sec20 = out[out.id_secao == "AC_01015_0001_0020"]
    assert bool(sec10.flag_mudou_local.all())
    assert len(sec20) == 2 and bool(sec20.flag_agregada.all())
    assert set(sec20.id_local_apurador) == {
        "AC_01015_0001_1001", "AC_01015_0001_2002"}
    assert not bool(sec20.flag_local_apurador_ausente.any())


# --------------------------------------------------------------------------- #
# inventÃ¡rio e votos                                                           #
# --------------------------------------------------------------------------- #


COLS_LOCAIS_TESTE = [
    "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
    "NR_LOCAL_VOTACAO", "NR_LOCAL_VOTACAO_ORIGINAL", "NM_LOCAL_VOTACAO",
    "DS_ENDERECO", "NM_BAIRRO", "NR_CEP", "NR_LATITUDE", "NR_LONGITUDE",
    "CD_SITU_LOCAL_VOTACAO", "CD_TIPO_SECAO_AGREGADA", "NR_SECAO_PRINCIPAL",
    "QT_ELEITOR_SECAO",
]


def _zip_csv(caminho: Path, membro: str, colunas: list[str], linhas: list[list]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(colunas)
    w.writerows(linhas)
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(membro, buf.getvalue().encode("latin-1"))


def _lookup_fake(raiz: Path) -> None:
    _zip_csv(raiz / "data" / "raw" / "ibge_setores" / "municipio_tse_ibge.zip",
             "municipio_tse_ibge.csv",
             ["SG_UF", "CD_MUNICIPIO_TSE", "CD_MUNICIPIO_IBGE", "CD_UF_IBGE",
              "NM_MUNICIPIO_TSE", "NM_MUNICIPIO_IBGE"],
             [["AC", "01015", "1200179", "12", "Capixaba", "Capixaba"]])


def test_inventariar_locais_ids_turnos_e_agregacao(tmp_path):
    linha_t1 = ["1", "AC", "01015", "CAPIXABA", "1", "10", "1001", "1001",
                "ESCOLA", "RUA A", "CENTRO", "69900000", "-10,5", "-67,5",
                "1", "1", "-1", "100"]
    linha_t2 = ["2", "AC", "01015", "CAPIXABA", "1", "10", "2002", "2002",
                "ESCOLA", "RUA A", "CENTRO", "69900000", "-10,5", "-67,5",
                "1", "1", "-1", "100"]
    linha_agr = ["1", "AC", "01015", "CAPIXABA", "1", "20", "-1", "3003",
                 "ESCOLA", "RUA B", "CENTRO", "69900000", "-10,6", "-67,6",
                 "1", "2", "10", "50"]
    _zip_csv(tmp_path / "data" / "raw" / "eleitorado_local_votacao_2026.zip",
             "eleitorado_local_votacao_2026_AC.csv", COLS_LOCAIS_TESTE,
             [linha_t1, linha_t2, linha_agr])
    _lookup_fake(tmp_path)
    out = e.inventariar_locais(("AC",), tmp_path)
    assert len(out) == 3
    assert set(out.nr_turno) == {1, 2}
    sec10 = out[(out.nr_turno == 1) & (out.NR_SECAO == "0010")].iloc[0]
    assert sec10.id_local == "AC_01015_0001_1001"
    assert sec10.id_secao == "AC_01015_0001_0010"
    assert sec10.cd_municipio_ibge == "1200179"
    agr = out[out.NR_SECAO == "0020"].iloc[0]
    assert bool(agr.flag_agregada)
    assert agr.id_local == "AC_01015_0001_3003"   # usa o local original
    assert agr.nr_secao_principal == "0010"


def test_cobertura_votos_preserva_soma(tmp_path, monkeypatch):
    votes = pd.DataFrame({
        "cd_cargo": [1, 1, 1, 1, 1],
        "sg_uf": ["AC"] * 5,
        "cd_municipio_tse": ["01015"] * 5,
        "nr_zona": ["0001"] * 5,
        "nr_secao": ["0010", "0010", "0020", "0010", "0030"],
        "nr_turno": [1, 1, 1, 2, 1],
        "qt_votos": [6, 4, 5, 8, 5],
    })
    p = tmp_path / "votes.parquet"
    votes.to_parquet(p, index=False)
    monkeypatch.setattr(e, "VOTOS_GLOB", str(p))
    secoes = pd.DataFrame({
        "sg_uf": ["AC", "AC", "AC"],
        "cd_municipio_tse": ["01015"] * 3,
        "nr_zona": ["0001"] * 3,
        "nr_secao": ["0010", "0020", "0010"],
        "nr_turno": [1, 1, 2],
    })
    out = e.cobertura_votos("AC", secoes)
    assert out["votos_total"] == 28
    assert out["votos_vinculados"] == 23
    assert out["votos_sem_secao_local"] == 5
    assert out["secoes_com_voto_sem_local"] == 1
    assert out["join_um_para_um"] is True


def test_urbanizacao_municipal_soma_setores(tmp_path):
    _lookup_fake(tmp_path)
    s = pd.DataFrame([
        {"CD_SETOR": "110001505000001", "CD_MUN": "1200179", "pop": 100,
         "dom": 40, "area_km2_calc": 1.0, "flag_urbano": True,
         "flag_sem_basico": False},
        {"CD_SETOR": "110001505000002", "CD_MUN": "1200179", "pop": 300,
         "dom": 80, "area_km2_calc": 3.0, "flag_urbano": False,
         "flag_sem_basico": False},
    ])
    out = e.urbanizacao_municipal([s], tmp_path)
    assert len(out) == 1
    row = out.iloc[0]
    assert row.pop_total == 400 and row.pop_urbana == 100
    assert row.pct_urbana == pytest.approx(25.0)
    assert row.cd_municipio_tse == "01015"
    assert "pop_sidra" not in out.columns or pd.isna(row.get("pop_sidra"))




# --------------------------------------------------------------------------- #
# cache de setores vinculado aos insumos (R38-2)                               #
# --------------------------------------------------------------------------- #


def _cache_falso(tmp_path, monkeypatch):
    raw = tmp_path / "data" / "raw" / "ibge_setores"
    raw.mkdir(parents=True)
    for uf in ("AA", "BB"):
        (raw / f"{uf}_setores_CD2022.gpkg").write_bytes(b"malha " + uf.encode())
    chamadas = []

    def consolidar(malha_path, b, r):
        chamadas.append(malha_path.name)
        return _setores([{"CD_SETOR": b.CD_SETOR.iloc[0], "renda": float(r.V06004.sum()),
                          "geometry": box(0, 0, 1, 1)}])

    monkeypatch.setattr(e, "_consolidar_uf", consolidar)
    monkeypatch.setattr(e, "_recortes_uf", lambda uf, b, r, root: (b[b.UF == uf], r[r.UF == uf]))
    basico = pd.DataFrame({"CD_SETOR": ["1", "2"], "UF": ["AA", "BB"], "pop": [10, 20]})
    renda = pd.DataFrame({"CD_SETOR": ["1", "2"], "UF": ["AA", "BB"], "V06004": [100.0, 200.0]})
    return raw, chamadas, basico, renda


def test_cache_de_setores_e_refeito_quando_insumo_ou_versao_mudam(tmp_path, monkeypatch):
    raw, chamadas, basico, renda = _cache_falso(tmp_path, monkeypatch)
    e.carregar_setores("AA", basico, renda, tmp_path)
    e.carregar_setores("AA", basico, renda, tmp_path)
    assert len(chamadas) == 1                      # mesma chave: reutiliza
    renda2 = renda.assign(V06004=[150.0, 200.0])
    s = e.carregar_setores("AA", basico, renda2, tmp_path)
    assert len(chamadas) == 2 and s.renda.iloc[0] == 150.0   # renda mudou: refaz
    (raw / "AA_setores_CD2022.gpkg").write_bytes(b"malha nova")
    e.carregar_setores("AA", basico, renda2, tmp_path)
    assert len(chamadas) == 3                      # malha mudou: refaz
    monkeypatch.setattr(e, "VERSAO_CONSOLIDACAO", "outra")
    e.carregar_setores("AA", basico, renda2, tmp_path)
    assert len(chamadas) == 4                      # regra de consolidação mudou: refaz
    e.carregar_setores("AA", basico, renda2, tmp_path)
    assert len(chamadas) == 4


def test_cache_sem_chave_e_vizinho_desatualizado_nao_sao_reutilizados(tmp_path, monkeypatch):
    raw, chamadas, basico, renda = _cache_falso(tmp_path, monkeypatch)
    cache = tmp_path / "data" / "staging" / "entorno_local" / "_cache"
    e.carregar_setores("BB", basico, renda, tmp_path)
    # cache antigo sem chave (anterior à correção) é refeito
    (cache / "setores_BB.chave.json").unlink()
    e.carregar_setores("BB", basico, renda, tmp_path)
    assert chamadas == ["BB_setores_CD2022.gpkg"] * 2
    # vizinho: a UF principal é refeita com force; BB, carregado como vizinho (sem force), é refeito
    # só porque a renda de BB mudou
    chaves = {}
    renda2 = renda.assign(V06004=[100.0, 999.0])
    e.carregar_setores("AA", basico, renda2, tmp_path, force=True, chaves=chaves)
    viz = e.carregar_setores("BB", basico, renda2, tmp_path, chaves=chaves)
    assert viz.renda.iloc[0] == 999.0 and chamadas[-1] == "BB_setores_CD2022.gpkg"
    assert set(chaves) == {"AA", "BB"}


def test_validar_cache_grava_chave_so_quando_conteudo_identico(tmp_path, monkeypatch):
    raw, chamadas, basico, renda = _cache_falso(tmp_path, monkeypatch)
    cache = tmp_path / "data" / "staging" / "entorno_local" / "_cache"
    e.carregar_setores("AA", basico, renda, tmp_path)
    (cache / "setores_AA.chave.json").unlink()
    assert e.validar_cache_setores("AA", basico, renda, tmp_path) == "IDENTICO"
    assert e.validar_cache_setores("AA", basico, renda, tmp_path) == "CHAVE_OK"
    # cache antigo com conteúdo diferente (feito com outra renda) é substituído
    (cache / "setores_AA.chave.json").unlink()
    _setores([{"CD_SETOR": "1", "renda": -1.0, "geometry": box(0, 0, 1, 1)}]).to_parquet(cache / "setores_AA.parquet")
    assert e.validar_cache_setores("AA", basico, renda, tmp_path) == "REFEITO"
    assert gpd.read_parquet(cache / "setores_AA.parquet").renda.iloc[0] == 100.0
    assert gpd.read_parquet(cache / "setores_AA.substituido.parquet").renda.iloc[0] == -1.0
