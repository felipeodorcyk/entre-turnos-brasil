"""Linter de integridade narrativa, alegações indevidas e triagem contextual (Frente C).

Cobre a Tarefa 7 e orientações C4 de 09_REVISAO_E_CONTINUACAO_ANTIGRAVITY.md:
1. Detectar alegações metodologicamente indevidas (afirmações positivas de causalidade,
   população cadastral como votantes, margem de erro dos votos, eleitores após 17h).
2. Distinguir afirmações indevidas de ressalvas científicas legítimas
   ("não demonstra causalidade", "não sabemos em quem votaram após as 17h",
   "não reflete o perfil dos votantes").
3. Triagem contextual estruturada com separação entre violações e ressalvas válidas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Padrões de alegações indevidas a monitorar
PROHIBITED_PATTERNS = {
    "CADASTRO_AS_VOTERS": [
        r"\bperfil dos votantes\b",
        r"\beleitores votantes\b",
        r"\bperfil do eleitorado votante\b",
        r"\bcaracter[ií]sticas dos que votaram\b",
        r"\bescolha individual dos votantes\b",
        r"\bvotantes de \d+ a \d+ anos\b",
        r"\bvotantes com (?:ensino|fundamental|m[ée]dio|superior)\b",
    ],
    "ASSOCIATION_AS_CAUSALITY": [
        r"\befeito causal\b",
        r"\brela[cç][aã]o causal\b",
        r"\bimpacto causal\b",
        r"\binterpreta[cç][aã]o causal\b",
        r"\batribui[cç][aã]o causal\b",
        r"\bcausalidade\b",
        r"\bcausou\b",
        r"\bdeterminou a vit[oó]ria\b",
        r"\bprovocou o aumento\b",
        r"\befeito de abrir at[eé] 19h\b",
    ],
    "MODEL_INTERVAL_AS_VOTE_MARGIN_OF_ERROR": [
        r"\bmargem de erro dos votos\b",
        r"\bmargem de erro da vota[cç][aã]o\b",
        r"\berro amostral da apura[cç][aã]o\b",
        r"\berro amostral dos votos\b",
        r"\bintervalo de confian[cç]a da contagem\b",
    ],
    "LATE_SECTION_AS_LATE_VOTERS": [
        r"\bnovos eleitores admitidos\b",
        r"\badmitidos at[eé] 19h\b",
        r"\badmitidos ap[oó]s (?:as )?17h\b",
        r"\beleitores que votaram ap[oó]s (?:as )?17h\b",
        r"\bvotaram ap[oó]s (?:as )?17h\b",
        r"\beleitores retardat[aá]rios\b",
        r"\bvota[cç][aã]o de novos eleitores\b",
    ],
}

# Indicadores de negação, ressalva ou disclaimer legítimo que antecedem o termo
NEGATION_PATTERNS = [
    r"\bn[aã]o\s+(?:h[aá]|demonstra|implica|reflete|sabemos|podemos|deve|constitui|significa|permite)\b",
    r"\bn[aã]o\b",
    r"\bsem\s+(?:interpreta[cç][aã]o|atribui[cç][aã]o|demonstra[cç][aã]o)\b",
    r"\bsem\b",
    r"\bimposs[ií]vel\s+(?:de\s+)?(?:inferir|atribuir|determinar|saber)\b",
    r"\bincerteza\s+condicional\b",
]

_NEGATION_REGEX = re.compile(
    r"(?:" + "|".join(NEGATION_PATTERNS) + r")(?:\s+\w+){0,6}\s*$",
    flags=re.IGNORECASE,
)


@dataclass
class LinterAuditResult:
    violations: dict[str, list[str]] = field(default_factory=dict)
    legitimate_caveats: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0


class AcceptanceLinter:
    """Linter contextual de aceite da Frente C."""

    @classmethod
    def audit(cls, text: str) -> LinterAuditResult:
        result = LinterAuditResult()

        for category, patterns in PROHIBITED_PATTERNS.items():
            for pat in patterns:
                for match in re.finditer(pat, text, flags=re.IGNORECASE):
                    start_idx = match.start()
                    # Analisar a janela de texto antecedente (até 60 caracteres antes)
                    prefix_window = text[max(0, start_idx - 60):start_idx].strip()

                    # Verificar se a ocorrência está sob escopo de ressalva/negação legítima
                    if _NEGATION_REGEX.search(prefix_window):
                        result.legitimate_caveats.setdefault(category, []).append(match.group(0))
                    else:
                        result.violations.setdefault(category, []).append(match.group(0))

        return result

    @classmethod
    def find_violations(cls, text: str) -> dict[str, list[str]]:
        return cls.audit(text).violations


def test_linter_detects_positive_violations():
    """Valida que afirmações positivas indevidas são capturadas como violações."""
    bad_texts = [
        ("CADASTRO_AS_VOTERS", "O perfil dos votantes mostrou maior preferência no segundo turno."),
        ("ASSOCIATION_AS_CAUSALITY", "O modelo encontrou efeito causal significativo na votação."),
        ("ASSOCIATION_AS_CAUSALITY", "A abstenção causou a perda de vantagem do candidato."),
        ("ASSOCIATION_AS_CAUSALITY", "A relação causal entre idade e voto foi confirmada."),
        ("MODEL_INTERVAL_AS_VOTE_MARGIN_OF_ERROR", "A margem de erro dos votos apurados na seção ficou em 2%."),
        ("LATE_SECTION_AS_LATE_VOTERS", "Os eleitores que votaram após as 17h decidiram a eleição."),
        ("LATE_SECTION_AS_LATE_VOTERS", "Houve votação de novos eleitores admitidos até 19h."),
    ]
    for category, text in bad_texts:
        res = AcceptanceLinter.audit(text)
        assert category in res.violations, f"Esperada violação de {category} em: {text!r}"
        assert not res.is_clean


def test_linter_respects_legitimate_caveats_without_false_positives():
    """Valida que ressalvas e negações científicas legítimas NÃO são tratadas como violações (C4).

    Exemplos obrigatórios de 09_REVISAO_E_CONTINUACAO_ANTIGRAVITY.md:
    - 'Esta análise não demonstra causalidade'
    - 'Não sabemos em quem votaram após as 17h'
    - 'O perfil cadastral não reflete o perfil dos votantes'
    """
    legitimate_caveats = [
        "Esta análise não demonstra causalidade.",
        "Não há evidência de efeito causal entre o horário e o desfecho.",
        "Sem interpretação causal para os coeficientes estimados.",
        "Não sabemos em quem votaram após as 17h.",
        "É impossível inferir em quem votaram após as 17h a partir do boletim de urna.",
        "O perfil cadastral não reflete o perfil dos votantes observados.",
        "Não constitui margem de erro dos votos, mas incerteza do modelo estatístico.",
    ]
    for text in legitimate_caveats:
        res = AcceptanceLinter.audit(text)
        assert res.is_clean, f"Ressalva legítima tratada indevidamente como violação: {text!r} -> {res.violations}"
        assert len(res.legitimate_caveats) > 0, f"Ressalva não foi devidamente classificada como caveat em: {text!r}"


def test_linter_separates_caveats_from_violations_in_mixed_text():
    """Valida que texto misto contendo ressalva e violação separa adequadamente cada uma."""
    mixed_text = (
        "Esta análise não demonstra causalidade entre as variáveis. "
        "Contudo, a abstenção causou a mudança no total de votos."
    )
    res = AcceptanceLinter.audit(mixed_text)
    # A primeira menção (não demonstra causalidade) vai para caveats
    assert "ASSOCIATION_AS_CAUSALITY" in res.legitimate_caveats
    # A segunda menção (causou a mudança) vai para violations
    assert "ASSOCIATION_AS_CAUSALITY" in res.violations
    assert not res.is_clean


def test_linter_audit_on_clean_scientific_report():
    """Valida texto de relatório com linguagem científica descritiva rigorosa."""
    clean_report = (
        "Utilizou-se o cadastro eleitoral como característica dos eleitores aptos da seção. "
        "A análise associativa estima coeficientes de regressão com erros-padrão agrupados, "
        "sem alegação de causalidade ou determinação individual. "
        "O intervalo condicional ao modelo mensura a variabilidade amostral do estimador, "
        "não devendo ser interpretado como margem de erro dos votos apurados. "
        "As seções com encerramento posterior às 17h foram comparadas quanto à votação da seção inteira."
    )
    res = AcceptanceLinter.audit(clean_report)
    assert res.is_clean
    assert len(res.violations) == 0
