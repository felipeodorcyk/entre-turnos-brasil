"""Extrai texto de PDFs oficiais (leiame dos arquivos TSE) — auxiliar do A0.

O interpretador com `pypdf` instalado é o do SOURCE_ROOT (somente leitura);
a escrita vai sempre para o PROJECT_ROOT.

Uso:
    python a0_pdf_text.py <pdf> <saida.txt>
    python a0_pdf_text.py --zip <zip> [--member nome] <saida.txt>
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main(argv: list[str]) -> int:
    from pypdf import PdfReader
    if argv[0] == "--zip":
        zip_path = Path(argv[1])
        rest = argv[2:]
        member = None
        if rest and rest[0] == "--member":
            member, rest = rest[1], rest[2:]
        out = Path(rest[0])
        with zipfile.ZipFile(zip_path) as zf:
            infos = [i for i in zf.infolist()
                     if member is None or i.filename == member]
            infos = [i for i in infos if i.filename.lower().endswith(".pdf")]
            if not infos:
                print(f"nenhum pdf em {zip_path} (member={member})", file=sys.stderr)
                return 4
            data = zf.read(infos[0])
            src_name = infos[0].filename
        tmp = out.with_suffix(".pdf.tmp")
        tmp.write_bytes(data)
        reader = PdfReader(str(tmp))
        tmp.unlink(missing_ok=True)
    else:
        pdf = Path(argv[0])
        out = Path(argv[1])
        reader = PdfReader(str(pdf))
        src_name = pdf.name

    lines = [f"# fonte: {src_name}", f"# paginas: {len(reader.pages)}"]
    for i, page in enumerate(reader.pages):
        lines.append(f"\n===== pagina {i + 1} =====")
        lines.append(page.extract_text() or "")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{out} ({out.stat().st_size} B, {len(reader.pages)} paginas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
