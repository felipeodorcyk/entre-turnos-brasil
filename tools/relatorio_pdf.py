"""PDF do relatório nacional: resumo executivo + relatório + apêndice técnico resumido.

Converte o Markdown gerado por `br2026 report` (subconjunto usado nos documentos: títulos, listas,
tabelas, imagens, negrito, itálico, código e links) para um HTML autocontido, com as figuras
embutidas, e imprime com o Chrome/Edge em modo headless. Não altera os Markdown nem os números:
o PDF é uma apresentação dos mesmos documentos, que continuam sendo a fonte rastreada.

Apêndice: por padrão, só as seções A.1 a A.5 e A.7 (as tabelas completas de associações e de
proveniência têm milhares de linhas e ficam no repositório); `--apendice-completo` inclui tudo.

Uso: python tools/relatorio_pdf.py [--saida reports/analysis/RELATORIO_NACIONAL.pdf]
"""
from __future__ import annotations

import argparse
import base64
import html
import re
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "reports" / "analysis"
NAVEGADORES = (Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
               Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"))
CSS = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.2pt; line-height: 1.42; color: #1f2933; }
h1 { font-size: 19pt; color: #1e3a5f; border-bottom: 2px solid #1e3a5f; padding-bottom: 4px; margin-top: 0; }
h2 { font-size: 13.5pt; color: #1e3a5f; margin-top: 18px; border-bottom: 1px solid #d5dde6; padding-bottom: 2px; }
h3 { font-size: 11.5pt; color: #1e3a5f; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 8.4pt; page-break-inside: auto; }
th { background: #eef2f6; color: #1e3a5f; text-align: left; }
th, td { border: 1px solid #d5dde6; padding: 3px 5px; vertical-align: top; }
table.larga { font-size: 6.4pt; table-layout: fixed; }
table.larga th, table.larga td { padding: 2px 3px; overflow-wrap: anywhere; }
table.entorno { table-layout: fixed; }
table.entorno th, table.entorno td { padding: 2px 3px; overflow-wrap: anywhere; white-space: normal; text-align: left; }
tr { page-break-inside: avoid; }
img { max-width: 100%; display: block; margin: 8px auto 14px; page-break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f3f5f8; padding: 0 2px; }
ul { margin: 4px 0 8px 18px; padding: 0; } li { margin: 2px 0; }
.quebra { page-break-before: always; }
.capa { color: #52606d; font-size: 9pt; margin-bottom: 14px; }
"""


def _inline(t: str, base: Path) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    return t


def _img(alt: str, src: str, base: Path) -> str:
    p = (base / src).resolve()
    if not p.exists():
        return f"<p><em>[figura ausente: {html.escape(src)}]</em></p>"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f'<img alt="{html.escape(alt)}" src="data:image/png;base64,{b64}">'


def md_para_html(md: str, base: Path) -> str:
    out, i = [], 0
    linhas = md.splitlines()
    while i < len(linhas):
        l = linhas[i]
        if not l.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", l)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2), base)}</h{n}>")
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", l)
        if m:
            out.append(_img(m.group(1), m.group(2), base))
            i += 1
            continue
        if l.startswith("|"):
            bloco = []
            while i < len(linhas) and linhas[i].startswith("|"):
                bloco.append(linhas[i])
                i += 1
            cel = [[c.strip() for c in b.strip().strip("|").split("|")] for b in bloco]
            corpo = [r for r in cel[2:]] if len(cel) > 1 and set("".join(cel[1])) <= set("-: ") else cel[1:]
            # tabelas com muitas colunas (A.5) em letra menor e largura fixa, para caberem na página
            classe = ' class="larga"' if len(cel[0]) > 9 else ""
            colunas = ""
            if cel[0][0] == "Entorno" and "Amostra" in cel[0] and len(cel[0]) == 9:
                classe = ' class="entorno"'
                colunas = "<colgroup>" + "".join(
                    f'<col style="width:{w}%">' for w in (27, 17, 20, 6, 6, 6, 6, 6, 6)
                ) + "</colgroup>"
            out.append(f"<table{classe}>{colunas}<thead><tr>" + "".join(f"<th>{_inline(c, base)}</th>" for c in cel[0])
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c, base)}</td>" for c in r) + "</tr>" for r in corpo)
                       + "</tbody></table>")
            continue
        if re.match(r"^\s*- ", l):
            itens = []
            while i < len(linhas) and (re.match(r"^\s*- ", linhas[i]) or
                                       (linhas[i].startswith("  ") and linhas[i].strip() and itens)):
                x = linhas[i]
                nivel = (len(x) - len(x.lstrip())) // 2
                if re.match(r"^\s*- ", x):
                    itens.append((nivel, x.strip()[2:]))
                else:
                    itens[-1] = (itens[-1][0], itens[-1][1] + " " + x.strip())
                i += 1
            html_l, atual = [], -1
            for nivel, txt in itens:
                while atual < nivel:
                    html_l.append("<ul>")
                    atual += 1
                while atual > nivel:
                    html_l.append("</ul>")
                    atual -= 1
                html_l.append(f"<li>{_inline(txt, base)}</li>")
            html_l += ["</ul>"] * (atual + 1)
            out.append("".join(html_l))
            continue
        par = []
        while i < len(linhas) and linhas[i].strip() and not re.match(r"^(#{1,4}\s|\||\s*- |!\[)", linhas[i]):
            par.append(linhas[i].lstrip("> ").strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(par), base)}</p>")
    return "\n".join(out)


def apendice_resumido(md: str) -> str:
    """Mantém A.1–A.5, A.7 e A.9; corta A.6 (associações completas), A.8 (proveniência) e A.10 (faixas por UF)."""
    partes = re.split(r"(?m)^(## A\.\d.*)$", md)
    out = [partes[0]]
    for k in range(1, len(partes), 2):
        tit, corpo = partes[k], partes[k + 1]
        if tit.startswith(("## A.6", "## A.8", "## A.10")):
            out.append(tit + "\n\n*Tabela completa no repositório (`APENDICE_TECNICO_NACIONAL.md`).*\n")
        else:
            out.append(tit + corpo)
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=str(DOCS / "RELATORIO_NACIONAL.pdf"))
    ap.add_argument("--apendice-completo", action="store_true")
    ap.add_argument("--html", help="grava também o HTML intermediário (para revisão visual)")
    a = ap.parse_args(argv)
    resumo = (DOCS / "RESUMO_EXECUTIVO_NACIONAL.md").read_text(encoding="utf-8")
    rel = (DOCS / "RELATORIO_NACIONAL_T1_T2.md").read_text(encoding="utf-8")
    apx = (DOCS / "APENDICE_TECNICO_NACIONAL.md").read_text(encoding="utf-8")
    if not a.apendice_completo:
        apx = apendice_resumido(apx)
    corpo = ('<p class="capa">Projeto presidenciais_2026_br · documento gerado a partir dos Markdown rastreados '
             '(RESUMO_EXECUTIVO_NACIONAL, RELATORIO_NACIONAL_T1_T2, APENDICE_TECNICO_NACIONAL); cada número tem '
             'origem em RASTRO_RELATORIO_NACIONAL.csv.</p>'
             + md_para_html(resumo, DOCS) + '<div class="quebra"></div>' + md_para_html(rel, DOCS)
             + '<div class="quebra"></div>' + md_para_html(apx, DOCS))
    doc = f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Lula × Flávio — 2026</title>' \
          f'<style>{CSS}</style></head><body>{corpo}</body></html>'
    if a.html:
        Path(a.html).write_text(doc, encoding="utf-8")
    nav = next((p for p in NAVEGADORES if p.exists()), None)
    if nav is None:
        raise SystemExit("Chrome/Edge não encontrado para imprimir o PDF")
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "relatorio.html"
        h.write_text(doc, encoding="utf-8")
        saida = Path(a.saida).resolve()
        subprocess.run([str(nav), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={saida}", h.as_uri()], check=True, capture_output=True, timeout=300)
    print(f"{saida} ({saida.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
