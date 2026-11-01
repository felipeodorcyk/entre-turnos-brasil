"""Marco M1 — engenharia eleitoral do 1º turno, sobre dados oficiais reais.

Não exige 2º turno, correspondências nem horários. Aprovação do M1 não
promove G2 nem G4.
"""
import pandas as pd
import pytest

from integration_support import (MIN_PILOT_UFS, MIN_SIZE_RATIO, manifest_hashes,
                                 reference_problems, require)

pytestmark = [pytest.mark.integration, pytest.mark.m1]


def _t1(df):
    return df[(df.nr_turno == 1) & (df.cd_cargo == 1)]


def test_m1_pilot_scope_three_ufs_distinct_sizes():
    st = _t1(require("section_turn")[0])
    sizes = st[st.sg_uf != "ZZ"].groupby("sg_uf").size()
    assert sizes.size >= MIN_PILOT_UFS, f"{sizes.size} UF(s): {list(sizes.index)}"
    assert sizes.max() / sizes.min() >= MIN_SIZE_RATIO, f"portes pouco distintos: {sizes.to_dict()}"


def test_m1_provenance_in_manifest():
    tables = require("section_turn", "votes_long")
    hashes = manifest_hashes()
    for name, df in zip(("section_turn", "votes_long"), tables):
        unknown = set(df.source_id) - hashes
        assert not unknown, f"{name}: source_id fora do manifesto {sorted(unknown)[:3]}"


def test_m1_identity_flags_follow_contract_rules():
    st = _t1(require("section_turn")[0])
    full = st.dropna(subset=["qt_aptos", "qt_comparecimento", "qt_abstencoes"])
    rec = full.qt_aptos == full.qt_comparecimento + full.qt_abstencoes
    assert (full.flag_identidade_aptos.astype(bool) == rec).all()
    anul = st.qt_votos_anulados_apu_sep.fillna(0) > 0
    assert st.loc[anul, "flag_identidade_comparecimento"].isna().all(), \
        "Q2: identidade indeterminada quando anulados em separado > 0"
    ok = st[~anul].dropna(subset=["qt_comparecimento", "qt_votos_nominais", "qt_votos_legenda",
                                  "qt_votos_brancos", "qt_votos_nulos"])
    rec = ok.qt_comparecimento == (ok.qt_votos_nominais + ok.qt_votos_legenda
                                   + ok.qt_votos_brancos + ok.qt_votos_nulos)
    assert (ok.flag_identidade_comparecimento.astype(bool) == rec).all()


def test_m1_not_installed_sections_preserved_not_edited():
    st = _t1(require("section_turn")[0])
    ni = st[st.st_secao_instalada.eq(False)]
    # Q3: preservadas com aptos e sem comparecimento inventado.
    assert ni.qt_aptos.notna().all()
    assert (ni.qt_comparecimento.fillna(0) == 0).all()


def test_m1_votes_long_matches_section_totals():
    st, vl = require("section_turn", "votes_long")
    key = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
    v = _t1(vl).pivot_table(index=key, columns="tipo_votavel", values="qt_votos", aggfunc="sum",
                            fill_value=0)
    j = _t1(st).set_index(key).join(v, how="left")
    apurada = j.qt_votos_nominais.notna()
    valid = j.get("NOMINAL", 0) + j.get("LEGENDA", 0)
    bad = apurada & (pd.Series(valid, index=j.index).fillna(0) != j.qt_votos_nominais + j.qt_votos_legenda)
    assert not bad.any(), f"{int(bad.sum())} seção(ões) com Σ votáveis ≠ válidos"
    for col, tipo in (("qt_votos_brancos", "BRANCO"), ("qt_votos_nulos", "NULO")):
        if tipo in j:
            diff = apurada & (j[tipo].fillna(0) != j[col])
            assert not diff.any(), f"{int(diff.sum())} seção(ões) com {tipo} divergente"
    orphan = _t1(vl).set_index(key).index.difference(_t1(st).set_index(key).index)
    assert len(orphan) == 0, f"{len(orphan)} seção(ões) com votos sem linha em section_turn"


def test_m1_official_reference_turn1():
    probs = reference_problems(turnos={1})
    assert not probs, "referência T1:\n" + "\n".join(probs[:20])


def test_m1_valid_and_null_votes_match_independent_pdf_oracle():
    """Handoff 17: válidos/nulos do painel (com 'nulo técnico' reclassificado) = PDF oficial.

    Oráculo: reports/analysis/evidencias_unificado/referencia_pdf_B.csv, extraído dos PDFs
    da totalização com pypdf por B (tools/verify_reference_pdf.py), sem o parser de A.
    """
    import pandas as pd

    from br2026.config import load_config
    from br2026.contract import PROJECT_ROOT
    from br2026.panel.build import section_counts
    from integration_support import blocked

    oracle_path = PROJECT_ROOT / "reports" / "analysis" / "evidencias_unificado" / "referencia_pdf_B.csv"
    if not oracle_path.exists():
        blocked("oráculo PDF de B ausente")
    st, vl = require("section_turn", "votes_long")
    cfg = load_config()
    e = cfg["election"]
    c = section_counts(st, vl, e["nr_votavel_lula"], e["nr_votavel_flavio"], technical_null=e["nulo_tecnico"])
    obs = c[c.nr_turno == 1].groupby("sg_uf")[["qt_votos_validos", "qt_votos_nulos", "qt_votos_brancos",
                                               "qt_lula", "qt_flavio", "qt_comparecimento"]].sum()
    oracle = pd.read_csv(oracle_path)
    oracle["sg_uf"] = oracle.arquivo.str.extract(r"6257_([A-Z]{2})_")[0]
    oracle = oracle.set_index("sg_uf")
    assert set(oracle.index) == set(obs.index)
    for uf, r in oracle.iterrows():
        assert r.turno == 1 and r.cargo_presidente
        assert obs.at[uf, "qt_votos_validos"] == r.qt_votos_validos, uf
        assert obs.at[uf, "qt_votos_nulos"] == r.nulos_total == r.nulos_na_urna + r.nulos_tecnicos, uf
        assert obs.at[uf, "qt_votos_brancos"] == r.qt_votos_brancos, uf
        assert obs.at[uf, "qt_lula"] == r.qt_lula and obs.at[uf, "qt_flavio"] == r.qt_flavio, uf
        assert obs.at[uf, "qt_comparecimento"] == r.total_votos == r.qt_comparecimento, uf
