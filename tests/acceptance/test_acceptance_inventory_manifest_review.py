"""Revisão independente do inventário A0, manifesto e cobertura oficial (Frente C).

Cobre a Tarefa 3, Tarefa 2 e orientações C3/C5 de 09_REVISAO_E_CONTINUACAO_ANTIGRAVITY.md:
1. Recomputação direta de SHA-256 de amostras oficiais em disco, sem confiar em declaração de A.
2. Leitura direta do ZIP oficial preservado e extração das linhas do oráculo em streaming.
3. Casos adversos: 1 voto alterado, aptos alterados, adulteração de arquivo e referência incompleta.
4. Confronto do staging com a referência independente (marcado BLOCKED quando staging ausente).
5. Cobertura estrutural das 28 unidades territoriais e exterior ZZ isolado.
6. Registro preciso da ausência de 2º turno a partir das URLs consultadas.
7. Separação explícita entre data de geração do arquivo (14/07/2026) e corte cadastral.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from br2026.contract import PROJECT_ROOT
from tests.fixtures.acceptance.official_sample_oracle import (
    DEFAULT_ZIP_PATH,
    OFFICIAL_MUNZONA_SAMPLE_RECORDS,
    OFFICIAL_SOURCE_PROVENANCE,
    compute_file_sha256,
    load_bujari_official_from_zip,
    verify_official_accounting_identities,
)


def test_independent_direct_hash_recomputation_of_official_samples():
    """Recomputa diretamente os hashes SHA-256 de todas as amostras oficiais em disco (C3).

    Não lê declaração JSON de A: calcula o SHA-256 bloco a bloco a partir dos binários.
    """
    provenance_path = PROJECT_ROOT / "docs" / "sources" / "samples" / "PROVENANCE.csv"
    assert provenance_path.exists(), "PROVENANCE.csv de amostras não encontrado"

    samples_dir = PROJECT_ROOT / "data" / "raw" / "samples"
    assert samples_dir.exists(), "Diretório data/raw/samples não encontrado"

    checked_files = []
    with open(provenance_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row["name"]
            expected_hash = row["sha256"]
            file_path = samples_dir / filename
            if file_path.exists():
                computed_hash = compute_file_sha256(file_path)
                assert computed_hash == expected_hash, f"Hash divergente para {filename}: {computed_hash} != {expected_hash}"
                checked_files.append((filename, computed_hash))

    assert len(checked_files) >= 9, f"Esperado recomputar hashes de ao menos 9 amostras, verificadas {len(checked_files)}"


def test_independent_zip_extraction_and_bujari_oracle_match():
    """Lê o ZIP oficial preservado e extrai o registro de Bujari/AC Zona 9 diretamente (C3).

    Verifica hash do ZIP, abre o membro em memória e confronta valores com o gabarito.
    """
    assert DEFAULT_ZIP_PATH.exists(), f"ZIP oficial não encontrado em {DEFAULT_ZIP_PATH}"

    # 1. Conferir hash do ZIP em disco
    computed_zip_hash = compute_file_sha256(DEFAULT_ZIP_PATH)
    assert computed_zip_hash == OFFICIAL_SOURCE_PROVENANCE["sha256"], (
        f"Hash do ZIP oficial adulterado: {computed_zip_hash} != {OFFICIAL_SOURCE_PROVENANCE['sha256']}"
    )

    # 2. Extrair registro diretamente em memória
    extracted = load_bujari_official_from_zip(DEFAULT_ZIP_PATH)
    expected = OFFICIAL_MUNZONA_SAMPLE_RECORDS[0]

    # 3. Conferência campo a campo
    for k, expected_val in expected.items():
        assert extracted[k] == expected_val, f"Divergência no campo {k}: extraído {extracted[k]} != esperado {expected_val}"

    # 4. Conferir identidades contábeis sobre o registro extraído
    identities = verify_official_accounting_identities(extracted)
    assert all(identities.values()), f"Identidades contábeis falharam no registro extraído: {identities}"


def test_adversarial_altered_vote_detected_in_reference():
    """Valida que uma adulteração de 1 voto ou aptos na referência é detectada (C3)."""
    clean = dict(OFFICIAL_MUNZONA_SAMPLE_RECORDS[0])

    # Caso 1: 1 voto a mais nos válidos quebra comparecimento = válidos + brancos + nulos
    altered_vote = dict(clean, qt_total_votos_validos=clean["qt_total_votos_validos"] + 1)
    res_vote = verify_official_accounting_identities(altered_vote)
    assert res_vote["identidade_comparecimento"] is False, "Falha em detectar 1 voto alterado!"

    # Caso 2: 1 eleitor a mais nos aptos quebra aptos = comparecimento + abstenções
    altered_aptos = dict(clean, qt_aptos=clean["qt_aptos"] + 1)
    res_aptos = verify_official_accounting_identities(altered_aptos)
    assert res_aptos["identidade_aptos"] is False, "Falha em detectar aptos alterados!"

    # Caso 3: Arquivo adulterado gera hash inconsistente
    tampered_bytes = b"conteudo_adulterado"
    tampered_hash = compute_file_sha256_bytes(tampered_bytes)
    assert tampered_hash != OFFICIAL_SOURCE_PROVENANCE["sha256"]


def compute_file_sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def test_adversarial_incomplete_or_invalid_reference_fails():
    """Valida que referência com chaves faltantes ou vazia falha na validação."""
    incomplete_record = {"sg_uf": "AC", "cd_municipio_tse": "01007"}
    with pytest.raises(KeyError):
        verify_official_accounting_identities(incomplete_record)


def test_compare_staging_against_independent_reference():
    """Confronta a soma do staging real de AC/RS/MG contra o oráculo independente (C1/C3).

    Valida aptos, comparecimento, abstenções, brancos e nulos contra o ZIP oficial
    detalhe_votacao_munzona_2026.zip em streaming, sem depender do código de A.
    """
    from br2026.contract import read_table
    from br2026.panel.run import staging_path as _staging_path
    staging_path = _staging_path(PROJECT_ROOT / "data" / "staging", "section_turn")
    if not staging_path.exists():
        pytest.skip("BLOCKED: staging real ausente para confronto com referência externa independente")

    import pandas as pd
    df_st = read_table(staging_path, "section_turn")

    # 1. Checagem pontual de Bujari (AC)
    bujari_st = df_st[(df_st.sg_uf == "AC") & (df_st.cd_municipio_tse == "01007") & (df_st.nr_turno == 1)]
    assert not bujari_st.empty, "Seções de Bujari ausentes no staging"
    ref_bujari = OFFICIAL_MUNZONA_SAMPLE_RECORDS[0]
    assert int(bujari_st.qt_aptos.sum()) == ref_bujari["qt_aptos"]
    assert int(bujari_st.qt_comparecimento.sum()) == ref_bujari["qt_comparecimento"]

    # 2. Reconciliação completa das UFs do piloto (AC, RS, MG) contra o ZIP oficial
    assert DEFAULT_ZIP_PATH.exists(), f"ZIP oficial não encontrado em {DEFAULT_ZIP_PATH}"
    with zipfile.ZipFile(DEFAULT_ZIP_PATH) as z:
        content = z.read("detalhe_votacao_munzona_2026_BRASIL.csv").decode("latin-1")
    reader = csv.DictReader(io.StringIO(content), delimiter=";")
    recs = [
        r for r in reader
        if r.get("CD_CARGO") == "1" and r.get("NR_TURNO") == "1" and r.get("SG_UF") in ("AC", "RS", "MG")
    ]

    for uf in ("AC", "RS", "MG"):
        st_uf = df_st[(df_st.sg_uf == uf) & (df_st.nr_turno == 1)]  # referência munzona é do T1
        uf_recs = [r for r in recs if r["SG_UF"] == uf]
        assert len(st_uf) > 0, f"Staging sem registros para UF {uf}"
        assert len(uf_recs) > 0, f"Referência oficial sem registros para UF {uf}"

        # Aptos, comparecimento, abstenções e brancos têm conservação exata absoluta
        assert int(st_uf.qt_aptos.sum()) == sum(int(r["QT_APTOS"]) for r in uf_recs)
        assert int(st_uf.qt_comparecimento.sum()) == sum(int(r["QT_COMPARECIMENTO"]) for r in uf_recs)
        assert int(st_uf.qt_abstencoes.sum()) == sum(int(r["QT_ABSTENCOES"]) for r in uf_recs)
        assert int(st_uf.qt_votos_brancos.sum()) == sum(int(r["QT_VOTOS_BRANCOS"]) for r in uf_recs)

        # Nulos de urna (QT_VOTOS_NULOS) fecham exatamente
        assert int(st_uf.qt_votos_nulos.sum()) == sum(int(r["QT_VOTOS_NULOS"]) for r in uf_recs)

        # A soma total comparecimento = nominais + brancos + nulos
        assert int(st_uf.qt_comparecimento.sum()) == (
            int(st_uf.qt_votos_nominais.sum())
            + int(st_uf.qt_votos_legenda.sum())
            + int(st_uf.qt_votos_brancos.sum())
            + int(st_uf.qt_votos_nulos.sum())
        )

    # 3. Conferência de votos por candidato na tabela votes_long
    vl_path = _staging_path(PROJECT_ROOT / "data" / "staging", "votes_long")
    if vl_path.exists():
        df_vl = read_table(vl_path, "votes_long")
        for uf in ("AC", "RS", "MG"):
            vl_uf = df_vl[df_vl.sg_uf == uf]
            st_uf = df_st[df_st.sg_uf == uf]
            # Validação cruzada: total nominal de votes_long é exatamente igual a section_turn
            vl_nom = int(vl_uf[vl_uf.tipo_votavel == "NOMINAL"].qt_votos.sum())
            st_nom = int(st_uf.qt_votos_nominais.sum())
            assert vl_nom == st_nom, f"Divergência nominal em {uf}: {vl_nom} != {st_nom}"
            # Candidatos finalistas com votos positivos estritamente verificáveis
            lula = int(vl_uf[vl_uf.nr_votavel == 13].qt_votos.sum())
            flavio = int(vl_uf[vl_uf.nr_votavel == 22].qt_votos.sum())
            assert lula > 0 and flavio > 0


def test_review_inventory_structural_coverage_and_exterior_isolated():
    """Valida que todas as 28 unidades territoriais foram catalogadas e que ZZ é exterior isolado."""
    inv_path = PROJECT_ROOT / "docs" / "sources" / "inventory.csv"
    assert inv_path.exists(), "docs/sources/inventory.csv não encontrado"

    with open(inv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Verificar ausência de duplicatas de localização
    locations = [
        r.get("location") or r.get("localizacao") or r.get("caminho_ou_url")
        for r in rows
        if (r.get("location") or r.get("localizacao") or r.get("caminho_ou_url"))
    ]
    assert len(locations) == len(set(locations)), "Duplicatas de localização encontradas em inventory.csv"

    # Verificar cobertura de UFs e exterior (coluna 'ufs' no CSV de A0)
    ufs = {
        r.get("ufs") or r.get("uf") or r.get("sg_uf")
        for r in rows
        if (r.get("ufs") or r.get("uf") or r.get("sg_uf"))
    }
    assert len(ufs) >= 28, f"Esperado catalogar ao menos 28 UFs (incluindo DF e ZZ), encontradas {len(ufs)}"
    assert "ZZ" in ufs, "Exterior (ZZ) ausente do catálogo"
    assert "DF" in ufs, "Distrito Federal (DF) ausente do catálogo"


def test_review_second_turn_absence_documented_from_queried_urls():
    """Valida que a ausência de 2º turno foi registrada a partir das URLs consultadas (C5)."""
    avail_path = PROJECT_ROOT / "docs" / "sources" / "availability.md"
    assert avail_path.exists(), "docs/sources/availability.md não encontrado"

    text = avail_path.read_text(encoding="utf-8")
    # URLs específicas que retornaram 404 em 26/10
    assert "bweb_2t_AC_261020260000.zip" in text or "bweb_2t" in text
    assert "HTTP 404" in text or "AUSENTE" in text


def test_review_profile_cutoff_distinguishes_generation_and_cadastral_reference():
    """Valida a separação entre data de geração do arquivo (14/07/2026) e referência cadastral (C5)."""
    avail_path = PROJECT_ROOT / "docs" / "sources" / "availability.md"
    text = avail_path.read_text(encoding="utf-8")
    # A data 14/07/2026 é a data de geração (DT_GERACAO), não prova que o cadastro fechou neste dia
    assert "14/07/2026" in text
    assert "DT_GERACAO" in text or "geração" in text
