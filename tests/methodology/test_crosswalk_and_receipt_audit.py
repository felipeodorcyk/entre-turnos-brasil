"""R16-5 (QB-A2-01, QB-A2-04) e R18-1..R18-3: conferência do vínculo efetivado, recebimentos, CEFT, proveniência e sem_perfil."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from br2026.analysis.closure_audit import ocorrencias_urna_summary, receipt_consistency
from br2026.analysis.crosswalk_check import check_effective_against_ceft
from br2026.analysis.t1_diagnostic import t1_sem_perfil_breakdown
from br2026.reporting.report import forbidden_matches, lint_template

GEO = {"sg_uf": "AC", "cd_municipio_tse": "01007", "nr_zona": "0001"}


def cw_rows(pairs):
    """pairs: (seção, apuradora, tipo)."""
    return pd.DataFrame([{"nr_turno": 1, **GEO, "nr_secao": s, "nr_secao_apuradora": a,
                          "tipo_correspondencia": t, "status_correspondencia": "EFETIVADA"} for s, a, t in pairs])


CW = cw_rows([("0001", "0001", "PRINCIPAL_COM_AGREGADAS"), ("0002", "0001", "AGREGADA_EM_OUTRA"),
              ("0003", "0003", "PROPRIA")])
CEFT_OK = pd.DataFrame([{**GEO, "nr_turno": 1, "nr_secao": "0001", "nr_urna_efetivada": "111"},
                        {**GEO, "nr_turno": 1, "nr_secao": "0003", "nr_urna_efetivada": "333"}])


def _make_zip(member_name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member_name, text.encode("latin-1"))
    return buf.getvalue()


def _write_ceft_manifest(raw_dir: Path, uf: str, turno: int, rows: list[tuple[str, str, str, int]],
                         stem_suffix: str = "051020261049") -> tuple[Path, str]:
    """Cria um ZIP CEFT válido em raw_dir e o registra em data/raw/manifest.json."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = f"CEFT_{turno}t_{uf}_{stem_suffix}"
    fname = f"{stem}.zip"
    member = f"ceft_{turno}t_{uf}_{stem_suffix}.csv"
    lines = ['"SG_UF";"CD_MUNICIPIO";"NR_ZONA";"NR_SECAO";"NR_URNA_ESPERADA";"NR_URNA_EFETIVADA";"CD_ORIGEM_VOTO";"TP_DIVERGENCIA"']
    for mun, zona, sec, tp in rows:
        u_efet = "200" if tp else "100"
        tp_str = str(tp) if tp else ""
        lines.append(f'"{uf}";"{mun}";"{zona}";"{sec}";"100";"{u_efet}";"U";"{tp_str}"')
    zbytes = _make_zip(member, "\n".join(lines))
    zpath = raw_dir / fname
    zpath.write_bytes(zbytes)
    sha = hashlib.sha256(zbytes).hexdigest()
    mpath = raw_dir / "manifest.json"
    if mpath.exists():
        man = json.loads(mpath.read_text(encoding="utf-8"))
    else:
        man = {"manifest_version": "1.0", "registros": {}}
    man["registros"][stem] = {
        "fonte": "correspondencia_efetivada",
        "arquivo": fname,
        "sha256": sha,
        "uf": uf,
        "turnos": [turno],
        "conteudo": {"membro_validado": member},
    }
    mpath.write_text(json.dumps(man, indent=2), encoding="utf-8")
    return zpath, sha


def test_effective_crosswalk_consistent_with_ceft():
    r = check_effective_against_ceft(CW, CEFT_OK)
    assert r["ausentes_na_ceft_sao_exatamente_agregadas"] and r["apuradoras_do_crosswalk_igual_secoes_com_urna"]


def test_detects_section_with_urn_marked_as_aggregated():
    """BU diz que 0003 foi agregada em 0001, mas a CEFT mostra urna própria em 0003."""
    cw = cw_rows([("0001", "0001", "PRINCIPAL_COM_AGREGADAS"), ("0002", "0001", "AGREGADA_EM_OUTRA"),
                  ("0003", "0001", "AGREGADA_EM_OUTRA")])
    r = check_effective_against_ceft(cw, CEFT_OK)
    assert not r["apuradoras_do_crosswalk_igual_secoes_com_urna"]
    assert r["secoes_com_urna_que_nao_sao_apuradoras"] == 1


def test_detects_aggregated_section_missing_from_crosswalk_marking():
    """CEFT sem a 0003 (sem urna), mas o BU a trata como própria."""
    r = check_effective_against_ceft(CW, CEFT_OK.iloc[[0]])
    assert not r["ausentes_na_ceft_sao_exatamente_agregadas"]


def rec(sec, raw, src):
    return {"nr_turno": 1, **GEO, "nr_secao": sec, "semantica": "RECEBIMENTO_BU_TSE",
            "ts_bruto": raw, "source_id": src}


def test_receipt_same_instant_different_format_is_same_event():
    cl = pd.DataFrame([rec("0001", "2026-10-04 18:55:55", "bweb"), rec("0001", "04/10/2026 18:55:55", "detalhe")])
    s, c = receipt_consistency(cl)
    assert s.set_index("classe").secoes.to_dict() == {"MESMO_EVENTO": 1} and c.empty


def test_receipt_conflict_single_source_and_invalid_are_reported_not_dropped():
    cl = pd.DataFrame([rec("0001", "2026-10-04 18:55:55", "bweb"), rec("0001", "04/10/2026 19:05:00", "detalhe"),
                       rec("0002", "2026-10-04 18:00:00", "bweb"),
                       rec("0003", "2026-10-04 18:00:00", "bweb"), rec("0003", "lixo", "detalhe")])
    s, c = receipt_consistency(cl)
    classes = c.set_index("nr_secao").classe.to_dict()
    assert classes == {"0001": "CONFLITO_RECEBIMENTO", "0002": "FONTE_UNICA", "0003": "BRUTO_INVALIDO"}


def _sample_cl_and_av():
    cl = pd.DataFrame([
        {"nr_turno": 1, **GEO, "nr_secao": "0001", "flag_reemissao": False, "flag_substituicao_urna": False},
        {"nr_turno": 1, **GEO, "nr_secao": "0002", "flag_reemissao": True, "flag_substituicao_urna": False},
    ])
    av = pd.DataFrame([
        {"nr_turno": 1, **GEO, "nr_secao": "0001", "correspondencia": "Esperada",
         "id_urna": "100", "ocorrencia": "---", "origem": "---"},
        {"nr_turno": 1, **GEO, "nr_secao": "0001", "correspondencia": "Efetivada",
         "id_urna": "200", "ocorrencia": "Contingência", "origem": "UE"},
        {"nr_turno": 1, **GEO, "nr_secao": "0002", "correspondencia": "Esperada",
         "id_urna": "300", "ocorrencia": "---", "origem": "---"},
        {"nr_turno": 1, **GEO, "nr_secao": "0002", "correspondencia": "Efetivada",
         "id_urna": "300", "ocorrencia": "BU gerado por RED", "origem": "RED-Seção"},
    ])
    return cl, av


def test_ocorrencias_urna_summary_integrates_anexo_v_and_ceft(tmp_path):
    """R18-1: conciliação só é PASS quando CEFT está presente no manifesto e bate 100%."""
    cl, av = _sample_cl_and_av()
    raw_dir = tmp_path / "raw"
    _write_ceft_manifest(raw_dir, "AC", 1, [
        ("01007", "0001", "0001", 1),
        ("01007", "0001", "0002", 2),
        ("01007", "0001", "0003", 0),
    ])
    summary, ok = ocorrencias_urna_summary(cl, av, raw_dir=raw_dir)
    assert ok is True
    assert summary.attrs["status"] == "PASS"
    row = summary.iloc[0]
    assert row["secoes_closure"] == 2
    assert row["secoes_reemissao_bu"] == 1
    assert row["anexo_v_secoes"] == 2
    assert row["anexo_v_troca_urna"] == 1
    assert row["anexo_v_red_mesma_urna"] == 1
    assert row["ceft_divergencias_conciliadas_dif"] == 0
    assert row["status_conciliacao"] == "PASS"


def test_ocorrencias_urna_blocked_when_ceft_absent():
    """R18-1: sem raw_dir ou sem CEFT, nunca retorna dif=0 nem ok=True."""
    cl, av = _sample_cl_and_av()
    summary, ok = ocorrencias_urna_summary(cl, av, raw_dir=None)
    assert ok is False
    assert summary.attrs["status"] == "BLOCKED"
    row = summary.iloc[0]
    assert pd.isna(row["ceft_divergencias_conciliadas_dif"])
    assert row["status_conciliacao"] == "NAO_VERIFICADO"


def test_ocorrencias_urna_fails_on_ceft_set_divergence(tmp_path):
    """R18-1: divergência entre o conjunto do Anexo V e TP_DIVERGENCIA != 0 da CEFT resulta em FAIL."""
    cl, av = _sample_cl_and_av()
    raw_dir = tmp_path / "raw"
    _write_ceft_manifest(raw_dir, "AC", 1, [
        ("01007", "0001", "0001", 1),  # falta 0002 na CEFT
    ])
    summary, ok = ocorrencias_urna_summary(cl, av, raw_dir=raw_dir)
    assert ok is False
    assert summary.attrs["status"] == "FAIL"
    row = summary.iloc[0]
    assert row["ceft_divergencias_conciliadas_dif"] == 1
    assert row["status_conciliacao"] == "FAIL"


def test_ocorrencias_urna_fails_on_corrupt_or_tampered_ceft(tmp_path):
    """R18-1: CEFT corrompida ou com SHA-256 divergente do manifesto resulta em FAIL."""
    cl, av = _sample_cl_and_av()
    raw_dir = tmp_path / "raw"
    zpath, _ = _write_ceft_manifest(raw_dir, "AC", 1, [
        ("01007", "0001", "0001", 1),
        ("01007", "0001", "0002", 2),
    ])
    zpath.write_bytes(b"corrompido")
    summary, ok = ocorrencias_urna_summary(cl, av, raw_dir=raw_dir)
    assert ok is False
    assert summary.attrs["status"] == "FAIL"
    assert summary.iloc[0]["status_conciliacao"] == "FAIL"
    assert pd.isna(summary.iloc[0]["ceft_divergencias_conciliadas_dif"])


def test_ocorrencias_urna_fails_on_structural_anexo_v_errors(tmp_path):
    """R18-1: par incompleto, linha duplicada ou nr_turno inválido no Anexo V resultam em FAIL."""
    cl, av = _sample_cl_and_av()
    raw_dir = tmp_path / "raw"
    _write_ceft_manifest(raw_dir, "AC", 1, [
        ("01007", "0001", "0001", 1),
        ("01007", "0001", "0002", 2),
    ])
    # 1) Par incompleto (Esperada sem Efetivada)
    av_incompleto = av.iloc[:-1].copy()
    s1, ok1 = ocorrencias_urna_summary(cl, av_incompleto, raw_dir=raw_dir)
    assert ok1 is False and s1.attrs["status"] == "FAIL"

    # 2) Linha duplicada
    av_dup = pd.concat([av, av.iloc[[0]]], ignore_index=True)
    s2, ok2 = ocorrencias_urna_summary(cl, av_dup, raw_dir=raw_dir)
    assert ok2 is False and s2.attrs["status"] == "FAIL"

    # 3) nr_turno inválido (não pode virar 1 por fillna)
    av_bad_turno = av.copy()
    av_bad_turno["nr_turno"] = av_bad_turno["nr_turno"].astype(object)
    av_bad_turno.loc[0, "nr_turno"] = "invalido"
    s3, ok3 = ocorrencias_urna_summary(cl, av_bad_turno, raw_dir=raw_dir)
    assert ok3 is False and s3.attrs["status"] == "FAIL"


def test_r18_2_manifest_selects_ceft_and_eleitorado_over_lexicographic_glob(tmp_path):
    """R18-2: com 2 arquivos no diretório, usa o declarado no manifesto e não sorted(glob)[-1]."""
    cl, av = _sample_cl_and_av()
    raw_dir = tmp_path / "raw"
    # Registra a versão oficial no manifesto (com as 2 divergências corretas)
    _write_ceft_manifest(raw_dir, "AC", 1, [
        ("01007", "0001", "0001", 1),
        ("01007", "0001", "0002", 2),
    ], stem_suffix="051020261049")
    # Cria um arquivo espúrio com sufixo lexicograficamente maior ("999999999999") fora do manifesto
    spurious_ceft = raw_dir / "CEFT_1t_AC_999999999999.zip"
    spurious_ceft.write_bytes(b"lixo_nao_manifestado")

    summary, ok = ocorrencias_urna_summary(cl, av, raw_dir=raw_dir)
    assert ok is True
    assert summary.attrs["status"] == "PASS"
    assert "data/raw/CEFT_1t_AC_051020261049.zip" in summary.attrs["insumos_sha256"]


def test_r18_3_sem_perfil_does_not_duplicate_aptos_on_multi_section_unit(tmp_path):
    """R18-3: unidade sem perfil com múltiplas seções no membership não multiplica qt_aptos_t1."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_lines = [
        '"NR_TURNO";"SG_UF";"CD_MUNICIPIO";"NR_ZONA";"NR_SECAO";"CD_TIPO_LOCAL";"DS_TIPO_LOCAL";"QT_ELEITOR_SECAO"',
        '"1";"RS";"88013";"0001";"0010";"6";"Voto em Trânsito";"0"',
        '"1";"RS";"88013";"0001";"0011";"6";"Voto em Trânsito";"0"',
    ]
    zbytes = _make_zip("eleitorado_local_votacao_2026_RS.csv", "\n".join(csv_lines))
    zpath = raw_dir / "eleitorado_local_votacao_2026.zip"
    zpath.write_bytes(zbytes)
    sha = hashlib.sha256(zbytes).hexdigest()
    man = {
        "manifest_version": "1.0",
        "registros": {
            "eleitorado_local_votacao_2026": {
                "fonte": "eleitorado_local_votacao",
                "arquivo": "eleitorado_local_votacao_2026.zip",
                "sha256": sha,
                "conteudo": {"membro_validado": "eleitorado_local_votacao_2026_RS.csv"},
            }
        },
    }
    (raw_dir / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")

    # Cria arquivo espúrio com nome maior para testar R18-2 também em eleitorado_local_votacao
    (raw_dir / "eleitorado_local_votacao_2026__zzzzzzzzzzzz.zip").write_bytes(b"corrompido")

    # 1 unidade com qt_aptos_t1 = 150, mas formada por 2 seções (0010 e 0011) no membership
    panel = pd.DataFrame([{
        "id_unidade": "U_RS_1", "sg_uf": "RS", "cd_municipio_tse": "88013",
        "qt_aptos_t1": 150, "qt_comparecimento_t1": 120,
    }])
    diag = pd.DataFrame([{"id_unidade": "U_RS_1", "n_origens": pd.NA, "motivo_exclusao": "SEM_PERFIL"}])
    membership = pd.DataFrame([
        {"id_unidade": "U_RS_1", "nr_turno": 1, "sg_uf": "RS", "cd_municipio_tse": "88013", "nr_zona": "0001", "nr_secao": "0010"},
        {"id_unidade": "U_RS_1", "nr_turno": 1, "sg_uf": "RS", "cd_municipio_tse": "88013", "nr_zona": "0001", "nr_secao": "0011"},
    ])
    bd = t1_sem_perfil_breakdown(diag, panel, membership, raw_dir=raw_dir)
    assert len(bd) == 1
    row = bd.iloc[0]
    assert int(row["unidades"]) == 1
    assert int(row["secoes"]) == 2
    assert int(row["aptos_t1"]) == 150, "aptos_t1 da unidade não pode ser multiplicado pelo nº de seções"
    assert not forbidden_matches(str(row["rotulo"]))
    assert "data/raw/eleitorado_local_votacao_2026.zip" in bd.attrs["insumos_sha256"]


def test_r18_2_provenance_official_totals_manifest_and_hashes(tmp_path):
    """R18-2: verifica proveniência PDF -> anexo_v_ocorrencias.csv e registro de todos os hashes."""
    cl, av = _sample_cl_and_av()
    raw_dir = tmp_path / "raw"
    _write_ceft_manifest(raw_dir, "AC", 1, [
        ("01007", "0001", "0001", 1),
        ("01007", "0001", "0002", 2),
    ])
    totals_dir = tmp_path / "official_totals"
    totals_dir.mkdir(parents=True, exist_ok=True)
    av_path = totals_dir / "anexo_v_ocorrencias.csv"
    av.to_csv(av_path, index=False)
    pdf_zip = totals_dir / "Relatorio_Resultado_Totalizacao_2026_AC.zip"
    pdf_bytes = _make_zip("6257_AC_ACRE_2026_T1_PRESIDENTE.pdf", "%PDF-1.4 fake")
    pdf_zip.write_bytes(pdf_bytes)
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
    tman = {
        "manifest_version": "1.0",
        "registros": {
            "Relatorio_Resultado_Totalizacao_2026_AC": {
                "arquivo": "Relatorio_Resultado_Totalizacao_2026_AC.zip",
                "sha256": pdf_sha,
                "uf": "AC",
                "turnos": [1],
            }
        },
    }
    (totals_dir / "manifest.json").write_text(json.dumps(tman, indent=2), encoding="utf-8")

    summary, ok = ocorrencias_urna_summary(cl, av, raw_dir=raw_dir, totals_dir=totals_dir)
    assert ok is True
    ins = summary.attrs["insumos_sha256"]
    assert "docs/sources/official_totals/anexo_v_ocorrencias.csv" in ins
    assert "docs/sources/official_totals/manifest.json" in ins
    assert "docs/sources/official_totals/Relatorio_Resultado_Totalizacao_2026_AC.zip" in ins
    assert "data/raw/manifest.json" in ins
    assert "data/raw/CEFT_1t_AC_051020261049.zip" in ins

    # Se adulterarmos o ZIP do PDF oficial, o hash diverge do manifesto e deve falhar
    pdf_zip.write_bytes(b"adulterado")
    summary_bad, ok_bad = ocorrencias_urna_summary(cl, av, raw_dir=raw_dir, totals_dir=totals_dir)
    assert ok_bad is False
    assert summary_bad.attrs["status"] == "FAIL"


def test_r18_3_linter_blocks_unverified_cadastral_cutoff_claim():
    """R18-3: linter rejeita afirmação factual de criação/alocação após o corte cadastral."""
    for phrase in (
        "Seções criadas após o corte cadastral de julho.",
        "Unidades posteriores ao corte cadastral do TSE.",
        "Trata-se de corte cadastral confirmado na base.",
    ):
        assert forbidden_matches(phrase), f"Deveria bloquear: {phrase!r}"
        errs = lint_template(phrase)
        assert any("frase proibida" in e for e in errs)



def test_ocorrencia_nao_instalada_fica_fora_da_conciliacao(tmp_path):
    """Handoff 26: seção "Não instalada" no Anexo V não tem urna efetivada nem linha na CEFT; é
    contada à parte e não vira divergência. Qualquer outra seção ausente da CEFT continua FAIL."""
    cl, av = _sample_cl_and_av()
    nao_inst = pd.DataFrame([
        {"nr_turno": 1, **GEO, "nr_secao": "0009", "correspondencia": "Esperada",
         "id_urna": "900", "ocorrencia": "---", "origem": "---"},
        {"nr_turno": 1, **GEO, "nr_secao": "0009", "correspondencia": "Efetivada",
         "id_urna": "---", "ocorrencia": "Não instalada", "origem": "---"},
    ])
    raw_dir = tmp_path / "raw"
    _write_ceft_manifest(raw_dir, "AC", 1, [("01007", "0001", "0001", 1), ("01007", "0001", "0002", 2)])
    summary, ok = ocorrencias_urna_summary(cl, pd.concat([av, nao_inst], ignore_index=True), raw_dir=raw_dir)
    row = summary.iloc[0]
    assert ok is True and row["status_conciliacao"] == "PASS"
    assert row["anexo_v_nao_instalada"] == 1 and row["anexo_v_secoes"] == 2
    # a mesma seção com outra ocorrência, ausente da CEFT, é divergência
    outra = nao_inst.assign(ocorrencia=["---", "Contingência"], id_urna=["900", "901"])
    s2, ok2 = ocorrencias_urna_summary(cl, pd.concat([av, outra], ignore_index=True), raw_dir=raw_dir)
    assert ok2 is False and s2.iloc[0]["status_conciliacao"] == "FAIL"


def test_identidade_de_aptos_conta_secoes_nao_instaladas():
    """Handoff 26: aptos de unidades sem comparecimento nem abstenção (não instaladas) são parcela
    própria da identidade, não divergência; uma divergência real continua aparecendo."""
    from br2026.analysis.t1_diagnostic import t1_metrics
    base = {"qt_votos_validos_t1": 10, "qt_votos_brancos_t1": 0, "qt_votos_nulos_t1": 0,
            "qt_lula_t1": 6, "qt_flavio_t1": 4}
    p = pd.DataFrame([
        {"sg_uf": "ZZ", "qt_aptos_t1": 15, "qt_comparecimento_t1": 10, "qt_abstencoes_t1": 5, **base},
        {"sg_uf": "ZZ", "qt_aptos_t1": 7, "qt_comparecimento_t1": 0, "qt_abstencoes_t1": 0,
         **{k: 0 for k in base}},
    ])
    m = t1_metrics(p).set_index("sg_uf")
    assert m.at["ZZ", "identidade_aptos_dif"] == 0
    assert m.at["ZZ", "qt_aptos_sem_comparecimento_nem_abstencao_t1"] == 7
    p.loc[0, "qt_abstencoes_t1"] = 4
    assert t1_metrics(p).set_index("sg_uf").at["ZZ", "identidade_aptos_dif"] == 1
