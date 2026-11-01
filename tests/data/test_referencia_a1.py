"""Testes offline da referência oficial (A1) — `pdf_texto` e `relatorio_totalizacao`.

Sem rede e sem tocar nos Relatórios reais do piloto: constroem um PDF
sintético no formato do SISTOT (streams FlateDecode, operadores Tm/Td/Tj/TJ,
literais entre parênteses em latin-1) e verificam a extração posicional, as
identidades de consistência, a data de emissão e a gravação atômica do CSV de
referência. Também cobrem a validação de conteúdo da família documental
(ZIP + PDF + marcadores) antes da promoção.
"""
from __future__ import annotations

import io
import sys
import zipfile
import zlib
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "data"))

from br2026.ingest import ConteudoInvalido, _validar_conteudo  # noqa: E402
from br2026.ingest.pdf_texto import Fragmento, extrair_paginas, linhas  # noqa: E402
from br2026.ingest.relatorio_totalizacao import (  # noqa: E402
    COLUNAS, COLUNAS_ANEXO_V, FAMILIA_RELATORIO, ReferenciaInvalida,
    _consistencia, _data_emissao, _metricas_anexo_iv, _metricas_resumo,
    _ocorrencias_anexo_v, gravar_anexo_v, gravar_referencia)

# --------------------------------------------------------------------------- #
# PDF sintético (formato observado no Relatório do SISTOT)                     #
# --------------------------------------------------------------------------- #


def _literal(texto: str) -> bytes:
    # o SISTOT envolve cada linha em parênteses e escapa os internos
    escapado = texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return b"(" + escapado.encode("latin-1") + b")"


def _pagina(*fragmentos: tuple[float, float, str]) -> bytes:
    """Content stream com um objeto de texto por fragmento (Tm + Tj)."""
    ops = []
    for x, y, texto in fragmentos:
        ops.append(b"BT /F1 9 Tf ")
        ops.append(f"1 0 0 1 {x} {y} Tm ".encode())
        ops.append(_literal(texto) + b" Tj ET\n")
    return zlib.compress(b"".join(ops))


def _pdf(*paginas: bytes) -> bytes:
    """PDF mínimo com cada página em um stream FlateDecode fechado."""
    partes = [b"%PDF-1.4\n"]
    for i, p in enumerate(paginas):
        partes.append(f"{i + 2} 0 obj << /Length {len(p)} >> stream\n".encode())
        partes.append(p)
        partes.append(b"\nendstream\nendobj\n")
    partes.append(b"trailer << >>\n%%EOF\n")
    return b"".join(partes)


def _pdf_relatorio(uf: str, data: str, aptos: str, comp: str, abst: str,
                   brancos: str, nulos_urna: str, nulos_tec: str, nulos_total: str,
                   concorrentes: str, lula: str, flavio: str) -> bytes:
    """Relatório sintético com Resumo Geral + Anexo IV no layout real."""
    capa = _pagina(
        (145.8, 702.5, "Justiça Eleitoral"),
        (206.3, 447.9, "Eleição Geral Federal 2026"),
        (375.9, 375.9, "1º Turno"),
    )
    resumo = _pagina(
        (126.0, 811.6, f"Justiça Eleitoral/{uf}"), (525.0, 811.6, data),
        (126.0, 795.6, "SISTOT - SISTEMA DE GERENCIAMENTO DA TOTALIZAÇÃO"),
        (48.0, 437.6, "2.2 Eleitorado apto a votar"), (517.9, 438.6, aptos),
        (48.0, 344.6, "2.3 Comparecimento"), (517.9, 345.6, comp),
        (47.0, 252.6, "2.4 Abstenção"), (517.9, 253.6, abst),
        (101.0, 600.6, "a) Votos a candidatos(as) concorrentes)"),
        (517.9, 601.6, concorrentes),
        (132.0, 561.6, "Votos anulados sub judice"), (533.2, 562.6, "0"),
        (132.0, 542.6, "Votos anulados"), (534.2, 543.6, "0"),
        (101.0, 524.6, "b) Votos nulos)"), (520.7, 525.6, nulos_total),
        (130.0, 506.6, "Votos nulos na urna"), (519.7, 507.6, nulos_urna),
        (130.0, 487.6, "Votos nulos técnico"), (530.4, 488.6, nulos_tec),
        (101.0, 467.6, "c) Votos em branco)"), (523.5, 468.6, brancos),
    )
    anexo = _pagina(
        (226.1, 698.4, "Anexo IV - Resultado de votação"),
        (25.0, 679.6, "Cargo: Presidente"),
        (25.0, 613.1, "22 - FLAVIO NANTES BOLSONARO"), (280.1, 613.1, flavio),
        (25.0, 576.1, "13 - LUIZ INACIO LULA DA SILVA"), (280.1, 576.1, lula),
    )
    return _pdf(capa, resumo, anexo)


def _zip_relatorio(uf: str, pdf: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"6257_{uf}_CIDADE-DA-UF_2026_T1_PRESIDENTE.pdf", pdf)
        z.writestr("6259_CIDADE_2026_T1.pdf", b"%PDF-1.4 outro documento")
        z.writestr("_leiame.pdf", b"%PDF-1.4 leiame")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# pdf_texto                                                                    #
# --------------------------------------------------------------------------- #


def test_extrai_paginas_e_linhas_com_coordenadas():
    pdf = _pdf(_pagina((10.0, 100.0, "rótulo"), (500.0, 101.0, "1.234"),
                       (400.0, 100.5, "9,9%")))
    paginas = extrair_paginas(pdf)
    assert len(paginas) == 1
    ls = linhas(paginas[0])
    # y com diferença ≤ 2 vira a mesma linha visual; fragmentos ordenados por x
    assert len(ls) == 1
    _, fs = ls[0]
    # o literal sai com o parêntese que envolve a linha no PDF do SISTOT
    assert [f.texto.strip("( )") for f in fs] == ["rótulo", "9,9%", "1.234"]


def test_literal_com_pareneses_e_octal():
    pdf = _pdf(_pagina((10.0, 10.0, "nível (parcial) e \\(escape\\)")))
    texto = extrair_paginas(pdf)[0][0].texto
    assert "nível (parcial)" in texto


# --------------------------------------------------------------------------- #
# relatorio_totalizacao: extração das métricas                                 #
# --------------------------------------------------------------------------- #


def _paginas_do(uf="AC", **kw):
    defaults = dict(data="04/10/2026", aptos="613.742", comp="488.330",
                    abst="125.412", brancos="5.579", nulos_urna="13.662",
                    nulos_tec="23", nulos_total="13.685", concorrentes="469.066",
                    lula="134.770", flavio="302.807")
    defaults.update(kw)
    return extrair_paginas(_pdf_relatorio(uf, **defaults))


def test_resumo_e_anexo_iv_completos():
    paginas = _paginas_do()
    m = _metricas_resumo(paginas)
    assert m["qt_aptos"] == 613_742
    assert m["qt_comparecimento"] == 488_330
    assert m["qt_abstencoes"] == 125_412
    assert m["qt_votos_brancos"] == 5_579
    # nulos "na urna" (fecha com o staging) e técnico separados
    assert m["qt_votos_nulos"] == 13_662
    assert m["qt_votos_nulos_tecnico"] == 23
    assert m["qt_votos_nulos_total"] == 13_685
    assert m["qt_concorrentes"] == 469_066
    assert _metricas_anexo_iv(paginas, 13) == 134_770
    assert _metricas_anexo_iv(paginas, 22) == 302_807


def test_data_de_emissao_vem_do_documento():
    assert _data_emissao(_paginas_do(data="16/10/2026")) == "2026-10-16"


def test_anexo_iv_sem_candidato_levanta_erro():
    with pytest.raises(ReferenciaInvalida, match="Anexo IV"):
        _metricas_anexo_iv(_paginas_do(), 99)


# --------------------------------------------------------------------------- #
# identidades de consistência                                                  #
# --------------------------------------------------------------------------- #


def _metricas_validas():
    return {"qt_aptos": 100, "qt_comparecimento": 80, "qt_abstencoes": 20,
            "qt_votos_brancos": 5, "qt_votos_nulos": 4, "qt_votos_nulos_tecnico": 1,
            "qt_votos_nulos_total": 5, "qt_concorrentes": 70, "qt_anulados": 0,
            "qt_anulados_sub_judice": 0}


def test_consistencia_aceita_identities_e_rejeita_erro():
    assert _consistencia(_metricas_validas()) == []
    quebrado = _metricas_validas()
    quebrado["qt_abstencoes"] = 21            # aptos != comp + abst
    assert any("aptos" in p for p in _consistencia(quebrado))
    quebrado = _metricas_validas()
    quebrado["qt_votos_nulos"] = 3            # 3 + 1 != 5
    assert any("nulos" in p for p in _consistencia(quebrado))


# --------------------------------------------------------------------------- #
# validação de conteúdo da família documental (pré-promoção)                   #
# --------------------------------------------------------------------------- #


def test_validacao_documento_aceita_relatorio_e_rejeita_impostor(tmp_path):
    uf = "AC"
    bom = tmp_path / "bom.zip"
    bom.write_bytes(_zip_relatorio(uf, _pdf_relatorio(
        uf, "04/10/2026", "613.742", "488.330", "125.412", "5.579", "13.662",
        "23", "13.685", "469.066", "134.770", "302.807")))
    fatos = _validar_conteudo(bom, FAMILIA_RELATORIO, uf, turno=1)
    assert fatos["membro_validado"].startswith(f"6257_{uf}_")
    assert "PRESIDENTE" in fatos["membro_validado"]

    ruim = tmp_path / "ruim.zip"
    with zipfile.ZipFile(ruim, "w") as z:
        z.writestr(f"6257_{uf}_CIDADE_2026_T1_PRESIDENTE.pdf", b"%PDF-1.4 sem marcadores")
    with pytest.raises(ConteudoInvalido, match="marcadores"):
        _validar_conteudo(ruim, FAMILIA_RELATORIO, uf, turno=1)

    sem_pdf = tmp_path / "sempdf.zip"
    with zipfile.ZipFile(sem_pdf, "w") as z:
        z.writestr(f"6257_{uf}_CIDADE_2026_T1_PRESIDENTE.pdf", b"PK nao e pdf")
    with pytest.raises(ConteudoInvalido, match="não é PDF"):
        _validar_conteudo(sem_pdf, FAMILIA_RELATORIO, uf, turno=1)


def test_familia_documental_exige_membro_do_cargo_presidente(tmp_path):
    # ZIP só com o relatório estadual (6259) não pode servir de referência federal
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("6259_AC_ACRE_2026_T1.pdf", b"%PDF-1.4 estadual")
    zp = tmp_path / "estadual.zip"
    zp.write_bytes(buf.getvalue())
    with pytest.raises(ConteudoInvalido, match="membro esperado"):
        _validar_conteudo(zp, FAMILIA_RELATORIO, "AC", turno=1)


# --------------------------------------------------------------------------- #
# gravação do CSV de referência                                                #
# --------------------------------------------------------------------------- #


def test_gravacao_atomica_com_colunas_do_aceite(tmp_path):
    linhas = []
    for uf, valor in (("AC", 613_742), ("RS", 8_522_545)):
        base = {"nr_turno": 1, "sg_uf": uf, "fonte_tipo": "RESULTADO_DIVULGADO_TSE",
                "url": f"https://cdn.tse.jus.br/x_{uf}.zip", "sha256_fonte": "a" * 64,
                "data_corte": "2026-10-04"}
        linhas.append({**base, "metrica": "qt_aptos", "valor": valor})
    destino = gravar_referencia(linhas, tmp_path)
    assert destino.exists()
    assert not destino.with_suffix(".csv.tmp").exists()   # tmp promovido, sem sobra
    df = pd.read_csv(destino, dtype={"sg_uf": str})
    assert tuple(df.columns) == COLUNAS
    assert len(df) == 2
    assert int(df[df.sg_uf == "AC"].valor.iloc[0]) == 613_742


def test_anexo_v_ocorrencias_extrai_par_e_quebra_multilinha(tmp_path):
    p_anexo_v = _pagina(
        (173.4, 705.4, "Anexo V - Ocorrências especiais de correspondências"),
        (25.0, 681.6, "Município: 01120 - ACRELÂNDIA"),
        (31.1, 634.2, "0008"), (61.1, 634.2, "0205"), (108.5, 634.2, "---"),
        (145.0, 634.2, "04/10/2026"), (210.4, 634.2, "Esperada"),
        (281.0, 634.2, "---"), (309.4, 634.2, "2019031"),
        (351.4, 634.2, "882.676"), (485.7, 634.2, "B2FA201E"),
        (535.0, 634.2, "23/09/2026"),
        (149.4, 625.0, "17:37:42"), (539.4, 625.0, "12:41:00"),
        (31.1, 611.2, "0008"), (61.1, 611.2, "0205"), (86.5, 611.2, "BU gerado por"),
        (145.0, 611.2, "04/10/2026"), (210.8, 611.2, "Efetivada"),
        (275.2, 611.2, "RED-"), (309.4, 611.2, "2047973"),
        (351.4, 611.2, "671.655"), (485.9, 611.2, "8D9D5087"),
        (535.0, 606.6, "24/09/2026"),
        (88.3, 602.0, "RED em urna"), (149.4, 602.0, "17:37:42"),
        (273.7, 602.0, "Seção"),
        (539.4, 597.4, "09:57:00"),
    )
    paginas = extrair_paginas(_pdf(p_anexo_v))
    regs = _ocorrencias_anexo_v(paginas, "AC", turno=1)
    assert len(regs) == 2
    esp, efe = regs[0], regs[1]
    assert esp["correspondencia"] == "Esperada" and esp["id_urna"] == "2019031"
    assert efe["correspondencia"] == "Efetivada" and efe["id_urna"] == "2047973"
    assert efe["ocorrencia"] == "BU gerado por RED em urna"
    assert efe["origem"] == "RED-Seção"
    assert efe["ts_ocorrencia"] == "04/10/2026 17:37:42"
    assert efe["ts_carga"] == "24/09/2026 09:57:00"
    linhas_csv = [{**r, "url": "https://cdn.tse.jus.br/x.zip",
                   "sha256_fonte": "b" * 64, "data_corte": "2026-10-04"} for r in regs]
    destino = gravar_anexo_v(linhas_csv, tmp_path)
    df = pd.read_csv(destino, dtype=str)
    assert tuple(df.columns) == COLUNAS_ANEXO_V and len(df) == 2


def test_r20_1_referencia_t2_json_resultados_e_validacao_pdf_t2(tmp_path):
    """R20-1: extrai métricas oficiais do T2 via JSON EA20 (6258) e valida PDF T2 quando presente."""
    import json
    from br2026.ingest.relatorio_totalizacao import _metricas_json_resultados

    # Estrutura do JSON oficial do portal Resultados conferida em 27/10/2026 (ac-c0001-e006258-u.json);
    # valores SINTÉTICOS, escolhidos só para exercitar o parser e as validações.
    def payload(ele="6258", t="2", uf="ac", aptos="1000", lula="400", flavio="450"):
        return {
            "ele": ele, "t": t, "cdabr": uf, "dg": "26/10/2026", "dt": "25/10/2026",
            "e": {"te": aptos, "c": "900", "a": "100"},
            "v": {"tv": "900", "vvc": "850", "vv": "850", "vb": "20", "tvn": "30", "vn": "30", "vnt": "0",
                  "van": "0", "vansj": "0"},
            "carg": [{"cd": "1", "agr": [{"par": [{"cand": [{"n": "22", "vap": flavio}]}]},
                                         {"par": [{"cand": [{"n": "13", "vap": lula}]}]}]}],
        }

    m, dt_corte = _metricas_json_resultados(payload(), "AC", 2, 13, 22)
    assert dt_corte == "2026-10-25"
    assert (m["qt_aptos"], m["qt_comparecimento"], m["qt_abstencoes"]) == (1000, 900, 100)
    assert (m["qt_lula"], m["qt_flavio"], m["qt_concorrentes"]) == (400, 450, 850)
    for bad, msg in ((payload(ele="6257"), "cd_eleicao"), (payload(t="1"), "turno"),
                     (payload(uf="rs"), "UF"), (payload(aptos="999"), "inconsist"),
                     (payload(lula="500"), "excede")):
        with pytest.raises(ReferenciaInvalida, match=msg):
            _metricas_json_resultados(bad, "AC", 2, 13, 22)

    # Validação de ZIP documental quando solicitado turno=2: rejeita ZIP que só tem T1_PRESIDENTE.pdf
    zip_so_t1 = tmp_path / "so_t1.zip"
    zip_so_t1.write_bytes(_zip_relatorio("AC", _pdf_relatorio(
        "AC", "04/10/2026", "613.742", "488.330", "125.412", "5.579", "13.662",
        "23", "13.685", "469.066", "134.770", "302.807")))
    with pytest.raises(ConteudoInvalido, match="T2_PRESIDENTE"):
        _validar_conteudo(zip_so_t1, FAMILIA_RELATORIO, "AC", turno=2)
