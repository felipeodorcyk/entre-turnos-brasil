"""DoD 7: números rastreáveis, sem números fixos e sem narrativa causal/de transferência."""
import pandas as pd
import pytest

from br2026.reporting.report import ReportError, build, lint_template

TABLES = {"agregado": pd.DataFrame({"universo": ["pareado_nacional"], "share_lula_t1": [0.4375],
                                    "delta_qt_lula": [20], "n_unidades": [3]})}


def test_render_with_trace():
    tpl = ("No universo pareado ({{agregado|universo=pareado_nacional|n_unidades|int}} unidades), "
           "a participação de Lula no 1º turno foi {{agregado|universo=pareado_nacional|share_lula_t1|pct}}.")
    text, trace = build(tpl, TABLES)
    assert "43,8%" in text and len(trace) == 2
    assert set(trace.tabela) == {"agregado"}


def test_hard_coded_number_rejected():
    issues = lint_template("Lula ganhou 20 votos em 2026.")
    assert any("número fixo '20'" in i for i in issues)


@pytest.mark.parametrize("phrase", ["Eleitores de Ciro votaram em Lula", "a abstenção causou",
                                    "os eleitores transferiram", "quem votou após 17h... votaram após 17h",
                                    "margem de erro dos votos"])
def test_forbidden_narratives(phrase):
    assert any("frase proibida" in i for i in lint_template(phrase))


def test_missing_row_or_table_fails():
    with pytest.raises(ReportError):
        build("{{agregado|universo=outro|share_lula_t1|pct}}", TABLES)
    with pytest.raises(ReportError):
        build("{{inexistente||x}}", TABLES)


@pytest.mark.parametrize("phrase", ["há relação causal", "impacto causal do horário", "prova de causalidade",
                                    "eleitores admitidos até 19h"])
def test_forbidden_synonyms_from_review(phrase):
    """Achado F-05 de C."""
    assert any("frase proibida" in i for i in lint_template(phrase))


@pytest.mark.parametrize("phrase", [
    "Esta análise não demonstra causalidade.",
    "Associações entre unidades não estabelecem relação causal.",
    "Os coeficientes não são efeitos causais do horário.",
    "Sem desenho experimental, não há como afirmar que o horário causou a variação.",
])
def test_legitimate_causal_disclaimers_accepted(phrase):
    """O-R5: ressalva negada na mesma oração não é alegação causal."""
    assert lint_template(phrase) == []


@pytest.mark.parametrize("phrase", [
    "A abstenção causou a virada.",
    "Os dados mostram causalidade entre horário e voto.",
    "Não só houve associação, mas o horário teve impacto causal.",
    "Não apenas correlação: há relação causal clara.",
    "Os eleitores não transferiram votos de Ciro para Lula.",   # transferência é sempre proibida
])
def test_improper_claims_still_flagged(phrase):
    assert any("frase proibida" in i for i in lint_template(phrase))
