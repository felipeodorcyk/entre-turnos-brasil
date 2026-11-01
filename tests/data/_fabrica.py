"""Construtor de ZIPs sintéticos no formato TSE, para os testes offline de ingestão."""
from __future__ import annotations

import io
import zipfile


def zip_sintetico(familia, uf, *, ano="2026", turno="1", colunas=None, membro=None,
                  linhas=3) -> bytes:
    """Monta um ZIP válido (Latin-1, `;`, campos entre aspas) para a família.

    `ano`/`turno` permitem fabricar conteúdo inválido de propósito (ex.: 2022).
    """
    cols = list(colunas if colunas is not None else familia.colunas)
    membro_uf = uf if familia.escopo == "uf" else "BR"
    nome = membro or familia.membro.format(uf=membro_uf)
    corpo = [";".join(f'"{c}"' for c in cols)]
    for i in range(linhas):
        vals = []
        for c in cols:
            if c == familia.campo_ano:
                vals.append(f'"{ano}"')
            elif c == familia.campo_turno:
                vals.append(f'"{turno}"')
            elif c == "SG_UF" and uf not in ("BR", "ZZ"):
                vals.append(f'"{uf}"')
            elif c == "CD_CARGO":
                vals.append('"1"')  # presidente, como nos consolidados reais
            else:
                vals.append(f'"{i}"')
        corpo.append(";".join(vals))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, "\n".join(corpo))
    return buf.getvalue()
