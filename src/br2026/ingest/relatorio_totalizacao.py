"""Referência oficial independente (frente A, tarefa A1).

Fonte: **Relatório de Totalização** (SISTOT) por UF, eleição 6257
(presidente), 1º turno — `RESULTADO_DIVULGADO_TSE` no vocabulário de
`br2026.reporting.acceptance`. Em 2026 o TSE separou os datasets: os arquivos
`votacao/detalhe_votacao_munzona` cobrem só as eleições estaduais (6259) e a
presidencial não está lá; o Relatório por UF é a fonte agregada disponível e
distinta do arquivo por seção.

Extração posicional (`br2026.ingest.pdf_texto`): rótulos e valores do PDF
saem fora de ordem, então cada linha é reconstruída por coordenadas — valor à
direita (x > 500 no Resumo Geral; x ≈ 280 no Anexo IV), tolerância de 2
unidades em y. Percentuais têm vírgula decimal e nunca são confundidos com
contagens (ponto de milhar).

Duas convenções documentadas aqui (não inferidas):

- `qt_votos_nulos` = **"Votos nulos na urna"** (fecha com o staging por
  seção). O relatório também publica "Votos nulos técnico"; a soma dos dois é
  o total "b) Votos nulos", usado só na checagem de identidade.
- `data_corte` = data de emissão impressa no cabeçalho do próprio relatório
  (o RS foi reemitido em 26/10; a data vem do documento, não do Last-Modified).

Saída: `docs/sources/official_totals_reference.csv`, gravado de forma atômica
(tmp + `os.replace`), colunas exatamente `REF_COLUMNS` do aceite.

Aquisição própria (`docs/sources/official_totals/`): a referência do aceite
não é insumo do staging e por isso **não** passa por `data/raw/manifest.json` —
o teste de integração trata qualquer URL do manifesto de brutos como fonte de
seção não independente. O ZIP é baixado (ou reusado de `data/raw/.reuso/`),
validado por conteúdo (PDF + marcadores do SISTOT + cargo presidente) e
registrado em `docs/sources/official_totals/manifest.json` com URL, SHA-256,
bytes, ETag/Last-Modified remotos e verificação de versão.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import time
import urllib.error
import zipfile
from pathlib import Path

from br2026.config import election_numbers, load_config
from br2026.ingest import (_baixar, _head, _hash, _url_catalogada,
                           _validar_conteudo, ConteudoInvalido, Familia)
from br2026.ingest.pdf_texto import Fragmento, extrair_paginas, linhas

FONT_TIPO = "RESULTADO_DIVULGADO_TSE"
FONTES_DIR = Path("docs") / "sources" / "official_totals"
MANIFEST_REL = FONTES_DIR / "manifest.json"
SAIDA_REL = Path("docs") / "sources" / "official_totals_reference.csv"
SAIDA_ANEXO_V_REL = FONTES_DIR / "anexo_v_ocorrencias.csv"
COLUNAS = ("nr_turno", "sg_uf", "metrica", "valor", "fonte_tipo", "url",
           "sha256_fonte", "data_corte")
COLUNAS_ANEXO_V = (
    "nr_turno", "sg_uf", "cd_municipio_tse", "nm_municipio", "nr_zona",
    "nr_secao", "correspondencia", "ocorrencia", "ts_ocorrencia", "origem",
    "id_urna", "id_carga", "id_mc", "ts_carga", "url", "sha256_fonte",
    "data_corte",
)
CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"

# Família documental do Relatório (mesma validação de conteúdo do M2, mas com
# manifesto próprio — ver docstring). Nome real do membro:
# 6257_AC_ACRE_2026_T1_PRESIDENTE.pdf (não é template fixo).
FAMILIA_RELATORIO = Familia(
    fonte="relatorio_resultado_totalizacao", escopo="uf", turnos=(1,),
    nome="Relatorio_Resultado_Totalizacao_2026_{uf}.zip",
    url=(f"{CDN}/relatorio_resultado_totalizacao/"
         "Relatorio_Resultado_Totalizacao_2026_{uf}.zip"),
    membro="", colunas=(), campo_ano=None, campo_turno=None,
    tipo="documento",
    membro_padrao=r"6257_{uf}_.+_2026_T1_PRESIDENTE\.pdf",
    # marcadores sem acento que identificam o relatório oficial da UF
    texto_esperado=("SISTOT - SISTEMA DE GERENCIAMENTO DA TOTALIZA",
                    "Cargo: Presidente"),
)

_RE_CONTAGEM = re.compile(r"^\d{1,3}(?:\.\d{3})+$|^\d+$")
_RE_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_RE_CANDIDATO = re.compile(r"^(\d{1,2}) - ")


class ReferenciaInvalida(RuntimeError):
    """O relatório não fecha internamente ou a extração não achou o valor."""


def _valor_da_linha(fs: list[Fragmento], x_minimo: float) -> int | None:
    """Maior contagem da linha à direita de `x_minimo` (ponto de milhar).

    Os literais saem envolvidos em parêntese (`"(613.742)"`); o percentual da
    mesma linha tem vírgula decimal e nunca casa o padrão de contagem.
    """
    for f in reversed(fs):
        texto = f.texto.strip("( )")
        if f.x >= x_minimo and _RE_CONTAGEM.fullmatch(texto):
            return int(texto.replace(".", ""))
    return None


def _procurar(fs: list[Fragmento], prefixo: str) -> bool:
    """Casa o prefixo do rótulo ignorando o parêntese que envolve o literal."""
    return any(f.texto.lstrip("( ").startswith(prefixo) for f in fs)


def _extrair_pdf(z: zipfile.ZipFile, uf: str, turno: int = 1) -> bytes:
    esperado = re.compile(rf"(?:6257|6258)_{uf}_.+_2026_T{turno}_PRESIDENTE\.pdf")
    membros = [m for m in z.namelist() if esperado.fullmatch(m)]
    if len(membros) != 1:
        raise ReferenciaInvalida(
            f"{uf}/T{turno}: {len(membros)} PDF(s) de presidente no ZIP (esperado 1): {membros}")
    return z.read(membros[0])


def _tem_pdf_turno(z: zipfile.ZipFile, uf: str, turno: int) -> bool:
    esperado = re.compile(rf"(?:6257|6258)_{uf}_.+_2026_T{turno}_PRESIDENTE\.pdf")
    return len([m for m in z.namelist() if esperado.fullmatch(m)]) == 1


def _metricas_json_resultados(
    dados: dict, uf: str, turno: int, nr_lula: int, nr_flavio: int
) -> tuple[dict[str, int], str]:
    """Extrai e valida métricas do JSON oficial do portal Resultados (`*-c0001-e006258-u.json`)."""
    cd_esperado = "6258" if turno == 2 else "6257"
    if str(dados.get("ele") or "").strip() != cd_esperado:
        raise ReferenciaInvalida(f"{uf}/T{turno}: cd_eleicao JSON {dados.get('ele')!r} != {cd_esperado!r}")
    if str(dados.get("t") or "").strip() != str(turno):
        raise ReferenciaInvalida(f"{uf}/T{turno}: turno JSON {dados.get('t')!r} != {turno!r}")
    if str(dados.get("cdabr") or "").strip().upper() != uf.upper():
        raise ReferenciaInvalida(f"{uf}/T{turno}: UF JSON {dados.get('cdabr')!r} != {uf!r}")
    e_blk = dados.get("e") or {}
    v_blk = dados.get("v") or {}
    try:
        m = {
            "qt_aptos": int(e_blk["te"]),
            "qt_comparecimento": int(e_blk["c"]),
            "qt_abstencoes": int(e_blk["a"]),
            "qt_votos_brancos": int(v_blk["vb"]),
            "qt_votos_nulos": int(v_blk["vn"]),
            "qt_votos_nulos_tecnico": int(v_blk.get("vnt", 0)),
            "qt_votos_nulos_total": int(v_blk["tvn"]),
            "qt_concorrentes": int(v_blk["vvc"]),
            "qt_anulados": int(v_blk.get("van", 0)),
            "qt_anulados_sub_judice": int(v_blk.get("vansj", 0)),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ReferenciaInvalida(f"{uf}/T{turno}: campos obrigatórios inválidos no JSON ({exc})")
    # `te` é o eleitorado total, inclusive o das seções não instaladas (`esni`; exterior, 2026:
    # 423 eleitores), que não entram em comparecimento nem em abstenção (handoff 26)
    m["qt_aptos_nao_instaladas"] = int(e_blk.get("esni") or 0)
    problemas = _consistencia(m)
    if problemas:
        raise ReferenciaInvalida(f"{uf}/T{turno}: inconsistência no JSON oficial: {problemas}")

    carg = dados.get("carg") or []
    if not carg or str(carg[0].get("cd") or "") != "1":
        raise ReferenciaInvalida(f"{uf}/T{turno}: JSON sem cargo Presidente (cd=1)")
    votos_cand: dict[int, int] = {}
    for agr in carg[0].get("agr") or []:
        for par in agr.get("par") or []:
            for cand in par.get("cand") or []:
                nr = int(str(cand.get("n") or "0"))
                vap = int(str(cand.get("vap") or "0"))
                votos_cand[nr] = vap
    if nr_lula not in votos_cand or nr_flavio not in votos_cand:
        raise ReferenciaInvalida(
            f"{uf}/T{turno}: candidatos {nr_lula}/{nr_flavio} ausentes no JSON ({sorted(votos_cand)})"
        )
    m["qt_lula"] = votos_cand[nr_lula]
    m["qt_flavio"] = votos_cand[nr_flavio]
    if m["qt_lula"] + m["qt_flavio"] > m["qt_concorrentes"]:
        raise ReferenciaInvalida(f"{uf}/T{turno}: lula+flavio excede concorrentes no JSON")

    dt_bruta = str(dados.get("dt") or dados.get("dg") or "").strip()
    m_dt = _RE_DATA.fullmatch(dt_bruta)
    if not m_dt:
        raise ReferenciaInvalida(f"{uf}/T{turno}: data inválida no JSON ({dt_bruta!r})")
    data_corte = f"{m_dt.group(3)}-{m_dt.group(2)}-{m_dt.group(1)}"
    return m, data_corte


def _metricas_resumo(paginas: list[list[Fragmento]]) -> dict[str, int]:
    """Resumo Geral: aptos, comparecimento, abstenção, brancos e nulos."""
    alvos = {
        "2.2 Eleitorado apto a votar": "qt_aptos",
        "2.2.2 Aptos nas se": "qt_aptos_nao_instaladas",
        "2.3 Comparecimento": "qt_comparecimento",
        "2.4 Absten": "qt_abstencoes",
        "c) Votos em branco": "qt_votos_brancos",
        "Votos nulos na urna": "qt_votos_nulos",
        "Votos nulos t": "qt_votos_nulos_tecnico",
        "b) Votos nulos": "qt_votos_nulos_total",
        "a) Votos a candidatos": "qt_concorrentes",
        "Votos anulados sub judice": "qt_anulados_sub_judice",
        "Votos anulados": "qt_anulados",
    }
    achados: dict[str, int] = {}
    for pagina in paginas:
        for _, fs in linhas(pagina):
            for prefixo, chave in alvos.items():
                if chave in achados or not _procurar(fs, prefixo):
                    continue
                # "Votos anulados" não pode casar com "Votos anulados sub judice"
                if prefixo == "Votos anulados" and _procurar(fs, "Votos anulados sub judice"):
                    continue
                valor = _valor_da_linha(fs, x_minimo=500)
                if valor is not None:
                    achados[chave] = valor
    return achados


def _metricas_anexo_iv(paginas: list[list[Fragmento]], numero: int) -> int:
    """Anexo IV (Cargo: Presidente): total computado do candidato `numero`."""
    for pagina in paginas:
        textos = [f.texto.lstrip("( ") for f in pagina]
        if not any(t.startswith("Anexo IV - Resultado de vota") for t in textos):
            continue
        if not any(t.startswith("Cargo: Presidente") for t in textos):
            continue
        for _, fs in linhas(pagina):
            cabecalho = _RE_CANDIDATO.match(fs[0].texto.lstrip("( "))
            if not cabecalho or int(cabecalho.group(1)) != numero:
                continue
            valor = _valor_da_linha(fs, x_minimo=200)
            if valor is not None:
                return valor
    raise ReferenciaInvalida(f"Anexo IV sem total do candidato {numero}")


def _data_emissao(paginas: list[list[Fragmento]]) -> str:
    """Data ISO a partir do cabeçalho (``Justiça Eleitoral/{uf}`` + data à direita)."""
    for pagina in paginas:
        for _, fs in linhas(pagina):
            if not any(f.texto.lstrip("( ").startswith("Justi") for f in fs):
                continue
            for f in fs:
                m = _RE_DATA.search(f.texto)
                if m and f.x > 400:
                    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    raise ReferenciaInvalida("cabeçalho sem data de emissão à direita")


def _ocorrencias_anexo_v(paginas: list[list[Fragmento]], uf: str,
                         turno: int = 1) -> list[dict]:
    """Anexo V: ocorrências especiais de correspondências (Esperada vs Efetivada)."""
    in_anexo_v = False
    mun_cod, mun_nome = None, None
    registros: list[dict] = []
    for p in paginas:
        ls = list(linhas(p))
        page_texts = [f.texto.strip("() ") for _, fs in ls for f in fs]
        if any(t.startswith("Anexo V -") for t in page_texts):
            in_anexo_v = True
        elif any(t.startswith("Anexo ") for t in page_texts):
            in_anexo_v = False
        if not in_anexo_v:
            continue
        i = 0
        while i < len(ls):
            y, fs = ls[i]
            t0 = fs[0].texto.strip("() ")
            m_mun = re.match(r"^Munic.pio:\s*(\d{5})\s*-\s*(.+)$", t0)
            if m_mun:
                mun_cod, mun_nome = m_mun.group(1), m_mun.group(2).strip()
                i += 1
                continue
            by_x = [(round(f.x, 1), f.texto.strip("() ")) for f in fs]
            if (len(by_x) >= 6
                    and re.fullmatch(r"\d{4}", by_x[0][1])
                    and re.fullmatch(r"\d{4}", by_x[1][1])):
                if mun_cod is None:
                    raise ReferenciaInvalida(f"{uf}: linha do Anexo V antes de Município")
                zona, secao = by_x[0][1], by_x[1][1]
                ocorr_parts = [by_x[2][1]]
                dt_ocorr = by_x[3][1]
                corresp = by_x[4][1]
                origem_parts = [by_x[5][1]]
                id_urna = by_x[6][1] if len(by_x) > 6 else ""
                id_carga = by_x[7][1] if len(by_x) > 7 else ""
                id_mc = by_x[8][1] if len(by_x) > 8 else ""
                dt_carga = by_x[9][1] if len(by_x) > 9 else ""
                hh_ocorr, hh_carga = "", ""
                j = i + 1
                while j < len(ls):
                    y2, fs2 = ls[j]
                    if not (0 < (y - y2) <= 22.0):
                        break
                    bx2 = [(round(f.x, 1), f.texto.strip("() ")) for f in fs2]
                    if (not bx2
                            or bx2[0][1].startswith("Munic")
                            or (len(bx2) >= 6
                                and re.fullmatch(r"\d{4}", bx2[0][1])
                                and re.fullmatch(r"\d{4}", bx2[1][1]))
                            or any(t in ("Zona", "Data/hora", "Ocorrência")
                                   for _, t in bx2)):
                        break
                    for x2, t2 in bx2:
                        if not t2:
                            continue
                        if 80 <= x2 < 140:
                            ocorr_parts.append(t2)
                        elif 140 <= x2 < 190 and re.fullmatch(r"\d{2}:\d{2}:\d{2}", t2):
                            hh_ocorr = t2
                        elif 265 <= x2 < 305:
                            origem_parts.append(t2)
                        elif x2 >= 520 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", t2):
                            dt_carga = t2
                        elif x2 >= 520 and re.fullmatch(r"\d{2}:\d{2}:\d{2}", t2):
                            hh_carga = t2
                    j += 1
                ocorr = " ".join(ocorr_parts)
                origem = " ".join(origem_parts).replace("- ", "-")
                registros.append({
                    "nr_turno": turno,
                    "sg_uf": uf,
                    "cd_municipio_tse": mun_cod,
                    "nm_municipio": mun_nome,
                    "nr_zona": zona,
                    "nr_secao": secao,
                    "correspondencia": corresp,
                    "ocorrencia": ocorr,
                    "ts_ocorrencia": f"{dt_ocorr} {hh_ocorr}".strip(),
                    "origem": origem,
                    "id_urna": id_urna,
                    "id_carga": id_carga,
                    "id_mc": id_mc,
                    "ts_carga": f"{dt_carga} {hh_carga}".strip(),
                })
                i = j
            else:
                i += 1
    por_secao: dict[tuple[str, str, str], set[str]] = {}
    for r in registros:
        chave = (r["cd_municipio_tse"], r["nr_zona"], r["nr_secao"])
        por_secao.setdefault(chave, set()).add(r["correspondencia"])
    incompletas = [k for k, v in por_secao.items() if v != {"Esperada", "Efetivada"}]
    if incompletas:
        raise ReferenciaInvalida(
            f"{uf}: seção(ões) do Anexo V sem par Esperada/Efetivada: {incompletas[:5]}")
    return registros


def _consistencia(m: dict[str, int]) -> list[str]:
    """Identidades que o relatório deve satisfazer; devolve as violações."""
    problemas = []
    # o eleitorado apto inclui o das seções não instaladas, que não comparece nem se abstém
    # (exterior, 2026); o staging por seção preserva essas seções com aptos e zero comparecimento
    if m["qt_aptos"] != m["qt_comparecimento"] + m["qt_abstencoes"] + m.get("qt_aptos_nao_instaladas", 0):
        problemas.append("aptos != comparecimento + abstenções + aptos de seções não instaladas")
    soma = (m["qt_concorrentes"] + m["qt_votos_nulos_total"] + m["qt_votos_brancos"]
            + m["qt_anulados"] + m["qt_anulados_sub_judice"])
    if soma != m["qt_comparecimento"]:
        problemas.append(
            f"concorrentes+nulos_total+brancos+anulados ({soma}) != comparecimento")
    if (m["qt_votos_nulos"] + m["qt_votos_nulos_tecnico"] != m["qt_votos_nulos_total"]):
        problemas.append("nulos na urna + técnico != total 'b) Votos nulos'")
    return problemas


def _chave(uf: str) -> str:
    return FAMILIA_RELATORIO.nome.format(uf=uf)[:-4]   # stem sem .zip


def adquirir(project_root: Path, ufs: tuple[str, ...],
             reuso_dir: Path | None = None, atualizar: bool = False) -> dict:
    """Adquire os Relatórios para `docs/sources/official_totals/` com manifesto próprio.

    Mesmas regras do M2 — URL só do catálogo A0, download com timeout, cópia
    local só após conferência de versão, validação de conteúdo (ZIP + PDF +
    marcadores do SISTOT + cargo presidente) e promoção atômica — mas gravando
    no manifesto da referência, nunca em `data/raw/manifest.json`.

    `atualizar=True` consulta o remoto (HEAD) mesmo com registro válido: se o `Last-Modified`
    mudou, baixa de novo; conteúdo diferente vira registro novo e a versão anterior fica
    preservada com o SHA no nome (`versao_anterior`). Usado quando o TSE republica o Relatório
    (27/10/2026: inclusão do PDF do 2º turno).
    """
    projeto = Path(project_root)
    fontes = projeto / FONTES_DIR
    tmp_dir = fontes / ".tmp"
    fontes.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    manifesto_path = projeto / MANIFEST_REL
    if manifesto_path.exists():
        manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    else:
        manifesto = {"manifest_version": "1.0", "registros": {}}
    registros = manifesto["registros"]
    agora = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    alterado = not manifesto_path.exists()

    for uf in ufs:
        fam = FAMILIA_RELATORIO
        nome = fam.nome.format(uf=uf)
        url = fam.url.format(uf=uf)
        if _url_catalogada(url, projeto) is False:
            raise ReferenciaInvalida(
                f"{uf}: {url} ausente do snapshot do catálogo A0; "
                "não adquirir sem evidência de catálogo")
        stem = _chave(uf)
        registro = registros.get(stem)
        destino = fontes / nome
        # reexecução: registro vigente + arquivo presente + SHA-256 confere ⇒ sem rede
        if registro and destino.exists() and _hash(destino) == registro["sha256"]:
            if not atualizar:
                continue
            try:
                lm = _head(url).get("last-modified")
            except (urllib.error.URLError, TimeoutError, OSError):
                lm = None
            if lm is None or lm == registro.get("last_modified_remoto"):
                continue
        alterado = True
        parcial = tmp_dir / f"{nome}.parcial"
        headers: dict[str, str] = {}
        reusado = False
        try:
            if reuso_dir is not None:
                cand = Path(reuso_dir) / nome
                if cand.exists():
                    try:
                        headers = _head(url)
                    except (urllib.error.URLError, TimeoutError, OSError):
                        headers = {}
                    tamanho_remoto = headers.get("content-length")
                    if (tamanho_remoto is None
                            or int(tamanho_remoto) == cand.stat().st_size):
                        shutil.copyfile(cand, parcial)
                        reusado = True
            if not reusado:
                _, headers = _baixar(url, parcial)
            try:
                fatos = _validar_conteudo(parcial, fam, uf, turno=1)
            except ConteudoInvalido as e:
                raise ReferenciaInvalida(f"{uf}: conteúdo inválido ({e})")
            sha = _hash(parcial)
            anterior = None
            if registro and registro.get("sha256") != sha and destino.exists():
                guardado = fontes / f"{Path(nome).stem}__{registro['sha256'][:12]}{Path(nome).suffix}"
                os.replace(destino, guardado)
                anterior = {k: registro.get(k) for k in
                            ("sha256", "bytes", "baixado_em", "last_modified_remoto")}
                anterior["arquivo"] = guardado.name
            elif registro and registro.get("sha256") == sha:
                anterior = registro.get("versao_anterior")
            os.replace(parcial, destino)
            registros[stem] = {
                "arquivo": nome, "bytes": destino.stat().st_size,
                "baixado_em": agora, "conteudo": fatos, "sha256": sha,
                "etag_remoto": headers.get("etag"),
                "last_modified_remoto": headers.get("last-modified"),
                "origem": f"local:{reuso_dir}" if reusado else "remoto",
                "url": url,
            }
            if anterior:
                registros[stem]["versao_anterior"] = anterior
        finally:
            parcial.unlink(missing_ok=True)

    if alterado:
        manifesto["atualizado_em"] = agora
        tmp = manifesto_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, manifesto_path)
    return manifesto


def _chave_json_resultados(uf: str, turno: int = 2) -> str:
    cd = "6258" if turno == 2 else "6257"
    return f"{uf.lower()}-c0001-e00{cd}-u"


def _url_json_resultados(uf: str, turno: int = 2) -> str:
    cd = "6258" if turno == 2 else "6257"
    stem = _chave_json_resultados(uf, turno)
    return f"https://resultados.tse.jus.br/oficial/ele2026/{cd}/dados/{uf.lower()}/{stem}.json"


def adquirir_json_resultados(
    project_root: Path, ufs: tuple[str, ...], turno: int = 2
) -> dict:
    """Adquire os JSONs oficiais consolidados do portal Resultados (`*-c0001-e006258-u.json`)
    para `docs/sources/official_totals/` com validação de consistência e manifesto próprio (`R20-1`).
    """
    projeto = Path(project_root)
    fontes = projeto / FONTES_DIR
    tmp_dir = fontes / ".tmp"
    fontes.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    manifesto_path = projeto / MANIFEST_REL
    if manifesto_path.exists():
        manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    else:
        manifesto = {"manifest_version": "1.0", "registros": {}}
    registros = manifesto["registros"]
    cfg = load_config(projeto / "config" / "analysis.toml")
    nr_lula, nr_flavio = election_numbers(cfg)
    agora = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    alterado = False

    for uf in ufs:
        stem = _chave_json_resultados(uf, turno)
        nome = f"{stem}.json"
        url = _url_json_resultados(uf, turno)
        if _url_catalogada(url, projeto) is False:
            raise ReferenciaInvalida(
                f"{uf}/T{turno}: {url} ausente do snapshot do catálogo A0; "
                "não adquirir sem evidência de catálogo"
            )
        registro = registros.get(stem)
        destino = fontes / nome
        if registro and destino.exists() and _hash(destino) == registro["sha256"]:
            continue
        alterado = True
        parcial = tmp_dir / f"{nome}.parcial"
        try:
            _, headers = _baixar(url, parcial)
            try:
                dados = json.loads(parcial.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ReferenciaInvalida(f"{uf}/T{turno}: JSON inválido ({e})")
            m, data_corte = _metricas_json_resultados(dados, uf, turno, nr_lula, nr_flavio)
            sha = _hash(parcial)
            anterior = None
            if registro and registro.get("sha256") != sha and destino.exists():
                guardado = fontes / f"{Path(nome).stem}__{registro['sha256'][:12]}{Path(nome).suffix}"
                os.replace(destino, guardado)
                anterior = {k: registro.get(k) for k in
                            ("sha256", "bytes", "baixado_em", "last_modified_remoto")}
                anterior["arquivo"] = guardado.name
            elif registro and registro.get("sha256") == sha:
                anterior = registro.get("versao_anterior")
            os.replace(parcial, destino)
            registros[stem] = {
                "arquivo": nome,
                "bytes": destino.stat().st_size,
                "baixado_em": agora,
                "conteudo": {
                    "eleicao": dados.get("ele"),
                    "turno": int(turno),
                    "uf": uf,
                    "data_corte": data_corte,
                    "qt_aptos": m["qt_aptos"],
                    "qt_comparecimento": m["qt_comparecimento"],
                },
                "sha256": sha,
                "etag_remoto": headers.get("etag"),
                "last_modified_remoto": headers.get("last-modified"),
                "origem": "remoto",
                "url": url,
            }
        finally:
            parcial.unlink(missing_ok=True)

    if alterado:
        manifesto["atualizado_em"] = agora
        tmp = manifesto_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, manifesto_path)
    return manifesto


def _extrair_turno_de_pdf(
    pdf: bytes, uf: str, turno: int, registro: dict, nr_lula: int, nr_flavio: int
) -> list[dict]:
    paginas = extrair_paginas(pdf)
    m = _metricas_resumo(paginas)
    faltantes = [k for k in ("qt_aptos", "qt_comparecimento", "qt_abstencoes",
                             "qt_votos_brancos", "qt_votos_nulos",
                             "qt_votos_nulos_tecnico", "qt_votos_nulos_total",
                             "qt_concorrentes", "qt_anulados",
                             "qt_anulados_sub_judice") if k not in m]
    if faltantes:
        raise ReferenciaInvalida(f"{uf}/T{turno}: resumo sem {faltantes}")
    m.setdefault("qt_aptos_nao_instaladas", 0)
    problemas = _consistencia(m)
    if problemas:
        raise ReferenciaInvalida(f"{uf}/T{turno}: inconsistência no relatório: {problemas}")
    m["qt_lula"] = _metricas_anexo_iv(paginas, nr_lula)
    m["qt_flavio"] = _metricas_anexo_iv(paginas, nr_flavio)
    if m["qt_lula"] + m["qt_flavio"] > m["qt_concorrentes"]:
        raise ReferenciaInvalida(f"{uf}/T{turno}: lula+flavio excede concorrentes")
    data_corte = _data_emissao(paginas)
    base = {"nr_turno": int(turno), "sg_uf": uf, "fonte_tipo": FONT_TIPO,
            "url": registro["url"], "sha256_fonte": registro["sha256"],
            "data_corte": data_corte}
    return [{**base, "metrica": metrica, "valor": m[metrica]}
            for metrica in ("qt_aptos", "qt_comparecimento", "qt_abstencoes",
                            "qt_votos_brancos", "qt_votos_nulos", "qt_lula", "qt_flavio")]


def extrair_referencia(
    project_root: Path, ufs: tuple[str, ...], turnos: tuple[int, ...] | None = None
) -> list[dict]:
    """Lê os Relatórios e/ou JSONs oficiais já adquiridos (manifesto da referência) e devolve as linhas."""
    projeto = Path(project_root)
    manifesto = json.loads((projeto / MANIFEST_REL).read_text(encoding="utf-8"))["registros"]
    cfg = load_config(projeto / "config" / "analysis.toml")
    nr_lula, nr_flavio = election_numbers(cfg)
    turnos_pedidos = turnos or (1, 2)
    exigir_t2 = turnos is not None and (2 in turnos)

    linhas_csv: list[dict] = []
    for uf in ufs:
        chave = _chave(uf)
        registro = manifesto.get(chave)
        if 1 in turnos_pedidos:
            if registro is None:
                raise ReferenciaInvalida(
                    f"{uf}: {chave} sem registro no manifesto da referência; "
                    "rodar adquirir() antes")
            zip_path = projeto / FONTES_DIR / registro["arquivo"]
            with zipfile.ZipFile(zip_path) as z:
                pdf_t1 = _extrair_pdf(z, uf, turno=1)
            linhas_csv.extend(_extrair_turno_de_pdf(pdf_t1, uf, 1, registro, nr_lula, nr_flavio))

        if 2 in turnos_pedidos:
            extraido_t2 = False
            if registro is not None:
                zip_path = projeto / FONTES_DIR / registro["arquivo"]
                if zip_path.exists():
                    with zipfile.ZipFile(zip_path) as z:
                        if _tem_pdf_turno(z, uf, turno=2):
                            pdf_t2 = _extrair_pdf(z, uf, turno=2)
                            linhas_csv.extend(
                                _extrair_turno_de_pdf(pdf_t2, uf, 2, registro, nr_lula, nr_flavio)
                            )
                            extraido_t2 = True
            if not extraido_t2:
                chave_j2 = _chave_json_resultados(uf, turno=2)
                reg_j2 = manifesto.get(chave_j2)
                if reg_j2 is not None:
                    json_path = projeto / FONTES_DIR / reg_j2["arquivo"]
                    dados_j2 = json.loads(json_path.read_text(encoding="utf-8"))
                    m_j2, data_corte_j2 = _metricas_json_resultados(dados_j2, uf, 2, nr_lula, nr_flavio)
                    base_j2 = {
                        "nr_turno": 2, "sg_uf": uf, "fonte_tipo": FONT_TIPO,
                        "url": reg_j2["url"], "sha256_fonte": reg_j2["sha256"],
                        "data_corte": data_corte_j2,
                    }
                    for metrica in ("qt_aptos", "qt_comparecimento", "qt_abstencoes",
                                    "qt_votos_brancos", "qt_votos_nulos", "qt_lula", "qt_flavio"):
                        linhas_csv.append({**base_j2, "metrica": metrica, "valor": m_j2[metrica]})
                    extraido_t2 = True
            if not extraido_t2 and exigir_t2:
                raise ReferenciaInvalida(
                    f"{uf}/T2: sem PDF de 2º turno no ZIP nem JSON oficial registrado em {MANIFEST_REL}"
                )
    return linhas_csv


def gravar_referencia(linhas_csv: list[dict], project_root: Path) -> Path:
    """Grava o CSV de referência de forma atômica (tmp + promoção)."""
    destino = Path(project_root) / SAIDA_REL
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUNAS, lineterminator="\n")
        escritor.writeheader()
        for linha in linhas_csv:
            escritor.writerow(linha)
    os.replace(tmp, destino)
    return destino


def extrair_anexo_v(project_root: Path, ufs: tuple[str, ...]) -> list[dict]:
    """Lê o Anexo V dos Relatórios já adquiridos e devolve as linhas."""
    projeto = Path(project_root)
    manifesto = json.loads((projeto / MANIFEST_REL).read_text(encoding="utf-8"))["registros"]
    linhas_csv: list[dict] = []
    for uf in ufs:
        chave = _chave(uf)
        registro = manifesto.get(chave)
        if registro is None:
            raise ReferenciaInvalida(
                f"{uf}: {chave} sem registro no manifesto da referência; "
                "rodar adquirir() antes")
        zip_path = projeto / FONTES_DIR / registro["arquivo"]
        with zipfile.ZipFile(zip_path) as z:
            for t_av in (1, 2):
                if t_av == 1 or _tem_pdf_turno(z, uf, turno=t_av):
                    pdf = _extrair_pdf(z, uf, turno=t_av)
                    paginas = extrair_paginas(pdf)
                    data_corte = _data_emissao(paginas)
                    ocorrencias = _ocorrencias_anexo_v(paginas, uf, turno=t_av)
                    for item in ocorrencias:
                        linhas_csv.append({
                            **item,
                            "url": registro["url"],
                            "sha256_fonte": registro["sha256"],
                            "data_corte": data_corte,
                        })
    return linhas_csv


def gravar_anexo_v(linhas_csv: list[dict], project_root: Path) -> Path:
    """Grava o CSV do Anexo V de forma atômica (tmp + promoção)."""
    destino = Path(project_root) / SAIDA_ANEXO_V_REL
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUNAS_ANEXO_V, lineterminator="\n")
        escritor.writeheader()
        for linha in linhas_csv:
            escritor.writerow(linha)
    os.replace(tmp, destino)
    return destino


def main(ufs: tuple[str, ...] = ("AC", "RS", "MG"),
         reuso_dir: Path | None = None) -> int:
    from br2026.contract import PROJECT_ROOT  # import tardio (CLI)
    if reuso_dir is None:
        reuso_dir = PROJECT_ROOT / "data" / "raw" / ".reuso"
    adquirir(PROJECT_ROOT, ufs, reuso_dir=reuso_dir)
    if all(_url_catalogada(_url_json_resultados(uf, 2), PROJECT_ROOT) is True for uf in ufs):
        adquirir_json_resultados(PROJECT_ROOT, ufs, turno=2)
    linhas_csv = extrair_referencia(PROJECT_ROOT, ufs)
    destino = gravar_referencia(linhas_csv, PROJECT_ROOT)
    linhas_av = extrair_anexo_v(PROJECT_ROOT, ufs)
    destino_av = gravar_anexo_v(linhas_av, PROJECT_ROOT)
    print(f"{len(linhas_csv)} linhas gravadas em {destino}; "
          f"{len(linhas_av)} linhas de Anexo V em {destino_av}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
