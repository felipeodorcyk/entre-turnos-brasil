"""Extração posicional de texto de PDF oficial, sem dependência externa.

O Relatório de Totalização do TSE é gerado pelo SISTOT com fontes
LiberationSans embutidas e streams FlateDecode. Não há lib de PDF no `.venv` e
o `requirements.lock` não pode ser alterado neste ciclo; a extração usa só a
biblioteca padrão (zlib + operadores de texto), que foi validada contra os
três relatórios do piloto (AC/RS/MG) em 26/10/2026.

Os literais saem fora de ordem em relação aos rótulos da mesma linha visual,
então a associação é **posicional**: cada fragmento carrega (x, y) e as linhas
são reconstruídas agrupando y com tolerância. Valores ficam à direita
(x > 500 no Resumo Geral; x ≈ 280 no Anexo IV).
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

TOLERANCIA_Y = 2.0        # unidades de ponto entre fragmentos da mesma linha
LARGURA_CARACTERE = 5.5   # avanço médio da fonte para estimar x seguinte em TJ

_TOKEN = re.compile(rb"""
    (?P<tm>-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+
            -?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+Tm)
  | (?P<td>-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+(?:Td|TD))
  | (?P<tj>\[(?:[^\]]*)\]\s*TJ)
  | (?P<lit>\((?:\\.|[^\\()])*\)\s*Tj)
  | (?P<et>ET)
""", re.X)

_LITERAL = re.compile(rb"\((?:\\.|[^\\()])*\)|-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Fragmento:
    """Trecho de texto com coordenada de canto inferior esquerda (unidades PDF)."""
    x: float
    y: float
    texto: str


def _decodifica(cru: bytes) -> str:
    """Literal PDF → texto latin-1 (com escape de octal, parêntese e barra)."""
    txt = cru.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
    txt = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8)]), txt)
    return txt.decode("latin-1", "replace")


def _streams(pdf: bytes):
    """Descomprime cada stream FlateDecode do PDF (bytes crus → zlib)."""
    for m in re.finditer(rb"stream\r?\n", pdf):
        inicio = m.end()
        fim = pdf.find(b"endstream", inicio)
        if fim < 0:
            continue
        bruto = pdf[inicio:fim]
        for tentativa in (bruto, bruto.rstrip(b"\r\n")):
            try:
                yield zlib.decompress(tentativa)
                break
            except zlib.error:
                continue


def extrair_paginas(pdf: bytes) -> list[list[Fragmento]]:
    """Fragmentos por página (página = um content stream FlateDecode).

    O SISTOT emite vários objetos de texto (BT/ET) por página visual, todos no
    mesmo content stream; o separador de página é o stream, não o ET.
    """
    paginas: list[list[Fragmento]] = []
    for dados in _streams(pdf):
        if b"BT" not in dados:
            continue
        x = y = 0.0
        pagina: list[Fragmento] = []
        for m in _TOKEN.finditer(dados):
            if m.group("tm"):
                nums = [float(v) for v in m.group("tm").split()[:6]]
                x, y = nums[4], nums[5]
            elif m.group("td"):
                nums = [float(v) for v in m.group("td").split()[:2]]
                x += nums[0]
                y += nums[1]
            elif m.group("lit"):
                s = _decodifica(m.group("lit").strip()[:-2])
                if s.strip():
                    pagina.append(Fragmento(x, y, s))
                x += LARGURA_CARACTERE * len(s)
            elif m.group("tj"):
                corpo = m.group("tj").strip()[1:-3]
                s = ""
                for p in _LITERAL.findall(corpo):
                    if p.startswith(b"("):
                        s += _decodifica(p[1:-1])
                    else:
                        x -= float(p) / 18.0   # ajuste de kerning (TJ)
                if s.strip():
                    pagina.append(Fragmento(x, y, s))
                x += LARGURA_CARACTERE * len(s)
        if pagina:
            paginas.append(pagina)
    return paginas


def linhas(pagina: list[Fragmento]) -> list[tuple[float, list[Fragmento]]]:
    """Agrupa os fragmentos da página em linhas visuais (y com tolerância).

    Devolve [(y_da_linha, fragmentos ordenados por x)]. A tolerância cobre o
    deslocamento de ~1 unidade entre rótulo e valor observado no Relatório.
    """
    grupos: dict[float, list[Fragmento]] = {}
    for f in sorted(pagina, key=lambda f: -f.y):
        for y in grupos:
            if abs(y - f.y) <= TOLERANCIA_Y:
                grupos[y].append(f)
                break
        else:
            grupos[f.y] = [f]
    return [(y, sorted(fs, key=lambda f: f.x)) for y, fs in sorted(grupos.items(),
                                                                  reverse=True)]
