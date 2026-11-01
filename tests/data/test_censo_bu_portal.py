"""Censo de BU do portal (handoff 29): coleta, retomada e integração ao closure."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tools"))

import censo_bu  # noqa: E402
from br2026.analysis.closure_tz import parse_naive_series  # noqa: E402
from br2026.contract import validate  # noqa: E402
from br2026.normalize import _construir_closure_bu_portal, _ler_bu_portal  # noqa: E402


class _ClienteFalso:
    """Responde por sufixo de caminho; status 0 = erro de rede."""

    def __init__(self, respostas: dict[str, tuple[int, bytes | None]]):
        self.respostas = respostas

    def get(self, caminho: str):
        for suf, r in self.respostas.items():
            if caminho.endswith(suf):
                return r
        return 404, None


def _aux(nm="o00407-0100700090001.bu", st="Totalizado"):
    return json.dumps({"hashes": [{"hash": "abc", "st": st, "arq": [{"nm": nm, "tp": "bu"}]}]}).encode()


def test_buscar_classifica_falhas_sem_inventar_horario(monkeypatch):
    # 404 no aux: terminal, sem horário
    r, aux, dat = censo_bu.buscar(_ClienteFalso({}), 3221, "AC", "01007", "0009", "0001")
    assert r["status"] == "SEM_AUX" and aux is None and dat is None
    # erro de rede: não terminal (refeito na retomada)
    r, *_ = censo_bu.buscar(_ClienteFalso({"aux.json": (0, None)}), 3221, "AC", "01007", "0009", "0001")
    assert r["status"] == "ERRO_REDE" and r["status"] not in censo_bu.TERMINAIS
    # BU de outra seção: identificação diverge e o status não é OK
    monkeypatch.setattr(censo_bu, "decodificar_bu", lambda b: {
        "municipio": 1007, "zona": 9, "local": 1, "secao": 2, "emissao": "20261025T170500",
        "abertura": "20261025T080001", "encerramento": "20261025T170100"})
    cli = _ClienteFalso({"aux.json": (200, _aux()), ".bu": (200, b"\x30\x00")})
    r, aux, dat = censo_bu.buscar(cli, 3221, "AC", "01007", "0009", "0001")
    assert r["status"] == "IDENTIFICACAO_DIVERGE" and dat == b"\x30\x00"
    assert r["sha256"] and r["bu_encerramento"] == "20261025T170100"


def test_retomada_refaz_so_o_que_nao_terminou(tmp_path, monkeypatch):
    pasta = tmp_path / "data" / "raw" / "bu_portal" / "censo_3221"
    pasta.mkdir(parents=True)
    linhas = [{"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0009", "nr_secao": "0001", "status": "OK"},
              {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0009", "nr_secao": "0002", "status": "ERRO_REDE"}]
    (pasta / "resultados.jsonl").write_text("\n".join(json.dumps(x) for x in linhas) + "\n{truncada",
                                            encoding="utf-8")
    uni = pd.DataFrame({"sg_uf": ["AC"] * 3, "cd_municipio_tse": ["01007"] * 3, "nr_zona": ["0009"] * 3,
                        "nr_secao": ["0001", "0002", "0003"]})
    pedidas = []
    monkeypatch.setattr(censo_bu, "RAIZ", tmp_path)
    monkeypatch.setattr(censo_bu, "universo", lambda p, s: uni)

    def falso(cli, pleito, uf, m, z, s):
        pedidas.append(s)
        return {"pleito": pleito, "sg_uf": uf, "cd_municipio_tse": m, "nr_zona": z, "nr_secao": s,
                "bytes": 0, "status": "SEM_AUX"}, None, None
    monkeypatch.setattr(censo_bu, "buscar", falso)
    assert censo_bu.main(["--paralelo", "1", "--max-req-s", "0"]) == 0
    assert sorted(pedidas) == ["0002", "0003"]   # 0001 já OK; linha truncada ignorada
    assert (pasta / "execucoes.jsonl").exists()


def test_closure_do_portal_so_com_ok_e_bruto_preservado(tmp_path):
    raw = tmp_path / "data" / "raw"
    (raw / "bu_portal" / "censo_3221").mkdir(parents=True)
    res = raw / "bu_portal" / "censo_3221" / "resultados.jsonl"
    base = {"pleito": 3221, "sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0009"}
    linhas = [{**base, "nr_secao": "0001", "status": "OK", "sha256": "a" * 64, "bu_abertura": "20261025T060001",
               "bu_encerramento": "20261025T170102", "bu_emissao": "20261025T170330"},
              {**base, "nr_secao": "0002", "status": "IDENTIFICACAO_DIVERGE", "sha256": "b" * 64,
               "bu_abertura": "20261025T060001", "bu_encerramento": "20261025T190500", "bu_emissao": "x"},
              {**base, "nr_secao": "0003", "status": "ERRO_REDE"},
              {**base, "nr_secao": "0003", "status": "OK", "sha256": "c" * 64, "bu_abertura": "20261025T060002",
               "bu_encerramento": "20261025T190012", "bu_emissao": "20261025T190200"}]
    res.write_text("\n".join(json.dumps(x) for x in linhas) + "\n", encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(res.read_bytes()).hexdigest()
    man = {"registros": {"bu_portal_censo_3221": {"arquivo": "bu_portal/censo_3221/resultados.jsonl",
                                                    "sha256": sha}}}
    bu, sha_lido, cont = _ler_bu_portal(tmp_path, man, "AC", 2)
    assert sha_lido == sha and cont == {"OK": 2, "IDENTIFICACAO_DIVERGE": 1}
    cl = _construir_closure_bu_portal(bu, sha, "AC", 2)
    validate(cl, "closure")
    assert set(cl.nr_secao) == {"0001", "0003"}          # divergente fora; retomada vale a última
    enc = cl[cl.semantica == "ENCERRAMENTO_URNA"].set_index("nr_secao")
    assert enc.at["0003", "ts_bruto"] == "20261025T190012" and enc.at["0003", "id_bu"] == "c" * 64
    assert not cl.flag_anomalia.any() and (cl.source_id == sha).all()
    assert parse_naive_series(enc.ts_bruto).dt.hour.tolist() == [17, 19]
