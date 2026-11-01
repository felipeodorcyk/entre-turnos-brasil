"""Alegações de fraude no 2º turno de 2026 contra os dados oficiais por seção.

Cada alegação vem de uma fonte localizada (checagens do TSE e da Lupa, 25–29/10/2026; ver
`docs/sources/contraste/alegacoes_fraude.csv`). Para cada uma, o teste usa só dados oficiais:

- BUs do 2º turno do portal Resultados (censo `data/raw/bu_portal/censo_3221`, 497.897 seções do
  território): votos de presidente, comparecimento, habilitação por biometria, número da urna e
  horários. Os campos de habilitação foram conferidos contra o BU web do 1º turno (60/60 seções);
- logs de urna das 8.562 seções baixadas no handoff 29 (modelo da urna);
- staging do painel (`votes_long`, `section_turn`) e fuso municipal (`closure_tz_offsets.csv`);
- votação e detalhe por seção de 2022 (TSE), como controle.

Etapas:
    python tools/alegacoes_fraude.py extrair  [--root R] [--ref2022 ZIP]
    python tools/alegacoes_fraude.py analisar [--root R]

`extrair` grava `data/analytics/alegacoes/*.parquet` sob a raiz de dados; `analisar` grava as
tabelas em `reports/analysis/tabelas_nacional/alegacoes_*.csv` e os números citados no relatório
em `reports/analysis/evidencias_nacional/alegacoes_numeros.json`.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from poc_bu_horarios import _filhos, _int, _tlv  # noqa: E402
from logs_tardias import ler_logd  # noqa: E402

ELEICAO_PRES = 6258
LULA, FLAVIO = 13, 22
TIPO_VOTO = {1: "nominal", 2: "branco", 3: "nulo"}
DIA_T2 = "20261025"


def _kids(v: bytes) -> list[tuple[int, int, bytes]]:
    return _filhos(v, 0, len(v))


# --------------------------------------------------------------------------- BU
def decodificar_bu_completo(dat: bytes) -> dict:
    """Campos do BU usados aqui. Posições conferidas no BU 2026 (1º turno: 60/60 contra o BU web).

    Depois de `dadosSecao` vêm o comparecimento e a habilitação em três partes:
    [sem biometria cadastrada, habilitados pela digital, com biometria mas sem habilitação pela
    digital]; a terceira é igual a QT_ELEI_BIOM_SEM_HABILITACAO do BU web.
    """
    t, _, j, ln = _tlv(dat, 0)
    bu = [v for (tt, _, v) in _filhos(dat, j, j + ln) if tt == 0x04][-1]
    t, _, j, ln = _tlv(bu, 0)
    top = _filhos(bu, j, j + ln)
    urna = _kids(top[2][2])
    corr = [v for (tt, _, v) in urna if tt == 0x30][0]
    carga = [v for (tt, _, v) in _kids(corr) if tt == 0x30][0]
    ident = _kids(top[3][2])
    mz = _kids(ident[0][2])
    i = next(k for k, (tt, _, _) in enumerate(top) if tt == 0xA0)
    horas = [v.decode() for (tt, _, v) in _kids(top[i][2]) if tt == 0x1B]
    # o exterior não traz a habilitação ([1]); os resultados são a primeira SEQUENCE depois dela
    hab = [_int(v) for (_, _, v) in _kids(top[i + 2][2])] if top[i + 2][0] == 0xA1 else [None] * 3
    k_res = next(k for k in range(i + 2, len(top)) if top[k][0] == 0x30)
    out = {"bu_municipio": _int(mz[0][2]), "bu_zona": _int(mz[1][2]), "bu_secao": _int(ident[2][2]),
           "nr_urna": _int(_kids(carga)[0][2]), "versao": urna[1][2].decode("latin-1"),
           "emissao": top[i - 1][2].decode(), "abertura": (horas + [None, None])[0],
           "encerramento": (horas + [None, None])[1], "comparecimento": _int(top[i + 1][2]),
           "hab_sem_biometria": hab[0], "hab_digital": hab[1], "hab_biometria_falhou": hab[2],
           "lula": 0, "flavio": 0, "branco": 0, "nulo": 0}
    for (tt, _, el) in _kids(top[k_res][2]):
        campos = _kids(el)
        if _int(campos[0][2]) != ELEICAO_PRES:
            continue
        for (_, _, res) in _kids(campos[4][2]):
            for (_, _, cargo) in _kids([v for (tt2, _, v) in _kids(res) if tt2 == 0x30][0]):
                cc = _kids(cargo)
                if _int(cc[0][2]) != 1:   # código do cargo: presidente
                    continue
                for (_, _, vv) in _kids(cc[2][2]):
                    f = {tt3: v for (tt3, _, v) in _kids(vv)}   # [1] tipo, [2] quantidade, [3] votável
                    tipo, qtd = _int(f[0x81]), _int(f[0x82])
                    if tipo == 1:
                        cod = _int(_kids(f[0xA3])[1][2])
                        if cod == LULA:
                            out["lula"] += qtd
                        elif cod == FLAVIO:
                            out["flavio"] += qtd
                    elif tipo in TIPO_VOTO:
                        out[TIPO_VOTO[tipo]] += qtd
    return out


def extrair_bus(root: Path) -> pd.DataFrame:
    censo = root / "data/raw/bu_portal/censo_3221"
    res = pd.read_json(censo / "resultados.jsonl", lines=True, dtype=False)
    res = res[res.status == "OK"].drop_duplicates(["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"], keep="last")
    linhas = []
    for uf, g in res.groupby("sg_uf"):
        with zipfile.ZipFile(censo / f"bu_{uf}.zip") as z:
            nomes = {Path(n).name: n for n in z.namelist() if n.endswith("-bu.dat")}
            for r in g.itertuples():
                d = decodificar_bu_completo(z.read(nomes[r.arquivo]))
                linhas.append({"sg_uf": uf, "cd_municipio_tse": r.cd_municipio_tse, "nr_zona": r.nr_zona,
                               "nr_secao": r.nr_secao, **d})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- logs
RX_MODELO = re.compile(r"Identifica.{1,4}o do Modelo de Urna: (UE\d{4})")


def extrair_modelos(root: Path) -> pd.DataFrame:
    """Número interno e modelo da urna final de cada seção com log baixado."""
    pasta = root / "data/raw/bu_portal/logs_3221"
    linhas = []
    for zp in sorted(pasta.glob("logs_*.zip")):
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if not n.endswith("-log.jez"):
                    continue
                txt = ler_logd(z.read(n))
                m = RX_MODELO.search(txt)
                num = re.search(r"\t\w+\t(\d{8})\t", txt)
                linhas.append({"arquivo": n, "nr_urna": int(num.group(1)) if num else None,
                               "modelo": m.group(1) if m else None})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- 2022
def extrair_2022(zip2022: Path, tmp: Path) -> pd.DataFrame:
    """Presidente por seção em 2022 (1º e 2º turno), formato largo."""
    csv = tmp / "votacao_secao_2022_BR.csv"
    if not csv.exists():
        with zipfile.ZipFile(zip2022) as z:
            z.extract("votacao_secao_2022_BR.csv", tmp)
    rel = duckdb.sql(f"""
        select NR_TURNO::int as nr_turno, SG_UF as sg_uf, CD_MUNICIPIO as cd_municipio_tse,
               NR_ZONA::int as nr_zona, NR_SECAO::int as nr_secao,
               sum(case when NR_VOTAVEL = '13' then QT_VOTOS::bigint else 0 end) as lula,
               sum(case when NR_VOTAVEL = '22' then QT_VOTOS::bigint else 0 end) as bolsonaro,
               sum(case when NR_VOTAVEL not in ('95', '96') then QT_VOTOS::bigint else 0 end) as nominais
        from read_csv('{csv.as_posix()}', delim=';', header=true, encoding='latin-1', all_varchar=true)
        where CD_CARGO = '1' group by all""")
    return rel.df()


def extrair_2022_detalhe(csv: Path) -> pd.DataFrame:
    """Aptos, comparecimento e modelo da urna por seção em 2022 (presidente)."""
    return duckdb.sql(f"""
        select NR_TURNO::int as nr_turno, SG_UF as sg_uf, CD_MUNICIPIO as cd_municipio_tse,
               NR_ZONA::int as nr_zona, NR_SECAO::int as nr_secao, QT_APTOS::bigint as aptos,
               QT_COMPARECIMENTO::bigint as comparecimento, DS_MODELO_URNA as modelo,
               NR_LOCAL_VOTACAO as nr_local_votacao
        from read_csv('{csv.as_posix()}', delim=';', header=true, encoding='latin-1', all_varchar=true)
        where CD_CARGO = '1'""").df()


def cmd_extrair(a) -> int:
    root = Path(a.root)
    out = root / "data/analytics/alegacoes"
    out.mkdir(parents=True, exist_ok=True)
    bus = extrair_bus(root)
    bus.to_parquet(out / "bu_t2.parquet", index=False)
    print("BUs decodificados:", len(bus))
    mod = extrair_modelos(root)
    mod.to_parquet(out / "modelo_urna_logs.parquet", index=False)
    print("logs lidos:", len(mod), "com modelo:", mod.modelo.notna().sum())
    if a.ref2022:
        tmp = Path(a.tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        s22 = extrair_2022(Path(a.ref2022), tmp)
        s22.to_parquet(out / "secoes_2022.parquet", index=False)
        print("seções 2022 (seção × turno):", len(s22))
    if a.det2022:
        d22 = extrair_2022_detalhe(Path(a.det2022))
        d22.to_parquet(out / "secoes_2022_detalhe.parquet", index=False)
        print("detalhe 2022 (seção × turno):", len(d22))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("etapa", choices=["extrair", "analisar"])
    p.add_argument("--root", default=os.environ.get("BR2026_ROOT", str(REPO)), help="raiz com data/")
    p.add_argument("--ref2022", default=None, help="votacao_secao_2022_BR.zip do TSE")
    p.add_argument("--det2022", default=None, help="detalhe_votacao_secao_2022_BR.csv do TSE")
    p.add_argument("--tmp", default=str(REPO / "tmp"), help="pasta para extrair o CSV de 2022")
    a = p.parse_args(argv)
    if a.etapa == "extrair":
        return cmd_extrair(a)
    from alegacoes_analise import analisar
    return analisar(Path(a.root), REPO)


if __name__ == "__main__":
    raise SystemExit(main())
