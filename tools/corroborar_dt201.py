"""Corroboração da D-T2-01 por UF (handoff 26), sobre o staging normalizado.

A D-T2-01 liga cada seção agregada do 2º turno à principal esperada pelo cadastro, porque o
2º turno não tem BU web nem CEFT. No piloto, a regra foi corroborada por quatro checagens;
aqui elas são repetidas UF a UF:

1. **T1, esperada × efetivada:** no 1º turno, a apuradora esperada pelo cadastro coincide com
   a efetivada pelo BU web em todas as seções.
2. **Esperada estável:** a esperada do 2º turno é a mesma do 1º (mesma condição de agregada e
   mesma principal).
3. **Presença no detalhe do 2º turno:** as agregadas esperadas não têm apuração própria no
   2º turno e as principais têm.
4. **Mesmas apuradoras:** o conjunto de seções com apuração é o mesmo nos dois turnos, e os
   aptos por apuradora mudam pouco (sem o salto do tamanho de uma agregada).

Uma UF passa quando as checagens 1 a 3 não têm nenhuma exceção e a 4 não tem seção só num
turno. Seções sem apuração em nenhum dos turnos (exterior: seções não instaladas ou sem
votantes) não têm efetivada a conferir; são contadas à parte (`secoes_sem_apuracao`), ficam fora
das checagens e o painel as exclui. As demais exceções são contadas; a regra marca como AMBIGUA
a agregada com apuração própria, e o painel exclui a unidade afetada.

Saída: `reports/analysis/evidencias_nacional/corroboracao_dt201_uf.csv`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from br2026.contract import read_table  # noqa: E402
from br2026.panel.run import staging_path  # noqa: E402

CHAVE = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]


def corroborar(staging: Path) -> pd.DataFrame:
    cw = read_table(staging_path(staging, "section_crosswalk"), "section_crosswalk")
    st = read_table(staging_path(staging, "section_turn"), "section_turn")
    st = st[st.cd_cargo == 1]
    linhas = []
    for uf in sorted(set(cw.sg_uf)):
        c, s = cw[cw.sg_uf == uf], st[st.sg_uf == uf]

        def apuradora(turno: int, status: str) -> pd.Series:
            x = c[(c.nr_turno == turno) & (c.status_correspondencia == status)]
            return x.set_index(CHAVE[1:])["nr_secao_apuradora"]

        esp1, efe1, esp2 = apuradora(1, "ESPERADA"), apuradora(1, "EFETIVADA"), apuradora(2, "ESPERADA")
        # seções sem BU no 1º turno (SEM_APURACAO) e sem nenhum votante no 2º: não instaladas ou
        # vazias (exterior). Presentes no detalhe do 2º turno, viram "próprias" pela regra, mas não
        # têm votos a ligar; o painel as exclui por falta de efetivada no 1º turno
        t1_sem = set(c[(c.nr_turno == 1) & (c.status_correspondencia == "ESPERADA")
                       & (c.tipo_correspondencia == "SEM_APURACAO")].set_index(CHAVE[1:]).index)
        comp2 = s[s.nr_turno == 2].set_index(CHAVE[1:]).qt_comparecimento
        sem_apur = pd.MultiIndex.from_tuples(sorted(k for k in t1_sem if comp2.get(k, 0) == 0),
                                             names=CHAVE[1:]) if t1_sem else pd.MultiIndex.from_tuples([], names=CHAVE[1:])
        esp1, esp2 = esp1.drop(sem_apur, errors="ignore"), esp2.drop(sem_apur, errors="ignore")
        comuns = esp1.index.intersection(efe1.index)
        t1_diverge = int((esp1.loc[comuns] != efe1.loc[comuns]).sum())
        t1_sem_efetivada = int(len(esp1.index.difference(efe1.index)))

        tipo1 = c[(c.nr_turno == 1) & (c.status_correspondencia == "ESPERADA")].set_index(CHAVE[1:]).tipo_correspondencia
        tipo2 = c[(c.nr_turno == 2) & (c.status_correspondencia == "ESPERADA")].set_index(CHAVE[1:]).tipo_correspondencia
        tipo1, tipo2 = tipo1.drop(sem_apur, errors="ignore"), tipo2.drop(sem_apur, errors="ignore")
        comuns2 = esp1.index.intersection(esp2.index)
        esperada_muda = int(((esp1.loc[comuns2] != esp2.loc[comuns2])
                             | (tipo1.loc[comuns2] != tipo2.loc[comuns2])).sum())
        esperada_so_um_turno = int(len(esp1.index.symmetric_difference(esp2.index)))

        apur = {t: set(map(tuple, s[s.nr_turno == t][CHAVE[1:]].itertuples(index=False))) for t in (1, 2)}
        agregadas2 = esp2[tipo2.reindex(esp2.index) == "AGREGADA_EM_OUTRA"]
        agreg_com_apuracao = sum(1 for k in agregadas2.index if k in apur[2])
        principais = {(k[0], k[1], v) for k, v in agregadas2.items()}
        principais_sem_apuracao = len(principais - apur[2])

        a1 = s[s.nr_turno == 1].set_index(CHAVE[1:]).qt_aptos
        a2 = s[s.nr_turno == 2].set_index(CHAVE[1:]).qt_aptos
        ambos = a1.index.intersection(a2.index)
        dif = (a2.loc[ambos] - a1.loc[ambos])
        ambiguas = int(((c.nr_turno == 2) & (c.status_correspondencia == "AMBIGUA")).sum()) \
            if "AMBIGUA" in set(c.status_correspondencia) else 0

        ok = (t1_diverge == 0 and t1_sem_efetivada == 0 and esperada_muda == 0
              and esperada_so_um_turno == 0 and agreg_com_apuracao == 0
              and principais_sem_apuracao == 0 and len(apur[1] ^ apur[2]) == 0)
        linhas.append({
            "sg_uf": uf, "secoes_esperadas_t1": len(esp1), "secoes_sem_apuracao": len(sem_apur),
            "t1_esperada_diverge_efetivada": t1_diverge, "t1_esperada_sem_efetivada": t1_sem_efetivada,
            "esperada_muda_entre_turnos": esperada_muda, "esperada_so_num_turno": esperada_so_um_turno,
            "agregadas_t2": len(agregadas2), "agregadas_t2_com_apuracao_propria": agreg_com_apuracao,
            "principais_t2": len(principais), "principais_t2_sem_apuracao": principais_sem_apuracao,
            "apuradoras_t1": len(apur[1]), "apuradoras_t2": len(apur[2]),
            "apuradoras_so_t1": len(apur[1] - apur[2]), "apuradoras_so_t2": len(apur[2] - apur[1]),
            "aptos_iguais": int((dif == 0).sum()), "aptos_dif_abs_max": int(dif.abs().max()) if len(dif) else 0,
            "aptos_soma_dif": int(dif.sum()), "ambiguas_t2": ambiguas,
            "status": "PASS" if ok else "EXCECOES",
        })
    return pd.DataFrame(linhas)


def main() -> int:
    out = RAIZ / "reports" / "analysis" / "evidencias_nacional"
    out.mkdir(parents=True, exist_ok=True)
    df = corroborar(RAIZ / "data" / "staging")
    df.to_csv(out / "corroboracao_dt201_uf.csv", index=False)
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
