"""Marco M3 — horários sobre dados reais (revisto após O-R2/O-R3).

O aceite temporal usa só encerramentos com fuso documentado, ou a inferência
pela abertura apenas se a premissa legal E a semântica/relógio dos campos
estiverem confirmadas com fonte. Inferência sem essas confirmações é cenário
exploratório e nunca aprova o marco. Não se exige mais de um fuso no arquivo.
"""
import pytest

from br2026.analysis.closure import classify
from br2026.analysis.closure_tz import apply_offsets, infer_municipal_offsets, select_closure_variant
from br2026.config import election_dates, load_config
from integration_support import blocked, require

pytestmark = [pytest.mark.integration, pytest.mark.m3]
KEY = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]


@pytest.fixture(scope="module")
def closure():
    cl = require("closure")[0]
    if "ENCERRAMENTO_URNA" not in set(cl.semantica):
        blocked("nenhum registro ENCERRAMENTO_URNA")
    return cl


def _promoted(cz) -> bool:
    return bool(cz["premissa_horario_unico_confirmada"] and cz["fonte_premissa"]
                and cz["semantica_relogio_validada"] and cz["fonte_validacao_relogio"])


@pytest.fixture(scope="module")
def main_classified(closure):
    cfg = load_config()
    conv = apply_offsets(closure, infer_municipal_offsets(closure, cfg), cfg)
    variant = "exploratorio_inferido" if _promoted(cfg["closure_tz"]) else "documental"
    return variant, classify(select_closure_variant(conv, variant), election_dates(cfg), cfg)


def test_m3_staging_does_not_guess_timezone(closure):
    sem_fuso = closure.fuso_documentado.isna()
    assert closure.loc[sem_fuso, "ts_brasilia"].isna().all(), "staging converteu horário sem fuso documentado"
    assert (closure.loc[sem_fuso & closure.ts_bruto.notna(), "motivo_ausencia"] == "FUSO_NAO_DOCUMENTADO").all()


def test_m3_documented_timezones_cite_source(closure):
    doc = closure[closure.fuso_documentado.notna()]
    assert doc.fonte_fuso.fillna("").str.len().gt(0).all(), "fuso documentado sem fonte"


def test_m3_one_closure_per_section_or_flagged(closure):
    enc = closure[closure.semantica == "ENCERRAMENTO_URNA"]
    multi = enc.groupby(KEY).ts_bruto.nunique()
    flagged = enc.groupby(KEY).flag_reemissao.any()
    assert (flagged[multi > 1]).all(), "seção com encerramentos distintos sem flag de reemissão"


def test_m3_classification_exhaustive(main_classified, closure):
    _, c = main_classified
    assert len(c) == len(closure[KEY].drop_duplicates()) and not c.duplicated(KEY).any()
    assert c.faixa.notna().all()


def test_m3_temporal_basis_is_defensible(main_classified):
    variant, c = main_classified
    valid = c[c.faixa != "INVALIDO"]
    if variant == "documental" and valid.empty:
        blocked("nenhum ENCERRAMENTO_URNA com fuso documentado; inferência pela abertura é só exploratória "
                "até premissa legal e semântica do relógio serem confirmadas (O-R3)")
    assert not valid.empty
