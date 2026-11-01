"""Modelo ecológico restrito de taxas de transição (B4).

Formulação: em cada unidade i, as proporções de destino p_i ∈ Δ^C satisfazem
aproximadamente p_i ≈ q_i β, com q_i ∈ Δ^R as proporções de origem e β uma
matriz R × C com linhas no simplex (taxas não negativas que somam 1). A
hipótese de taxas constantes entre unidades (ou dentro de estratos) é forte e
não testável só com marginais; heterogeneidade intraunidade é falácia ecológica.

Duas saídas distintas, nunca confundidas:
  * `beta` — ajuste APROXIMADO por mínimos quadrados ponderados restritos;
    as marginais preditas não reproduzem exatamente as observadas, e o
    resíduo é reportado.
  * `unit_tables` — tabelas por unidade com conservação EXATA das marginais
    (IPF semeado por diag(x_i) β). A distribuição interna continua dependendo
    da hipótese do modelo; a conservação não a valida.

Incerteza por bootstrap de grupos é condicional ao modelo e não cobre a falta
de identificação, que se lê nos limites de `bounds.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def project_rows_simplex(B: np.ndarray) -> np.ndarray:
    """Projeção euclidiana de cada linha no simplex (Duchi et al., 2008)."""
    B = np.asarray(B, float)
    R, C = B.shape
    u = -np.sort(-B, axis=1)
    css = np.cumsum(u, axis=1) - 1
    idx = np.arange(1, C + 1)
    cond = u - css / idx > 0
    rho = C - 1 - np.argmax(cond[:, ::-1], axis=1)
    theta = css[np.arange(R), rho] / (rho + 1)
    return np.maximum(B - theta[:, None], 0.0)


@dataclass
class FitResult:
    beta: np.ndarray
    identificado: bool
    condicao: float
    iteracoes: int
    convergiu: bool
    residuo_marginal: np.ndarray        # Σ_i N_i (q_i β − p_i), por destino
    residuo_relativo_max: float
    lam: float
    avisos: list[str] = field(default_factory=list)


def _proportions(counts):
    counts = np.asarray(counts, float)
    N = counts.sum(1)
    if (N <= 0).any():
        raise ValueError("Unidade com população zero: remova-a com motivo antes do ajuste")
    return counts / N[:, None], N


def fit_constant_rates(X, Y, weights=None, lam: float = 0.0, prior=None,
                       max_iter: int = 100000, tol: float = 1e-12,
                       max_condition: float = 1e8) -> FitResult:
    """X: unidades × R contagens de origem; Y: unidades × C contagens de destino.

    Minimiza Σ_i w_i ||p_i − q_i β||² + lam ||β − β0||²_F com linhas de β no
    simplex, por gradiente projetado acelerado (FISTA). w padrão = N_i.
    """
    Q, N = _proportions(X)
    P, N2 = _proportions(Y)
    if not np.allclose(N, N2):
        raise ValueError("População não fechada: Σ origens ≠ Σ destinos por unidade")
    R, C = Q.shape[1], P.shape[1]
    w = N if weights is None else np.asarray(weights, float)
    w = w / w.sum()
    G = Q.T @ (w[:, None] * Q)
    H = Q.T @ (w[:, None] * P)
    eig = np.linalg.eigvalsh(G)
    cond = float(eig.max() / eig.min()) if eig.min() > 0 else float("inf")
    identificado = cond < max_condition
    avisos = []
    if not identificado:
        avisos.append("X'WX singular ou mal condicionada: taxas não identificadas pelas marginais "
                      "(sem variação suficiente das origens entre unidades).")
    B0 = np.full((R, C), 1.0 / C) if prior is None else np.asarray(prior, float)
    Lc = 2 * (eig.max() + lam)
    step = 1.0 / Lc
    grad_at = lambda M: 2 * (G @ M - H) + 2 * lam * (M - B0)
    B = project_rows_simplex(B0.copy())
    Z, tk = B.copy(), 1.0
    convergiu = False
    for it in range(1, max_iter + 1):
        Bn = project_rows_simplex(Z - step * grad_at(Z))
        # Reinício adaptativo (O'Donoghue & Candès, 2015) quando o momento aponta para subida.
        if np.sum((Z - Bn) * (Bn - B)) > 0:
            tk = 1.0
        tn = (1 + np.sqrt(1 + 4 * tk * tk)) / 2
        Z = Bn + ((tk - 1) / tn) * (Bn - B)
        B, tk = Bn, tn
        # Critério de otimalidade: mapa de gradiente projetado em B (KKT do problema restrito).
        if it % 10 == 0 and np.abs(B - project_rows_simplex(B - step * grad_at(B))).max() < tol:
            convergiu = True
            break
    if not convergiu:
        avisos.append(f"Não convergiu em {max_iter} iterações")
    pred = (Q @ B) * N[:, None]
    res = (pred - np.asarray(Y, float)).sum(0)
    rel = float(np.abs(res).max() / np.asarray(Y, float).sum())
    return FitResult(B, identificado, cond, it, convergiu, res, rel, lam, avisos)


def unit_tables_ipf(X, Y, beta, max_iter: int = 5000, tol: float = 1e-10,
                    floor: float = 1e-12) -> tuple[np.ndarray, float]:
    """Tabelas unidade × R × C com marginais exatas; retorna (tabelas, erro máximo)."""
    X, Y = np.asarray(X, float), np.asarray(Y, float)
    T = X[:, :, None] * np.maximum(np.asarray(beta, float), floor)[None, :, :]
    T = np.where((X[:, :, None] > 0) & (Y[:, None, :] > 0), T, 0.0)
    err = np.inf
    for _ in range(max_iter):
        rs = T.sum(2)
        T *= np.divide(X, rs, out=np.zeros_like(X), where=rs > 0)[:, :, None]
        cs = T.sum(1)
        T *= np.divide(Y, cs, out=np.zeros_like(Y), where=cs > 0)[:, None, :]
        err = max(np.abs(T.sum(2) - X).max(), np.abs(T.sum(1) - Y).max())
        if err < tol:
            break
    return T, float(err)


def cluster_bootstrap(X, Y, groups, reps: int = 200, seed: int = 0, lam: float = 0.0,
                      level: float = 0.95) -> dict:
    """Reamostra GRUPOS inteiros com reposição; intervalos percentis de β.

    Incerteza condicional à hipótese de taxas constantes; não é margem de erro
    dos votos nem resolve a falácia ecológica.
    """
    X, Y = np.asarray(X, float), np.asarray(Y, float)
    groups = np.asarray(groups)
    ug = np.unique(groups)
    if len(ug) < 2:
        raise ValueError("Bootstrap por grupos requer ao menos 2 grupos")
    idx = {g: np.flatnonzero(groups == g) for g in ug}
    rng = np.random.default_rng(seed)
    draws, nao_ident = [], 0
    for _ in range(reps):
        pick = rng.choice(ug, size=len(ug), replace=True)
        rows = np.concatenate([idx[g] for g in pick])
        f = fit_constant_rates(X[rows], Y[rows], lam=lam)
        nao_ident += not f.identificado
        draws.append(f.beta)
    D = np.stack(draws)
    a = (1 - level) / 2
    return {"inf": np.quantile(D, a, axis=0), "sup": np.quantile(D, 1 - a, axis=0),
            "reps": reps, "grupos": len(ug), "reps_nao_identificadas": nao_ident,
            "rotulo": "incerteza condicional ao modelo (bootstrap de grupos)"}


def compare_specifications(X, Y, lambdas, strata=None) -> list[dict]:
    """Ajusta cada λ e, se dado, cada estrato separadamente; retorna diagnósticos."""
    X, Y = np.asarray(X, float), np.asarray(Y, float)
    out = []
    for lam in lambdas:
        f = fit_constant_rates(X, Y, lam=lam)
        out.append({"especificacao": f"global_lambda_{lam}", "beta": f.beta,
                    "identificado": f.identificado, "residuo_relativo_max": f.residuo_relativo_max})
    if strata is not None:
        strata = np.asarray(strata)
        for s in np.unique(strata):
            m = strata == s
            f = fit_constant_rates(X[m], Y[m])
            out.append({"especificacao": f"estrato_{s}", "beta": f.beta,
                        "identificado": f.identificado, "residuo_relativo_max": f.residuo_relativo_max})
    return out


def publication_decision(fit: FitResult, bounds_df, max_resid: float = 0.01) -> dict:
    """Regra explícita: só publica matriz pontual se identificada, convergida e com
    resíduo marginal pequeno. Limites são sempre publicados."""
    motivos = []
    if not fit.identificado:
        motivos.append("taxas não identificadas pelas marginais")
    if not fit.convergiu:
        motivos.append("otimização não convergiu")
    if fit.residuo_relativo_max > max_resid:
        motivos.append(f"resíduo marginal relativo {fit.residuo_relativo_max:.3g} > {max_resid}")
    frac_wide = float(bounds_df.pouco_informativo.mean())
    return {"publicar_matriz_pontual": not motivos, "motivos": motivos,
            "fracao_celulas_limites_pouco_informativos": frac_wide,
            "publicar_limites": True}
