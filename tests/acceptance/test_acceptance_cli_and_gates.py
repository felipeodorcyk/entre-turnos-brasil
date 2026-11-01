"""Testes de interface CLI, reexecução, sandbox e conformidade de Gates (Frente C).

Cobre as diretrizes C2 de 09_REVISAO_E_CONTINUACAO_ANTIGRAVITY.md e Tarefa 4 de 04_HANDOFF_VALIDACAO.md:
1. Sandbox temporário isolado:
   - Sem insumos: status BLOCKED.
   - Insumos válidos: status PASS, geração de artefatos.
   - Insumos inválidos: ContractError / falha de validação.
2. Idempotência e determinismo:
   - Duas chamadas consecutivas de run_panel sobre a mesma fixture produzem saídas idênticas,
     sem introduzir duplicações de chaves e conservando dif == 0.
3. Validação de sintaxe e uso da CLI:
   - `--help` sai com 0.
   - Comando inexistente sai com 2 (EXIT_USAGE).
   - Estágios validate, panel, analyze e report em ambiente limpo sem staging retornam 4 (EXIT_BLOCKED).
4. Proibição de rede na suíte rápida: testes que acessam recursos externos ou staging vivo
   são marcados como `integration`.

Atualização de 26/10/2026 (handoff 17, frente B/Opus — AUTOVERIFICAÇÃO, não revisão
independente de C): R16-2. A ausência de tabelas passa a ser testada numa raiz
temporária controlada (`--root`), e o teste sobre o projeto real verifica o pacote
publicado por A (hashes da entrega) em vez de pressupor uma tabela ausente.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from br2026.cli import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, main
from br2026.contract import PROJECT_ROOT, ContractError, validate_parquet
from br2026.panel.run import run_panel

PYTHON = sys.executable


def make_valid_staging(staging_dir: Path) -> Path:
    """Cria fixtures mínimas válidas em sandbox estritamente aderentes ao contrato v1."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    fix_dir = PROJECT_ROOT / "tests" / "fixtures" / "contract"
    src = "0" * 63 + "a"

    # 1. section_turn
    st = pd.read_csv(fix_dir / "panel_section_turn.csv", dtype=str, keep_default_na=False, na_values=[""])
    counts = [
        "qt_aptos", "qt_comparecimento", "qt_abstencoes", "qt_votos_nominais",
        "qt_votos_legenda", "qt_votos_brancos", "qt_votos_nulos"
    ]
    for c in counts:
        st[c] = pd.to_numeric(st[c]).astype("int64")
    for b in ["st_secao_instalada", "st_secao_anulada"]:
        st[b] = st[b].map({"True": True, "False": False}).astype("boolean")
    st["nr_turno"] = st.nr_turno.astype("int8")
    st.insert(0, "ano", np.int16(2026).astype("int16"))
    st.insert(1, "cd_eleicao", st.nr_turno.map({1: "6257", 2: "6258"}))
    st["cd_cargo"] = np.int16(1).astype("int16")
    st["qt_votos_anulados_apu_sep"] = np.int64(0)
    st["ds_origem_voto"] = "Urna Eletrônica"
    st["flag_identidade_aptos"] = (st.qt_aptos == st.qt_comparecimento + st.qt_abstencoes).astype("boolean")
    st["flag_identidade_comparecimento"] = (
        st.qt_comparecimento == st.qt_votos_nominais + st.qt_votos_legenda
        + st.qt_votos_brancos + st.qt_votos_nulos
    ).astype("boolean")
    st["source_id"] = src
    st.to_parquet(staging_dir / "section_turn.parquet", index=False)

    # 2. votes_long
    vl = pd.read_csv(fix_dir / "panel_votes.csv", dtype=str, keep_default_na=False, na_values=[""])
    vl["qt_votos"] = pd.to_numeric(vl["qt_votos"]).astype("int64")
    vl["nr_turno"] = vl.nr_turno.astype("int8")
    vl["nr_votavel"] = vl.nr_votavel.astype("int32")
    vl.insert(0, "ano", np.int16(2026).astype("int16"))
    vl.insert(1, "cd_eleicao", vl.nr_turno.map({1: "6257", 2: "6258"}))
    vl["cd_cargo"] = np.int16(1).astype("int16")
    vl["tipo_votavel"] = vl.nr_votavel.map({95: "BRANCO", 96: "NULO"}).fillna("NOMINAL")
    vl["sq_candidato"] = np.where(vl.tipo_votavel == "NOMINAL", "28000" + vl.nr_votavel.astype(str), None)
    vl["source_id"] = src
    vl.to_parquet(staging_dir / "votes_long.parquet", index=False)

    # 3. section_crosswalk
    cw = pd.read_csv(fix_dir / "panel_crosswalk.csv", dtype=str, keep_default_na=False, na_values=[""])
    cw["nr_turno"] = cw.nr_turno.astype("int8")
    cw.insert(0, "ano", np.int16(2026).astype("int16"))
    cw["nr_local_votacao_original"] = cw.nr_local_votacao
    cw["fonte"] = "fixture"
    cw["justificativa"] = None
    cw["flag_ambigua"] = False
    cw.insert(cw.columns.get_loc("tipo_correspondencia") + 1, "status_correspondencia", "EFETIVADA")
    cw["source_id"] = src
    cw.to_parquet(staging_dir / "section_crosswalk.parquet", index=False)

    return staging_dir


def test_run_panel_sandbox_blocked_when_staging_empty(tmp_path: Path):
    """Valida que run_panel em staging vazio retorna BLOCKED sem produzir artefatos (C2)."""
    empty_stg = tmp_path / "empty_staging"
    empty_stg.mkdir()
    out = tmp_path / "out"

    res = run_panel(empty_stg, out)
    assert res["status"] == "BLOCKED"
    assert "staging ausente" in res["motivo"]
    assert not out.exists() or not (out / "panel.parquet").exists()


def test_run_panel_sandbox_pass_with_valid_staging(tmp_path: Path):
    """Valida que run_panel com staging válido executa com status PASS e gera artefatos esperados (C2)."""
    staging = make_valid_staging(tmp_path / "staging")
    out = tmp_path / "out"

    res = run_panel(staging, out)
    assert res["status"] == "PASS"
    assert res["problemas"] == []
    assert res["unidades"] == 6
    assert res["pareadas"] == 3

    # Validação da integridade dos arquivos gerados
    assert (out / "panel.parquet").exists()
    assert (out / "panel_membership.parquet").exists()
    assert (out / "panel_reconciliation.csv").exists()
    assert (out / "coverage_uf.csv").exists()
    assert (out / "coverage_municipio.csv").exists()


def test_run_panel_sandbox_idempotence_and_determinism(tmp_path: Path):
    """Valida a idempotência: reexecuções consecutivas conservam registros e não geram duplicatas (C2)."""
    staging = make_valid_staging(tmp_path / "staging")
    out = tmp_path / "out"

    # 1ª Execução
    res1 = run_panel(staging, out)
    assert res1["status"] == "PASS"
    panel1 = pd.read_parquet(out / "panel.parquet")
    rec1 = pd.read_csv(out / "panel_reconciliation.csv")

    # 2ª Execução sobre o mesmo diretório de saída
    res2 = run_panel(staging, out)
    assert res2["status"] == "PASS"
    panel2 = pd.read_parquet(out / "panel.parquet")
    rec2 = pd.read_csv(out / "panel_reconciliation.csv")

    # Determinismo estrito
    pd.testing.assert_frame_equal(panel1, panel2)
    pd.testing.assert_frame_equal(rec1, rec2)
    assert len(panel2) == 6
    assert panel2["id_unidade"].nunique() == 6, "Chave primária id_unidade duplicada na reexecução"
    assert (rec2["dif"] == 0).all(), "Reconciliação introduziu discrepâncias na reexecução"


def test_sandbox_invalid_inputs_fail_contract(tmp_path: Path):
    """Valida que insumo adulterado ou em não-conformidade com o contrato v1 falha com ContractError (C2)."""
    staging = tmp_path / "invalid_staging"
    staging.mkdir()

    # Cria tabela section_turn deliberadamente mutilada (ausência de colunas obrigatórias)
    invalid_st = pd.DataFrame([
        {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001", "nr_secao": "0001"}
    ])
    invalid_st.to_parquet(staging / "section_turn.parquet", index=False)

    with pytest.raises(ContractError):
        validate_parquet(staging / "section_turn.parquet", "section_turn")


def test_cli_argument_parsing_and_usage():
    """Valida códigos de saída de sintaxe e argumentos (--help -> 0, inválido -> 2) (C2)."""
    with pytest.raises(SystemExit) as exc_help:
        main(["--help"])
    assert exc_help.value.code == EXIT_OK

    with pytest.raises(SystemExit) as exc_invalid:
        main(["comando_inexistente"])
    assert exc_invalid.value.code == EXIT_USAGE


def test_cli_pipeline_stages_return_blocked_on_clean_environment(tmp_path: Path):
    """Etapas retornam exit 4 (BLOCKED) numa raiz limpa isolada via --root (C2; R16-2)."""
    clean_root = tmp_path / "clean_project_root"
    clean_root.mkdir()
    for cmd in (["validate"], ["panel"], ["analyze"], ["report"]):
        assert main(["--root", str(clean_root)] + cmd) == EXIT_BLOCKED, cmd


def _validate_lines(stdout: str) -> dict:
    out = {}
    for line in stdout.splitlines():
        if ": " in line and line.split(": ", 1)[1].split()[0] in ("PASS", "FAIL", "BLOCKED"):
            name, rest = line.split(": ", 1)
            out[name.strip()] = rest.split()[0]
    return out


def test_cli_validate_reports_controlled_absence_in_temp_root(tmp_path: Path):
    """Ausência controlada: só section_turn/votes_long presentes numa raiz temporária."""
    staging = tmp_path / "root" / "data" / "staging"
    make_valid_staging(staging)
    for extra in ("section_crosswalk.parquet",):
        (staging / extra).unlink(missing_ok=True)
    res = subprocess.run([PYTHON, "-m", "br2026", "--root", str(tmp_path / "root"), "validate"],
                         cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8")
    st = _validate_lines(res.stdout)
    assert res.returncode == EXIT_BLOCKED
    assert st["section_turn"] == "PASS" and st["votes_long"] == "PASS"
    assert st["section_crosswalk"] == "BLOCKED" and st["closure"] == "BLOCKED"


def _inventario():
    """Inventário por partição do pacote publicado (R30-2; `tools/inventario_staging.py`)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("inventario_staging",
                                                  PROJECT_ROOT / "tools" / "inventario_staging.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parquet_minimo(p: Path, v: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"x": [v]}).to_parquet(p, index=False)


def test_inventario_aponta_adulteracao_particao_ausente_e_a_mais(tmp_path):
    inv = _inventario()
    st = tmp_path / "staging"
    for nome in ("AC_T1", "AC_T2"):
        _parquet_minimo(st / "votes_long" / f"{nome}.parquet", 1)
    esperado = inv.inventariar(st)
    assert inv.conferir(st, esperado) == []
    _parquet_minimo(st / "votes_long" / "AC_T2.parquet", 2)              # adulterada
    (st / "votes_long" / "AC_T1.parquet").unlink()                         # ausente
    _parquet_minimo(st / "votes_long" / "RS_T1.parquet", 1)              # a mais
    prob = inv.conferir(st, esperado)
    assert "votes_long/AC_T2.parquet: hash difere do inventário" in prob
    assert "votes_long/AC_T1.parquet: partição ausente" in prob
    assert "votes_long/RS_T1.parquet: partição fora do inventário" in prob


@pytest.mark.integration
def test_live_cli_validate_published_package():
    """Projeto real: cada partição publicada confere com o inventário e cada tabela passa no contrato."""
    import json
    inv = _inventario()
    alvo = PROJECT_ROOT / inv.INVENTARIO
    js = json.loads(alvo.read_text(encoding="utf-8"))
    pkg = js["particoes"]
    assert set(pkg) == {"votes_long", "section_turn", "profiles", "closure", "section_crosswalk"}
    assert all(pkg.values()), "tabela sem partição no inventário"
    assert inv.conferir(PROJECT_ROOT / "data" / "staging", pkg) == []
    # produtos socioeconômicos (handoff 37): mesma conferência de adulteração, ausência e excesso
    socio = js.get("particoes_socio", {})
    assert set(socio) == set(inv.SOCIO) and all(socio.values()), "produtos socioeconômicos fora do inventário"
    assert inv.conferir(PROJECT_ROOT / "data" / "staging", socio, inv.SOCIO) == []
    for name in pkg:
        res = subprocess.run([PYTHON, "-m", "br2026", "--root", str(PROJECT_ROOT), "validate", "--table", name],
                             cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8")
        assert res.returncode == EXIT_OK and f"{name}: PASS" in res.stdout, res.stdout
