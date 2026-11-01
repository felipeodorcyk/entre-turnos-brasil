"""Marco M4 — entrega nacional: 26 estados + DF + exterior, dois turnos.

G2 exige M1 e M2 aprovados com este escopo; G4 exige também M3 e a revisão de C.
"""
import pytest

from integration_support import ALL_UNITS, blocked, reference_problems, require, turns_by_uf

pytestmark = [pytest.mark.integration, pytest.mark.m4]


def test_m4_all_28_units_both_turns():
    require("section_turn")
    by = turns_by_uf()
    unknown = sorted(set(by) - ALL_UNITS)
    assert not unknown, f"unidades fora das 28 esperadas: {unknown}"
    missing = sorted(ALL_UNITS - set(by))
    if missing:
        # Escopo nacional ainda não adquirido (ex.: piloto AC/RS/MG): marco não aprovado, sem ser defeito.
        blocked(f"escopo nacional não adquirido: {len(by)} de 28 unidades no staging; faltam {missing}")
    sem_t2 = sorted(uf for uf in ALL_UNITS if 2 not in by[uf])
    if sem_t2:
        blocked(f"2º turno ausente para {len(sem_t2)} unidade(s): {sem_t2}")


def test_m4_official_reference_national():
    probs = reference_problems(turnos={1, 2})
    assert not probs, "referência nacional:\n" + "\n".join(probs[:20])
