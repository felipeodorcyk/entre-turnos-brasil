"""Limites de identificação dos fluxos a partir apenas das marginais (B4).

Em cada unidade, a tabela origem × destino é desconhecida; só as marginais
são observadas. Para a célula (r, c), os limites de Fréchet
    max(0, R_r + C_c − N) ≤ n_rc ≤ min(R_r, C_c)
são exatos para aquela célula. Somar por unidade dá limites agregados também
exatos célula a célula (cada unidade atinge seu extremo independentemente),
mas não conjuntamente: os extremos de células diferentes não são atingíveis
ao mesmo tempo.

Nenhum limite diz de onde veio um voto individual.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def check_margins(rows: np.ndarray, cols: np.ndarray) -> None:
    rows, cols = np.asarray(rows, float), np.asarray(cols, float)
    if rows.ndim != 2 or cols.ndim != 2 or rows.shape[0] != cols.shape[0]:
        raise ValueError("Marginais precisam ser matrizes unidades × categorias")
    if (rows < 0).any() or (cols < 0).any() or not (np.isfinite(rows).all() and np.isfinite(cols).all()):
        raise ValueError("Marginais negativas ou não finitas")
    # tolerância de arredondamento: cenários com rotatividade ρ > 0 têm marginais fracionárias
    # (ρ·aptos), e a soma em ponto flutuante só fecha até ~1e-12 (mesma regra de build_margins)
    gap = np.abs(rows.sum(1) - cols.sum(1))
    if (gap > 1e-9 * np.maximum(1.0, rows.sum(1))).any():
        raise ValueError(f"População não fechada em {int((gap > 0).sum())} unidade(s): "
                         "Σ origens ≠ Σ destinos. Inclua categorias explícitas de entrada/saída do cadastro.")


def frechet_unit_bounds(rows, cols) -> tuple[np.ndarray, np.ndarray]:
    """Retorna (L, U) com forma unidades × R × C."""
    check_margins(rows, cols)
    r = np.asarray(rows, float)[:, :, None]
    c = np.asarray(cols, float)[:, None, :]
    n = r.sum(1, keepdims=True)
    return np.maximum(0.0, r + c - n), np.minimum(r, c)


def aggregate_bounds(rows, cols, origin_names, dest_names,
                     wide_threshold: float = 0.5) -> pd.DataFrame:
    """Limites agregados em contagens e em taxas (proporção da origem)."""
    L, U = frechet_unit_bounds(rows, cols)
    Ls, Us = L.sum(0), U.sum(0)
    Rtot = np.asarray(rows, float).sum(0)
    out = []
    for i, o in enumerate(origin_names):
        for j, d in enumerate(dest_names):
            den = Rtot[i]
            lo = Ls[i, j] / den if den > 0 else np.nan
            hi = Us[i, j] / den if den > 0 else np.nan
            out.append({"origem": o, "destino": d, "fluxo_min": Ls[i, j], "fluxo_max": Us[i, j],
                        "taxa_min": lo, "taxa_max": hi, "largura_taxa": hi - lo})
    df = pd.DataFrame(out)
    df["pouco_informativo"] = df.largura_taxa >= wide_threshold
    return df


def contains(bounds: pd.DataFrame, flows: np.ndarray, origin_names, dest_names) -> bool:
    """Verifica se uma matriz agregada de fluxos é compatível com os limites."""
    b = bounds.set_index(["origem", "destino"])
    for i, o in enumerate(origin_names):
        for j, d in enumerate(dest_names):
            lo, hi = b.loc[(o, d), ["fluxo_min", "fluxo_max"]]
            if not (lo - 1e-9 <= flows[i, j] <= hi + 1e-9):
                return False
    return True


def merged_origin_bounds(rows, cols, origin_idx, dest_idx) -> tuple[np.ndarray, np.ndarray]:
    """Limites de Fréchet por unidade para a origem formada pela soma de `origin_idx`
    rumo ao destino `dest_idx`. Ao contrário de somar os limites célula a célula,
    tratar as origens como uma só categoria dá limites exatos e conjuntos para o
    grupo (p.ex. "todos os demais candidatos do T1 → Lula")."""
    check_margins(rows, cols)
    r = np.asarray(rows, float)[:, list(origin_idx)].sum(1)
    c = np.asarray(cols, float)[:, dest_idx]
    n = np.asarray(rows, float).sum(1)
    return np.maximum(0.0, r + c - n), np.minimum(r, c)
