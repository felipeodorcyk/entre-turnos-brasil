"""O-R4 (revisão 10): CLI isolada em raiz temporária, sem rede e sem tocar o projeto real.

As etapas de A são substituídas por módulos simulados injetados em sys.modules;
o código real de ingestão/normalização nunca é executado aqui.
"""
import importlib.util
import socket
import sys
import types
from pathlib import Path

import pytest

from br2026.cli import (EXIT_BLOCKED, EXIT_NOT_IMPLEMENTED, EXIT_OK, EXIT_STAGE_ERROR, main)
from br2026.contract import PROJECT_ROOT
from br2026.interfaces import StageResult

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "synth_staging.py"


def fake_stage(monkeypatch, name, run=None):
    mod = types.ModuleType(f"br2026.{name}")
    calls = []
    if run is not None:
        def _run(uf, turno, project_root, **kw):
            calls.append({"uf": uf, "turno": turno, "root": Path(project_root), **kw})
            return run(uf, turno, project_root, **kw)
        mod.run = _run
    monkeypatch.setitem(sys.modules, f"br2026.{name}", mod)
    return calls


def ok_result(*_a, **_k):
    return StageResult("ingest", (), {"linhas": 1})


def test_implementation_present_receives_injected_root(monkeypatch, tmp_path):
    calls = fake_stage(monkeypatch, "ingest", ok_result)
    assert main(["--root", str(tmp_path), "ingest", "--uf", "AC", "--turno", "1", "--force"]) == EXIT_OK
    assert calls == [{"uf": "AC", "turno": 1, "root": tmp_path.resolve(), "force": True}]


def test_root_from_environment(monkeypatch, tmp_path):
    calls = fake_stage(monkeypatch, "normalize", lambda *a, **k: StageResult("normalize", (), {}))
    monkeypatch.setenv("BR2026_ROOT", str(tmp_path))
    assert main(["normalize", "--uf", "RS", "--turno", "1"]) == EXIT_OK
    assert calls[0]["root"] == tmp_path.resolve()


def test_stage_reporting_blockers_returns_blocked(monkeypatch, tmp_path):
    fake_stage(monkeypatch, "ingest",
               lambda *a, **k: StageResult("ingest", (), {}, bloqueios=("fonte ausente",)))
    assert main(["--root", str(tmp_path), "ingest", "--uf", "MG", "--turno", "2"]) == EXIT_BLOCKED


def test_controlled_failure_is_reported_not_raised(monkeypatch, tmp_path, capsys):
    def boom(*a, **k):
        raise OSError("falha simulada de aquisição")
    fake_stage(monkeypatch, "ingest", boom)
    assert main(["--root", str(tmp_path), "ingest", "--uf", "RS", "--turno", "1"]) == EXIT_STAGE_ERROR
    assert "FALHA OSError: falha simulada" in capsys.readouterr().err


def test_module_without_run_is_not_implemented(monkeypatch, tmp_path):
    fake_stage(monkeypatch, "normalize")
    assert main(["--root", str(tmp_path), "normalize", "--uf", "RS", "--turno", "1"]) == EXIT_NOT_IMPLEMENTED


@pytest.mark.parametrize("cmd", [["validate"], ["panel"], ["analyze"], ["report"]])
def test_methodological_stages_blocked_on_empty_root(tmp_path, cmd):
    assert main(["--root", str(tmp_path)] + cmd) == EXIT_BLOCKED
    assert not (tmp_path / "reports").exists()


def test_full_methodological_pipeline_inside_temporary_root(tmp_path):
    spec = importlib.util.spec_from_file_location("synth_staging", FIX)
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    synth.make_staging(tmp_path / "data" / "staging")
    for cmd in (["validate", "--table", "section_turn"], ["panel"], ["analyze"], ["report"]):
        assert main(["--root", str(tmp_path)] + cmd) == EXIT_OK, cmd
    assert (tmp_path / "data" / "analytics" / "analysis_manifest.json").exists()
    assert (tmp_path / "reports" / "analysis" / "relatorio.md").exists()


def test_network_is_blocked_in_fast_suite():
    with pytest.raises(RuntimeError, match="rede proibida"):
        socket.create_connection(("cdn.tse.jus.br", 443), timeout=1)


def test_project_root_is_not_the_temporary_root(tmp_path):
    assert PROJECT_ROOT.resolve() != tmp_path.resolve()
