"""Oráculo independente de B para a referência oficial T1 (handoff 17, item 4.2).

Lê diretamente os PDFs do Relatório Resultado da Totalização (cargo Presidente)
com `pypdf`, ferramenta distinta do extrator posicional da frente A. Uso:

    <python com pypdf> -I tools/verify_reference_pdf.py SAIDA.csv PDF_AC PDF_RS PDF_MG

Não importa nada de `br2026`. A comparação com a referência de A e com o
staging é feita à parte, no venv do projeto.
"""
import csv
import re
import sys
from pathlib import Path

from pypdf import PdfReader

NUM = r"([\d.]+)"


def to_int(s: str) -> int:
    return int(s.replace(".", ""))


def extract(pdf: Path) -> dict:
    pages = [p.extract_text() or "" for p in PdfReader(str(pdf)).pages]
    head = "\n".join(pages[:3])
    full = "\n".join(pages)
    out = {"arquivo": pdf.name}
    m = re.search(r"Eleição Geral Federal 2026 - (\d)º Turno", head)
    out["turno"] = int(m.group(1)) if m else None
    m = re.search(r"Oficial\s*\n(\d{2}/\d{2}/\d{4})\s*\n(\d{2}:\d{2}:\d{2})", head)
    out["emissao"] = f"{m.group(1)} {m.group(2)}" if m else None
    out["cargo_presidente"] = "Total de votos - Presidente" in head
    pats = {
        "qt_aptos": r"2\.2 Eleitorado apto a votar " + NUM,
        "qt_comparecimento": r"2\.3 Comparecimento " + NUM,
        "qt_abstencoes": r"2\.4 Abstenção [\d,]+% " + NUM,
        "nulos_na_urna": r"Votos nulos na urna " + NUM,
        "nulos_tecnicos": r"Votos nulos técnico [\d,]+% " + NUM,
        "anulados": r"Votos anulados [\d,]+% " + NUM,
        "anulados_sub_judice": r"Votos anulados sub judice [\d,]+% " + NUM,
        "qt_votos_validos": r"Votos válidos [\d,]+% " + NUM,
    }
    for k, p in pats.items():
        m = re.search(p, head)
        out[k] = to_int(m.group(1)) if m else None
    # Bloco 2.5.1: os quatro valores na ordem total, concorrentes, brancos, nulos.
    m = re.search(r"b\) Votos nulos\s*\n" + NUM + r"\s*\n" + NUM + r"\s*\n" + NUM + r"\s*\n" + NUM, head)
    if m:
        out["total_votos"], out["votos_concorrentes"], out["qt_votos_brancos"], out["nulos_total"] = \
            (to_int(g) for g in m.groups())
    for nr, key in ((13, "qt_lula"), (22, "qt_flavio")):
        m = re.search(NUM + r" [\d,]+%" + f"{nr} - ", full)
        out[key] = to_int(m.group(1)) if m else None
    return out


def main() -> None:
    dest = Path(sys.argv[1])
    rows = [extract(Path(p)) for p in sys.argv[2:]]
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
