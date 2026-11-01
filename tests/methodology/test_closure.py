"""DoD 6: fusos documentados, ausentes/inválidos, reemissão, limites exatos, exaustividade."""
import pandas as pd
import pytest

from br2026.analysis.closure import band_transitions, classify, normalize_timestamp, support_check
from br2026.config import election_dates, load_config

DATES = election_dates()
SP_TZ, AC_TZ = "America/Sao_Paulo", "America/Rio_Branco"


def rec(secao, raw, tz=SP_TZ, turno=1, sem="ENCERRAMENTO_URNA", reemissao=False, rid=None):
    return {"ano": 2026, "nr_turno": turno, "sg_uf": "AC", "cd_municipio_tse": "01007",
            "nr_zona": "0001", "nr_secao": secao, "id_registro": rid or f"{secao}-{turno}-{raw}",
            "id_bu": None, "id_urna": None, "semantica": sem, "ts_bruto": raw,
            "fuso_documentado": tz, "fonte_fuso": "fixture", "ts_brasilia": pd.NaT,
            "motivo_ausencia": None, "flag_reemissao": reemissao,
            "flag_substituicao_urna": False, "flag_anomalia": False}


def run(rows, **kw):
    return classify(pd.DataFrame(rows), DATES, **kw).set_index("nr_secao")


def test_documented_timezones_differ():
    out = run([rec("0001", "04/10/2026 16:00:00", SP_TZ), rec("0002", "04/10/2026 16:00:00", AC_TZ)])
    assert out.at["0001", "faixa"] == "ANTES_17H"
    assert out.at["0002", "faixa"] == "18H_19H"  # 16h no Acre = 18h em Brasília


def test_timezone_never_inferred_from_uf():
    ts, motivo = normalize_timestamp("04/10/2026 17:30:00", None)
    assert ts is None and motivo == "FUSO_NAO_DOCUMENTADO"


@pytest.mark.parametrize("raw,motivo", [(None, "SEM_REGISTRO"), ("#NULO", "SEM_REGISTRO"),
                                        ("31/31/2026 25:00", "BRUTO_INVALIDO")])
def test_missing_and_invalid(raw, motivo):
    out = run([rec("0001", raw)])
    assert out.at["0001", "faixa"] == "INVALIDO" and out.at["0001", "motivo_invalido"] == motivo


@pytest.mark.parametrize("hms,band", [("16:59:59", "ANTES_17H"), ("17:00:00", "17H00_17H15"),
                                      ("17:14:59", "17H00_17H15"), ("17:15:00", "17H15_18H"),
                                      ("18:59:59", "18H_19H"), ("19:00:00", "A_PARTIR_19H"),
                                      ("23:59:59", "A_PARTIR_19H")])
def test_exact_limits(hms, band):
    assert run([rec("0001", f"04/10/2026 {hms}")]).at["0001", "faixa"] == band


def test_reissue_same_time_collapses_conflict_invalid():
    out = run([rec("0001", "04/10/2026 17:05:00", rid="a"),
               rec("0001", "04/10/2026 17:05:00", reemissao=True, rid="b"),
               rec("0002", "04/10/2026 17:05:00", rid="c"),
               rec("0002", "04/10/2026 19:30:00", reemissao=True, rid="d")])
    assert out.at["0001", "faixa"] == "17H00_17H15" and out.at["0001", "flag_reemissao"]
    assert out.at["0002", "faixa"] == "INVALIDO"
    assert out.at["0002", "motivo_invalido"] == "CONFLITO_REEMISSAO"


def test_transmission_does_not_replace_closure():
    out = run([rec("0001", "04/10/2026 18:56:44", sem="RECEBIMENTO_BU_TSE")])
    assert out.at["0001", "faixa"] == "INVALIDO"
    assert out.at["0001", "motivo_invalido"] == "SEM_SEMANTICA_ELEGIVEL"


def test_wrong_date_invalid():
    out = run([rec("0001", "05/10/2026 17:05:00")])
    assert out.at["0001", "motivo_invalido"] == "DATA_DIFERENTE_DA_ELEICAO"


def test_bands_exhaustive_and_exclusive():
    cfg = load_config()
    names = {b["nome"] for b in cfg["closure"]["faixas"]} | {"INVALIDO"}
    rows = [rec(f"{i:04d}", f"04/10/2026 {h:02d}:{m:02d}:00") for i, (h, m) in
            enumerate([(h, m) for h in range(0, 24) for m in (0, 15, 30, 45)])]
    rows.append(rec("9999", None))
    out = run(rows)
    assert len(out) == len(rows) and out.index.is_unique
    assert set(out.faixa) <= names and out.faixa.notna().all()


def test_tolerance_sensitivity_moves_cut():
    r = [rec("0001", "04/10/2026 17:20:00")]
    assert run(r).at["0001", "faixa"] == "17H15_18H"
    assert run(r, tolerance_min=30).at["0001", "faixa"] == "17H00_17H15"


def test_transitions_and_support_rule():
    rows = [rec("0001", "04/10/2026 17:05:00"), rec("0001", "25/10/2026 19:10:00", turno=2),
            rec("0002", "04/10/2026 19:05:00")]
    c = classify(pd.DataFrame(rows), DATES)
    tr = band_transitions(c)
    assert tr.loc["17H00_17H15", "A_PARTIR_19H"] == 1
    assert tr.loc["A_PARTIR_19H", "SEM_TURNO"] == 1
    s = support_check(c, ["17H00_17H15", "A_PARTIR_19H"], 30, 10, turno=1)
    assert not s["estimar"] and set(s["faixas_sem_suporte"]) == {"17H00_17H15", "A_PARTIR_19H"}


@pytest.mark.parametrize("tz", [float("nan"), pd.NA, None, ""])
def test_missing_timezone_values_never_raise(tz):
    """Achado F-01 de C: NaN/NA de Parquet não pode quebrar a normalização."""
    assert normalize_timestamp("2026-10-04 17:15:00", tz) == (None, "FUSO_NAO_DOCUMENTADO")
