"""Testes do exportador web com fixture sintética pequena.

A fixture cobre: dois municípios de pesos distintos, denominador zero,
ausência de contexto, ausência de geometria e fronteira de faixa. Nunca é
publicada como eleição real: vive só no diretório temporário do teste.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/web_export"))

import export_web_release as exporter  # noqa: E402

COUNT = exporter.COUNT_FIELDS


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def _metrics(rows: list[dict]) -> dict[str, int]:
    return {field: int(rows[0].get(field, 0)) for field in COUNT}


def build_fixture(base: Path) -> exporter.Inputs:
    base.mkdir(parents=True, exist_ok=True)

    municipios = [
        {
            "sg_uf": "AA",
            "cd_municipio_tse": "00001",
            "n_unidades": 10,
            "qt_aptos_t1": 100,
            "qt_aptos_t2": 100,
            "qt_comparecimento_t1": 80,
            "qt_comparecimento_t2": 80,
            "qt_abstencoes_t1": 20,
            "qt_abstencoes_t2": 20,
            "qt_votos_validos_t1": 50,
            "qt_votos_validos_t2": 50,
            "qt_votos_brancos_t1": 5,
            "qt_votos_brancos_t2": 4,
            "qt_votos_nulos_t1": 5,
            "qt_votos_nulos_t2": 4,
            "qt_lula_t1": 30,
            "qt_lula_t2": 40,
            "qt_flavio_t1": 20,
            "qt_flavio_t2": 10,
        },
        {
            "sg_uf": "BB",
            "cd_municipio_tse": "00002",
            "n_unidades": 30,
            "qt_aptos_t1": 300,
            "qt_aptos_t2": 300,
            "qt_comparecimento_t1": 240,
            "qt_comparecimento_t2": 240,
            "qt_abstencoes_t1": 60,
            "qt_abstencoes_t2": 60,
            "qt_votos_validos_t1": 200,
            "qt_votos_validos_t2": 200,
            "qt_votos_brancos_t1": 20,
            "qt_votos_brancos_t2": 20,
            "qt_votos_nulos_t1": 20,
            "qt_votos_nulos_t2": 20,
            "qt_lula_t1": 100,
            "qt_lula_t2": 100,
            "qt_flavio_t1": 100,
            "qt_flavio_t2": 100,
        },
        {
            "sg_uf": "AA",
            "cd_municipio_tse": "00003",
            "n_unidades": 1,
            **{field: 0 for field in COUNT},
        },
        {
            "sg_uf": "BB",
            "cd_municipio_tse": "00004",
            "n_unidades": 5,
            "qt_aptos_t1": 50,
            "qt_aptos_t2": 50,
            "qt_comparecimento_t1": 40,
            "qt_comparecimento_t2": 40,
            "qt_abstencoes_t1": 10,
            "qt_abstencoes_t2": 10,
            "qt_votos_validos_t1": 30,
            "qt_votos_validos_t2": 30,
            "qt_votos_brancos_t1": 3,
            "qt_votos_brancos_t2": 3,
            "qt_votos_nulos_t1": 3,
            "qt_votos_nulos_t2": 3,
            "qt_lula_t1": 10,
            "qt_lula_t2": 10,
            "qt_flavio_t1": 20,
            "qt_flavio_t2": 20,
        },
    ]
    _write_csv(base / "metrics_municipio.csv", municipios, ["sg_uf", "cd_municipio_tse", "n_unidades", *COUNT])

    uf_rows = []
    for uf in ("AA", "BB"):
        rows = [m for m in municipios if m["sg_uf"] == uf]
        uf_rows.append({"sg_uf": uf, "universo": "pareado_territorial", "n_unidades": sum(m["n_unidades"] for m in rows), **{f: sum(m[f] for m in rows) for f in COUNT}})
    total = {"sg_uf": "TOTAL", "universo": "pareado_territorial", "n_unidades": sum(m["n_unidades"] for m in municipios), **{f: sum(m[f] for m in municipios) for f in COUNT}}
    _write_csv(base / "metrics_uf.csv", [*uf_rows, total], ["sg_uf", "universo", "n_unidades", *COUNT])

    pd.DataFrame([{"universo": "pareado_territorial", "metrica": "share_lula_validos_t2", "valor": 0.5, "n_unidades": 4}]).to_csv(
        base / "metrics_aggregate.csv", index=False
    )

    socio_rows = [
        {"sg_uf": "AA", "cd_municipio_tse": "00001", "renda_pc": 1000.0, "baixa_renda": 30.0, "desocupacao": 5.0, "vinculos": 200.0, "pbf": 10.0, "urbana": 80.0},
        {"sg_uf": "BB", "cd_municipio_tse": "00002", "renda_pc": 500.0, "baixa_renda": 60.0, "desocupacao": 10.0, "vinculos": 100.0, "pbf": None, "urbana": 50.0},
        {"sg_uf": "AA", "cd_municipio_tse": "00003", "renda_pc": None, "baixa_renda": None, "desocupacao": None, "vinculos": None, "pbf": None, "urbana": None},
        {"sg_uf": "BB", "cd_municipio_tse": "00004", "renda_pc": 2000.0, "baixa_renda": 10.0, "desocupacao": 2.0, "vinculos": 300.0, "pbf": 100.0, "urbana": 95.0},
    ]
    _write_csv(base / "painel_socio.csv", socio_rows, ["sg_uf", "cd_municipio_tse", *exporter.SOCIO_FIELDS])

    _write_csv(
        base / "coverage.csv",
        [{"sg_uf": "AA", "cd_municipio_tse": "00001", "unidades_incluida": 10}],
        ["sg_uf", "cd_municipio_tse", "unidades_incluida"],
    )

    faixas = [
        {"indicador": "renda_pc", "faixa": 1, "valor_min": 500.0, "valor_max": 1000.0, "municipios": 2, "municipios_sem_indicador": 1, "corte_inferior": None, "corte_superior": 1000.0},
        {"indicador": "renda_pc", "faixa": 2, "valor_min": 1000.01, "valor_max": 2000.0, "municipios": 1, "municipios_sem_indicador": 1, "corte_inferior": 1000.0, "corte_superior": None},
    ]
    _write_csv(base / "faixas.csv", faixas, ["indicador", "faixa", "valor_min", "valor_max", "municipios", "municipios_sem_indicador", "corte_inferior", "corte_superior"])

    cross = [
        {"SG_UF": "AA", "CD_MUNICIPIO_TSE": "1", "NM_MUNICIPIO_TSE": "ALFA", "CD_MUNICIPIO_IBGE": "1000001", "NM_MUNICIPIO_IBGE": "Alfa"},
        {"SG_UF": "BB", "CD_MUNICIPIO_TSE": "2", "NM_MUNICIPIO_TSE": "BETA", "CD_MUNICIPIO_IBGE": "2000002", "NM_MUNICIPIO_IBGE": "Beta"},
        {"SG_UF": "AA", "CD_MUNICIPIO_TSE": "3", "NM_MUNICIPIO_TSE": "GAMA", "CD_MUNICIPIO_IBGE": "3000003", "NM_MUNICIPIO_IBGE": "Gama"},
        {"SG_UF": "BB", "CD_MUNICIPIO_TSE": "4", "NM_MUNICIPIO_TSE": "DELTA", "CD_MUNICIPIO_IBGE": "4000004", "NM_MUNICIPIO_IBGE": "Delta"},
    ]
    _write_csv(base / "crosswalk.csv", cross, list(cross[0]))

    localidades = []
    for code, name in (("1000001", "Alfa"), ("2000002", "Beta"), ("3000003", "Gama"), ("4000004", "Delta")):
        uf = "AA" if code.startswith(("1", "3")) else "BB"
        regiao = "Norte" if uf == "AA" else "Sul"
        localidades.append(
            {
                "id": int(code),
                "nome": name,
                "regiao-imediata": {
                    "id": int(code[:6]),
                    "nome": f"RI {name}",
                    "regiao-intermediaria": {
                        "UF": {"sigla": uf, "nome": f"UF {uf}", "regiao": {"nome": regiao}}
                    },
                },
            }
        )
    (base / "localidades.json").write_text(json.dumps(localidades, ensure_ascii=False), encoding="utf-8")

    ref_rows = []
    for turn in (1, 2):
        for uf, values in (
            ("AA", {"aptos": 100, "comparecimento": 80, "abstencoes": 20, "votos_brancos": 5, "votos_nulos": 5, "lula": 30 if turn == 1 else 40, "flavio": 20 if turn == 1 else 10}),
            ("ZZ", {"aptos": 423, "comparecimento": 0, "abstencoes": 0, "votos_brancos": 0, "votos_nulos": 0, "lula": 0, "flavio": 0}),
        ):
            for metric, value in values.items():
                ref_rows.append({"nr_turno": turn, "sg_uf": uf, "metrica": f"qt_{metric}", "valor_referencia": value, "valor_staging": value, "dif": 0, "url": "https://example.invalid/tse"})
    _write_csv(base / "referencia.csv", ref_rows, ["nr_turno", "sg_uf", "metrica", "valor_referencia", "valor_staging", "dif", "url"])

    (base / "analysis_manifest.json").write_text(json.dumps({"git_commit": "abcdef1234567890", "contract_version": "1.2.0", "codigo_com_alteracoes_nao_commitadas": False}), encoding="utf-8")

    geo = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"codarea": code}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
            for code in ("1000001", "2000002", "4000004")
        ],
    }
    (base / "malha.geojson").write_text(json.dumps(geo), encoding="utf-8")

    return exporter.Inputs(
        root=base,
        metrics_municipio=base / "metrics_municipio.csv",
        metrics_uf=base / "metrics_uf.csv",
        metrics_aggregate=base / "metrics_aggregate.csv",
        painel_socio=base / "painel_socio.csv",
        coverage_municipio=base / "coverage.csv",
        faixas_nacional=base / "faixas.csv",
        crosswalk=base / "crosswalk.csv",
        localidades=base / "localidades.json",
        referencia_oficial=base / "referencia.csv",
        analysis_manifest=base / "analysis_manifest.json",
        malha=base / "malha.geojson",
    )


def test_fixture_export(tmp_path: Path) -> None:
    inputs = build_fixture(tmp_path / "in")
    out = tmp_path / "out"
    result = exporter.export_release(inputs, out)

    assert result.release_id.startswith("p0-abcdef1-")
    assert (out / "current.json").exists()
    manifest = json.loads((result.out_dir / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads((result.out_dir / "municipios.json").read_text(encoding="utf-8"))
    assert data["fields"] == exporter.MUNICIPIO_FIELDS
    assert len(data["rows"]) == 4
    idx = {name: i for i, name in enumerate(data["fields"])}
    by_code = {row[idx["cd_ibge"]]: row for row in data["rows"]}
    assert by_code["3000003"][idx["tem_geometria"]] == 0
    assert by_code["2000002"][idx["tem_contexto"]] == 0
    assert by_code["1000001"][idx["tem_contexto"]] == 1
    assert by_code["1000001"][idx["qt_lula_t2"]] == 40
    assert by_code["1000001"][idx["nome"]] == "Alfa"

    assert manifest["cobertura"]["sem_geometria"] == ["3000003"]
    assert set(manifest["cobertura"]["sem_contexto"]) == {"2000002", "3000003"}
    assert manifest["validacoes"]["somas_reconciliadas"] is True
    assert manifest["excecoes"]["aptos_sem_comparecimento_abstencao_t1"] == 423
    assert manifest["hashes_saida"] and all(len(h) == 64 for h in manifest["hashes_saida"].values())
    bundle = json.loads((result.out_dir / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["release_id"] == result.release_id
    assert bundle["municipios"]["fields"] == exporter.CORE_FIELDS
    assert len(bundle["municipios"]["rows"]) == 4
    assert bundle["nacional"]["unidades"] == 2
    assert "bundle.json" in manifest["hashes_saida"]
    socio = json.loads((result.out_dir / "socio.json").read_text(encoding="utf-8"))
    assert socio["fields"] == ["cd_ibge", *exporter.SOCIO_FIELDS]
    assert len(socio["rows"]) == 4
    assert "socio.json" in manifest["hashes_saida"]

    nacional = json.loads((result.out_dir / "nacional.json").read_text(encoding="utf-8"))
    assert nacional["unidades"] == 2
    assert nacional["inclui_exterior"] is True
    assert nacional["totais"]["t2"]["validos_t2"] == 50


def test_export_is_deterministic_and_does_not_modify_inputs(tmp_path: Path) -> None:
    inputs = build_fixture(tmp_path / "in")
    before = {p.name: _hash(p) for p in (tmp_path / "in").iterdir() if p.is_file()}
    a = exporter.export_release(inputs, tmp_path / "out_a")
    b = exporter.export_release(inputs, tmp_path / "out_b")
    after = {p.name: _hash(p) for p in (tmp_path / "in").iterdir() if p.is_file()}
    assert before == after
    assert a.release_id == b.release_id
    ma = json.loads((a.out_dir / "manifest.json").read_text(encoding="utf-8"))
    mb = json.loads((b.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert ma["hashes_saida"] == mb["hashes_saida"]
    assert ma["hashes_entrada"] == mb["hashes_entrada"]


def test_official_block_is_deterministic_across_hash_seeds(tmp_path: Path) -> None:
    inputs = build_fixture(tmp_path / "in")
    code = (
        "import json,sys;"
        f"sys.path.insert(0,{str(ROOT / 'tools/web_export')!r});"
        "import pandas as pd, export_web_release as e;"
        "block=e._official_block(pd.read_csv(sys.argv[1]));"
        "print(json.dumps(block,ensure_ascii=False,separators=(',',':')))"
    )
    outputs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", code, str(inputs.referencia_oficial)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1]

    inputs = build_fixture(tmp_path / "in")
    rows = pd.read_csv(inputs.metrics_municipio, dtype={"cd_municipio_tse": str})
    pd.concat([rows, rows.iloc[[0]]], ignore_index=True).to_csv(inputs.metrics_municipio, index=False)
    with pytest.raises(ValueError, match="(?i)(merge|duplic|linhas|unique)"):
        exporter.export_release(inputs, tmp_path / "out")


def test_duplicate_key_is_rejected(tmp_path: Path) -> None:
    inputs = build_fixture(tmp_path / "in")
    rows = pd.read_csv(inputs.metrics_municipio, dtype={"cd_municipio_tse": str})
    pd.concat([rows, rows.iloc[[0]]], ignore_index=True).to_csv(inputs.metrics_municipio, index=False)
    with pytest.raises(ValueError, match="(?i)(merge|duplic|linhas|unique)"):
        exporter.export_release(inputs, tmp_path / "out")


def test_total_mismatch_is_rejected(tmp_path: Path) -> None:
    inputs = build_fixture(tmp_path / "in")
    uf = pd.read_csv(inputs.metrics_uf)
    uf.loc[uf.sg_uf == "TOTAL", "qt_aptos_t2"] = 999
    uf.to_csv(inputs.metrics_uf, index=False)
    with pytest.raises(ValueError, match="divergente"):
        exporter.export_release(inputs, tmp_path / "out")


def test_official_reference_difference_is_rejected(tmp_path: Path) -> None:
    inputs = build_fixture(tmp_path / "in")
    ref = pd.read_csv(inputs.referencia_oficial)
    ref.loc[0, "dif"] = 1
    ref.to_csv(inputs.referencia_oficial, index=False)
    with pytest.raises(ValueError, match="diferença"):
        exporter.export_release(inputs, tmp_path / "out")


def test_repeated_export_preserves_manifest_and_collision(tmp_path):
    inputs = build_fixture(tmp_path / "in")
    out = tmp_path / "out"
    a = exporter.export_release(inputs, out)
    original = (a.out_dir / "manifest.json").read_bytes()
    pointer = (out / "current.json").read_bytes()
    exporter.export_release(inputs, out)
    assert (a.out_dir / "manifest.json").read_bytes() == original
    (a.out_dir / "bundle.json").write_text("corrupted", encoding="utf-8")
    with pytest.raises(ValueError, match="collision"):
        exporter.export_release(inputs, out)
    assert (a.out_dir / "bundle.json").read_text() == "corrupted"
    assert (out / "current.json").read_bytes() == pointer


def test_export_failure_preserves_current(tmp_path, monkeypatch):
    inputs = build_fixture(tmp_path / "in")
    out = tmp_path / "out"
    a = exporter.export_release(inputs, out)
    before = {p.name: p.read_bytes() for p in a.out_dir.iterdir()}
    pointer = (out / "current.json").read_bytes()
    write = exporter._write_json
    def fail(path, payload):
        if path.name == "bundle.json":
            raise OSError("injected failure")
        return write(path, payload)
    monkeypatch.setattr(exporter, "_write_json", fail)
    with pytest.raises(OSError, match="injected"):
        exporter.export_release(inputs, out)
    assert (out / "current.json").read_bytes() == pointer
    assert {p.name: p.read_bytes() for p in a.out_dir.iterdir()} == before
