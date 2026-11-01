"""Aquisição determinística de brutos (frente A, marco M2).

Regras desta etapa, derivadas do handoff `07_CONTINUACAO_OPENCODE_MIMO.md`:

- **Nenhuma URL é inventada.** Cada família tem um padrão fixo de URL que consta
  do snapshot do catálogo A0 (`docs/sources/remote_snapshot.json`, coletado via
  CKAN `package_show`). URL que não aparece no snapshot ⇒ **bloqueio explícito**,
  nunca tentativa. Ausência de turno é `AUSENTE_EM_26_10` (catálogo), não 404 de
  nome com timestamp inventado.
- **Download com timeout e tentativas limitadas** (`TIMEOUT_S`, `TENTATIVAS`);
  resposta HTML ou corpo truncado (bytes < `Content-Length`) é erro, e nada é
  promovido. Promoção é atômica (`os.replace` no mesmo volume).
- **Todo arquivo promovido é validado por conteúdo**: ZIP legível, membro
  esperado presente, colunas obrigatórias no cabeçalho, ano 2026 e turnos
  dentro do declarado para a família (leitura de amostra, Latin-1, `;`).
- **`data/raw/manifest.json`** registra por arquivo: URL, SHA-256, bytes,
  `Last-Modified`/`ETag` remotos, origem (remoto × reuso local), verificação de
  versão usada, fatos de conteúdo, tempo e pico de memória. Versão diferente do
  mesmo conteúdo **gera registro novo** (`<stem>__<sha12>.zip`) com
  `versao_anterior`; nada é sobrescrito silenciosamente.
- **Reuso de cópia local** (ex.: `SOURCE_ROOT/data/01_raw`) só com validação de
  conteúdo **e** versão contra o remoto (ETag/MD5 quando o servidor publica MD5
  puro; senão igualdade de tamanho). Diferença ⇒ download da versão remota e
  registro novo.
- `uf='BR'` adquire as famílias nacionais; `'ZZ'` o exterior. Família por UF não
  tem versão nacional no catálogo (28 unidades + ZZ), então `uf='BR'` a pula com
  aviso. Turnos: as famílias de votação/BU/detalhe de 2026 ainda são só T1 no
  catálogo; rodar com `turno=2` devolve bloqueios explícitos para elas, e
  adquire as que já cobrem os dois turnos (perfil e eleitorado local).

A CLI chama `run(uf, turno, project_root, force=...)`; `reuso_dir` é opcional e
não altera a assinatura do contrato (`br2026.interfaces.Ingest`).
"""
from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from br2026.interfaces import StageResult

CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
SNAPSHOT_REL = Path("docs") / "sources" / "remote_snapshot.json"
MANIFEST_REL = Path("data") / "raw" / "manifest.json"
MANIFEST_VERSION = "1.0"
DATA_CATALOGO = "26_10"          # data da consulta ao catálogo CKAN (A0)
USER_AGENT = "br2026-ingest/1.0 (pesquisa; frente A)"

TIMEOUT_S = 120.0                # timeout por requisição
TENTATIVAS = 3                   # tentativas de download (erros de rede/corpo)
PAUSA_TENTATIVA_S = 2.0          # espera linear entre tentativas
TAMANHO_BLOCO = 1 << 20          # 1 MiB por bloco lido
N_LINHAS_AMOSTRA = 50            # linhas lidas do CSV para validar ano/turno


class IngestError(RuntimeError):
    """Falha de aquisição com causa legível (entra em `StageResult.bloqueios`)."""


class ConteudoInvalido(IngestError):
    """Resposta recebida mas o conteúdo não é o arquivo oficial esperado."""


class DownloadInterrompido(IngestError):
    """Corpo menor que `Content-Length`, resposta vazia ou rede instável."""


@dataclass(frozen=True)
class Familia:
    """Família de arquivo oficial: nome, URL, membro e validação de conteúdo."""
    fonte: str
    escopo: str                       # "nacional" | "uf"
    turnos: tuple[int, ...]           # turnos declarados no conteúdo (vazio = sem coluna de turno)
    nome: str                         # nome do arquivo; "{uf}" quando escopo "uf"
    url: str                          # URL fixa do catálogo; "{uf}" quando escopo "uf"
    membro: str                       # template do membro; "{uf}"
    colunas: tuple[str, ...]          # colunas obrigatórias no cabeçalho (vazio em documento)
    campo_ano: str | None             # "ANO_ELEICAO" | "AA_ELEICAO"; None em documento
    campo_turno: str | None           # coluna de turno, se existir
    tipo: str = "csv"                 # "csv" | "documento" (PDF oficial, texto posicional)
    membro_padrao: str | None = None  # regex do membro quando o nome não é template fixo
    texto_esperado: tuple[str, ...] = ()  # marcadores literais exigidos em documento
    # cargo cujo turno é exigido no conteúdo e membro preferido (UF ou BR). Nos consolidados de
    # votação o presidente fica no membro `_BR`; o membro da UF traz só cargos estaduais
    # (conferido em 27/10: AC tem T2 de governador no membro AC e T2 de presidente só no BR).
    cargo_turno: str | None = None
    membro_preferido: tuple[str, ...] = ("{uf}", "BR", "BRASIL")


FAMILIAS: tuple[Familia, ...] = (
    Familia(
        fonte="perfil_eleitor_secao", escopo="uf", turnos=(),
        nome="perfil_eleitor_secao_2026_{uf}.zip",
        url=f"{CDN}/perfil_eleitor_secao/perfil_eleitor_secao_2026_{{uf}}.zip",
        membro="perfil_eleitor_secao_2026_{uf}.csv",
        colunas=("AA_ELEICAO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                 "CD_GENERO", "CD_FAIXA_ETARIA", "CD_GRAU_ESCOLARIDADE",
                 "CD_ESTADO_CIVIL", "CD_RACA_COR", "QT_ELEITORES"),
        campo_ano="AA_ELEICAO", campo_turno=None,
    ),
    Familia(
        fonte="consulta_cand", escopo="nacional", turnos=(1,),
        nome="consulta_cand_2026.zip",
        url=f"{CDN}/consulta_cand/consulta_cand_2026.zip",
        membro="consulta_cand_2026_{uf}.csv",
        # não há CD_MUNICIPIO: a abrangência é por UE (SG_UE/NM_UE), não município
        colunas=("ANO_ELEICAO", "NR_TURNO", "CD_ELEICAO", "SG_UF", "SG_UE",
                 "CD_CARGO", "SQ_CANDIDATO", "NR_CANDIDATO", "NM_CANDIDATO",
                 "CD_SITUACAO_CANDIDATURA"),
        campo_ano="ANO_ELEICAO", campo_turno="NR_TURNO",
    ),
    Familia(
        fonte="eleitorado_local_votacao", escopo="nacional", turnos=(1, 2),
        nome="eleitorado_local_votacao_2026.zip",
        url=f"{CDN}/eleitorado_locais_votacao/eleitorado_local_votacao_2026.zip",
        membro="eleitorado_local_votacao_2026_{uf}.csv",
        colunas=("AA_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
                 "NR_SECAO", "CD_TIPO_SECAO_AGREGADA", "NR_SECAO_PRINCIPAL",
                 "NR_LOCAL_VOTACAO_ORIGINAL", "QT_ELEITOR_SECAO"),
        campo_ano="AA_ELEICAO", campo_turno="NR_TURNO",
    ),
    Familia(
        fonte="votacao_secao", escopo="nacional", turnos=(1,),
        nome="votacao_secao_2026_BR.zip",
        url=f"{CDN}/votacao_secao/votacao_secao_2026_BR.zip",
        membro="votacao_secao_2026_{uf}.csv",
        colunas=("ANO_ELEICAO", "NR_TURNO", "CD_ELEICAO", "SG_UF", "CD_MUNICIPIO",
                 "NR_ZONA", "NR_SECAO", "CD_CARGO", "NR_VOTAVEL", "QT_VOTOS",
                 "SQ_CANDIDATO"),
        campo_ano="ANO_ELEICAO", campo_turno="NR_TURNO",
        cargo_turno="1", membro_preferido=("BR", "{uf}", "BRASIL"),
    ),
    Familia(
        fonte="detalhe_votacao_secao", escopo="nacional", turnos=(1,),
        nome="detalhe_votacao_secao_2026.zip",
        url=f"{CDN}/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip",
        membro="detalhe_votacao_secao_2026_{uf}.csv",
        colunas=("ANO_ELEICAO", "NR_TURNO", "CD_ELEICAO", "SG_UF", "CD_MUNICIPIO",
                 "NR_ZONA", "NR_SECAO", "CD_CARGO", "QT_APTOS", "QT_COMPARECIMENTO",
                 "QT_ABSTENCOES", "QT_VOTOS_NOMINAIS", "QT_VOTOS_BRANCOS",
                 "QT_VOTOS_NULOS", "QT_VOTOS_LEGENDA", "QT_VOTOS_ANULADOS_APU_SEP",
                 "ST_SECAO_INSTALADA", "ST_SECAO_ANULADA", "DS_ORIGEM_VOTO"),
        campo_ano="ANO_ELEICAO", campo_turno="NR_TURNO",
        cargo_turno="1", membro_preferido=("BR", "{uf}", "BRASIL"),
    ),
    # --------------------------------------------------------------------- #
    # Piloto AC/RS/MG (ciclo 26/10/2026). Em 2026 o TSE separou os datasets:
    # votacao/detalhe_munzona cobrem só CD_ELEICAO 6259 (estaduais) e a
    # presidencial (6257) não está lá. A fonte compatível com
    # RESULTADO_DIVULGADO_TSE é o Relatório de Totalização (PDF) por UF —
    # ele é referência do aceite, não insumo do staging, e por isso tem
    # aquisição/manifesto próprios em `br2026.ingest.relatorio_totalizacao`
    # (docs/sources/official_totals/), fora de data/raw/manifest.json.
    # --------------------------------------------------------------------- #
    Familia(
        fonte="bweb", escopo="uf", turnos=(1,),
        nome="bweb_1t_{uf}_051020261403.zip",
        url=(f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/"
             "buweb/bweb_1t_{uf}_051020261403.zip"),
        membro="bweb_1t_{uf}_051020261403.csv",
        colunas=("ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
                 "NR_SECAO", "QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES",
                 "DT_BU_RECEBIDO", "DT_ABERTURA", "DT_ENCERRAMENTO",
                 "DT_EMISSAO_BU", "DS_SECOES_AGREGADAS", "NR_URNA_EFETIVADA",
                 "NR_JUNTA_APURADORA", "NR_TURMA_APURADORA"),
        campo_ano="ANO_ELEICAO", campo_turno="NR_TURNO",
    ),
    Familia(
        fonte="correspondencia_esperada", escopo="uf", turnos=(1,),
        nome="CESP_1t_{uf}_041020261259.zip",
        url=(f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/"
             "correspesp/CESP_1t_{uf}_041020261259.zip"),
        # o ZIP traz csec_ (por seção) e ccont_ (controle, sem NR_SECAO);
        # o membro útil é o csec_, escolhido pelo prefixo
        membro="csec_1t_{uf}_041020261259.csv",
        colunas=("AA_ELEICAO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                 "NR_URNA_ESPERADA", "CD_CARGA_URNA_ESPERADA",
                 "DT_CARGA_URNA_ESPERADA", "ST_CORRESP_ALTERADA"),
        campo_ano="AA_ELEICAO", campo_turno=None,
    ),
    Familia(
        fonte="correspondencia_efetivada", escopo="uf", turnos=(1,),
        nome="CEFT_1t_{uf}_051020261049.zip",
        url=(f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/"
             "correspefet/CEFT_1t_{uf}_051020261049.zip"),
        membro="ceft_1t_{uf}_051020261049.csv",
        colunas=("AA_ELEICAO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                 "SQ_CORRESPONDENCIA_ESPERADA", "NR_URNA_ESPERADA",
                 "SQ_CORRESPONDENCIA_EFETIVADA", "NR_URNA_EFETIVADA",
                 "CD_ORIGEM_VOTO", "DS_ORIGEM_VOTO", "TP_DIVERGENCIA"),
        campo_ano="AA_ELEICAO", campo_turno=None,
    ),
)


# --------------------------------------------------------------------------- #
# utilitários                                                                  #
# --------------------------------------------------------------------------- #


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(caminho: Path, algoritmo: str = "sha256") -> str:
    h = hashlib.new(algoritmo)
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(TAMANHO_BLOCO), b""):
            h.update(bloco)
    return h.hexdigest()


def _pico_memoria_kb() -> int:
    """Pico de memória (working set) do processo, em KiB — medido no sistema.

    No Windows usa `GetProcessMemoryInfo` via ctypes; `argtypes`/`restype` são
    fixados porque, sem eles, ctypes trunca o handle de 64 bits e a chamada falha.
    """
    if sys.platform == "win32":
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                               wintypes.DWORD]
        contador = PROCESS_MEMORY_COUNTERS()
        contador.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(contador), contador.cb):
            return int(contador.PeakWorkingSetSize // 1024)
        return 0
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if sys.platform == "darwin" else rss // 1024)


def _url_da_familia(familia: Familia, uf: str) -> str:
    """URL da família para a UF. Padrões fixos, todos presentes no snapshot do catálogo."""
    return familia.url.format(uf=uf)


def _carregar_snapshot(projeto: Path) -> dict | None:
    caminho = projeto / SNAPSHOT_REL
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _url_catalogada(url: str, projeto: Path) -> bool | None:
    """True/False se a URL consta (status 200) no snapshot do catálogo; None sem snapshot."""
    snap = _carregar_snapshot(projeto)
    if snap is None:
        return None
    return any(h.get("url") == url and h.get("status") == 200 for h in snap.get("heads", []))


_CORTE_T2_UTC = datetime(2026, 10, 26, 15, 0, 0, tzinfo=timezone.utc)


def _head_tem_evidencia_t2(head: dict) -> bool:
    """Verifica se um registro `head` do snapshot anuncia suporte ao 2º turno."""
    turnos_decl = head.get("turnos")
    if isinstance(turnos_decl, list) and (2 in turnos_decl or "2" in turnos_decl):
        return True
    lm = head.get("last_modified")
    if isinstance(lm, str) and lm.strip():
        try:
            dt = parsedate_to_datetime(lm.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= _CORTE_T2_UTC:
                return True
        except (ValueError, TypeError):
            pass
    return False


def _resolver_recurso_familia(
    familia: Familia, uf: str, turno: int, projeto: Path, *, force: bool = False
) -> Familia | None:
    """Resolve a definição efetiva da família para `(uf, turno)` via catálogo/força (`R20-1`).

    Devolve `Familia` ajustada quando o turno é suportado pelo catálogo ou por `force=True`,
    ou `None` quando o turno continua ausente do catálogo.
    """
    if not familia.turnos or turno in familia.turnos:
        return familia
    if turno != 2:
        return None

    snap = _carregar_snapshot(projeto)
    heads = [h for h in (snap.get("heads", []) if isinstance(snap, dict) else [])
             if isinstance(h, dict) and h.get("status") == 200]
    url_padrao = _url_da_familia(familia, uf)

    # 1) Famílias com URL específica por turno no catálogo (bweb_2t, CESP_2t, CEFT_2t ou cs.json)
    if familia.fonte in ("bweb", "correspondencia_esperada", "correspondencia_efetivada"):
        padroes_2t = {
            "bweb": (
                re.compile(rf".*/(bweb_2t_{uf}_\d+\.zip)$", re.IGNORECASE),
                lambda stem: f"{stem}.csv",
                "csv",
            ),
            "correspondencia_esperada": (
                re.compile(rf".*/(CESP_2t_{uf}_\d+\.zip)$", re.IGNORECASE),
                lambda stem: re.sub(r"^CESP_", "csec_", stem, flags=re.IGNORECASE) + ".csv",
                "csv",
            ),
            "correspondencia_efetivada": (
                re.compile(rf".*/(CEFT_2t_{uf}_\d+\.zip)$", re.IGNORECASE),
                lambda stem: re.sub(r"^CEFT_", "ceft_", stem, flags=re.IGNORECASE) + ".csv",
                "csv",
            ),
        }
        rx, fn_membro, tipo_arq = padroes_2t[familia.fonte]
        for h in heads:
            u = str(h.get("url") or "")
            m = rx.match(u)
            if m:
                nome_2t = m.group(1)
                stem_2t = nome_2t[:-4]
                return replace(
                    familia,
                    turnos=(2,),
                    nome=nome_2t,
                    url=u,
                    membro=fn_membro(stem_2t),
                    tipo=tipo_arq,
                )
        # Revisão B (handoff 22): o índice `arquivo-urna/.../{uf}-p003221-cs.json` do portal
        # Resultados lista seções e datas, sem nenhum campo de agregação (conferido no AC em
        # 27/10: 2.411 seções só com ns/da/ha). Não é correspondência efetivada e não é usado.

    # Sem coluna de turno (CESP/CEFT), o conteúdo não prova o turno: o arquivo do 1º turno não
    # pode ser reaproveitado como 2º turno, nem por evidência de catálogo nem por --force.
    if familia.campo_turno is None:
        return None

    # 2) URL padrão da família com evidência de T2 no snapshot ou execução forçada (--force)
    for h in heads:
        if h.get("url") == url_padrao and _head_tem_evidencia_t2(h):
            return replace(familia, turnos=tuple(sorted(set(familia.turnos) | {2})))

    if force:
        return replace(familia, turnos=tuple(sorted(set(familia.turnos) | {2})))

    return None


# --------------------------------------------------------------------------- #


def _baixar_uma(url: str, destino: Path) -> tuple[int, dict[str, str]]:
    """Uma tentativa de download. Corpo truncado ou HTML ⇒ erro (nada promovido)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        ctype = headers.get("content-type", "")
        if ctype.startswith("text/html"):
            raise ConteudoInvalido(f"{url}: content-type '{ctype}' no lugar do arquivo binário")
        esperado = headers.get("content-length")
        recebidos = 0
        with open(destino, "wb") as fh:
            while True:
                bloco = resp.read(TAMANHO_BLOCO)
                if not bloco:
                    break
                fh.write(bloco)
                recebidos += len(bloco)
        if recebidos == 0:
            raise ConteudoInvalido(f"{url}: resposta vazia")
        if esperado is not None and recebidos != int(esperado):
            raise DownloadInterrompido(
                f"{url}: corpo interrompido — recebidos {recebidos:,} de {int(esperado):,} bytes")
    return recebidos, headers


def _baixar(url: str, destino: Path) -> tuple[int, dict[str, str]]:
    """Download com tentativas limitadas. Erros de rede/corpo são repetidos;
    conteúdo invalidamente formatado não é (repetir não muda a resposta)."""
    ultimo: Exception | None = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return _baixar_uma(url, destino)
        except ConteudoInvalido:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, DownloadInterrompido) as e:
            ultimo = e
            if tentativa < TENTATIVAS:
                time.sleep(PAUSA_TENTATIVA_S * tentativa)
    raise DownloadInterrompido(f"{url}: {TENTATIVAS} tentativas esgotadas; último erro: {ultimo}")


def _head(url: str) -> dict[str, str]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return {k.lower(): v for k, v in resp.headers.items()}


def _versao_confere(local: Path, headers: dict[str, str]) -> tuple[bool, str]:
    """Compara cópia local com o remoto (HEAD). ETag/MD5 puro é comparação exata;
    sem ele, só igualdade de tamanho (marcado como checagem fraca)."""
    etag = (headers.get("etag") or "").strip('"')
    if re.fullmatch(r"[0-9a-fA-F]{32}", etag):
        return _hash(local, "md5").lower() == etag.lower(), "etag_md5"
    tamanho_remoto = headers.get("content-length")
    if tamanho_remoto is not None:
        return int(tamanho_remoto) == local.stat().st_size, "tamanho"
    return False, "indeterminavel"


def _texto_pdf_plano(pdf: bytes) -> str:
    """Texto acessível do PDF sem dependência externa: descomprime streams (zlib)
    e devolve os literais dos operadores de texto em latin-1, mais o cabeçalho.

    Suficiente para marcadores de identificação (título, Sistema, UF). A
    extração posicional com coordenadas vive em `br2026.ingest.pdf_texto` e é
    usada na leitura de métricas, não aqui.
    """
    partes = [pdf[:2000].decode("latin-1", "replace")]
    for m in re.finditer(rb"stream\r?\n", pdf):
        inicio = m.end()
        fim = pdf.find(b"endstream", inicio)
        if fim < 0:
            continue
        bruto = pdf[inicio:fim]
        dados = None
        for tentativa in (bruto, bruto.rstrip(b"\r\n")):
            try:
                dados = zlib.decompress(tentativa)
                break
            except zlib.error:
                continue
        if dados:
            partes.append(dados.decode("latin-1", "replace"))
    return "\n".join(partes)


def _padrao_membro_turno(padrao: str, turno: int) -> str:
    """Ajusta o padrão de documento por turno: T1 = eleição 6257, T2 = 6258 (conferido no portal)."""
    if turno == 2:
        return padrao.replace("6257", "6258").replace("_T1_", "_T2_")
    return padrao


def _escolher_membro(nomes: list[str], familia: Familia, uf: str, turno: int = 1) -> str | None:
    """Membro a inspecionar: UF pedida > BR (nacional) > BRASIL > nome exato.

    Quando a família declara `membro_padrao` (regex), o nome do membro não é um
    template fixo — ex.: o Relatório de totalização vem como
    ``6257_AC_ACRE_2026_T1_PRESIDENTE.pdf``. Nesse caso vale o primeiro membro
    que casa com o padrão já restrito à UF pedida.
    """
    if familia.membro_padrao:
        padrao_uf = re.compile(_padrao_membro_turno(familia.membro_padrao, turno).format(uf=uf))
        candidatos = sorted(n for n in nomes if padrao_uf.fullmatch(n))
        if candidatos:
            return candidatos[0]
        return None
    for sufixo in familia.membro_preferido:
        nome = familia.membro.format(uf=sufixo.format(uf=uf))
        if nome in nomes:
            return nome
    return None


def _validar_conteudo(caminho: Path, familia: Familia, uf: str, turno: int) -> dict:
    """Valida o arquivo adquirido antes da promoção. Levanta `ConteudoInvalido`
    com a causa; devolve os fatos observados para o manifesto."""
    with open(caminho, "rb") as fh:
        inicio = fh.read(200)
    if inicio[:2] != b"PK":
        texto = inicio.decode("latin-1", "replace").lower()
        if "<html" in texto or "<!doctype" in texto:
            raise ConteudoInvalido(f"{familia.fonte}: recebido HTML no lugar do ZIP")
        raise ConteudoInvalido(f"{familia.fonte}: conteúdo não é ZIP (início: {inicio[:40]!r})")
    try:
        z = zipfile.ZipFile(caminho)      # BadZipFile se truncado/central directory corrompido
    except zipfile.BadZipFile as e:
        raise ConteudoInvalido(f"{familia.fonte}: ZIP ilegível ou truncado ({e})")
    with z:
        nomes = z.namelist()
        membro = _escolher_membro(nomes, familia, uf, turno)
        if membro is None:
            esperado = (_padrao_membro_turno(familia.membro_padrao, turno).format(uf=uf)
                        if familia.membro_padrao else familia.membro.format(uf=uf))
            raise ConteudoInvalido(
                f"{familia.fonte}: ZIP sem o membro esperado "
                f"({esperado}); primeiros membros: {nomes[:5]}")
        if familia.tipo == "documento":
            conteudo = z.read(membro)
            if not conteudo.startswith(b"%PDF"):
                raise ConteudoInvalido(
                    f"{familia.fonte}: {membro} não é PDF (início: {conteudo[:20]!r})")
            texto_pdf = _texto_pdf_plano(conteudo)
            ausentes = [s for s in familia.texto_esperado if s not in texto_pdf]
            if ausentes:
                raise ConteudoInvalido(
                    f"{familia.fonte}: {membro} sem marcadores {ausentes} "
                    "(não é o relatório oficial esperado)")
            return {
                "membro_validado": membro,
                "membros_zip": len(nomes),
                "bytes_pdf": len(conteudo),
                "marcadores": len(familia.texto_esperado),
                "turnos_observados": [str(turno)] if familia.membro_padrao else list(familia.turnos),
            }
        with z.open(membro) as fh:
            texto = io.TextIOWrapper(fh, encoding="latin-1", newline="")
            colunas = [c.strip().strip('"') for c in texto.readline().strip().split(";")]
            faltantes = [c for c in familia.colunas if c not in colunas]
            if faltantes:
                raise ConteudoInvalido(
                    f"{familia.fonte}: colunas obrigatórias ausentes em {membro}: {faltantes}")
            idx_ano = colunas.index(familia.campo_ano)
            idx_turno = colunas.index(familia.campo_turno) if familia.campo_turno else None
            anos: set[str] = set()
            turnos: set[str] = set()
            n_amostra = 0
            for linha in texto:
                if not linha.strip():
                    continue
                campos = next(csv.reader([linha.strip()], delimiter=";", quotechar='"'))
                anos.add(campos[idx_ano].strip())
                if idx_turno is not None:
                    turnos.add(campos[idx_turno].strip())
                n_amostra += 1
                if n_amostra >= N_LINHAS_AMOSTRA:
                    break
        # Em arquivos consolidados multi-turno (ex.: votacao_secao, detalhe_votacao_secao),
        # o 1º turno pode ocupar as primeiras N_LINHAS_AMOSTRA linhas e o 2º aparecer adiante.
        # A busca lê a coluna NR_TURNO de fato (handoff 22, revisão B): um marcador em bytes
        # casaria com qualquer outro campo igual ao turno e daria falso positivo.
        # Com `cargo_turno`, o turno só conta se houver linha do cargo e da UF pedidos: o T2 de
        # governador não é evidência do T2 de presidente.
        idx_cargo = colunas.index("CD_CARGO") if familia.cargo_turno and "CD_CARGO" in colunas else None
        idx_uf = colunas.index("SG_UF") if idx_cargo is not None and "SG_UF" in colunas else None
        if idx_cargo is not None:
            turnos.discard(str(turno))
        if idx_turno is not None and str(turno) not in turnos:
            with z.open(membro) as fh_bin:
                texto2 = io.TextIOWrapper(fh_bin, encoding="latin-1", newline="")
                texto2.readline()
                for campos in csv.reader(texto2, delimiter=";", quotechar='"'):
                    if len(campos) <= idx_turno or campos[idx_turno].strip() != str(turno):
                        continue
                    if idx_cargo is not None and campos[idx_cargo].strip() != familia.cargo_turno:
                        continue
                    if idx_uf is not None and uf not in ("BR",) and campos[idx_uf].strip() != uf:
                        continue
                    turnos.add(str(turno))
                    break
    if n_amostra == 0:
        raise ConteudoInvalido(f"{familia.fonte}: {membro} sem linhas de dados")
    if anos != {"2026"}:
        raise ConteudoInvalido(
            f"{familia.fonte}: {familia.campo_ano} observado {sorted(anos)} != 2026 "
            f"(amostra de {n_amostra} linhas)")
    if idx_turno is not None:
        permitidos = {str(t) for t in familia.turnos} | {str(turno)}
        fora = turnos - permitidos
        if fora:
            raise ConteudoInvalido(
                f"{familia.fonte}: {familia.campo_turno} observado {sorted(turnos)} fora do "
                f"declarado para a família {list(familia.turnos)}")
        if str(turno) not in turnos:
            raise ConteudoInvalido(
                f"{familia.fonte}: turno {turno} ausente no conteúdo de {membro} "
                f"({familia.campo_turno} observado: {sorted(turnos)})")
    return {
        "membro_validado": membro,
        "membros_zip": len(nomes),
        "colunas_obrigatorias": len(familia.colunas),
        "ano_observado": sorted(anos),
        "turnos_observados": sorted(turnos),
        "linhas_amostradas": n_amostra,
    }


def _carregar_manifesto(caminho: Path) -> dict:
    if not caminho.exists():
        return {"manifest_version": MANIFEST_VERSION, "atualizado_em": None, "registros": {}}
    try:
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise IngestError(f"manifesto ilegível ({e}): {caminho}")
    if not isinstance(manifesto.get("registros"), dict):
        raise IngestError(f"manifesto sem mapa 'registros': {caminho}")
    return manifesto


def _salvar_manifesto(caminho: Path, manifesto: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, caminho)


def run(uf: str, turno: int, project_root: Path, *, force: bool = False,
        reuso_dir: Path | None = None) -> StageResult:
    """Adquire os brutos oficiais para `uf`/`turno`, atualizando `data/raw/manifest.json`.

    `force=True` rebaixa mesmo com registro válido. `reuso_dir` permite adotar
    cópia local (ex.: `SOURCE_ROOT/data/01_raw`) após validar conteúdo e versão.
    """
    projeto = Path(project_root)
    uf = str(uf).strip().upper()
    turno = int(turno)
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise IngestError(f"UF inválida: {uf!r} (esperado par de letras: AC, RS, BR, ZZ)")
    if turno not in (1, 2):
        raise IngestError(f"turno inválido: {turno!r} (esperado 1 ou 2)")

    raw_dir = projeto / "data" / "raw"
    tmp_dir = raw_dir / ".tmp"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    manifesto = _carregar_manifesto(projeto / MANIFEST_REL)
    registros = manifesto["registros"]

    avisos: list[str] = []
    bloqueios: list[str] = []
    arquivos: list[Path] = []
    tot_bytes = n_downloads = n_reusos = 0
    t_total = time.perf_counter()

    for familia_base in FAMILIAS:
        if familia_base.escopo == "uf" and uf == "BR":
            avisos.append(
                f"{familia_base.fonte}: recurso por UF, sem versão nacional no catálogo "
                "(28 unidades + ZZ); adquirir chamando run(uf=<UF>, ...)")
            continue
        familia = _resolver_recurso_familia(familia_base, uf, turno, projeto, force=force)
        # turnos fora do catálogo: bloqueio explícito, sem tentar URL nova
        if familia is None:
            bloqueios.append(
                f"{familia_base.fonte}: turno {turno} não anunciado no catálogo CKAN "
                f"(turnos no conteúdo: {list(familia_base.turnos)}); AUSENTE_EM_{DATA_CATALOGO}, "
                "revalidar package_show antes de qualquer declaração de G2")
            continue

        nome = familia.nome.format(uf=uf)
        url = familia.url.format(uf=uf) if familia is not familia_base and familia.url != familia_base.url else _url_da_familia(familia, uf)
        catalogada = _url_catalogada(url, projeto)
        if catalogada is False:
            bloqueios.append(
                f"{familia.fonte}: {url} ausente do snapshot do catálogo A0; "
                "não adquirir sem evidência de catálogo (atualizar com a0_inventory.py remote)")
            continue
        if catalogada is None:
            avisos.append(f"{familia.fonte}: snapshot do catálogo ausente/ilegível; "
                          "URL não conferida contra o catálogo")

        ext = ".json" if nome.endswith(".json") else (".zip" if nome.endswith(".zip") else "")
        stem = nome[:-len(ext)] if ext else nome
        registro = registros.get(stem)

        # reexecução: registro vigente + arquivo presente + SHA-256 confere + cobre o turno ⇒ sem rede
        turnos_reg = {int(t) for t in (registro.get("turnos") or []) if str(t).isdigit()} if registro else set()
        turnos_obs = {int(t) for t in ((registro.get("conteudo") or {}).get("turnos_observados") or []) if str(t).isdigit()} if registro else set()
        cobre_turno = (not familia.turnos) or (turno in (turnos_reg | turnos_obs))
        if registro and not force and registro.get("url") == url and cobre_turno:
            existente = raw_dir / registro["arquivo"]
            if existente.exists() and _hash(existente) == registro["sha256"]:
                chave_uf = f"{uf}:{turno}"
                if (turno == 2 and familia.escopo == "nacional" and familia.cargo_turno
                        and chave_uf not in (registro.get("ufs_turno_validados") or [])):
                    # consolidado nacional já baixado para outra UF: o turno desta UF ainda não
                    # foi conferido no conteúdo; confere sem rede antes de reaproveitar
                    try:
                        _validar_conteudo(existente, familia, uf, turno)
                    except IngestError as e:
                        bloqueios.append(str(e))
                        continue
                    registro["ufs_turno_validados"] = sorted(
                        set(registro.get("ufs_turno_validados") or []) | {chave_uf})
                    avisos.append(f"{stem}: turno {turno} de {uf} conferido no conteúdo do arquivo já registrado")
                avisos.append(f"{stem}: reexecução — registro validado por SHA-256, sem download")
                arquivos.append(existente)
                n_reusos += 1
                continue

        parcial = tmp_dir / f"{nome}.parcial"
        t_fam = time.perf_counter()
        try:
            reusado = False
            origem = "remoto"
            metodo_versao = "nenhuma"
            headers: dict[str, str] = {}
            nbytes = 0

            # reuso de cópia local: só com conteúdo válido e versão conferida
            candidato = None
            if reuso_dir is not None and not force:
                cand = Path(reuso_dir) / nome
                if cand.exists():
                    candidato = cand
            if candidato is not None:
                try:
                    headers = _head(url)
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    headers = {}
                    avisos.append(f"{familia.fonte}: HEAD falhou ({type(e).__name__}); "
                                  "reuso local sem conferência contra o remoto")
                confere, metodo_versao = _versao_confere(candidato, headers)
                if confere:
                    shutil.copyfile(candidato, parcial)
                    reusado = True
                    origem = f"local:{candidato}"
                    nbytes = parcial.stat().st_size
                    if metodo_versao == "tamanho":
                        avisos.append(f"{familia.fonte}: reuso local por igualdade de tamanho "
                                      "(remoto sem ETag/MD5); conteúdo validado")
                else:
                    avisos.append(
                        f"{familia.fonte}: cópia local {candidato.name} difere do remoto "
                        "(versão diferente); baixando a versão remota e registrando-a")
            if not reusado:
                nbytes, headers = _baixar(url, parcial)
            # validação de conteúdo é obrigatória nos dois caminhos (reuso e download)
            fatos = _validar_conteudo(parcial, familia, uf, turno)

            sha = _hash(parcial)
            destino = raw_dir / nome
            sufixo_ext = ext or ".zip"
            if registro:
                if registro["sha256"] == sha:
                    destino = raw_dir / registro["arquivo"]
                else:
                    destino = raw_dir / f"{stem}__{sha[:12]}{sufixo_ext}"
                    avisos.append(
                        f"{stem}: conteúdo difere do registro anterior "
                        f"({registro['sha256'][:12]}… → {sha[:12]}…); registro novo, "
                        f"versão anterior preservada em {registro['arquivo']}")
            elif destino.exists() and _hash(destino) != sha:
                destino = raw_dir / f"{stem}__{sha[:12]}{sufixo_ext}"
                avisos.append(f"{stem}: arquivo pré-existente difere do remoto; mantido e "
                              f"baixado para {destino.name}")
            os.replace(parcial, destino)

            novo = {
                "arquivo": destino.name, "baixado_em": _agora_iso(), "bytes": nbytes,
                "conteudo": fatos, "escopo": familia.escopo, "etag_remoto": headers.get("etag"),
                "fonte": familia.fonte,
                "last_modified_remoto": headers.get("last-modified"),
                "origem": origem, "pico_memoria_kb": _pico_memoria_kb(),
                "reuso_local": reusado, "sha256": sha,
                "tempo_s": round(time.perf_counter() - t_fam, 3),
                "turnos": list(familia.turnos), "uf": uf, "url": url,
                "verificacao_versao": metodo_versao,
            }
            if familia.escopo == "nacional" and familia.cargo_turno:
                novo["ufs_turno_validados"] = [f"{uf}:{turno}"]
            if registro and registro["sha256"] == sha:
                # mesmo conteúdo: preserva a cadeia de versões em vez de apontar para si mesmo
                if registro.get("versao_anterior"):
                    novo["versao_anterior"] = registro["versao_anterior"]
                validados = set(registro.get("ufs_turno_validados") or []) | set(novo.get("ufs_turno_validados") or [])
                if validados:
                    novo["ufs_turno_validados"] = sorted(validados)
            elif registro:
                novo["versao_anterior"] = {k: registro.get(k) for k in
                                           ("sha256", "arquivo", "bytes", "baixado_em", "origem", "turnos")}
            registros[stem] = novo
            arquivos.append(destino)
            tot_bytes += nbytes
            n_reusos += 1 if reusado else 0
            n_downloads += 0 if reusado else 1
        except IngestError as e:
            bloqueios.append(str(e))
        finally:
            parcial.unlink(missing_ok=True)

    tempo_total_ms = int((time.perf_counter() - t_total) * 1000)
    manifesto["atualizado_em"] = _agora_iso()
    manifesto["ultimo_run"] = {
        "uf": uf, "turno": turno, "quando": _agora_iso(), "force": force,
        "arquivos": len(arquivos), "downloads": n_downloads, "reusos": n_reusos,
        "bytes": tot_bytes, "tempo_total_ms": tempo_total_ms,
        "pico_memoria_kb": _pico_memoria_kb(),
        "bloqueios": len(bloqueios), "avisos": len(avisos),
    }
    _salvar_manifesto(projeto / MANIFEST_REL, manifesto)

    return StageResult(
        etapa="ingest",
        arquivos=tuple(arquivos),
        linhas={"arquivos": len(arquivos), "bytes": tot_bytes, "downloads": n_downloads,
                "reusos": n_reusos, "tempo_total_ms": tempo_total_ms,
                "pico_memoria_kb": _pico_memoria_kb()},
        avisos=tuple(avisos),
        bloqueios=tuple(bloqueios),
    )
