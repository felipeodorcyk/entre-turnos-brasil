"""DoD 1: agregação, mudança e ausência preservam totais e classificam exclusões."""
import pandas as pd

from br2026.contract import validate
from br2026.panel.build import aggregate_panel, build_panel, coverage, reconcile

LULA, FLAVIO = 13, 22


def _build(st, vl, cw):
    return build_panel(st, vl, cw, LULA, FLAVIO, return_membership=True)


def test_units_and_status_match_manual(section_turn, votes_long, crosswalk, expected):
    panel, _ = _build(section_turn, votes_long, crosswalk)
    validate(panel, "panel")
    got = panel.set_index("id_unidade")
    assert set(got.index) == set(expected["unidades"])
    for uid, e in expected["unidades"].items():
        assert got.at[uid, "status_painel"] == e["status"], uid
        assert got.at[uid, "tipo_unidade"] == e["tipo"], uid
        assert got.at[uid, "n_secoes_origem"] == e["n"], uid
        for k, v in e.items():
            if k.startswith(("qt_", "flag_")):
                assert got.at[uid, k] == v, (uid, k)


def test_same_section_number_in_other_uf_does_not_collide(section_turn, votes_long, crosswalk):
    panel, _ = _build(section_turn, votes_long, crosswalk)
    sp = panel[panel.sg_uf == "SP"]
    assert len(sp) == 1 and sp.qt_lula_t1.iloc[0] == 60


def test_paired_and_full_totals_reconcile(section_turn, votes_long, crosswalk, expected):
    panel, mem = _build(section_turn, votes_long, crosswalk)
    rec = reconcile(panel, mem, section_turn, votes_long, LULA, FLAVIO)
    assert rec.attrs["secoes_sem_unidade"] == 0
    assert rec.attrs["secoes_duplicadas"] == 0
    assert (rec.dif == 0).all()
    tot = rec.attrs["total_completo"]
    for k, v in expected["totais_completos"].items():
        metric, t = k.rsplit("_t", 1)
        assert tot[(int(t), metric)] == v
        # incluídas + excluídas = completo, sem perdas
        assert rec[(rec.nr_turno == int(t)) & (rec.metrica == metric)].total_secoes.sum() == v
    pareada = panel[panel.status_painel == "PAREADA"]
    for k, v in expected["pareadas"].items():
        assert pareada[k].sum() == v


def test_aggregation_never_redistributes(section_turn, votes_long, crosswalk):
    """A unidade agregada soma as seções; nenhum valor fracionário aparece."""
    panel, _ = _build(section_turn, votes_long, crosswalk)
    for c in panel.columns:
        if c.startswith("qt_"):
            assert pd.api.types.is_integer_dtype(panel[c].dtype), c


def test_missing_is_not_zero(section_turn, votes_long, crosswalk):
    st = section_turn.copy()
    st.loc[(st.nr_secao == "0001") & (st.sg_uf == "AC") & (st.nr_turno == 2), "qt_votos_brancos"] = pd.NA
    st["qt_votos_brancos"] = st.qt_votos_brancos.astype("Int64")
    panel, mem = _build(st, votes_long, crosswalk)
    u = panel.set_index("id_unidade").loc["AC-01007-0001-0001"]
    assert pd.isna(u.qt_votos_brancos_t2)
    rec = reconcile(panel, mem, st, votes_long, LULA, FLAVIO)
    r = rec[(rec.nr_turno == 2) & (rec.metrica == "qt_votos_brancos") & (rec.status_painel == "PAREADA")]
    assert r.unidades_nao_totalizaveis.iloc[0] == 1


def test_ambiguous_crosswalk_excluded(section_turn, votes_long, crosswalk):
    cw = crosswalk.copy()
    cw.loc[(cw.sg_uf == "SP"), "flag_ambigua"] = True
    panel, _ = _build(section_turn, votes_long, cw)
    assert panel.set_index("id_unidade").at["SP-71072-0001-0001", "status_painel"] == "EXCLUIDA_AMBIGUA"


def test_coverage_counts_included_and_excluded(section_turn, votes_long, crosswalk):
    panel, _ = _build(section_turn, votes_long, crosswalk)
    cov = coverage(panel, ["sg_uf"]).set_index("sg_uf")
    assert cov.at["AC", "unidades_incluida"] == 2 and cov.at["AC", "unidades_excluida"] == 3
    assert cov.at["AC", "qt_aptos_t1_incluida"] == 250
    assert cov.at["AC", "qt_aptos_t1_excluida"] == 170
    assert cov.at["SP", "unidades_pct_incluida"] == 1.0


def test_sensitivity_aggregation_levels_conserve(section_turn, votes_long, crosswalk):
    panel, _ = _build(section_turn, votes_long, crosswalk)
    pareada = panel[panel.status_painel == "PAREADA"]
    for level in ("LOCAL", "MUNICIPIO"):
        agg = aggregate_panel(panel, level)
        assert agg.qt_lula_t2.sum() == pareada.qt_lula_t2.sum()


def test_expected_only_correspondence_never_promoted(section_turn, votes_long, crosswalk):
    """v1.1/Q4: CESP (ESPERADA) sem EFETIVADA no turno exclui a unidade com motivo próprio."""
    cw = crosswalk.copy()
    m = (cw.sg_uf == "SP") & (cw.nr_turno == 2)
    cw.loc[m, "status_correspondencia"] = "ESPERADA"
    panel, mem = _build(section_turn, votes_long, cw)
    u = panel.set_index("id_unidade").loc["SP-71072-0001-0001"]
    assert u.status_painel == "EXCLUIDA_CORRESPONDENCIA_NAO_EFETIVADA"
    rec = reconcile(panel, mem, section_turn, votes_long, LULA, FLAVIO)
    assert (rec.dif == 0).all() and rec.attrs["secoes_sem_unidade"] == 0


def test_expected_row_alongside_effective_is_ignored(section_turn, votes_long, crosswalk):
    """Linha ESPERADA divergente não altera a unidade quando há EFETIVADA no turno."""
    extra = crosswalk[(crosswalk.sg_uf == "SP") & (crosswalk.nr_turno == 2)].copy()
    extra["status_correspondencia"] = "ESPERADA"
    extra["nr_secao_apuradora"] = "0999"
    panel, _ = _build(section_turn, votes_long, pd.concat([crosswalk, extra]))
    assert panel.set_index("id_unidade").at["SP-71072-0001-0001", "status_painel"] == "PAREADA"
    assert len(panel) == 6


def test_separately_annulled_votes_make_identity_indeterminate(section_turn, votes_long, crosswalk):
    """v1.1/Q2: anulados apurados em separado > 0 sem regra documentada → exclusão contábil."""
    st = section_turn.copy()
    st.loc[(st.sg_uf == "SP") & (st.nr_turno == 1), "qt_votos_anulados_apu_sep"] = 3
    panel, _ = _build(st, votes_long, crosswalk)
    assert panel.set_index("id_unidade").at["SP-71072-0001-0001", "status_painel"] == "EXCLUIDA_CONTABILIDADE"


def test_chained_aggregation_forms_single_unit(section_turn, votes_long, crosswalk):
    """Achado F-03 de C: 0006→0005 e 0005→0001 no T1 (0005 sem urna própria) → uma unidade."""
    cw = crosswalk.copy()
    t1 = cw.nr_turno == 1
    cw.loc[t1 & (cw.sg_uf == "AC") & (cw.nr_secao == "0006"), "nr_secao_apuradora"] = "0005"
    cw.loc[t1 & (cw.sg_uf == "AC") & (cw.nr_secao == "0005"), "nr_secao_apuradora"] = "0001"
    st = section_turn[~((section_turn.nr_turno == 1) & (section_turn.sg_uf == "AC")
                        & section_turn.nr_secao.isin(["0005", "0006"]))]
    vl = votes_long[~((votes_long.nr_turno == 1) & (votes_long.sg_uf == "AC")
                      & votes_long.nr_secao.isin(["0005", "0006"]))]
    panel, mem = _build(st, vl, cw)
    u = panel.set_index("id_unidade").loc["AC-01007-0001-0001"]
    assert u.n_secoes_origem == 3 and u.status_painel != "EXCLUIDA_AUSENTE_T1"
    rec = reconcile(panel, mem, st, vl, LULA, FLAVIO)
    assert (rec.dif == 0).all() and rec.attrs["secoes_sem_unidade"] == 0


def test_technical_null_votes_leave_valid_and_join_null(section_turn, votes_long, crosswalk):
    """Handoff 17: votos em 'Nulo técnico' (ex.: renúncia) saem dos válidos e entram nos nulos."""
    # Na fixture, o votável 30 tem 15 votos na seção AC/0001 do T1; tratamos 30 como nulo técnico.
    panel, mem = build_panel(section_turn, votes_long, crosswalk, LULA, FLAVIO,
                             return_membership=True, technical_null={"t1": [30]})
    u = panel.set_index("id_unidade").loc["AC-01007-0001-0001"]
    assert u.qt_votos_validos_t1 == 70 - 15 and u.qt_votos_nulos_t1 == 6 + 15
    assert u.qt_comparecimento_t1 == u.qt_votos_validos_t1 + u.qt_votos_brancos_t1 + u.qt_votos_nulos_t1
    assert u.qt_votos_validos_t2 == 76  # lista vazia para o T2: inalterado
    rec = reconcile(panel, mem, section_turn, votes_long, LULA, FLAVIO, technical_null={"t1": [30]})
    assert (rec.dif == 0).all()


def test_coverage_sem_exclusoes_traz_colunas_excluida_com_zero():
    """Painel real de dois turnos (27/10): 100% pareado; a cobertura ainda declara zero excluídas."""
    import pandas as pd
    from br2026.panel.build import coverage
    p = pd.DataFrame({"id_unidade": ["a", "b"], "sg_uf": ["AC", "AC"], "status_painel": ["PAREADA", "PAREADA"],
                      "qt_aptos_t1": [10, 20], "qt_aptos_t2": [10, 21],
                      "qt_votos_validos_t1": [8, 15], "qt_votos_validos_t2": [7, 16]})
    cov = coverage(p)
    assert cov.loc[0, "unidades_incluida"] == 2 and cov.loc[0, "unidades_excluida"] == 0
    assert cov.loc[0, "qt_aptos_t2_excluida"] == 0 and cov.loc[0, "unidades_pct_incluida"] == 1.0
