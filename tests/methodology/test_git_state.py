"""R23-5: falha na consulta ao Git nunca vira atestado de código limpo."""
import subprocess

import pytest

from br2026.analysis import run as run_mod


def _fake(results):
    def fake_run(cmd, **kw):
        r = results[cmd[1]]
        if isinstance(r, Exception):
            raise r
        return subprocess.CompletedProcess(cmd, r[0], stdout=r[1], stderr=r[2])
    return fake_run


@pytest.mark.parametrize("status, esperado", [
    ((0, "", ""), False),                        # árvore limpa de verdade
    ((0, " M src/x.py\n", ""), True),            # alteração
    ((128, "", "fatal: must be run in a work tree"), None),   # caso da revisão 23
    (OSError("sem git"), None),
])
def test_status_falho_vira_desconhecido(monkeypatch, tmp_path, status, esperado):
    monkeypatch.setattr(run_mod.subprocess, "run", _fake({"rev-parse": (0, "abc123\n", ""), "status": status}))
    commit, dirty, diag = run_mod.git_state(tmp_path)
    assert commit == "abc123"
    assert dirty is esperado
    assert (diag is None) == (esperado is not None)


def test_rev_parse_falho(monkeypatch, tmp_path):
    monkeypatch.setattr(run_mod.subprocess, "run", _fake({"rev-parse": (128, "", "not a repo"), "status": (0, "", "")}))
    assert run_mod.git_state(tmp_path)[:2] == (None, None)
