"""DoD 5: covariância agrupada contra cálculo independente; separação por grupos."""
import numpy as np
import pandas as pd
import pytest

from br2026.analysis.associations import (TrainOnlyPreprocessor, clustered_fit,
                                          compositional_design, demean, few_clusters_warning,
                                          group_kfold, morans_i, weight_sensitivity,
                                          wild_cluster_bootstrap)


def data(n=400, G=25, seed=0):
    rng = np.random.default_rng(seed)
    g = rng.integers(0, G, size=n)
    u = rng.normal(size=G)[g]
    X = np.column_stack([np.ones(n), rng.normal(size=n), rng.normal(size=n)])
    y = X @ [1.0, 0.5, -0.2] + u + rng.normal(size=n)
    w = rng.uniform(0.5, 2.0, size=n)
    return X, y, w, g


def independent_cr1(X, y, w, g):
    """Cálculo independente: WLS por lstsq em dados reescalados e soma explícita por cluster."""
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    e = y - X @ beta
    n, k = X.shape
    groups = np.unique(g)
    meat = np.zeros((k, k))
    for gg in groups:
        m = g == gg
        s = (X[m] * (w[m] * e[m])[:, None]).sum(0)
        meat += np.outer(s, s)
    bread = np.linalg.inv((X * w[:, None]).T @ X)
    G = len(groups)
    c = G / (G - 1) * (n - 1) / (n - k)
    return beta, c * bread @ meat @ bread


def test_clustered_cov_matches_independent():
    X, y, w, g = data()
    f = clustered_fit(X, y, w, g)
    b, V = independent_cr1(X, y, w, g)
    np.testing.assert_allclose(f["beta"], b, rtol=1e-10)
    np.testing.assert_allclose(f["cov"], V, rtol=1e-10)


def test_singleton_clusters_equal_hc1():
    X, y, w, _ = data(n=120)
    g = np.arange(len(y))
    f = clustered_fit(X, y, w, g)
    n, k = X.shape
    e = f["resid"]
    bread = np.linalg.inv((X * w[:, None]).T @ X)
    meat = (X * (w * e)[:, None]).T @ (X * (w * e)[:, None])
    np.testing.assert_allclose(f["cov"], n / (n - k) * bread @ meat @ bread, rtol=1e-10)


def test_fixed_effects_demeaning_matches_dummies():
    X, y, w, g = data(n=200, G=8)
    xd, yd = demean(X[:, 1:], w, g), demean(y, w, g)
    f = clustered_fit(xd, yd, w, g, absorbed=8)
    D = pd.get_dummies(g).to_numpy(float)
    full = np.column_stack([X[:, 1:], D])
    sw = np.sqrt(w)
    b, *_ = np.linalg.lstsq(full * sw[:, None], y * sw, rcond=None)
    np.testing.assert_allclose(f["beta"], b[:2], rtol=1e-8)


def test_compositional_requires_reference():
    s = pd.DataFrame({"a": [.2, .3, .5, .1], "b": [.5, .3, .2, .6], "c": [.3, .4, .3, .3]})
    X = compositional_design(s, "c")
    assert list(X.columns) == ["a", "b"]
    with pytest.raises(ValueError, match="não somam 1"):
        compositional_design(s.assign(a=s.a + .1), "c")
    full = np.column_stack([np.ones(4), s.to_numpy()])
    assert np.linalg.matrix_rank(full) < full.shape[1]


def test_group_kfold_never_mixes_groups():
    g = np.repeat(np.arange(30), 7)
    for tr, te in group_kfold(g, k=5):
        assert not set(g[tr]) & set(g[te])
        assert len(tr) + len(te) == len(g)


def test_preprocessor_fitted_on_train_only():
    rng = np.random.default_rng(0)
    tr = rng.normal(size=(50, 2))
    tr[0, 0] = np.nan
    te = rng.normal(loc=100, size=(20, 2))
    p = TrainOnlyPreprocessor().fit(tr)
    m = p.mean_.copy()
    p.transform(te)
    np.testing.assert_array_equal(p.mean_, m)
    assert abs(p.mean_[1]) < 1


def test_few_clusters_flag_and_wild_bootstrap():
    assert few_clusters_warning(12) is not None and few_clusters_warning(60) is None
    X, y, w, g = data(n=150, G=10)
    r = wild_cluster_bootstrap(X, y, w, g, coef=1, reps=199, seed=1)
    assert 0 <= r["p_valor"] <= 1 and r["grupos"] == 10
    assert r["p_valor"] < 0.05


def test_morans_i_detects_positive_autocorrelation():
    vals = np.r_[np.zeros(20), np.ones(20)] + np.random.default_rng(0).normal(0, .05, 40)
    nb = {i: [j for j in (i - 1, i + 1) if 0 <= j < 40] for i in range(40)}
    r = morans_i(vals, nb, permutations=199)
    assert r["I"] > 0.5 and r["p_permutacao"] < 0.05


def test_weight_sensitivity_reports_each_scheme():
    X, y, w, g = data()
    out = weight_sensitivity(X, y, g, {"aptos": w, "sem_pesos": np.ones_like(w)})
    assert set(out.pesos) == {"aptos", "sem_pesos"}
