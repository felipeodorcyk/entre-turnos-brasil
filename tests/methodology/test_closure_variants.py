"""O-R2/O-R3 (revisão 10): elegibilidade pelo encerramento e bloqueio da inferência.

O-R2: um recebimento documentado não admite encerramento inferido; offset zero
inferido não é documental. O-R3: inferência pela abertura só como exploração;
casos de abertura preparatória e atraso uniforme mostram por que uma solução
numérica única não valida o relógio.
"""
import pandas as pd

from br2026.analysis.closure import classify
from br2026.analysis.closure_tz import apply_offsets, infer_municipal_offsets, select_closure_variant
from br2026.config import election_dates, load_config

CFG = load_config()
DATES = election_dates(CFG)


def rec(sec, sem, raw, tz=None, mun="01007", uf="AC", rid=None, reemissao=False):
    return {"ano": 2026, "nr_turno": 1, "sg_uf": uf, "cd_municipio_tse": mun, "nr_zona": "0001",
            "nr_secao": sec, "id_registro": rid or f"{mun}{sec}{sem}{raw}", "id_bu": None, "id_urna": None,
            "semantica": sem, "ts_bruto": f"2026-10-04 {raw}", "fuso_documentado": tz, "fonte_fuso": None,
            "ts_brasilia": pd.NaT, "motivo_ausencia": None if tz else "FUSO_NAO_DOCUMENTADO",
            "flag_reemissao": reemissao, "flag_substituicao_urna": False, "flag_anomalia": False}


def bands(rows, variant):
    cl = pd.DataFrame(rows)
    conv = apply_offsets(cl, infer_municipal_offsets(cl, CFG), CFG)
    c = classify(select_closure_variant(conv, variant), DATES, CFG)
    return c.set_index("nr_secao")


# Caso literal da revisão 10: abertura e encerramento sem fuso; recebimento documentado.
OR2 = [rec("0001", "ABERTURA_URNA", "06:00:01"), rec("0001", "ENCERRAMENTO_URNA", "15:00:17"),
       rec("0001", "RECEBIMENTO_BU_TSE", "17:30:00", tz="America/Sao_Paulo")]


def test_documented_receipt_does_not_admit_inferred_closure():
    b = bands(OR2, "documental")
    assert b.at["0001", "faixa"] == "INVALIDO"
    assert b.at["0001", "motivo_invalido"] == "FUSO_NAO_DOCUMENTADO"


def test_same_case_only_in_exploratory_inferred_variant():
    assert bands(OR2, "exploratorio_inferido").at["0001", "faixa"] == "17H00_17H15"
    assert bands(OR2, "exploratorio_inferido_offset_zero").at["0001", "faixa"] == "INVALIDO"


def test_inferred_offset_zero_is_not_documental():
    rows = [rec("0001", "ABERTURA_URNA", "08:01:00", mun="71072", uf="SP"),
            rec("0001", "ENCERRAMENTO_URNA", "17:05:00", mun="71072", uf="SP")]
    assert bands(rows, "documental").at["0001", "faixa"] == "INVALIDO"
    assert bands(rows, "exploratorio_inferido_offset_zero").at["0001", "faixa"] == "17H00_17H15"


def test_documented_closure_used_in_documental():
    rows = [rec("0001", "ENCERRAMENTO_URNA", "15:20:00", tz="America/Rio_Branco")]
    b = bands(rows, "documental")
    assert b.at["0001", "faixa"] == "17H15_18H"  # 15:20 no Acre = 17:20 em Brasília


def test_documented_reissue_conflict_invalid():
    rows = [rec("0001", "ENCERRAMENTO_URNA", "17:05:00", tz="America/Sao_Paulo", rid="a"),
            rec("0001", "ENCERRAMENTO_URNA", "19:30:00", tz="America/Sao_Paulo", rid="b", reemissao=True)]
    b = bands(rows, "documental")
    assert b.at["0001", "faixa"] == "INVALIDO" and b.at["0001", "motivo_invalido"] == "CONFLITO_REEMISSAO"


def test_partially_documented_closures_not_admitted():
    """Uma urna documentada e outra não, na mesma seção: não escolher a conveniente."""
    rows = [rec("0001", "ABERTURA_URNA", "06:00:01"),
            rec("0001", "ENCERRAMENTO_URNA", "17:05:00", tz="America/Sao_Paulo", rid="a"),
            rec("0001", "ENCERRAMENTO_URNA", "15:10:00", rid="b")]
    assert bands(rows, "documental").at["0001", "faixa"] == "INVALIDO"


def test_preparatory_opening_fools_inference_but_not_main_result():
    """Abertura preparatória às 07h em município de Brasília produz offset +1 falso."""
    rows = [rec(f"{i:04d}", "ABERTURA_URNA", f"07:{10 + i:02d}:00", mun="71072", uf="SP") for i in range(3)]
    rows += [rec(f"{i:04d}", "ENCERRAMENTO_URNA", f"17:{10 + i:02d}:00", mun="71072", uf="SP") for i in range(3)]
    off = infer_municipal_offsets(pd.DataFrame(rows), CFG)
    assert off.offset_h.iloc[0] == 1  # solução numérica única, porém errada
    # Encerramento real às 17h1x (Brasília) aparece como 18h1x: artefato da inferência.
    assert (bands(rows, "exploratorio_inferido").faixa == "18H_19H").all()
    assert (bands(rows, "documental").faixa == "INVALIDO").all()


def test_uniform_delay_fools_inference_but_not_main_result():
    """Atraso uniforme (aberturas às 09h20 em Brasília) produz offset −1 falso."""
    rows = [rec(f"{i:04d}", "ABERTURA_URNA", f"09:{20 + i:02d}:00", mun="71072", uf="SP") for i in range(3)]
    rows += [rec(f"{i:04d}", "ENCERRAMENTO_URNA", "17:05:00", mun="71072", uf="SP") for i in range(3)]
    off = infer_municipal_offsets(pd.DataFrame(rows), CFG)
    assert off.offset_h.iloc[0] == -1
    assert (bands(rows, "exploratorio_inferido").faixa == "ANTES_17H").all()  # artefato da inferência
    assert (bands(rows, "documental").faixa == "INVALIDO").all()


def test_municipality_without_solution_excluded_everywhere():
    rows = [rec("0001", "ABERTURA_URNA", "06:05:00", mun="04278", uf="PA"),
            rec("0002", "ABERTURA_URNA", "08:05:00", mun="04278", uf="PA"),
            rec("0001", "ENCERRAMENTO_URNA", "15:05:00", mun="04278", uf="PA"),
            rec("0002", "ENCERRAMENTO_URNA", "17:05:00", mun="04278", uf="PA")]
    for v in ("documental", "exploratorio_inferido", "exploratorio_inferido_offset_zero"):
        assert (bands(rows, v).faixa == "INVALIDO").all(), v
