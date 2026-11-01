"""O-R6: contexto municipal — derivação, ausência e ano heterogêneo."""
import numpy as np
import pandas as pd
import pytest

from br2026.analysis.context import municipal_features
from br2026.config import load_config

CFG = load_config()


def ctx(rows):
    df = pd.DataFrame(rows, columns=["sg_uf", "cd_municipio_tse", "variavel", "valor", "ano_referencia"])
    df["valor"] = df.valor.astype(float)
    return df


BASE = [("AC", "01007", "populacao_residente", 20000, 2022), ("AC", "01007", "area_territorial_km2", 3000, 2022),
        ("AC", "01007", "pib_mil_reais", 360000, 2022),
        ("AC", "01015", "populacao_residente", 10000, 2022), ("AC", "01015", "area_territorial_km2", 1700, 2022),
        ("AC", "01015", "pib_mil_reais", None, 2022)]


def test_lean_set_defined_with_sources():
    c = CFG["context"]
    assert c["variaveis"] and set(c["variaveis"]) <= set(c["fontes"])


def test_derivations_and_missing_is_not_zero():
    f, d = municipal_features(ctx(BASE), CFG)
    assert f.loc[("AC", "01007"), "log_densidade"] == pytest.approx(np.log(20000 / 3000))
    assert f.loc[("AC", "01007"), "log_pib_por_habitante"] == pytest.approx(np.log(360000 / 20000))
    assert np.isnan(f.loc[("AC", "01015"), "log_pib_por_habitante"])  # ausente continua ausente
    assert d.set_index("variavel").at["pib_mil_reais", "valores_ausentes"] == 1


def test_heterogeneous_reference_year_invalidates_variable():
    rows = BASE[:-1] + [("AC", "01015", "pib_mil_reais", 15000, 2020)]
    f, d = municipal_features(ctx(rows), CFG)
    assert f.log_pib_por_habitante.isna().all()
    assert d.set_index("variavel").at["pib_mil_reais", "ano_heterogeneo"]


def test_nonpositive_area_gives_missing_density():
    rows = [r if r[2] != "area_territorial_km2" or r[1] != "01007" else ("AC", "01007", r[2], 0, 2022) for r in BASE]
    f, _ = municipal_features(ctx(rows), CFG)
    assert np.isnan(f.loc[("AC", "01007"), "log_densidade"])
