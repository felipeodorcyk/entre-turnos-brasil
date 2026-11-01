"""Gerador de staging SINTÉTICO conforme contrato v1, para o teste ponta a ponta.

Não representa a eleição real. Taxas de transição, horários e tamanhos são
inventados e servem só para exercitar a orquestração. Nenhum resultado
produzido a partir daqui pode ser lido como achado empírico.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SRC = "0" * 63 + "b"
UFS = {"SP": "America/Sao_Paulo", "AM": "America/Manaus", "AC": "America/Rio_Branco"}
ORIG = [13, 22, 30, 15, 95, 96, -1]          # -1 = abstenção
DEST = [13, 22, 95, 96, -1]
BETA = np.array([[0.93, 0.02, 0.01, 0.01, 0.03],
                 [0.02, 0.93, 0.01, 0.01, 0.03],
                 [0.45, 0.35, 0.06, 0.04, 0.10],
                 [0.30, 0.45, 0.07, 0.05, 0.13],
                 [0.20, 0.20, 0.40, 0.10, 0.10],
                 [0.15, 0.25, 0.10, 0.40, 0.10],
                 [0.08, 0.08, 0.01, 0.01, 0.82]])
BANDS = [("16:00:00", 60), ("17:00:00", 15), ("17:15:00", 45), ("18:00:00", 60), ("19:00:00", 90)]
BAND_P = [0.02, 0.45, 0.25, 0.15, 0.13]


def _clock(rng, turno_date: str, tz: str) -> str:
    """Encerramento em Brasília sorteado por faixa, escrito no relógio local da urna."""
    start, span = BANDS[rng.choice(len(BANDS), p=BAND_P)]
    t = pd.Timestamp(f"{turno_date} {start}", tz="America/Sao_Paulo") + pd.Timedelta(
        seconds=int(rng.integers(0, span * 60)))
    return t.tz_convert(tz).strftime("%Y-%m-%d %H:%M:%S")


def _opening(rng, turno_date: str, tz: str) -> str:
    """Abertura entre 08:00 e 08:40 de Brasília, no relógio local da urna."""
    t = pd.Timestamp(f"{turno_date} 08:00:00", tz="America/Sao_Paulo") + pd.Timedelta(
        seconds=int(rng.integers(0, 40 * 60)))
    return t.tz_convert(tz).strftime("%Y-%m-%d %H:%M:%S")


# Só SP tem fuso "documentado" no sintético; AM e AC exercitam a inferência pela abertura.
DOCUMENTED = {"SP"}
PROFILE = {"GENERO": [("2", "MASCULINO", 0.48), ("4", "FEMININO", 0.52)],
           "FAIXA_ETARIA": [("1800", "18 anos", 0.05), ("2529", "25 a 29 anos", 0.30),
                            ("4549", "45 a 49 anos", 0.35), ("6569", "65 a 69 anos", 0.28),
                            ("-3", "Inválida", 0.02)],
           "GRAU_ESCOLARIDADE": [("3", "ENSINO FUNDAMENTAL INCOMPLETO", 0.35),
                                 ("6", "ENSINO MÉDIO COMPLETO", 0.40),
                                 ("8", "SUPERIOR COMPLETO", 0.24), ("0", "NÃO INFORMADO", 0.01)]}


def make_staging(out: Path, n_mun: int = 12, n_sec: int = 25, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    st, vl, cw, cl, pr = [], [], [], [], []
    truth = {"secoes": 0}
    geo = []
    for k, uf in enumerate(UFS):
        for m in range(n_mun):
            mun = f"{10000 + 1000 * k + m:05d}"
            geo += [(uf, mun, "0001", f"{s + 1:04d}") for s in range(n_sec)]
    geo.append(("ZZ", "29999", "0001", "0001"))
    for i, (uf, mun, zona, sec) in enumerate(geo):
        truth["secoes"] += 1
        N1 = int(rng.integers(150, 400))
        q = rng.dirichlet([8, 7, 2, 1, 0.4, 0.5, 3])
        orig = rng.multinomial(N1, q)
        dest = np.zeros(5, int)
        for r, n in enumerate(orig):
            dest += rng.multinomial(int(n), BETA[r])
        N2 = N1
        if i % 17 == 0:                      # aptos diferentes entre turnos
            extra = int(rng.integers(1, 8))
            N2 = N1 + extra
            dest += rng.multinomial(extra, [0.15, 0.15, 0.0, 0.0, 0.70])
        if uf != "ZZ":
            for dim, cats in PROFILE.items():
                shares = np.array([c[2] for c in cats]) * rng.uniform(0.7, 1.3, len(cats))
                q_ = rng.multinomial(N1, shares / shares.sum())
                pr += [{"sg_uf": uf, "cd_municipio_tse": mun, "nr_zona": zona, "nr_secao": sec,
                        "dimensao": dim, "cd_categoria": c[0], "ds_categoria": c[1],
                        "flag_desconhecido": c[0] in ("-3", "0"), "qt_eleitores": int(n)}
                       for c, n in zip(cats, q_)]
        absent_t2 = (uf, mun, sec) == ("SP", "10000", "0003")
        agg_t1 = (uf, mun) == ("AM", "11000") and sec in ("0001", "0002")
        for t, counts, N in ((1, dict(zip(ORIG, orig)), N1), (2, dict(zip(DEST, dest)), N2)):
            if t == 2 and absent_t2:
                cw.append(_cw(t, uf, mun, zona, sec, None, "SEM_APURACAO"))
                continue
            apur = "0001" if (t == 1 and agg_t1) else sec
            tipo = ("AGREGADA_EM_OUTRA" if apur != sec else
                    "PRINCIPAL_COM_AGREGADAS" if (t == 1 and agg_t1) else "PROPRIA")
            cw.append(_cw(t, uf, mun, zona, sec, apur, tipo))
            for nr, q_ in counts.items():
                if nr == -1 or q_ == 0:
                    continue
                vl.append({"nr_turno": t, "sg_uf": uf, "cd_municipio_tse": mun, "nr_zona": zona,
                           "nr_secao": apur, "nr_votavel": nr, "qt_votos": int(q_)})
            st.append({"nr_turno": t, "sg_uf": uf, "cd_municipio_tse": mun, "nr_zona": zona,
                       "nr_secao": apur, "qt_aptos": N, "qt_comparecimento": N - counts[-1],
                       "qt_abstencoes": counts[-1],
                       "qt_votos_nominais": sum(v for n, v in counts.items() if n not in (95, 96, -1)),
                       "qt_votos_brancos": counts[95], "qt_votos_nulos": counts[96]})
            if t == 2 and uf == "AM":
                vl.append({"nr_turno": 2, "sg_uf": uf, "cd_municipio_tse": mun, "nr_zona": zona,
                           "nr_secao": apur, "nr_votavel": 77, "qt_votos": 1, "cd_cargo": 3})
            if uf != "ZZ" and apur == sec:
                date = "2026-10-04" if t == 1 else "2026-10-25"
                tz = UFS[uf] if uf in DOCUMENTED else None
                cl.append(_cl(t, uf, mun, zona, sec, "ABERTURA_URNA", _opening(rng, date, UFS[uf]), tz))
                cl.append(_cl(t, uf, mun, zona, sec, "ENCERRAMENTO_URNA", _clock(rng, date, UFS[uf]), tz))
                cl.append(_cl(t, uf, mun, zona, sec, "RECEBIMENTO_BU_TSE",
                              f"{date} 20:00:00", "America/Sao_Paulo"))
    st = pd.DataFrame(st).groupby(["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"],
                                  as_index=False).sum()
    vl = pd.DataFrame(vl)
    vl["cd_cargo"] = vl.cd_cargo.fillna(1).astype(int)
    vl = vl.groupby(["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao", "cd_cargo",
                     "nr_votavel"], as_index=False).sum()
    out.mkdir(parents=True, exist_ok=True)
    _finish_st(st).to_parquet(out / "section_turn.parquet", index=False)
    _finish_vl(vl).to_parquet(out / "votes_long.parquet", index=False)
    _finish_cw(pd.DataFrame(cw)).to_parquet(out / "section_crosswalk.parquet", index=False)
    _finish_cl(pd.DataFrame(cl)).to_parquet(out / "closure.parquet", index=False)
    _finish_pr(pd.DataFrame(pr)).to_parquet(out / "profiles.parquet", index=False)
    truth["beta"] = BETA
    return truth


def _cw(t, uf, mun, zona, sec, apur, tipo):
    return {"nr_turno": t, "sg_uf": uf, "cd_municipio_tse": mun, "nr_zona": zona, "nr_secao": sec,
            "nr_secao_apuradora": apur, "nr_local_votacao": "1001" if apur else None,
            "nr_local_votacao_original": "1001", "tipo_correspondencia": tipo}


def _cl(t, uf, mun, zona, sec, sem, raw, tz):
    return {"nr_turno": t, "sg_uf": uf, "cd_municipio_tse": mun, "nr_zona": zona, "nr_secao": sec,
            "id_registro": f"{uf}{mun}{sec}{t}{sem}", "semantica": sem, "ts_bruto": raw,
            "fuso_documentado": tz}


def _base(df, with_eleicao=True):
    df.insert(0, "ano", np.int16(2026))
    df["ano"] = df.ano.astype("int16")
    df["nr_turno"] = df.nr_turno.astype("int8")
    if with_eleicao:
        df.insert(1, "cd_eleicao", df.nr_turno.map({1: "6257", 2: "6258"}).astype(object))
    df["source_id"] = SRC
    return df


def _finish_st(st):
    st = _base(st)
    st["cd_cargo"] = np.int16(1)
    st["cd_cargo"] = st.cd_cargo.astype("int16")
    st["qt_votos_legenda"] = 0
    st["qt_votos_anulados_apu_sep"] = 0
    for c in [c for c in st if c.startswith("qt_")]:
        st[c] = st[c].astype("int64")
    st["nr_local_votacao"] = "1001"
    st["st_secao_instalada"] = True
    st["st_secao_anulada"] = False
    st["ds_origem_voto"] = "Urna Eletrônica"
    st["flag_identidade_aptos"] = (st.qt_aptos == st.qt_comparecimento + st.qt_abstencoes).astype("boolean")
    st["flag_identidade_comparecimento"] = (st.qt_comparecimento == st.qt_votos_nominais
                                            + st.qt_votos_brancos + st.qt_votos_nulos).astype("boolean")
    return st


def _finish_vl(vl):
    vl = _base(vl)
    vl["cd_cargo"] = vl.cd_cargo.astype("int16")
    vl["nr_votavel"] = vl.nr_votavel.astype("int32")
    vl["qt_votos"] = vl.qt_votos.astype("int64")
    vl["tipo_votavel"] = vl.nr_votavel.map({95: "BRANCO", 96: "NULO"}).fillna("NOMINAL")
    vl["sq_candidato"] = np.where(vl.tipo_votavel == "NOMINAL", "28000" + vl.nr_votavel.astype(str), None)
    return vl


def _finish_cw(cw):
    cw = _base(cw, with_eleicao=False)
    cw["fonte"] = "sintetico"
    cw["justificativa"] = None
    cw["flag_ambigua"] = False
    cw.insert(cw.columns.get_loc("tipo_correspondencia") + 1, "status_correspondencia", "EFETIVADA")
    return cw


def _finish_cl(cl):
    cl = _base(cl, with_eleicao=False)
    cl["id_bu"] = None
    cl["id_urna"] = None
    cl["fonte_fuso"] = "sintetico"
    cl["ts_brasilia"] = pd.Series(pd.NaT, index=cl.index, dtype="datetime64[ns, America/Sao_Paulo]")
    cl["motivo_ausencia"] = np.where(cl.fuso_documentado.isna(), "FUSO_NAO_DOCUMENTADO", None)
    for f in ("flag_reemissao", "flag_substituicao_urna", "flag_anomalia"):
        cl[f] = False
    return cl


def _finish_pr(pr):
    pr.insert(0, "ano_referencia", np.int16(2026))
    pr["ano_referencia"] = pr.ano_referencia.astype("int16")
    pr.insert(1, "dt_geracao", pd.Timestamp("2026-07-14"))
    pr.insert(2, "dt_referencia_cadastro", pd.Series(pd.NaT, index=pr.index, dtype="datetime64[ns]"))
    pr["qt_eleitores"] = pr.qt_eleitores.astype("int64")
    pr["source_id"] = SRC
    return pr
