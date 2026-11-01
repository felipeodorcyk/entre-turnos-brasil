"""Contexto municipal (handoff 17, escrito por B): parsing SIDRA, ausência e vínculo TSE, offline."""
import json
from pathlib import Path

import pandas as pd
import pytest

from br2026.contract import validate
from br2026.ingest import contexto_municipal as cm


def payload(var_id, series):
    return json.dumps([{"id": str(var_id), "variavel": "x", "unidade": "u", "resultados": [
        {"classificacoes": [], "series": [{"localidade": {"id": k, "nivel": {"id": "N6"}, "nome": k},
                                           "serie": {"2022": v}} for k, v in series.items()]}]}]).encode()


MAPPING = pd.DataFrame({"sg_uf": ["AC", "AC"], "cd_municipio_tse": ["01007", "01015"],
                        "cd_municipio_ibge": ["1200138", "1200179"]})


def test_parse_numbers_and_missing_markers_never_zero():
    p = payload(93, {"1200138": "20000", "1200179": "-"})
    df = cm.parse_sidra(p, 4714, 2022, "https://x", "a" * 64)
    v = df.set_index("cd_municipio_ibge").valor
    assert v["1200138"] == 20000 and pd.isna(v["1200179"])
    assert set(df.variavel) == {"populacao_residente"}


def test_unrequested_variable_ignored():
    df = cm.parse_sidra(payload(614, {"1200138": "5"}), 4714, 2022, "https://x", "a" * 64)
    assert df.empty


def test_build_context_conforms_and_requires_tse_link():
    parsed = cm.parse_sidra(payload(93, {"1200138": "20000", "1200179": "10000"}), 4714, 2022,
                            "https://x", "a" * 64)
    ctx = cm.build_context(parsed, MAPPING)
    validate(ctx, "municipal_context")
    assert list(ctx.cd_municipio_tse) == ["01007", "01015"]
    with pytest.raises(ValueError, match="sem correspondência TSE"):
        cm.build_context(parsed, MAPPING.iloc[[0]])


def test_run_with_fake_fetch_writes_raw_manifest_and_staging(tmp_path, monkeypatch):
    def fake_fetch(url):
        if "4714" in url:
            return json.dumps(json.loads(payload(93, {"1200138": "20000", "1200179": "10000"}))
                              + json.loads(payload(6318, {"1200138": "3000", "1200179": "1700"}))).encode()
        return payload(37, {"1200138": "360000", "1200179": "..."})
    monkeypatch.setattr(cm, "tse_ibge_map", lambda _p: MAPPING)
    r = cm.run(["AC"], tmp_path, Path("ignorado.zip"), fetch=fake_fetch)
    assert r == {"linhas": 6, "municipios": 2, "ausentes": 1, "arquivos_brutos": 2}
    man = json.loads((tmp_path / "data" / "raw" / "ibge" / "manifest.json").read_text(encoding="utf-8"))
    assert len(man["registros"]) == 2 and all(len(v["sha256"]) == 64 for v in man["registros"].values())
    st = pd.read_parquet(tmp_path / "data" / "staging" / "municipal_context.parquet")
    validate(st, "municipal_context")
    assert not list((tmp_path / "data").rglob("*.tmp"))
