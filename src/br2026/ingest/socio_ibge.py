# -*- coding: utf-8 -*-
"""Renda, trabalho e urbanização municipal — frente A, handoff 34.

Aquisição e derivação dos indicadores socioeconômicos municipais do Censo
Demográfico 2022 para todo o Brasil, em formato longo (uma linha por
`sg_uf × cd_municipio_ibge × indicador × periodo_referencia`), sem tocar nos
produtos eleitorais nem no contexto municipal básico
(`br2026.ingest.contexto_municipal` continua sendo o contexto população/área/PIB).

Fontes nacionais oficiais — metadados consultados na API v3 do IBGE em
28/10/2026 (`https://servicodados.ibge.gov.br/api/v3/agregados/<t>/metadados`),
antes de qualquer download; as variáveis, classificações e categorias abaixo
foram conferidas nos metadados, não assumidas de posições do JSON:

    10295 (Amostra) — var 13431 rendimento domiciliar mensal per capita médio,
        var 13534 mediano; classificações 2 (Sexo, 6794 Total), 86 (Cor ou raça,
        95251 Total) e 58 (Grupo de idade, 95253 Total).
    10296 (Amostra) — var 13604 moradores em DPP ocupados por classes de
        rendimento per capita; classificação 386: 9680 Total (universo
        classificado), 9681 até 1/4 SM, 9682 mais de 1/4 a 1/2 SM (+ 9683–9690 e
        9692 sem rendimento, usadas só na reconciliação de soma = Total).
    6580 (Amostra) — var 1641 pessoas de 14 anos ou mais; classificação 629:
        32385 Total, 32386 força de trabalho, 32387 ocupada, 32446 desocupada,
        32447 fora da força de trabalho; classificações 2 (6794) e 58 (95253).
    9923 (Universo) — var 93 população residente por situação do domicílio;
        classificação 1: 6795 Total, 1 Urbana, 2 Rural. É o agregado oficial
        municipal de população urbana/rural do Censo 2022: a urbanização NÃO
        depende da malha censitária, portanto esta frente não baixa nem processa
        a malha (sem duplicidade com a frente C).

Decisões metodológicas desta frente:

- **Símbolos do SIDRA preservados, nunca fundidos em zero.** `-` é zero
  observado e vira `0.0`; `z` (menor que meia unidade), `X` (supressão), `..`
  (não aplicável) e `...` (não disponível) viram ausentes com motivo distinto,
  registrados em `simbolo_ibge` e auditados em
  `data/staging/socio_ibge/auditoria_simbolos_ibge.json`. Falha de conversão é
  ausente com motivo, nunca zero.
- **Classificações localizadas por ID**, não pela posição no JSON (a ordem do
  array `classificacoes` varia entre consultas).
- **Componentes preservados**: numerador e denominador de cada taxa ficam em
  colunas próprias; componentes ausentes mantêm o numerador ausente (nada de
  virar zero) e denominador zero produz ausência, não taxa zero.
- **Mediana municipal não é agregada**: a tabela longa só tem linhas
  municipais; agregados nacionais de renda usam razão entre somas de
  componentes (`agregados_componentes`), nunca média ou mediana de medianas.
- **Amostral declarado**: 10295/10296/6580 são variáveis da Amostra do Censo
  2022; a API consultada não publica erro padrão para essas tabelas, então a
  coluna `precisao_disponivel` registra isso e a `limitacao` avisa do erro
  relativo elevado em municípios pequenos. 9923 é universo.
- **Lookup TSE/IBGE validado** pelo arquivo oficial `municipio_tse_ibge`
  (`validate="many_to_one"`: o join não aumenta linhas); códigos IBGE sem
  correspondência TSE ficam na tabela com `cd_municipio_tse` nulo e entram no
  relatório de não correspondidos. Nenhum voto é excluído por falta de renda —
  esta frente não lê nem escreve produtos eleitorais.
- **Cache com SHA-256 e promoção atômica**: reexecução com cache válido não usa
  a rede; hash alterado invalida o cache; falha de download não substitui a
  versão íntegra (nada é promovido parcialmente).

Uso (execução independente; a CLI global fica com o integrador)::

    python -m br2026.ingest.socio_ibge --ufs ALL --project-root .
    python -m br2026.ingest.socio_ibge --ufs RS,AC --offline --project-root .
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from br2026.ingest.contexto_municipal import UF_IBGE, tse_ibge_map

API = "https://servicodados.ibge.gov.br/api/v3/agregados"
PERIODO = "2022"
TRANSFORMACAO_VERSAO = "socio_ibge/1.0.0"
USER_AGENT = "br2026/1.0 (frente A; socio_ibge)"
TIMEOUT_S = 120.0
TENTATIVAS = 4
PAUSA_TENTATIVA_S = 5.0          # espera 5, 15 e 45 s entre tentativas

CONTRATO_REL = Path("contracts") / "socio_34" / "socio_ibge_long.json"
RAW_REL = Path("data") / "raw" / "socio_ibge"
STAGING_REL = Path("data") / "staging" / "socio_ibge"
MAPPING_PADRAO = Path("data") / "raw" / "samples" / "municipio_tse_ibge.zip"
MANIFEST_VERSION = "1.0"

# Símbolos do SIDRA distintos de zero observado → motivo de ausência.
SIMBOLOS_MOTIVO = {
    "z": "Z_MENOR_QUE_MEIA_UNIDADE",
    "X": "X_SUPRIMIDO",
    "..": "NAO_APLICAVEL",
    "...": "NAO_DISPONIVEL",
}
MOTIVO_SEM_COMP = "COMPONENTE_NAO_ENCONTRADO"
MOTIVO_PERIODO = "PERIODO_AUSENTE"
MOTIVO_DENOM_ZERO = "DENOMINADOR_ZERO"
MOTIVO_FALHA_CONVERSAO = "FALHA_CONVERSAO"

PRECISAO_AMOSTRAL = ("erro padrão não publicado pela API SIDRA para esta tabela em 28/10/2026; "
                     "estimativa amostral com erro relativo elevado em municípios pequenos")
PRECISAO_UNIVERSO = "não aplicável: dado de universo (não amostral)"

UNIV_RENDA = ("Moradores em domicílios particulares permanentes ocupados, exceto pensionistas, "
              "empregados domésticos e parentes do empregado doméstico (Amostra do Censo 2022)")
UNIV_TRABALHO = "Pessoas de 14 anos ou mais de idade (Amostra do Censo 2022)"
UNIV_POP = "População residente (Universo do Censo 2022)"

NOTA_MEDIANA = ("Mediana municipal publicada pelo IBGE; não se agrega como mediana estadual ou "
                "nacional sem microdados, nem se mistura com a média de medianas municipais.")
NOTA_MEDIA = "Média nominal mensal publicada pelo IBGE; não é média de médias municipais."
NOTA_CLASSES = ("Classes de rendimento nominal mensal domiciliar per capita em salários mínimos de "
                "2022; não é linha da pobreza nem renda corrente de outro ano.")
NOTA_TAXA = "Taxa do próprio Censo 2022; denominador zero permanece ausente, nunca zero."
NOTA_SITUACAO = ("Situação do domicílio (urbana/rural) segundo a classificação setorial do Censo "
                 "2022; não é área urbana de 2026 nem tipologia municipal corrente.")


class Bloqueio(RuntimeError):
    """Falha com causa legível (rede, cache, contrato) que não promove derivados."""


# --------------------------------------------------------------------------- #
# Fontes e indicadores (definidos a partir dos metadados consultados)          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Fonte:
    tabela: int
    nome: str
    variaveis: tuple[str, ...]
    classificacao: str              # parâmetro `classificacao` da API (IDs)
    principal: str                  # classificação da qual vem a categoria
    categorias: tuple[str, ...]     # categorias mapeadas em componentes
    extras_esperadas: tuple[tuple[str, str], ...] = ()   # (classificação, categoria Total)
    amostral: bool = True
    precisao: str = PRECISAO_AMOSTRAL


FONTES: tuple[Fonte, ...] = (
    Fonte(
        tabela=10295, nome="renda_domiciliar",
        variaveis=("13431", "13534"),
        classificacao="2[6794]|86[95251]|58[95253]", principal="86", categorias=("95251",),
        extras_esperadas=(("2", "6794"), ("58", "95253")),
    ),
    Fonte(
        tabela=10296, nome="baixa_renda",
        variaveis=("13604",),
        classificacao="386[all]|2[6794]|86[95251]", principal="386",
        categorias=("9680", "9681", "9682", "9683", "9684", "9685", "9686", "9687",
                    "9688", "9689", "9690", "9692"),
        extras_esperadas=(("2", "6794"), ("86", "95251")),
    ),
    Fonte(
        tabela=6580, nome="trabalho",
        variaveis=("1641",),
        classificacao="629[all]|2[6794]|58[95253]", principal="629",
        categorias=("32385", "32386", "32387", "32446", "32447"),
        extras_esperadas=(("2", "6794"), ("58", "95253")),
    ),
    Fonte(
        tabela=9923, nome="populacao_situacao",
        variaveis=("93",),
        classificacao="1[all]", principal="1", categorias=("6795", "1", "2"),
        extras_esperadas=(), amostral=False, precisao=PRECISAO_UNIVERSO,
    ),
)

FONTE_POR_TABELA = {f.tabela: f for f in FONTES}

# (tabela, variável, categoria) → componente. Localizado por ID, nunca por posição.
COMPONENTES: dict[tuple[int, str, str], str] = {
    (10295, "13431", "95251"): "renda_domiciliar_per_capita_media",
    (10295, "13534", "95251"): "renda_domiciliar_per_capita_mediana",
    (10296, "13604", "9680"): "pessoas_renda_classificada",
    (10296, "13604", "9681"): "pessoas_ate_1_4_sm",
    (10296, "13604", "9682"): "pessoas_1_4_ate_1_2_sm",
    # demais classes da tabela 10296: componentes usados só na reconciliação soma = Total
    (10296, "13604", "9683"): "pessoas_1_2_ate_1_sm",
    (10296, "13604", "9684"): "pessoas_1_ate_2_sm",
    (10296, "13604", "9685"): "pessoas_2_ate_3_sm",
    (10296, "13604", "9686"): "pessoas_3_ate_5_sm",
    (10296, "13604", "9687"): "pessoas_5_ate_10_sm",
    (10296, "13604", "9688"): "pessoas_10_ate_15_sm",
    (10296, "13604", "9689"): "pessoas_15_ate_20_sm",
    (10296, "13604", "9690"): "pessoas_20_mais_sm",
    (10296, "13604", "9692"): "pessoas_sem_rendimento",
    (6580, "1641", "32385"): "pessoas_14_mais",
    (6580, "1641", "32386"): "pessoas_forca_trabalho",
    (6580, "1641", "32387"): "pessoas_ocupadas",
    (6580, "1641", "32446"): "pessoas_desocupadas",
    (6580, "1641", "32447"): "pessoas_fora_forca_trabalho",
    (9923, "93", "6795"): "populacao_residente",
    (9923, "93", "1"): "populacao_urbana",
    (9923, "93", "2"): "populacao_rural",
}

# Classes da tabela 10296 usadas só para reconciliar soma das classes = Total (9680).
CLASSES_RENDA_EXCETO_TOTAL = ("9681", "9682", "9683", "9684", "9685", "9686",
                              "9687", "9688", "9689", "9690", "9692")
CLASSE_RENDA_TOTAL = "9680"


@dataclass(frozen=True)
class Indicador:
    nome: str
    tipo: str                     # "direto" | "soma" | "razao"
    unidade: str
    universo: str
    amostral: bool
    precisao: str
    limitacao: str
    componentes: tuple[str, ...] = field(default_factory=tuple)
    escala: float = 1.0           # só para "razao"
    fonte_tabela: int = 0


INDICADORES: tuple[Indicador, ...] = (
    # --- renda (Amostra) ---
    Indicador("renda_domiciliar_per_capita_media", "direto", "R$ correntes por pessoa ao mês",
              UNIV_RENDA, True, PRECISAO_AMOSTRAL, NOTA_MEDIA,
              ("renda_domiciliar_per_capita_media",), fonte_tabela=10295),
    Indicador("renda_domiciliar_per_capita_mediana", "direto", "R$ correntes por pessoa ao mês",
              UNIV_RENDA, True, PRECISAO_AMOSTRAL, NOTA_MEDIANA,
              ("renda_domiciliar_per_capita_mediana",), fonte_tabela=10295),
    # --- baixa renda (Amostra) ---
    Indicador("pessoas_renda_classificada", "direto", "pessoas", UNIV_RENDA, True,
              PRECISAO_AMOSTRAL, "Denominador classificado por rendimento da própria tabela 10296.",
              ("pessoas_renda_classificada",), fonte_tabela=10296),
    Indicador("pessoas_ate_1_4_sm", "direto", "pessoas", UNIV_RENDA, True,
              PRECISAO_AMOSTRAL, NOTA_CLASSES, ("pessoas_ate_1_4_sm",), fonte_tabela=10296),
    Indicador("pessoas_1_4_ate_1_2_sm", "direto", "pessoas", UNIV_RENDA, True,
              PRECISAO_AMOSTRAL, NOTA_CLASSES, ("pessoas_1_4_ate_1_2_sm",), fonte_tabela=10296),
    Indicador("pessoas_baixa_renda", "soma", "pessoas", UNIV_RENDA, True, PRECISAO_AMOSTRAL,
              "Soma completa das categorias 9681 e 9682; componente ausente mantém o numerador ausente.",
              ("pessoas_ate_1_4_sm", "pessoas_1_4_ate_1_2_sm"), fonte_tabela=10296),
    Indicador("pct_pessoas_baixa_renda_ate_meio_sm", "razao", "% das pessoas classificadas",
              UNIV_RENDA, True, PRECISAO_AMOSTRAL,
              "Percentual sobre o universo classificado da própria tabela 10296; não é % da população total.",
              ("pessoas_baixa_renda", "pessoas_renda_classificada"), escala=100.0,
              fonte_tabela=10296),
    # --- trabalho (Amostra) ---
    Indicador("pessoas_14_mais", "direto", "pessoas", UNIV_TRABALHO, True, PRECISAO_AMOSTRAL,
              "Total da tabela 6580 (denominador da participação).", ("pessoas_14_mais",),
              fonte_tabela=6580),
    Indicador("pessoas_forca_trabalho", "direto", "pessoas", UNIV_TRABALHO, True,
              PRECISAO_AMOSTRAL, "Força de trabalho total (ocupada + desocupada).",
              ("pessoas_forca_trabalho",), fonte_tabela=6580),
    Indicador("pessoas_ocupadas", "direto", "pessoas", UNIV_TRABALHO, True, PRECISAO_AMOSTRAL,
              "Componente publicado; confere a identidade ocupadas + desocupadas = força de trabalho.",
              ("pessoas_ocupadas",), fonte_tabela=6580),
    Indicador("pessoas_desocupadas", "direto", "pessoas", UNIV_TRABALHO, True, PRECISAO_AMOSTRAL,
              "Componente publicado; numerador da taxa de desocupação.", ("pessoas_desocupadas",),
              fonte_tabela=6580),
    Indicador("pessoas_fora_forca_trabalho", "direto", "pessoas", UNIV_TRABALHO, True,
              PRECISAO_AMOSTRAL, "Componente publicado; confere a identidade força de trabalho + fora = total.",
              ("pessoas_fora_forca_trabalho",), fonte_tabela=6580),
    Indicador("taxa_desocupacao", "razao", "% da força de trabalho", UNIV_TRABALHO, True,
              PRECISAO_AMOSTRAL, NOTA_TAXA,
              ("pessoas_desocupadas", "pessoas_forca_trabalho"), escala=100.0, fonte_tabela=6580),
    Indicador("taxa_participacao_forca_trabalho", "razao", "% das pessoas de 14 anos ou mais",
              UNIV_TRABALHO, True, PRECISAO_AMOSTRAL, NOTA_TAXA,
              ("pessoas_forca_trabalho", "pessoas_14_mais"), escala=100.0, fonte_tabela=6580),
    # --- urbanização (Universo) ---
    Indicador("populacao_residente", "direto", "pessoas", UNIV_POP, False, PRECISAO_UNIVERSO,
              "Total da tabela 9923; confere contra a população residente de outras fontes oficiais.",
              ("populacao_residente",), fonte_tabela=9923),
    Indicador("populacao_urbana", "direto", "pessoas", UNIV_POP, False, PRECISAO_UNIVERSO,
              NOTA_SITUACAO, ("populacao_urbana",), fonte_tabela=9923),
    Indicador("populacao_rural", "direto", "pessoas", UNIV_POP, False, PRECISAO_UNIVERSO,
              NOTA_SITUACAO, ("populacao_rural",), fonte_tabela=9923),
    Indicador("pct_populacao_urbana", "razao", "% da população residente", UNIV_POP, False,
              PRECISAO_UNIVERSO, NOTA_SITUACAO,
              ("populacao_urbana", "populacao_residente"), escala=100.0, fonte_tabela=9923),
)


def query_url(fonte: Fonte, uf: str) -> str:
    """URL oficial da consulta por UF (variáveis e classificações por ID)."""
    vs = "%7C".join(fonte.variaveis)
    return (f"{API}/{fonte.tabela}/periodos/{PERIODO}/variaveis/{vs}"
            f"?localidades=N6[N3[{UF_IBGE[uf]}]]&classificacao={fonte.classificacao}")


# --------------------------------------------------------------------------- #
# Aquisição com cache, retry e promoção atômica                                #
# --------------------------------------------------------------------------- #


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _atomic_write(path: Path, data: bytes) -> str:
    """Grava em `.tmp` e promove com `os.replace`: nunca deixa arquivo parcial."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return _sha256_bytes(data)


def _fetch(url: str, timeout: int = TIMEOUT_S, tentativas: int = TENTATIVAS) -> bytes:
    """GET com novas tentativas (5, 15 e 45 s): a API do SIDRA falha de forma intermitente."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    ultimo: Exception | None = None
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise OSError(f"HTTP {r.status} em {url}")
                corpo = r.read()
            return gzip.decompress(corpo) if corpo[:2] == b"\x1f\x8b" else corpo
        except OSError as e:
            ultimo = e
            if i == tentativas - 1:
                raise Bloqueio(f"{url}: {tentativas} tentativas esgotadas; último erro: {ultimo}")
            time.sleep(PAUSA_TENTATIVA_S * 3 ** i)
    raise AssertionError("inalcançável")


def _carregar_manifesto(caminho: Path) -> dict:
    if not caminho.exists():
        return {"manifest_version": MANIFEST_VERSION, "atualizado_em": None,
                "registros": {}, "falhas": []}
    try:
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Bloqueio(f"manifesto ilegível ({e}): {caminho}")
    if not isinstance(manifesto.get("registros"), dict):
        raise Bloqueio(f"manifesto sem mapa 'registros': {caminho}")
    manifesto.setdefault("falhas", [])
    return manifesto


def _salvar_manifesto(caminho: Path, manifesto: dict) -> None:
    _atomic_write(caminho, json.dumps(manifesto, ensure_ascii=False, indent=2,
                                      sort_keys=True).encode("utf-8"))


def _obter_bruto(nome: str, url: str, raw_dir: Path, manifest: dict, *,
                 offline: bool, fetch=_fetch) -> dict:
    """Bruto versionado por SHA-256: cache válido evita a rede; falha nunca substitui íntegro.

    - Registro vigente + arquivo presente + hash confere + URL igual ⇒ cache (sem rede).
    - Hash alterado ou arquivo ausente ⇒ cache inválido: baixa de novo (online) ou
      Bloqueio (offline). O arquivo antigo só é substituído por promoção atômica
      depois de um download íntegro.
    """
    registros = manifest["registros"]
    registro = registros.get(nome)
    arquivo = raw_dir / nome
    if registro and registro.get("url") == url and arquivo.exists():
        if _hash_arquivo(arquivo) == registro["sha256"]:
            registro["origem"] = "cache"
            return dict(registro)
        if offline:
            raise Bloqueio(f"{nome}: hash do cache alterado ({registro['sha256'][:12]}…) e --offline "
                           "impede reaquisição; invalidar ou reexecutar online")
        registro["invalidado_em"] = _agora_iso()
    if offline:
        raise Bloqueio(f"{nome}: ausente do cache e --offline")
    payload = fetch(url)
    try:
        corpo = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        # HTML/erro do SIDRA não substitui uma versão íntegra já promovida.
        raise Bloqueio(f"{nome}: resposta não é JSON da API v3 ({e})")
    if not isinstance(corpo, list):
        raise Bloqueio(f"{nome}: resposta inesperada (tipo {type(corpo).__name__})")
    sha = _atomic_write(arquivo, payload)
    novo = {"url": url, "sha256": sha, "bytes": len(payload), "obtido_em": _agora_iso(),
            "tabela": int(nome.split("_")[1]), "uf": nome.split("_")[-1].split(".")[0],
            "origem": "remoto"}
    if registro and registro.get("sha256") != sha:
        novo["versao_anterior"] = {k: registro.get(k) for k in
                                   ("sha256", "bytes", "obtido_em", "origem", "url")}
    registros[nome] = novo
    return dict(novo)


# --------------------------------------------------------------------------- #
# Parsing: símbolos preservados, classificações por ID                         #
# --------------------------------------------------------------------------- #


def _simbolo(raw) -> tuple[float, str | None, str | None]:
    """Valor numérico, símbolo IBGE e motivo de ausência (nunca zero imputado).

    `-` é zero observado; `z`, `X`, `..` e `...` são ausentes com motivo próprio;
    falha de conversão é ausente com motivo, também nunca zero.
    """
    if raw is None:
        return float("nan"), None, MOTIVO_SEM_COMP
    texto = str(raw).strip()
    if texto == "":
        return float("nan"), None, MOTIVO_FALHA_CONVERSAO
    if texto == "-":
        return 0.0, "-", None
    motivo = SIMBOLOS_MOTIVO.get(texto)
    if motivo is not None:
        return float("nan"), texto, motivo
    try:
        return float(texto), None, None
    except ValueError:
        return float("nan"), texto[:8], MOTIVO_FALHA_CONVERSAO


def parsear_fonte(payload: bytes, fonte: Fonte, url: str, source_id: str) -> tuple[pd.DataFrame, int]:
    """JSON bruto da API v3 → componentes longos de uma tabela/UF (+ combos descartados).

    Classificações e categorias são localizadas por ID (a ordem do array varia).
    Combinações fora das esperadas (sexo/idade/raça ≠ Total) são descartadas e
    contadas; nada é inferido por posição.
    """
    linhas: list[dict] = []
    descartadas = 0
    for var in json.loads(payload.decode("utf-8")):
        var_id = str(var.get("id"))
        if var_id not in fonte.variaveis:
            continue
        for res in var.get("resultados", []):
            cats: dict[str, str] = {}
            for cls in res.get("classificacoes", []):
                cat = cls.get("categoria") or {}
                if len(cat) != 1:
                    raise Bloqueio(f"{fonte.tabela}: classificação {cls.get('id')} sem categoria única")
                cats[str(cls.get("id"))] = next(iter(cat))
            categoria = cats.get(fonte.principal)
            if categoria not in fonte.categorias:
                descartadas += 1
                continue
            extras_ok = all(cats.get(cid) == catorig
                            for cid, catorig in fonte.extras_esperadas)
            if not extras_ok:
                descartadas += 1
                continue
            for serie in res.get("series", []):
                cd = str(serie.get("localidade", {}).get("id", "")).strip()
                if not cd:
                    continue
                bruto = serie.get("serie", {}).get(PERIODO)
                valor, simbolo, motivo = _simbolo(bruto)
                if bruto is None:
                    motivo = MOTIVO_PERIODO
                linhas.append({"cd_municipio_ibge": cd, "tabela": fonte.tabela,
                               "variavel": var_id, "categoria": categoria, "valor": valor,
                               "simbolo": simbolo, "motivo": motivo, "fonte_url": url,
                               "source_id": source_id})
    df = pd.DataFrame(linhas, columns=["cd_municipio_ibge", "tabela", "variavel", "categoria",
                                       "valor", "simbolo", "motivo", "fonte_url", "source_id"])
    return df, descartadas


def montar_componentes(parsed: pd.DataFrame, descartadas: int = 0) -> tuple[tuple, dict]:
    """Componentes nomeados, com política explícita de duplicatas.

    Duplicatas idênticas são mantidas uma vez e contabilizadas; duplicatas
    conflitantes (mesma chave, valor/símbolo/motivo diferente) bloqueiam a
    promoção — não se escolhe um valor silenciosamente.
    """
    df = parsed.copy()
    df["componente"] = [COMPONENTES.get((int(t), str(v), str(c)))
                        for t, v, c in zip(df.tabela, df.variavel, df.categoria)]
    inesperadas = int(df.componente.isna().sum())
    df = df.loc[df.componente.notna()].copy()

    chave = ["cd_municipio_ibge", "componente"]
    # Assinatura por chave: (valor, símbolo, motivo). Nulos entram como marcador próprio.
    assin = (df.valor.map(lambda v: "nan" if pd.isna(v) else repr(float(v)))
             + "§" + df.simbolo.fillna("§").astype(str)
             + "§" + df.motivo.fillna("§").astype(str))
    tmp = df.assign(_assin=assin)
    distintos = tmp.groupby(chave)["_assin"].nunique()
    conflitantes_idx = distintos[distintos > 1]
    conflitantes = int(len(conflitantes_idx))
    if conflitantes:
        ex = conflitantes_idx.index[0]
        raise Bloqueio(f"{conflitantes} duplicata(s) conflitante(s) em componentes, ex.: "
                       f"{ex[0]} / {ex[1]}; promoção bloqueada")
    contagem = tmp.groupby(chave)["_assin"].size()
    identicas = int((contagem - 1).clip(lower=0).sum())
    df = df.drop_duplicates(chave, keep="first")

    audit = {
        "combos_descartados": int(descartadas),
        "categorias_fora_do_mapa": inesperadas,
        "duplicatas_identicas_removidas": identicas,
        "duplicatas_conflitantes": conflitantes,
        "simbolos": {str(k): int(v) for k, v in
                     df.loc[df.simbolo.notna(), "simbolo"].value_counts().items()},
        "motivos": {str(k): int(v) for k, v in
                    df.loc[df.motivo.notna(), "motivo"].value_counts().items()},
    }
    wide_valor = df.pivot(index="cd_municipio_ibge", columns="componente", values="valor")
    wide_simb = df.pivot(index="cd_municipio_ibge", columns="componente", values="simbolo")
    wide_mot = df.pivot(index="cd_municipio_ibge", columns="componente", values="motivo")
    return (wide_valor, wide_simb, wide_mot), audit


def derivar_indicadores(largos: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> pd.DataFrame:
    """Componentes largos → tabela longa municipal, com numerador/denominador preservados.

    Indicadores podem referenciar componentes brutos ou indicadores já derivados
    (ex.: `pct_pessoas_baixa_renda_ate_meio_sm` usa a soma `pessoas_baixa_renda`),
    resolvidos na ordem declarada em `INDICADORES`. Componente ausente mantém o
    valor ausente com motivo; denominador zero nunca vira taxa zero.
    """
    wide_valor, wide_simb, wide_mot = largos
    municipios = sorted(wide_valor.index)
    linhas: list[dict] = []
    for cd in municipios:
        memoria: dict[str, float] = {}

        def comp(nome: str) -> float:
            if nome in memoria:
                return memoria[nome]
            if nome in wide_valor.columns:
                v = wide_valor.at[cd, nome]
                return float(v) if pd.notna(v) else float("nan")
            return float("nan")

        def simbolo_de(nome: str):
            if nome in wide_simb.columns:
                s = wide_simb.at[cd, nome]
                return s if pd.notna(s) else None
            return None

        def motivo_de(nome: str, direto: bool = False) -> str:
            """Direto: o motivo é o do próprio dado (símbolo); derivado: indica o componente."""
            if nome in wide_mot.columns:
                m = wide_mot.at[cd, nome]
                if pd.notna(m):
                    return str(m) if direto else f"COMPONENTE_AUSENTE:{nome}:{m}"
            return f"COMPONENTE_AUSENTE:{nome}:{MOTIVO_SEM_COMP}"

        for ind in INDICADORES:
            valores = {c: comp(c) for c in ind.componentes}
            obs = {c: pd.notna(v) for c, v in valores.items()}
            numerador = denominador = float("nan")
            motivo: str | None = None
            simbolo: str | None = None
            if ind.tipo == "direto":
                src = ind.componentes[0]
                simbolo = simbolo_de(src)
                if obs[src]:
                    valor = valores[src]
                else:
                    valor = float("nan")
                    motivo = motivo_de(src, direto=True)
            elif ind.tipo == "soma":
                if all(obs.values()):
                    valor = float(sum(valores.values()))
                    numerador = valor
                else:
                    primeiro = next(c for c in ind.componentes if not obs[c])
                    valor = float("nan")
                    simbolo = simbolo_de(primeiro)
                    motivo = motivo_de(primeiro)
            else:  # razao
                num, den = ind.componentes
                numerador, denominador = valores[num], valores[den]
                if not obs[num]:
                    valor, motivo, simbolo = float("nan"), motivo_de(num), simbolo_de(num)
                    numerador = denominador = float("nan")
                elif not obs[den]:
                    valor, motivo, simbolo = float("nan"), motivo_de(den), simbolo_de(den)
                    numerador = denominador = float("nan")
                elif valores[den] == 0.0:
                    valor, motivo = float("nan"), MOTIVO_DENOM_ZERO
                else:
                    numerador, denominador = valores[num], valores[den]
                    valor = ind.escala * numerador / denominador
            memoria[ind.nome] = valor
            linhas.append({
                "cd_municipio_ibge": cd, "indicador": ind.nome,
                "periodo_referencia": PERIODO, "valor": valor, "unidade": ind.unidade,
                "numerador": numerador, "denominador": denominador, "universo": ind.universo,
                "motivo_ausencia": motivo, "simbolo_ibge": simbolo, "amostral": ind.amostral,
                "precisao_disponivel": ind.precisao, "limitacao": ind.limitacao,
                "fonte_tabela": ind.fonte_tabela,
            })
    out = pd.DataFrame(linhas)
    out["valor"] = out["valor"].astype("float64")
    out["numerador"] = out["numerador"].astype("float64")
    out["denominador"] = out["denominador"].astype("float64")
    return out


# --------------------------------------------------------------------------- #
# Lookup TSE/IBGE                                                              #
# --------------------------------------------------------------------------- #


def vincular_tse(longo: pd.DataFrame, mapping: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Código TSE derivado do lookup oficial, sem aumentar linhas (many_to_one).

    Município IBGE sem correspondência permanece na tabela com `cd_municipio_tse`
    nulo e é publicado no relatório; nada é excluído para casar com o eleitorado.
    """
    antes = len(longo)
    m = mapping.drop_duplicates()
    invalidos = m.loc[m.cd_municipio_tse.notna()
                      & ~m.cd_municipio_tse.astype(str).str.fullmatch(r"[0-9]{5}"), "cd_municipio_tse"]
    if len(invalidos):
        raise Bloqueio(f"lookup TSE/IBGE com códigos TSE fora do padrão de 5 dígitos: "
                       f"{sorted(map(str, invalidos.unique()))[:5]}")
    duplicados = m[m.duplicated("cd_municipio_ibge", keep=False)]
    if len(duplicados):
        ex = sorted(duplicados.cd_municipio_ibge.unique())[:5]
        raise Bloqueio(f"lookup TSE/IBGE com correspondências conflitantes para {ex}")
    mapa = m[["sg_uf", "cd_municipio_ibge", "cd_municipio_tse"]].drop_duplicates(
        "cd_municipio_ibge")
    prefixo = {f"{cod:02d}": uf for uf, cod in UF_IBGE.items()}
    codigos = longo[["cd_municipio_ibge"]].drop_duplicates()
    codigos["sg_uf"] = codigos.cd_municipio_ibge.map(mapa.set_index("cd_municipio_ibge").sg_uf)
    codigos["sg_uf_pref"] = codigos.cd_municipio_ibge.str[:2].map(prefixo)
    sem_tse = sorted(codigos.loc[codigos.sg_uf.isna(), "cd_municipio_ibge"])
    divergentes = sorted(codigos.loc[codigos.sg_uf.notna() & codigos.sg_uf_pref.notna()
                                     & (codigos.sg_uf != codigos.sg_uf_pref), "cd_municipio_ibge"])
    codigos["sg_uf"] = codigos.sg_uf.fillna(codigos.sg_uf_pref)
    if codigos.sg_uf.isna().any():
        ex = sorted(codigos.loc[codigos.sg_uf.isna(), "cd_municipio_ibge"])[:5]
        raise Bloqueio(f"códigos IBGE sem UF conhecida: {ex}")

    out = longo.merge(codigos[["cd_municipio_ibge", "sg_uf"]],
                      on="cd_municipio_ibge", how="left", validate="many_to_one")
    out = out.merge(mapa[["cd_municipio_ibge", "cd_municipio_tse"]],
                    on="cd_municipio_ibge", how="left", validate="many_to_one")
    if len(out) != antes:
        raise Bloqueio(f"join com o lookup alterou o tamanho: {antes} → {len(out)}")

    ibges_dados = set(codigos.cd_municipio_ibge)
    tse_sem_dados = sorted(set(mapa.cd_municipio_ibge) - ibges_dados)
    relatorio = {
        "lookup_arquivo": None, "lookup_linhas": int(len(mapping)),
        "municipios_ibge_sem_correspondencia_tse": sem_tse,
        "municipios_ibge_divergentes_uf_prefixo": divergentes,
        "municipios_tse_sem_dados_censo": tse_sem_dados,
        "linhas_eleitorais_alteradas": 0,
    }
    return out, relatorio


# --------------------------------------------------------------------------- #
# Contrato longo (arquivo próprio desta frente; contracts/v1 intocado)         #
# --------------------------------------------------------------------------- #


def _carregar_contrato(project_root: Path) -> dict:
    caminho = Path(project_root) / CONTRATO_REL
    if not caminho.exists():
        raise Bloqueio(f"contrato ausente: {caminho} (entrega da frente 34)")
    return json.loads(caminho.read_text(encoding="utf-8"))


def validar_contrato(df: pd.DataFrame, project_root: Path) -> None:
    """Valida a tabela longa contra o contrato desta frente; levanta Bloqueio com todas as violações."""
    contrato = _carregar_contrato(project_root)
    viol: list[str] = []
    nomes = [c["name"] for c in contrato["columns"]]
    faltantes = [n for n in nomes if n not in df.columns]
    extras = [n for n in df.columns if n not in nomes]
    if faltantes:
        viol.append(f"colunas ausentes: {faltantes}")
    if extras:
        viol.append(f"colunas não previstas: {extras}")
    for col in contrato["columns"]:
        nome = col["name"]
        if nome not in df.columns:
            continue
        s = df[nome]
        if not col.get("nullable", False) and s.isna().any():
            viol.append(f"{nome}: {int(s.isna().sum())} nulo(s) em coluna não anulável")
        nn = s.dropna()
        tipo = col["type"]
        ok = True
        if tipo == "string":
            ok = pd.api.types.is_string_dtype(s.dtype) or all(isinstance(v, str) for v in nn)
        elif tipo == "float64":
            ok = pd.api.types.is_float_dtype(s.dtype)
        elif tipo == "bool":
            ok = pd.api.types.is_bool_dtype(s.dtype)
        elif tipo.startswith("int"):
            ok = pd.api.types.is_integer_dtype(s.dtype)
        if not ok:
            viol.append(f"{nome}: tipo {s.dtype} incompatível com {tipo}")
            continue
        if col.get("pattern") and len(nn):
            fora = ~nn.astype(str).str.fullmatch(col["pattern"])
            if fora.any():
                viol.append(f"{nome}: {int(fora.sum())} valor(es) fora do padrão "
                            f"{col['pattern']}, ex. {nn[fora].iloc[0]!r}")
    if not faltantes:
        chave = list(contrato["primary_key"])
        dup = df.duplicated(chave, keep=False)
        if dup.any():
            viol.append(f"chave primária {chave} duplicada em {int(dup.sum())} linha(s)")
    if viol:
        raise Bloqueio("contrato socio_ibge_long violado:\n  - " + "\n  - ".join(viol))


def dicionario_indicadores() -> pd.DataFrame:
    linhas = []
    for ind in INDICADORES:
        if ind.tipo == "direto":
            formula = f"valor publicado ({ind.componentes[0]})"
        elif ind.tipo == "soma":
            formula = " + ".join(ind.componentes)
        else:
            formula = (f"{ind.escala:g} × {' * '.join(ind.componentes[:1])} / "
                       f"{ind.componentes[1]}")
        linhas.append({
            "indicador": ind.nome, "tipo": ind.tipo, "unidade": ind.unidade,
            "formula": formula, "universo": ind.universo, "periodo_referencia": PERIODO,
            "tabela_sidra": ind.fonte_tabela, "amostral": ind.amostral,
            "precisao_disponivel": ind.precisao, "limitacao": ind.limitacao,
        })
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- #
# Cobertura, reconciliações e agregados de componentes                         #
# --------------------------------------------------------------------------- #


def cobertura(longo: pd.DataFrame) -> pd.DataFrame:
    """Cobertura observada por UF e indicador, com motivos de ausência contados.

    A completude nunca é afirmada por um número esperado fixo de municípios.
    """
    linhas = []
    base = longo.assign(sg_uf=longo.sg_uf.fillna("??"))
    grupos = [("BRASIL", base)] + [(uf, g) for uf, g in base.groupby("sg_uf", sort=True)]
    for uf, g in grupos:
        for ind, gi in g.groupby("indicador", sort=True):
            observados = int(gi.valor.notna().sum())
            motivos = gi.loc[gi.valor.isna(), "motivo_ausencia"].value_counts()
            linhas.append({
                "sg_uf": uf, "indicador": ind, "municipios": int(len(gi)),
                "observados": observados, "ausentes": int(len(gi) - observados),
                "cobertura_pct": round(100.0 * observados / len(gi), 4) if len(gi) else float("nan"),
                "motivos_ausencia": json.dumps({str(k): int(v) for k, v in motivos.items()},
                                               ensure_ascii=False, sort_keys=True),
            })
    return pd.DataFrame(linhas)


def reconciliacoes(largos, contexto_path: Path | None = None) -> dict:
    """Identidades publicadas: soma de classes = Total; ocupadas + desocupadas = força de
    trabalho; força + fora = total; urbana + rural = total; e população contra
    `municipal_context` (tabela 4714) quando o arquivo existe. Nenhum número é ajustado."""
    wide_valor, _, _ = largos

    def _identidade(num: tuple[str, ...], den: str, rotulo: str) -> dict:
        col_num = [c for c in num if c in wide_valor.columns]
        if den not in wide_valor.columns or len(col_num) != len(num):
            return {"identidade": rotulo, "status": "INDISPONIVEL"}
        base = wide_valor[col_num + [den]].dropna()
        soma = base[col_num].sum(axis=1)
        dif = (soma - base[den]).abs()
        diferentes = base.index[dif > 1e-9]
        return {
            "identidade": rotulo, "verificaveis": int(len(base)), "iguais": int((dif <= 1e-9).sum()),
            "diferentes": int(len(diferentes)), "max_diferenca_absoluta": float(dif.max()) if len(dif) else 0.0,
            "exemplos_divergentes": sorted(diferentes)[:5],
        }

    classes = [COMPONENTES[(10296, "13604", c)] for c in CLASSES_RENDA_EXCETO_TOTAL
               if (10296, "13604", c) in COMPONENTES]
    resultado = {
        "soma_classes_renda_igual_total": _identidade(tuple(classes), "pessoas_renda_classificada",
                                                      "soma das 11 classes de rendimento = total 9680"),
        "ocupadas_mais_desocupadas_igual_forca_trabalho": _identidade(
            ("pessoas_ocupadas", "pessoas_desocupadas"), "pessoas_forca_trabalho",
            "ocupadas + desocupadas = força de trabalho"),
        "forca_mais_fora_igual_total_14_mais": _identidade(
            ("pessoas_forca_trabalho", "pessoas_fora_forca_trabalho"), "pessoas_14_mais",
            "força de trabalho + fora = total de 14 anos ou mais"),
        "urbana_mais_rural_igual_total": _identidade(
            ("populacao_urbana", "populacao_rural"), "populacao_residente",
            "urbana + rural = população residente"),
    }
    if contexto_path is not None and Path(contexto_path).exists():
        ctx = pd.read_parquet(Path(contexto_path))
        pop = ctx.loc[ctx.variavel.eq("populacao_residente"), ["cd_municipio_ibge", "valor"]]
        nosso = (wide_valor["populacao_residente"].rename("valor_socio")
                 .rename_axis("cd_municipio_ibge").reset_index()
                 .merge(pop, on="cd_municipio_ibge", how="outer", indicator=True))
        par = nosso.loc[nosso._merge.eq("both")].dropna()
        dif = (par.valor_socio - par.valor).abs()
        resultado["populacao_9923_vs_4714"] = {
            "identidade": "população residente 9923 = população residente 4714 (contexto municipal)",
            "comparaveis": int(len(par)), "iguais": int((dif <= 0.5).sum()),
            "diferentes": int((dif > 0.5).sum()), "max_diferenca_absoluta": float(dif.max()) if len(dif) else 0.0,
            "so_9923": int((nosso._merge.eq("left_only")).sum()),
            "so_4714": int((nosso._merge.eq("right_only")).sum()),
            "nota": "Diferenças são documentadas, nunca ajustadas para coincidir.",
        }
    else:
        resultado["populacao_9923_vs_4714"] = {
            "identidade": "população residente 9923 vs 4714", "status": "INDISPONIVEL",
            "motivo": "municipal_context.parquet ausente nesta execução",
        }
    return resultado


def agregados_componentes(longo: pd.DataFrame) -> pd.DataFrame:
    """Razões entre somas de pares completos no nível municipal (nunca média de taxas,
    nunca média/mediana de renda agregada — a mediana municipal não agrega)."""
    especs = [
        ("Baixa renda (Censo 2022)", "pessoas_baixa_renda", "pessoas_renda_classificada", 100,
         "% das pessoas classificadas"),
        ("Desocupação (Censo 2022)", "pessoas_desocupadas", "pessoas_forca_trabalho", 100,
         "% da força de trabalho"),
        ("Participação (Censo 2022)", "pessoas_forca_trabalho", "pessoas_14_mais", 100,
         "% das pessoas de 14 anos ou mais"),
        ("Urbanização (Censo 2022)", "populacao_urbana", "populacao_residente", 100,
         "% da população residente"),
    ]
    linhas = []
    valores = longo.pivot(index="cd_municipio_ibge", columns="indicador", values="valor")
    for rotulo, num, den, escala, unidade in especs:
        if num not in valores.columns or den not in valores.columns:
            continue
        par = valores[[num, den]].dropna()
        if par.empty or float(par[den].sum()) == 0.0:
            continue
        linhas.append({
            "indicador": rotulo, "unidade": unidade,
            "formula": f"{escala:g} × soma({num}) / soma({den})",
            "municipios_com_pares_completos": int(len(par)),
            "valor": escala * float(par[num].sum()) / float(par[den].sum()),
        })
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- #
# Comparação RS contra a base socioeconômica original                          #
# --------------------------------------------------------------------------- #

# indicador desta frente → coluna da base original do RS (Censo 2022, mesma tabela)
MAPA_COMPARACAO_RS = {
    "renda_domiciliar_per_capita_media": "renda_domiciliar_per_capita_media",
    "renda_domiciliar_per_capita_mediana": "renda_domiciliar_per_capita_mediana",
    "pct_pessoas_baixa_renda_ate_meio_sm": "pct_pessoas_baixa_renda_ate_meio_sm",
    "taxa_desocupacao": "taxa_desocupacao_censo_2022",
    "taxa_participacao_forca_trabalho": "taxa_participacao_forca_trabalho",
    "pessoas_baixa_renda": "pessoas_baixa_renda",
    "pessoas_renda_classificada": "pessoas_renda_classificada",
    "pessoas_desocupadas": "pessoas_desocupadas",
    "pessoas_forca_trabalho": "pessoas_forca_trabalho",
    "pessoas_14_mais": "pessoas_14_mais",
    "populacao_residente": "populacao_censo_2022",
}
TOLERANCIA_RS = 1e-6


def comparar_rs(longo: pd.DataFrame, base_rs: Path) -> tuple[pd.DataFrame, dict]:
    """Compara o recorte RS contra a base socioeconômica original, por código, variável e
    período. Diferenças por fonte/versão/universo são explicadas no resumo; os números não
    são ajustados para coincidir e nenhuma associação eleitoral é avaliada aqui."""
    base = pd.read_parquet(Path(base_rs))
    rs = longo.loc[longo.sg_uf.eq("RS")]
    linhas = []
    for ind, coluna in MAPA_COMPARACAO_RS.items():
        if coluna not in base.columns:
            continue
        nosso = (rs.loc[rs.indicador.eq(ind), ["cd_municipio_ibge", "valor", "motivo_ausencia"]]
                 .rename(columns={"valor": "valor_socio_ibge"}))
        orig = base[["id_municipio_ibge", coluna]].rename(
            columns={"id_municipio_ibge": "cd_municipio_ibge", coluna: "valor_base_original"})
        par = orig.merge(nosso, on="cd_municipio_ibge", how="outer", indicator="vinculo")
        for r in par.to_dict("records"):
            a, b = r["valor_base_original"], r["valor_socio_ibge"]
            if r["vinculo"] == "left_only":
                status = "SOMENTE_BASE_ORIGINAL"
            elif r["vinculo"] == "right_only":
                status = "SOMENTE_SOCIO_IBGE"
            elif pd.isna(a) and pd.isna(b):
                status = "AUSENTE_NAS_DUAS"
            elif pd.isna(a) or pd.isna(b):
                status = "AUSENTE_EM_UMA"
            elif abs(float(a) - float(b)) <= TOLERANCIA_RS:
                status = "IGUAL"
            else:
                status = "DIFERENTE"
            linhas.append({
                "indicador": ind, "periodo_referencia": PERIODO,
                "cd_municipio_ibge": r["cd_municipio_ibge"], "valor_base_original": a,
                "valor_socio_ibge": b,
                "diferenca": (float(b) - float(a)) if (pd.notna(a) and pd.notna(b)) else float("nan"),
                "motivo_ausencia_socio_ibge": r["motivo_ausencia"], "status": status,
            })
    comparacao = pd.DataFrame(linhas)
    resumo = {
        "base_original": str(base_rs), "uf": "RS", "periodo": PERIODO,
        "tolerancia": TOLERANCIA_RS,
        "status_por_indicador": {
            ind: {str(k): int(v) for k, v in g.status.value_counts().items()}
            for ind, g in comparacao.groupby("indicador")} if not comparacao.empty else {},
        "explicacao": (
            "Base original: socioeconomico_municipal_rs.parquet (pro RS, Censo 2022 pelas mesmas "
            "tabelas SIDRA 10295/10296/6580; população do recorte estadual). socio_ibge: tabelas "
            "10295/10296/6580/9923 nacionais, mesmo período 2022. Divergências são atribuídas a "
            "fonte/versão/universo e ficam registradas por código; nenhum valor é ajustado para "
            "coincidir, e nada aqui avalia associação eleitoral."),
    }
    return comparacao, resumo


# --------------------------------------------------------------------------- #
# Execução                                                                     #
# --------------------------------------------------------------------------- #


def _resolver_ufs(ufs) -> list[str]:
    if isinstance(ufs, str):
        ufs = [u.strip().upper() for u in ufs.split(",") if u.strip()]
    if any(u in ("ALL", "BRASIL", "*") for u in ufs):
        return sorted(UF_IBGE)
    invalidas = [u for u in ufs if u not in UF_IBGE]
    if invalidas:
        raise Bloqueio(f"UFs inválidas: {invalidas} (esperado sigla de UF ou ALL)")
    return sorted(set(ufs))


def _atomic_parquet(df: pd.DataFrame, caminho: Path) -> str:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, caminho)
    return _hash_arquivo(caminho)


def run(ufs, project_root: Path, mapping_zip: Path | None = None, *, offline: bool = False,
        fetch=_fetch, base_rs: Path | None = None) -> dict:
    """Executa a frente 34 para as UFs pedidas e publica `data/staging/socio_ibge/`.

    Independente da CLI global: recebe UFs, cache/offline e caminhos como argumentos.
    Falha de download em uma UF não bloqueia as demais nem substitui brutos íntegros;
    todas as falhas ficam no relatório e no código de saída.
    """
    t0 = time.perf_counter()
    root = Path(project_root)
    mapping_zip = Path(mapping_zip) if mapping_zip else root / MAPPING_PADRAO
    if not mapping_zip.exists():
        raise Bloqueio(f"lookup TSE/IBGE ausente: {mapping_zip}")
    ufs_exec = _resolver_ufs(ufs)

    raw_dir = root / RAW_REL
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "manifest.json"
    manifest = _carregar_manifesto(manifest_path)

    partes: list[pd.DataFrame] = []
    falhas: list[dict] = []
    registros_usados: list[dict] = []
    combos_descartados = 0
    for uf in ufs_exec:
        for fonte in FONTES:
            nome = f"sidra_{fonte.tabela}_{PERIODO}_{uf}.json"
            url = query_url(fonte, uf)
            try:
                reg = _obter_bruto(nome, url, raw_dir, manifest, offline=offline, fetch=fetch)
                payload = (raw_dir / nome).read_bytes()
                parte, descartados = parsear_fonte(payload, fonte, url, reg["sha256"])
                if parte.empty:
                    raise Bloqueio(f"{nome}: resposta sem nenhum município (payload inesperado)")
                prefixos = set(parte.cd_municipio_ibge.str[:2])
                esperado = f"{UF_IBGE[uf]:02d}"
                if prefixos and prefixos != {esperado}:
                    raise Bloqueio(f"{nome}: códigos IBGE de outra UF na resposta "
                                   f"({sorted(prefixos)} ≠ {esperado})")
                partes.append(parte)
                combos_descartados += descartados
                registros_usados.append({"arquivo": nome, "tabela": fonte.tabela, "uf": uf,
                                         "sha256": reg["sha256"], "origem": reg["origem"],
                                         "bytes": reg["bytes"]})
            except Bloqueio as e:
                falhas.append({"uf": uf, "tabela": fonte.tabela, "erro": str(e)})
    if not partes:
        manifest["falhas"].extend(falhas)
        manifest["atualizado_em"] = _agora_iso()
        _salvar_manifesto(manifest_path, manifest)
        raise Bloqueio(f"nenhuma tabela obtida ({len(falhas)} falha(s)); ver manifesto {manifest_path}")

    parsed = pd.concat(partes, ignore_index=True)
    largos, auditoria = montar_componentes(parsed, descartadas=combos_descartados)
    longo = derivar_indicadores(largos)

    mapping = tse_ibge_map(mapping_zip)
    longo, rel_lookup = vincular_tse(longo, mapping)
    rel_lookup["lookup_arquivo"] = str(mapping_zip)
    rel_lookup["lookup_sha256"] = _hash_arquivo(mapping_zip)

    # Proveniência por linha: o arquivo bruto (e a URL) da UF consultada que trouxe o município.
    # Tabela não obtida numa UF: source_id nulo e motivo explícito — a linha permanece para a
    # cobertura medir a ausência, nunca vira zero nem some silenciosamente.
    prefixo_uf = {f"{cod:02d}": uf for uf, cod in UF_IBGE.items()}
    fontes_por_uf = {(int(r["tabela"]), r["uf"]): r for r in registros_usados}
    chave_fonte = [(int(t), prefixo_uf[str(cd)[:2]]) for t, cd in
                   zip(longo.fonte_tabela, longo.cd_municipio_ibge)]
    source_ids, motivos = [], []
    for (tabela, uf), valor, motivo in zip(chave_fonte, longo.valor, longo.motivo_ausencia):
        reg = fontes_por_uf.get((tabela, uf))
        source_ids.append(reg["sha256"] if reg else None)
        motivos.append(motivo if (reg or pd.notna(valor)) else f"FONTE_NAO_OBTIDA:{tabela}")
    longo["source_id"] = source_ids
    longo["motivo_ausencia"] = motivos
    longo["fonte_url"] = [query_url(FONTE_POR_TABELA[int(t)], uf) for t, uf in chave_fonte]
    longo["versao_transformacao"] = TRANSFORMACAO_VERSAO

    validar_contrato(longo, root)
    longo = longo.sort_values(["sg_uf", "cd_municipio_ibge", "indicador"]).reset_index(drop=True)

    staging = root / STAGING_REL
    staging.mkdir(parents=True, exist_ok=True)
    hashes_produtos: dict[str, str] = {}
    hashes_produtos["socio_ibge_long.parquet"] = _atomic_parquet(longo, staging / "socio_ibge_long.parquet")

    cov = cobertura(longo)
    buf = cov.to_csv(index=False).encode("utf-8")
    (staging / "cobertura_socio_ibge.csv").write_bytes(buf)
    hashes_produtos["cobertura_socio_ibge.csv"] = _sha256_bytes(buf)

    dic = dicionario_indicadores()
    buf = dic.to_csv(index=False).encode("utf-8")
    (staging / "dicionario_socio_ibge.csv").write_bytes(buf)
    hashes_produtos["dicionario_socio_ibge.csv"] = _sha256_bytes(buf)

    buf = json.dumps(auditoria, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    (staging / "auditoria_simbolos_ibge.json").write_bytes(buf)
    hashes_produtos["auditoria_simbolos_ibge.json"] = _sha256_bytes(buf)

    reconc = reconciliacoes(largos, root / "data" / "staging" / "municipal_context.parquet")
    agreg = agregados_componentes(longo)

    resumo_rs: dict | None = None
    comparacao_path = None
    if base_rs and Path(base_rs).exists() and not longo.loc[longo.sg_uf.eq("RS")].empty:
        comparacao, resumo_rs = comparar_rs(longo, Path(base_rs))
        comparacao_path = staging / "comparacao_rs_base_original.csv"
        buf = comparacao.to_csv(index=False).encode("utf-8")
        comparacao_path.write_bytes(buf)
        hashes_produtos["comparacao_rs_base_original.csv"] = _sha256_bytes(buf)
    elif base_rs:
        resumo_rs = {"status": "INDISPONIVEL", "base_original": str(base_rs),
                     "motivo": "arquivo da base socioeconômica original do RS não encontrado"}

    ufs_ok = sorted({r["uf"] for r in registros_usados})
    relatorio = {
        "execucao": {
            "frente": "34 — IBGE renda/trabalho/urbanização municipal", "modulo": TRANSFORMACAO_VERSAO,
            "quando": _agora_iso(), "ufs_pedidas": ufs_exec, "ufs_obtidas": ufs_ok,
            "ufs_com_falha": sorted({f["uf"] for f in falhas}), "falhas": falhas,
            "offline": bool(offline), "duracao_s": round(time.perf_counter() - t0, 1),
        },
        "fontes": [
            {"tabela": f.tabela, "nome": f.nome, "periodo": PERIODO, "variaveis": list(f.variaveis),
             "classificacao": f.classificacao, "amostral": f.amostral, "precisao": f.precisao,
             "url_modelo": query_url(f, "RS").replace("N3[43]", "N3[<UF>]"),
             "arquivos_brutos": [r["arquivo"] for r in registros_usados if r["tabela"] == f.tabela]}
            for f in FONTES
        ],
        "auditoria_simbolos": auditoria,
        "lookup_tse_ibge": rel_lookup,
        "reconciliacoes": reconc,
        "agregados_de_componentes": agreg.to_dict("records") if not agreg.empty else [],
        "comparacao_rs": resumo_rs,
        "cobertura_nacional": (cov.loc[cov.sg_uf.eq("BRASIL")].to_dict("records")),
        "produtos": {"dir": str(STAGING_REL), "sha256": hashes_produtos},
        "campos_liberados": sorted(longo.indicador.unique()),
        "limites": [
            "Indicadores municipais do Censo 2022 (renda/trabalho = Amostra; população = Universo).",
            "Contexto do município, não característica de eleitores; nenhum voto é identificado.",
            "Nenhuma conclusão sobre associação eleitoral é tarefa desta frente.",
            "Votos não são excluídos do painel principal por falta de renda: esta frente não toca "
            "produtos eleitorais.",
            "Mediana municipal não agrega como mediana estadual ou nacional.",
        ],
        "pendencias": [
            "Urbanização vem do agregado oficial 9923 (universo); a malha censitária da frente C "
            "não é necessária nem duplicada aqui.",
            "Erro padrão das estimativas amostrais não é publicado pela API SIDRA para 10295/10296/"
            "6580 (consultado em 28/10/2026); municípios pequenos têm erro relativo elevado.",
        ],
    }
    buf = json.dumps(relatorio, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    (staging / "relatorio_cobertura_socio_ibge.json").write_bytes(buf)

    manifest["falhas"].extend(falhas)
    manifest["falhas"] = manifest["falhas"][-200:]    # histórico limitado
    manifest["atualizado_em"] = _agora_iso()
    manifest["ultima_execucao"] = {
        "quando": _agora_iso(), "ufs": ufs_exec, "offline": bool(offline),
        "arquivos": len(registros_usados), "falhas": len(falhas),
        "linhas_longo": int(len(longo)),
    }
    _salvar_manifesto(manifest_path, manifest)

    return {
        "linhas": int(len(longo)), "municipios": int(longo.cd_municipio_ibge.nunique()),
        "indicadores": int(longo.indicador.nunique()), "ufs": ufs_ok,
        "ufs_com_falha": sorted({f["uf"] for f in falhas}), "falhas": falhas,
        "ausentes": int(longo.valor.isna().sum()), "arquivos_brutos": len(registros_usados),
        "produtos": sorted(hashes_produtos), "dir": str(staging),
        "comparacao_rs": comparacao_path is not None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m br2026.ingest.socio_ibge",
        description="Frente 34: renda, trabalho e urbanização municipal (Censo 2022, SIDRA).")
    ap.add_argument("--ufs", required=True,
                    help="siglas separadas por vírgula (RS,AC) ou ALL para as 27 UFs")
    ap.add_argument("--project-root", default=".", help="raiz do projeto presidenciais_2026_br")
    ap.add_argument("--mapping", default=None,
                    help="ZIP municipio_tse_ibge oficial (padrão: data/raw/samples/municipio_tse_ibge.zip)")
    ap.add_argument("--offline", action="store_true",
                    help="usa só o cache por SHA-256; sem rede, cache inválido bloqueia")
    ap.add_argument("--base-rs", default=None,
                    help="parquet da base socioeconômica original do RS para comparação")
    args = ap.parse_args(argv)
    resumo = run(args.ufs, Path(args.project_root),
                 Path(args.mapping) if args.mapping else None,
                 offline=args.offline, base_rs=Path(args.base_rs) if args.base_rs else None)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 2 if resumo["ufs_com_falha"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
