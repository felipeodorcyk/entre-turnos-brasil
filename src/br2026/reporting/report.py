"""Relatório reproduzível (B6): todo número vem de uma tabela exportada.

Modelos de texto usam marcadores `{{tabela|filtro|coluna|formato}}`, com
filtro `col=valor[&col=valor]` que precisa selecionar exatamente uma linha.
Cada substituição é registrada em um rastro (tabela, filtro, coluna, valor).
Um linter recusa números digitados à mão fora dos marcadores e frases de
causalidade ou de transferência individual observada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

PLACEHOLDER = re.compile(r"\{\{([^}|]+)\|([^}|]*)\|([^}|]+)(?:\|([^}]+))?\}\}")
# Números literais permitidos no texto: anos, turnos, horários e ordinais de seção.
ALLOWED_LITERAL = re.compile(r"\b(?:20\d\d|1º|2º|\d{1,2}h(?:\d\d)?|[12]º turno)\b")
NUMBER = re.compile(r"(?<![\w{|])\d+(?:[.,]\d+)*%?(?![\w}|])")

# Triagem textual, não validação científica: o texto final ainda exige revisão editorial.
# Sempre proibidas: alegações de transferência individual, de votantes observados,
# de erro amostral inexistente e de corte cadastral/cronologia não verificada (R18-3).
ALWAYS_FORBIDDEN = [
    r"\btransferi(?:u|ram|ência observada)\b", r"\bmigra(?:ram|ção de eleitores)\b",
    r"\beleitores de \w+ votaram em\b", r"\bvotaram após (?:as )?17h\b",
    r"\bnovos eleitores admitidos\b", r"\badmitidos at[ée] (?:as )?19h\b",
    r"\beleitores que votaram depois\b", r"\bmargem de erro dos votos\b",
    r"\bperfil dos votantes\b",
    r"\bap[óo]s o corte cadastral\b",
    r"\bposterior(?:es)? ao corte cadastral\b",
    r"\bcorte cadastral confirmado\b",
]
# Alegações causais: proibidas como afirmação, aceitas como ressalva negada na
# mesma oração (O-R5): "esta análise não demonstra causalidade".
CAUSAL = [
    r"\bcausou\b", r"\bcausaram\b", r"\befeitos? causa(?:l|is)\b",
    r"\brela[çc](?:[ãa]o|[õo]es) causa(?:l|is)\b", r"\bimpactos? causa(?:l|is)\b", r"\bcausalidade\b",
]
FORBIDDEN = ALWAYS_FORBIDDEN + CAUSAL  # compatibilidade com importações anteriores
NEGATION = re.compile(r"\b(?:não|nao|nem|sem|jamais|nunca|tampouco)\b(?!\s+(?:apenas|só|somente)\b)",
                      re.IGNORECASE)
CLAUSE_BREAK = re.compile(r"[.;:!?\n]|\bmas\b|\bporém\b|\bentretanto\b", re.IGNORECASE)


def _negated(text: str, start: int) -> bool:
    """Há negação entre o início da oração e o termo causal?"""
    clause_start = 0
    for m in CLAUSE_BREAK.finditer(text, 0, start):
        clause_start = m.end()
    return bool(NEGATION.search(text, clause_start, start))


def forbidden_matches(text: str) -> list[str]:
    hits = [m.group(0) for pat in ALWAYS_FORBIDDEN for m in re.finditer(pat, text, flags=re.IGNORECASE)]
    hits += [m.group(0) for pat in CAUSAL for m in re.finditer(pat, text, flags=re.IGNORECASE)
             if not _negated(text, m.start())]
    return hits


class ReportError(ValueError):
    pass


@dataclass
class Trace:
    marcador: str
    tabela: str
    filtro: str
    coluna: str
    valor: object


def _select(df: pd.DataFrame, filt: str, table: str) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for cond in filter(None, filt.split("&")):
        k, v = cond.split("=", 1)
        m &= df[k].astype(str) == v
    rows = df[m]
    if len(rows) != 1:
        raise ReportError(f"{table}|{filt}: {len(rows)} linhas (esperada exatamente 1)")
    return rows.iloc[0]


def _fmt(v, spec: str | None) -> str:
    if spec is None:
        return str(v)
    if spec == "pp":
        return f"{100 * v:.1f} p.p.".replace(".", ",")
    if spec == "pct":
        return f"{100 * v:.1f}%".replace(".", ",")
    if spec == "int":
        return f"{int(v):,}".replace(",", ".")
    return format(v, spec)


def render(template: str, tables: dict[str, pd.DataFrame]) -> tuple[str, list[Trace]]:
    traces: list[Trace] = []

    def sub(m):
        table, filt, col, spec = m.groups()
        if table not in tables:
            raise ReportError(f"tabela {table!r} não exportada")
        v = _select(tables[table], filt, table)[col]
        if pd.isna(v):
            raise ReportError(f"{table}|{filt}|{col}: valor ausente")
        traces.append(Trace(m.group(0), table, filt, col, v))
        return _fmt(v, spec)

    text = PLACEHOLDER.sub(sub, template)
    return text, traces


def lint_template(template: str) -> list[str]:
    """Problemas no modelo antes da renderização."""
    issues = []
    bare = PLACEHOLDER.sub("", template)
    bare = ALLOWED_LITERAL.sub("", bare)
    for line_no, line in enumerate(bare.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for n in NUMBER.findall(line):
            issues.append(f"linha {line_no}: número fixo {n!r} fora de marcador")
    for hit in forbidden_matches(template):
        issues.append(f"frase proibida: {hit!r}")
    return issues


def build(template: str, tables: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
    issues = lint_template(template)
    if issues:
        raise ReportError("modelo reprovado no linter:\n  " + "\n  ".join(issues))
    text, traces = render(template, tables)
    return text, pd.DataFrame([t.__dict__ for t in traces])
