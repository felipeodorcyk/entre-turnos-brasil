"""Q1/v1.1: inferência de fuso por município a partir da abertura, rotulada."""
import pandas as pd

from br2026.analysis.closure import classify
from br2026.analysis.closure_tz import apply_offsets, infer_municipal_offsets
from br2026.config import election_dates, load_config

CFG = load_config()


def rows(uf, mun, opens, closes, tz=None):
    out = []
    for i, (o, c) in enumerate(zip(opens, closes)):
        sec = f"{i + 1:04d}"
        for sem, raw in (("ABERTURA_URNA", o), ("ENCERRAMENTO_URNA", c)):
            out.append({"ano": 2026, "nr_turno": 1, "sg_uf": uf, "cd_municipio_tse": mun,
                        "nr_zona": "0001", "nr_secao": sec, "id_registro": f"{mun}{sec}{sem}",
                        "id_bu": None, "id_urna": None, "semantica": sem,
                        "ts_bruto": f"2026-10-04 {raw}", "fuso_documentado": tz,
                        "fonte_fuso": None, "ts_brasilia": pd.NaT,
                        "motivo_ausencia": None if tz else "FUSO_NAO_DOCUMENTADO",
                        "flag_reemissao": False, "flag_substituicao_urna": False,
                        "flag_anomalia": False})
    return out


def frame(*parts):
    return pd.DataFrame([r for p in parts for r in p])


AC = rows("AC", "01007", ["06:00:01", "06:10:00", "06:59:35"], ["15:00:17", "15:20:00", "17:10:00"])
SP = rows("SP", "71072", ["08:00:05", "08:02:00", "08:30:00"], ["16:50:00", "17:05:00", "19:10:00"])
AM_EAST = rows("AM", "02550", ["07:00:00", "07:05:00", "07:20:00"], ["16:00:30", "16:10:00", "16:20:00"])
AM_WEST = rows("AM", "02003", ["06:01:00", "06:05:00", "06:30:00"], ["15:02:00", "15:10:00", "15:30:00"])
MIXED = rows("PA", "04278", ["06:05:00", "06:10:00", "08:05:00", "08:10:00"],
             ["15:05:00", "15:10:00", "17:05:00", "17:10:00"])


def offsets(*parts):
    return infer_municipal_offsets(frame(*parts), CFG).set_index("cd_municipio_tse")


def test_acre_like_clock_is_plus_two():
    o = offsets(AC)
    assert o.at["01007", "offset_h"] == 2 and o.at["01007", "status_fuso"] == "INFERIDO_ABERTURA_MUNICIPAL"


def test_inferred_per_municipality_not_per_uf():
    o = offsets(AM_EAST, AM_WEST)
    assert o.at["02550", "offset_h"] == 1 and o.at["02003", "offset_h"] == 2


def test_inconsistent_openings_stay_unknown_and_unconverted():
    cl = frame(MIXED)
    o = infer_municipal_offsets(cl, CFG)
    assert o.status_fuso.iloc[0] == "DESCONHECIDO"
    a = apply_offsets(cl, o, CFG)
    assert a.ts_brasilia.isna().all() and (a.status_fuso == "DESCONHECIDO").all()
    assert (a.ts_bruto == cl.ts_bruto).all()


def test_closure_before_limit_remains_possible():
    """A inferência usa só a abertura: encerramento antes de 17h não é apagado."""
    cl = frame(SP)
    c = classify(apply_offsets(cl, infer_municipal_offsets(cl, CFG), CFG), election_dates(CFG), CFG)
    assert set(c.faixa) == {"ANTES_17H", "17H00_17H15", "A_PARTIR_19H"}
    assert (c.status_fuso == "INFERIDO_ABERTURA_MUNICIPAL").all()


def test_converted_closure_bands_for_acre_like():
    cl = frame(AC)
    c = classify(apply_offsets(cl, infer_municipal_offsets(cl, CFG), CFG), election_dates(CFG), CFG)
    assert c.set_index("nr_secao").faixa.to_dict() == {
        "0001": "17H00_17H15", "0002": "17H15_18H", "0003": "A_PARTIR_19H"}


def test_documented_timezone_prevails():
    cl = frame(rows("AC", "01007", ["06:00:01", "06:10:00", "06:20:00"],
                    ["17:00:30", "17:05:00", "17:10:00"], tz="America/Sao_Paulo"))
    a = apply_offsets(cl, infer_municipal_offsets(cl, CFG), CFG)
    assert (a.status_fuso == "DOCUMENTADO").all()
    enc = a[a.semantica == "ENCERRAMENTO_URNA"].ts_brasilia.dt.strftime("%H:%M:%S").tolist()
    assert enc == ["17:00:30", "17:05:00", "17:10:00"]
