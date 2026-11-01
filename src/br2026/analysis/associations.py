"""Associações territoriais da variação entre turnos (B3).

Coeficientes descrevem associações condicionais entre unidades, não efeitos
causais nem fluxos de eleitores. Participações do T1 somam 1 com abstenção,
brancos e nulos sobre os aptos; por isso uma categoria de referência é sempre
omitida e o coeficiente de cada outra é lido como diferença em relação a ela.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import t as student_t


def compositional_design(shares: pd.DataFrame, reference: str, tol: float = 1e-8) -> pd.DataFrame:
    """Remove a referência de um conjunto de proporções que soma 1.

    Falha se as colunas não fecharem (então não seriam composicionais) ou se o
    restante ainda for colinear.
    """
    if reference not in shares:
        raise ValueError(f"Referência {reference!r} ausente")
    total = shares.sum(axis=1)
    if (np.abs(total - 1) > tol).any():
        raise ValueError("Proporções não somam 1; defina o denominador comum antes")
    X = shares.drop(columns=reference)
    if np.linalg.matrix_rank(np.column_stack([np.ones(len(X)), X.to_numpy(float)])) < X.shape[1] + 1:
        raise ValueError("Desenho composicional ainda colinear após omitir a referência")
    return X


def demean(x, w, g) -> np.ndarray:
    """Remove médias ponderadas dentro de grupos (efeito fixo absorvido)."""
    x = np.asarray(x, float)
    w = np.asarray(w, float)
    if x.ndim == 1:
        x = x[:, None]
    df = pd.DataFrame(x * w[:, None])
    num = df.groupby(np.asarray(g)).transform("sum").to_numpy()
    den = pd.Series(w).groupby(np.asarray(g)).transform("sum").to_numpy()[:, None]
    out = x - num / den
    return out[:, 0] if out.shape[1] == 1 else out


def clustered_fit(X, y, weights, groups, absorbed: int = 0, level: float = 0.95) -> dict:
    """WLS com covariância sanduíche agrupada (CR1) e graus de liberdade G − 1."""
    X, y, w = np.asarray(X, float), np.asarray(y, float), np.asarray(weights, float)
    if X.ndim == 1:
        X = X[:, None]
    if not (np.isfinite(X).all() and np.isfinite(y).all() and np.isfinite(w).all() and (w > 0).all()):
        raise ValueError("Entrada não finita ou peso não positivo")
    codes, uniq = pd.factorize(np.asarray(groups))
    n, k = X.shape
    G = len(uniq)
    if G < 2 or n <= k + absorbed:
        raise ValueError("Grupos ou graus de liberdade insuficientes")
    XtWX = X.T @ (w[:, None] * X)
    if np.linalg.matrix_rank(XtWX) < k:
        raise ValueError("Desenho colinear")
    bread = np.linalg.inv(XtWX)
    beta = bread @ (X.T @ (w * y))
    resid = y - X @ beta
    scores = X * (w * resid)[:, None]
    S = np.zeros((G, k))
    np.add.at(S, codes, scores)
    corr = G / (G - 1) * (n - 1) / (n - k - absorbed)
    V = corr * bread @ (S.T @ S) @ bread
    se = np.sqrt(np.maximum(np.diag(V), 0))
    crit = student_t.ppf(0.5 + level / 2, G - 1)
    return {"beta": beta, "se": se, "inf": beta - crit * se, "sup": beta + crit * se,
            "cov": V, "grupos": G, "n": n, "resid": resid}


def few_clusters_warning(G: int, threshold: int = 42) -> str | None:
    if G < threshold:
        return (f"Apenas {G} grupos: erros agrupados assintóticos podem subestimar a incerteza; "
                "reporte também o wild cluster bootstrap.")
    return None


def wild_cluster_bootstrap(X, y, weights, groups, coef: int = 0, reps: int = 999,
                           seed: int = 0) -> dict:
    """Wild cluster bootstrap-t restrito (H0: β_coef = 0), pesos de Webb.

    Retorna p-valor bilateral; adequado a poucos grupos.
    """
    X, y, w = np.asarray(X, float), np.asarray(y, float), np.asarray(weights, float)
    if X.ndim == 1:
        X = X[:, None]
    full = clustered_fit(X, y, w, groups)
    t_obs = full["beta"][coef] / full["se"][coef]
    Xr = np.delete(X, coef, axis=1)
    if Xr.shape[1]:
        br = np.linalg.solve(Xr.T @ (w[:, None] * Xr), Xr.T @ (w * y))
        fitted_r = Xr @ br
    else:
        fitted_r = np.zeros_like(y)
    u_r = y - fitted_r
    codes, uniq = pd.factorize(np.asarray(groups))
    rng = np.random.default_rng(seed)
    webb = np.array([-np.sqrt(1.5), -1, -np.sqrt(.5), np.sqrt(.5), 1, np.sqrt(1.5)])
    ts = np.empty(reps)
    for b in range(reps):
        v = rng.choice(webb, size=len(uniq))[codes]
        yb = fitted_r + u_r * v
        f = clustered_fit(X, yb, w, groups)
        ts[b] = f["beta"][coef] / f["se"][coef]
    p = float(np.mean(np.abs(ts) >= abs(t_obs)))
    return {"t": float(t_obs), "p_valor": p, "reps": reps, "grupos": len(uniq)}


def morans_i(values, neighbors: dict, permutations: int = 999, seed: int = 0) -> dict:
    """I de Moran com pesos binários padronizados por linha e teste por permutação.

    neighbors: {índice: [índices vizinhos]} (ex.: municípios adjacentes).
    """
    z = np.asarray(values, float)
    z = z - z.mean()
    n = len(z)
    rows, cols = [], []
    for i, nb in neighbors.items():
        for j in nb:
            rows.append(i)
            cols.append(j)
    rows, cols = np.array(rows), np.array(cols)
    deg = np.bincount(rows, minlength=n).astype(float)
    wv = 1.0 / deg[rows]

    def stat(zz):
        lag = np.bincount(rows, weights=wv * zz[cols], minlength=n)
        return n / wv.sum() * (zz @ lag) / (zz @ zz)

    I = stat(z)
    rng = np.random.default_rng(seed)
    sims = np.array([stat(rng.permutation(z)) for _ in range(permutations)])
    p = (1 + np.sum(np.abs(sims - sims.mean()) >= abs(I - sims.mean()))) / (permutations + 1)
    return {"I": float(I), "esperado": -1 / (n - 1), "p_permutacao": float(p)}


def group_kfold(groups, k: int = 5, seed: int = 0) -> list[tuple[np.ndarray, np.ndarray]]:
    """Partições treino/teste por GRUPO territorial; nenhum grupo em ambos os lados."""
    g = np.asarray(groups)
    uniq = np.unique(g)
    if len(uniq) < k:
        raise ValueError("Menos grupos que dobras")
    rng = np.random.default_rng(seed)
    folds = np.array_split(rng.permutation(uniq), k)
    out = []
    for f in folds:
        test = np.isin(g, f)
        out.append((np.flatnonzero(~test), np.flatnonzero(test)))
    return out


class TrainOnlyPreprocessor:
    """Imputação pela mediana e padronização estimadas apenas no treino."""

    def fit(self, X):
        X = np.asarray(X, float)
        self.median_ = np.nanmedian(X, axis=0)
        Xi = np.where(np.isnan(X), self.median_, X)
        self.mean_ = Xi.mean(0)
        sd = Xi.std(0)
        self.sd_ = np.where(sd > 0, sd, 1.0)
        return self

    def transform(self, X):
        X = np.asarray(X, float)
        Xi = np.where(np.isnan(X), self.median_, X)
        return (Xi - self.mean_) / self.sd_


def weight_sensitivity(X, y, groups, weight_sets: dict, absorbed: int = 0) -> pd.DataFrame:
    """Mesmo modelo sob pesos alternativos (aptos, válidos, sem peso)."""
    rows = []
    for name, w in weight_sets.items():
        f = clustered_fit(X, y, w, groups, absorbed=absorbed)
        for j in range(len(f["beta"])):
            rows.append({"pesos": name, "coef": j, "beta": f["beta"][j], "ep": f["se"][j],
                         "inf": f["inf"][j], "sup": f["sup"][j]})
    return pd.DataFrame(rows)
