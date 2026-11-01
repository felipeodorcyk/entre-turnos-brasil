"""Análises socioeconômicas (handoff 37): faixas, razões de somas, modelos e conferência independente.

Dados sintéticos, sem relação com resultados eleitorais reais.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from br2026.analysis import associations as assoc
from br2026.analysis import socio


def _mun(n=60, seed=0, ufs=("AA", "BB", "CC")):
    rng = np.random.default_rng(seed)
    uf = np.array(ufs)[np.arange(n) % len(ufs)]
    aptos = rng.integers(1_000, 50_000, n)
    comp1 = (aptos * rng.uniform(0.7, 0.85, n)).astype(int)
    comp2 = (aptos * rng.uniform(0.7, 0.85, n)).astype(int)
    v1, v2 = (comp1 * 0.95).astype(int), (comp2 * 0.96).astype(int)
    l1 = (v1 * rng.uniform(0.3, 0.6, n)).astype(int)
    f1 = (v1 * rng.uniform(0.3, 0.4, n)).astype(int)
    l2 = (v2 * rng.uniform(0.4, 0.6, n)).astype(int)
    d = pd.DataFrame({"sg_uf": uf, "cd_municipio_tse": [f"{i:05d}" for i in range(n)],
                      "qt_aptos_t1": aptos, "qt_aptos_t2": aptos, "qt_comparecimento_t1": comp1,
                      "qt_comparecimento_t2": comp2, "qt_votos_validos_t1": v1, "qt_votos_validos_t2": v2,
                      "qt_lula_t1": l1, "qt_lula_t2": l2, "qt_flavio_t1": f1, "qt_flavio_t2": v2 - l2,
                      "qt_votos_brancos_t1": (comp1 - v1) // 2, "qt_votos_nulos_t1": comp1 - v1 - (comp1 - v1) // 2,
                      "qt_votos_brancos_t2": (comp2 - v2) // 2, "qt_votos_nulos_t2": comp2 - v2 - (comp2 - v2) // 2,
                      "cd_regiao_imediata": [f"R{i % 12}" for i in range(n)]})
    for k in (1, 2):
        d[f"share_lula_validos_t{k}"] = d[f"qt_lula_t{k}"] / d[f"qt_votos_validos_t{k}"]
        d[f"comparecimento_aptos_t{k}"] = d[f"qt_comparecimento_t{k}"] / d[f"qt_aptos_t{k}"]
    d["delta_share_lula_validos"] = d.share_lula_validos_t2 - d.share_lula_validos_t1
    d["delta_comparecimento_aptos"] = d.comparecimento_aptos_t2 - d.comparecimento_aptos_t1
    d["delta_margem_lula_flavio_validos"] = 2 * d.share_lula_validos_t2 - 1 - (d.qt_lula_t1 - d.qt_flavio_t1) / d.qt_votos_validos_t1
    d["log_aptos_t1"] = np.log(d.qt_aptos_t1.astype(float))
    d["share_demais_validos_t1"] = (d.qt_votos_validos_t1 - d.qt_lula_t1 - d.qt_flavio_t1) / d.qt_votos_validos_t1
    d["brancos_nulos_comparecimento_t1"] = (d.qt_votos_brancos_t1 + d.qt_votos_nulos_t1) / d.qt_comparecimento_t1
    d["renda_pc"] = rng.lognormal(7, 0.4, n)
    d["urbana"] = rng.uniform(20, 100, n)
    return d


# ---------------------------------------------------------------- faixas
def test_faixas_preservam_empates_e_cortes_sao_valores_observados():
    v = pd.Series([1, 1, 1, 1, 2, 3, 4, 5, 5, 5, np.nan])
    cortes = socio.cortes_quintis(v)
    assert set(cortes) <= set(v.dropna())
    f = socio.faixa(v, cortes)
    assert f.iloc[:4].nunique() == 1 and f.iloc[7:10].nunique() == 1      # empates juntos
    assert pd.isna(f.iloc[10])                                            # ausente fica sem faixa


def test_votacao_por_faixa_e_razao_de_somas_nao_media_de_percentuais():
    d = _mun(20)
    d.loc[0, ["qt_lula_t2", "qt_votos_validos_t2"]] = [9_000, 10_000]     # município grande
    d.loc[1, ["qt_lula_t2", "qt_votos_validos_t2"]] = [1, 100]           # município pequeno
    d["x"] = 1.0                                                          # todos na mesma faixa
    socio.INDICADORES["x"] = ("", "", "", "nivel", 1.0, "")
    try:
        t = socio.tabela_faixas(d, "x")
    finally:
        del socio.INDICADORES["x"]
    esperado = d.qt_lula_t2.sum() / d.qt_votos_validos_t2.sum()
    assert len(t) == 1 and t.share_lula_t2.iloc[0] == pytest.approx(esperado)
    assert t.share_lula_t2.iloc[0] != pytest.approx((d.qt_lula_t2 / d.qt_votos_validos_t2).mean())


# ---------------------------------------------------------------- modelos
def _referencia_dummies(y, X, w, fe, cl):
    """Implementação independente: EF como dummies explícitas e sanduíche agrupado em laço."""
    D = pd.get_dummies(pd.Series(fe)).to_numpy(float)
    Z = np.column_stack([X, D])
    W = np.diag(w)
    bread = np.linalg.pinv(Z.T @ W @ Z)
    b = bread @ Z.T @ W @ y
    e = y - Z @ b
    meat = np.zeros((Z.shape[1], Z.shape[1]))
    for g in np.unique(cl):
        m = cl == g
        s = Z[m].T @ (w[m] * e[m])
        meat += np.outer(s, s)
    n, k = Z.shape
    G = len(np.unique(cl))
    V = G / (G - 1) * (n - 1) / (n - k) * bread @ meat @ bread
    return b[: X.shape[1]], np.sqrt(np.diag(V))[: X.shape[1]]


def test_estimador_confere_com_implementacao_independente_e_escala():
    d = _mun(80, seed=3)
    x = np.log(d.renda_pc.to_numpy())
    ctrl = d[["log_aptos_t1", "share_lula_validos_t1"]].to_numpy()
    X = np.column_stack([x, ctrl])
    y, w = d.delta_share_lula_validos.to_numpy(), d.qt_aptos_t1.to_numpy(float)
    fe, cl = d.sg_uf.to_numpy(), d.cd_regiao_imediata.to_numpy()
    f = socio._ajuste_fe(y, X, w, fe, cl)
    b_ref, se_ref = _referencia_dummies(y, X, w, fe, cl)
    assert np.allclose(f["beta"], b_ref, rtol=1e-8)
    assert np.allclose(f["se"], se_ref, rtol=1e-8)
    # escala editorial: por duplicação = β·ln2 em p.p.; reparametrizar x em log2 dá o mesmo número
    X2 = np.column_stack([np.log2(d.renda_pc.to_numpy()), ctrl])
    f2 = socio._ajuste_fe(y, X2, w, fe, cl)
    assert 100 * f2["beta"][0] == pytest.approx(100 * f["beta"][0] * math.log(2), rel=1e-10)


def test_bruto_e_ajustado_usam_a_mesma_amostra():
    d = _mun(60)
    d.loc[5, "share_lula_validos_t1"] = np.nan          # falta um controle: sai das duas especificações
    r = socio.modelo_municipal(d, "renda_pc", "delta_share_lula_validos")
    assert r[0]["n"] == r[1]["n"] == 59


def test_invariancia_a_ordem_das_linhas():
    d = _mun(60, seed=7)
    a = socio.modelo_municipal(d, "renda_pc", "delta_share_lula_validos")
    b = socio.modelo_municipal(d.sample(frac=1, random_state=1), "renda_pc", "delta_share_lula_validos")
    assert a[1]["efeito_pp"] == pytest.approx(b[1]["efeito_pp"], rel=1e-10)
    assert a[1]["inf_pp"] == pytest.approx(b[1]["inf_pp"], rel=1e-10)


def test_indicador_constante_no_efeito_fixo_e_absorvido():
    d = _mun(30)
    d["renda_pc"] = d.sg_uf.map({"AA": 100.0, "BB": 200.0, "CC": 400.0})   # só varia entre UFs
    with pytest.raises(ValueError, match="colinear"):
        socio.modelo_municipal(d, "renda_pc", "delta_share_lula_validos")


def test_desenho_colinear_e_cluster_unico_falham():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(20, 2))
    X = np.column_stack([X, X[:, 0] + X[:, 1]])
    with pytest.raises(ValueError, match="colinear"):
        assoc.clustered_fit(X, rng.normal(size=20), np.ones(20), np.arange(20) % 4)
    with pytest.raises(ValueError, match="insuficientes"):
        assoc.clustered_fit(rng.normal(size=(20, 1)), rng.normal(size=20), np.ones(20), np.zeros(20))
    assert assoc.few_clusters_warning(10) is not None


def test_desfecho_sem_variacao_da_coeficiente_zero():
    d = _mun(40)
    d["delta_comparecimento_aptos"] = 0.01
    r = socio.modelo_municipal(d, "renda_pc", "delta_comparecimento_aptos")
    assert abs(r[1]["efeito_pp"]) < 1e-9


def test_perfis_ponderados_pelos_votos_da_base():
    d = _mun(10)
    for n in socio.INDICADORES:
        d[n] = 1.0
    d["renda_pc"] = np.arange(10, dtype=float)
    p = socio.perfis_bases(d).set_index("base")
    esperado = np.average(d.renda_pc, weights=d.qt_lula_t1)
    assert p.loc["Lula, 1º turno", "renda_pc"] == pytest.approx(esperado)
    dif = p.loc["Lula: 2º − 1º turno (diferença de perfil)", "renda_pc"]
    assert dif == pytest.approx(np.average(d.renda_pc, weights=d.qt_lula_t2) - esperado)


def test_escala_editorial_dos_termos_em_log_confere_com_coeficiente_original():
    """Item 9: termos em log ganham escala 'por duplicação' (β·ln2·100); ausente fica 'não estimado'."""
    from br2026.reporting.pilot_comparative import _normalize_associations_table
    t = pd.DataFrame({"bloco_termo": ["contexto", "composicao", "contexto"],
                      "beta_simples": [0.002, 0.03, np.nan], "inf_simples": [0.001, 0.02, np.nan],
                      "sup_simples": [0.003, 0.04, np.nan], "beta_ajustado": [0.0008, 0.05, np.nan],
                      "inf_ajustado": [0.0002, 0.04, np.nan], "sup_ajustado": [0.0014, 0.06, np.nan]})
    n = _normalize_associations_table(t)
    assert n.escala_editorial.tolist() == ["p.p. por duplicação", "p.p. por +10 p.p.", "p.p. por duplicação"]
    assert n.efeito_ajustado[0] == pytest.approx(0.0008 * math.log(2) * 100)
    assert n.efeito_inf_ajustado[0] == pytest.approx(0.0002 * math.log(2) * 100)
    assert n.efeito_ajustado[1] == pytest.approx(0.05 * 10)
    assert np.isnan(n.pp_por_10pp_ajustado[0])                 # escala antiga continua só para proporções
    assert n.situacao_estimativa.tolist() == ["estimado", "estimado", "não estimado"]


def test_cli_socio_recusa_etapa_desconhecida_e_offline_sem_cache(tmp_path):
    from br2026 import cli
    assert cli.main(["--root", str(tmp_path), "socio", "--etapas", "xyz"]) == cli.EXIT_USAGE
    # raiz vazia: RAIS principal ausente e --offline -> bloqueia sem tentar rede
    assert cli.main(["--root", str(tmp_path), "socio", "--etapas", "rais", "--offline"]) == cli.EXIT_BLOCKED


# ---------------------------------------------------------------- entorno: elegibilidade por raio (R38-1)
def test_raio_de_sensibilidade_usa_a_propria_cobertura():
    d = pd.DataFrame({
        "status_entorno": ["VALIDO", "VALIDO", "INVALIDO", "SEM_LOCAL"],
        "id_local": ["L1", "L2", "L3", None],
        "flag_renda_valida": [True, True, False, False],
        "densidade_hab_km2": [100.0, 200.0, 50.0, np.nan],
        "renda_media_responsavel": [1500.0, 2000.0, np.nan, np.nan],
        "cobertura_area_3000": [0.95, 0.60, 0.92, np.nan],   # L2 válido em 1 km, círculo de 3 km sem dados
        "cobertura_renda_3000": [0.80, 0.80, 0.50, np.nan],
        "densidade_hab_km2_3000": [80.0, 150.0, 40.0, np.nan],
        "renda_media_responsavel_3000": [1400.0, 1900.0, 1200.0, np.nan],
    })
    assert socio.elegivel_raio(d, "densidade").tolist() == [True, True, False, False]
    # 3 km: L2 sai (área 0,60) apesar de valer em 1 km; L3 entra (inválido só em 1 km, coberto em 3 km)
    assert socio.elegivel_raio(d, "densidade", 3000).tolist() == [True, False, True, False]
    # renda em 3 km também exige a cobertura de renda do próprio raio
    assert socio.elegivel_raio(d, "renda_resp", 3000).tolist() == [True, False, False, False]
    assert socio.elegivel_raio(d, "renda_resp").tolist() == [True, True, False, False]


# ---------------------------------------------------------------- versão final: raio único de 1 km (handoff 40)
FILTROS_1KM = {"principal", "sem_mudanca_local", "cobertura_area_075", "cobertura_area_095", "peso_domicilios",
               "cobertura_renda_0.50", "cobertura_renda_0.90", "sem_coord_fora_municipio"}


def _unidades_entorno(n=240, seed=3):
    rng = np.random.default_rng(seed)
    d = pd.DataFrame({"municipio": [f"M{i % 6}" for i in range(n)], "id_local": [f"L{i % 80}" for i in range(n)],
                      "peso": rng.integers(100, 400, n).astype(float),
                      "status_entorno": np.where(np.arange(n) % 10 == 0, "INVALIDO", "VALIDO"),
                      "flag_renda_valida": np.arange(n) % 15 != 0, "mudou_local": np.arange(n) % 30 == 0,
                      "flag_coord_fora_municipio": np.arange(n) % 40 == 0,
                      "cobertura_area": rng.uniform(0.7, 1.0, n), "cobertura_renda": rng.uniform(0.6, 1.0, n),
                      "renda_media_responsavel": rng.lognormal(7.5, 0.4, n),
                      "renda_media_responsavel_peso_domicilios": rng.lognormal(7.5, 0.4, n),
                      "pct_pop_urbana": rng.uniform(30, 100, n), "densidade_hab_km2": rng.lognormal(7, 1, n),
                      "pct_pop_favela": rng.uniform(0, 30, n), "log_aptos_t1": rng.normal(6, 0.3, n)})
    for y in DESFECHOS_TESTE:
        d[y] = rng.normal(0.05, 0.02, n)
    return d


DESFECHOS_TESTE = socio.DESFECHOS


def test_versao_final_gera_so_1km_sem_colunas_de_outros_raios():
    d = _unidades_entorno()
    assert not [c for c in d.columns if c.endswith(("_500", "_3000"))]
    me = socio.modelos_entorno(d, ["log_aptos_t1"])
    assert set(me.filtro) == FILTROS_1KM
    assert not me.filtro.str.contains("raio|intersecao").any()
    # amostra principal = elegíveis em 1 km, sem depender de outros raios
    p = me[(me.filtro == "principal") & (me.cluster == "id_local")].set_index(["indicador", "desfecho"])
    for var in socio.ENTORNO:
        esperado = int(socio.elegivel_raio(d, var).sum())
        assert (p.loc[var].n_unidades == esperado).all()


def test_unidade_valida_em_1km_continua_na_amostra_mesmo_invalida_em_outro_raio():
    d = _unidades_entorno()
    base = socio.modelos_entorno(d, ["log_aptos_t1"])
    # colunas de legado de outro raio, com cobertura ruim em todas as unidades, não alteram a versão final
    d2 = d.assign(cobertura_area_3000=0.10, densidade_hab_km2_3000=1.0, cobertura_renda_3000=0.10)
    pd.testing.assert_frame_equal(base, socio.modelos_entorno(d2, ["log_aptos_t1"]))


def test_cli_entorno_aceita_sem_sensibilidades_e_passa_so_o_raio_principal(tmp_path, monkeypatch):
    from br2026 import cli, config
    from br2026.ingest import entorno_nacional
    cfg = config.load_config()
    assert cfg["socio"]["entorno_raio_m"] == 1000 and cfg["socio"]["entorno_sensibilidades_m"] == []
    chamadas = []
    monkeypatch.setattr(entorno_nacional, "main", lambda argv: chamadas.append(argv) or 0)
    sem_chave = {**cfg, "socio": {k: v for k, v in cfg["socio"].items() if k != "entorno_sensibilidades_m"}}
    for c in (cfg, sem_chave):
        monkeypatch.setattr(config, "load_config", lambda c=c: c)
        assert cli.main(["--root", str(tmp_path), "socio", "--etapas", "entorno"]) == 0
    for argv in chamadas:
        assert argv[argv.index("--raio") + 1] == "1000" and argv[argv.index("--sensibilidades") + 1] == ""
        assert argv[argv.index("--cobertura-min") + 1] == "0.9" and argv[argv.index("--renda-min") + 1] == "0.75"
