"""Marginais de origem (T1) e destino (T2) para limites e modelo ecológico (B4).

Origens: cada candidato do T1 (ou grupo justificado), ABSTENCAO, BRANCO, NULO.
Destinos: LULA, FLAVIO, ABSTENCAO, BRANCO, NULO.

População entre turnos — HIPÓTESE, não observação. Só se observam os aptos de
cada turno (N1, N2). O saldo N2 − N1 não mede quem entrou e quem saiu: com
N1 = N2 pode haver troca de integrantes, e com N2 > N1 entradas e saídas podem
coexistir. Por isso as categorias de fechamento são CENÁRIOS:

    entradas_i = max(N2 − N1, 0) + r_i      saídas_i = max(N1 − N2, 0) + r_i
    r_i = ρ · N1_i   (rotatividade bruta não observada além do saldo)

ρ = 0 é o cenário de rotatividade MÍNIMA compatível com os aptos (principal,
justificado pelo cadastro fechado antes do 1º turno); ρ > 0 é sensibilidade.
Os limites de Fréchet e as taxas estimadas são condicionais ao cenário.
"""
from __future__ import annotations

import pandas as pd

DESTINOS = ["LULA", "FLAVIO", "ABSTENCAO", "BRANCO", "NULO"]
ENTRADA, SAIDA = "ENTRADA_CADASTRO_CENARIO", "SAIDA_CADASTRO_CENARIO"


def group_small(t1_cand: pd.DataFrame, keep: list[str], other: str = "OUTROS") -> pd.DataFrame:
    """Agrega candidatos fora de `keep`. A justificativa e a sensibilidade à
    escolha de `keep` ficam a cargo do chamador (registradas no relatório)."""
    rest = [c for c in t1_cand.columns if c not in keep]
    out = t1_cand[keep].copy()
    if rest:
        out[other] = t1_cand[rest].sum(axis=1)
    return out


def scenario_label(rho: float) -> str:
    return "rotatividade_minima" if rho == 0 else f"rotatividade_{rho:g}_aptos"


def build_margins(panel: pd.DataFrame, t1_cand: pd.DataFrame, rotatividade: float = 0.0) -> dict:
    """panel: unidades PAREADAS; t1_cand: id_unidade × candidatos do T1 (votos nominais).

    Exige que Σ candidatos T1 = votos válidos T1 na unidade (contabilidade).
    `rotatividade` = ρ ≥ 0, fração dos aptos do T1 trocada além do saldo.
    """
    if rotatividade < 0:
        raise ValueError("rotatividade não pode ser negativa")
    p = panel.set_index("id_unidade")
    c = t1_cand.reindex(p.index)
    if c.isna().any().any():
        raise ValueError("Unidade do painel sem votos de candidatos do T1")
    gap = c.sum(axis=1) - p.qt_votos_validos_t1
    if (gap != 0).any():
        raise ValueError(f"Σ candidatos T1 ≠ válidos T1 em {int((gap != 0).sum())} unidade(s)")
    origins = c.astype(float)
    origins["ABSTENCAO"] = p.qt_abstencoes_t1
    origins["BRANCO"] = p.qt_votos_brancos_t1
    origins["NULO"] = p.qt_votos_nulos_t1
    dest = pd.DataFrame({"LULA": p.qt_lula_t2, "FLAVIO": p.qt_flavio_t2,
                         "ABSTENCAO": p.qt_abstencoes_t2, "BRANCO": p.qt_votos_brancos_t2,
                         "NULO": p.qt_votos_nulos_t2}, index=p.index).astype(float)
    other_valid = p.qt_votos_validos_t2 - p.qt_lula_t2 - p.qt_flavio_t2
    if (other_valid != 0).any():
        raise ValueError("Votos válidos do T2 em votáveis além dos dois finalistas")
    d_aptos = (p.qt_aptos_t2 - p.qt_aptos_t1).astype(float)
    r = rotatividade * p.qt_aptos_t1.astype(float)
    origins[ENTRADA] = d_aptos.clip(lower=0) + r
    dest[SAIDA] = (-d_aptos).clip(lower=0) + r
    if ((origins.sum(axis=1) - dest.sum(axis=1)).abs() > 1e-9).any():
        raise ValueError("Marginais não fecham após categorias de cenário; verifique contabilidade")
    # Pseudo-categorias vazias são removidas para não criar linhas não identificadas à toa.
    if origins[ENTRADA].sum() == 0:
        origins = origins.drop(columns=ENTRADA)
    if dest[SAIDA].sum() == 0:
        dest = dest.drop(columns=SAIDA)
    return {"origens": origins, "destinos": dest,
            "nomes_origem": list(origins.columns), "nomes_destino": list(dest.columns),
            "unidades_aptos_divergentes": int((d_aptos != 0).sum()),
            "cenario_populacao": scenario_label(rotatividade), "rotatividade": rotatividade,
            "hipotese": ("população entre turnos assumida pelo cenário; entradas/saídas não observadas, "
                         "apenas o saldo de aptos é observado")}
