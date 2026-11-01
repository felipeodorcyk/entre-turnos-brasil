"""DoD 4: recuperação sintética, restrições, degenerados e intervalos.

Recuperação em dados sintéticos com taxas constantes mostra apenas que o
estimador funciona sob a sua própria hipótese; não valida o modelo real.
"""
import numpy as np
import pytest

from br2026.analysis.bounds import aggregate_bounds, contains
from br2026.analysis.ecological import (cluster_bootstrap, compare_specifications,
                                        fit_constant_rates, project_rows_simplex,
                                        unit_tables_ipf)

BETA = np.array([[0.80, 0.15, 0.05],
                 [0.10, 0.85, 0.05],
                 [0.30, 0.20, 0.50]])


def synth(n=300, noise=False, seed=1):
    rng = np.random.default_rng(seed)
    N = rng.integers(200, 600, size=n)
    Q = rng.dirichlet([2, 2, 1], size=n)
    X = np.round(Q * N[:, None]).astype(float)
    X[:, 0] += N - X.sum(1)
    X = np.clip(X, 0, None)
    if noise:
        Y = np.zeros((n, 3))
        for i in range(n):
            for r in range(3):
                Y[i] += rng.multinomial(int(X[i, r]), BETA[r])
    else:
        Y = X @ BETA
    return X, Y, rng.integers(0, 40, size=n)


def test_exact_recovery_without_noise():
    X, Y, _ = synth()
    f = fit_constant_rates(X, Y)
    assert f.identificado and f.convergiu
    np.testing.assert_allclose(f.beta, BETA, atol=1e-6)


def test_approximate_recovery_with_noise_and_constraints():
    X, Y, _ = synth(noise=True)
    f = fit_constant_rates(X, Y)
    assert f.convergiu and (f.beta >= 0).all()
    np.testing.assert_allclose(f.beta.sum(1), 1, atol=1e-12)
    assert np.abs(f.beta - BETA).max() < 0.05
    # Ajuste aproximado: resíduo marginal relatado, não zero por construção.
    assert f.residuo_relativo_max > 0


def test_ipf_conserves_margins_exactly_and_respects_bounds():
    X, Y, _ = synth(n=60, noise=True)
    f = fit_constant_rates(X, Y)
    T, err = unit_tables_ipf(X, Y, f.beta)
    assert err < 1e-8 and (T >= 0).all()
    names_o, names_d = ["a", "b", "c"], ["x", "y", "z"]
    b = aggregate_bounds(X, Y, names_o, names_d)
    assert contains(b, T.sum(0), names_o, names_d)


def test_no_variation_is_not_identified():
    X = np.tile([[50.0, 30.0, 20.0]], (20, 1))
    Y = X @ BETA
    f = fit_constant_rates(X, Y)
    assert not f.identificado and f.avisos


def test_zero_population_unit_rejected():
    X, Y, _ = synth(n=10)
    X[0] = 0
    Y[0] = 0
    with pytest.raises(ValueError, match="população zero"):
        fit_constant_rates(X, Y)


def test_simplex_projection():
    P = project_rows_simplex(np.array([[2.0, -1.0, 0.5], [0.2, 0.2, 0.2]]))
    np.testing.assert_allclose(P.sum(1), 1)
    assert (P >= 0).all()
    np.testing.assert_allclose(P[1], [1 / 3] * 3)


def test_regularization_shrinks_toward_prior():
    X, Y, _ = synth(noise=True)
    specs = compare_specifications(X, Y, [0.0, 10.0])
    d0 = np.abs(specs[0]["beta"] - 1 / 3).sum()
    d1 = np.abs(specs[1]["beta"] - 1 / 3).sum()
    assert d1 < d0


def test_cluster_bootstrap_interval_labeled_and_covers():
    X, Y, g = synth(noise=True, seed=3)
    b = cluster_bootstrap(X, Y, g, reps=60, seed=7)
    assert "condicional ao modelo" in b["rotulo"]
    assert (b["inf"] <= b["sup"]).all()
    covered = ((b["inf"] - 0.02 <= BETA) & (BETA <= b["sup"] + 0.02)).mean()
    assert covered >= 0.8
