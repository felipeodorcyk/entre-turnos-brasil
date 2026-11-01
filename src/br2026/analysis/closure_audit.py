"""Auditoria dos registros brutos de horário e ocorrências de urna (QB-A2-04, handoffs 17–19).

O recebimento do BU no TSE aparece duas vezes por seção: no BU web
(`DT_BU_RECEBIDO`, `AAAA-MM-DD HH:MM:SS`) e no detalhe de apuração
(`DT_RECEBIMENTO_BU_HOR_TSE`, `dd/mm/aaaa HH:MM:SS`). Decisão de B:
  * os dois registros permanecem no staging (rastreabilidade por `source_id`);
  * após o parsing, instantes iguais = MESMO_EVENTO (formato diferente não é
    evento diferente); instantes diferentes = CONFLITO_RECEBIMENTO, mantido e
    reportado, nunca resolvido escolhendo uma fonte;
  * o recebimento não é encerramento e não entra nas faixas de horário.

Integra também as ocorrências especiais de correspondência e substituição de
urna extraídas do Anexo V do Relatório de Totalização oficial e conciliadas
contra a CEFT do turno resolvida exclusivamente via manifesto (`R18-1`, `R18-2`).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

from br2026.analysis.closure_tz import parse_naive_series

KEY = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
SEC_KEY = ["cd_municipio_tse", "nr_zona", "nr_secao"]
REQUIRED_CEFT_COLS = {
    "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
    "NR_URNA_ESPERADA", "NR_URNA_EFETIVADA", "CD_ORIGEM_VOTO", "TP_DIVERGENCIA",
}
REQUIRED_ANEXO_V_COLS = {
    "nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao",
    "correspondencia", "id_urna", "ocorrencia", "origem",
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def receipt_consistency(closure: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retorna (resumo por UF × turno × classe, seções em conflito)."""
    r = closure[closure.semantica == "RECEBIMENTO_BU_TSE"].copy()
    r["instante"] = parse_naive_series(r.ts_bruto)
    r["_invalido"] = r.instante.isna()
    g = r.groupby(KEY)
    per = pd.DataFrame({
        "n_registros": g.size(),
        "n_fontes": g.source_id.nunique(),
        "n_instantes": g.instante.nunique(dropna=True),
        "n_invalidos": g._invalido.sum().astype(int),
    })
    per["classe"] = "MESMO_EVENTO"
    per.loc[per.n_fontes < 2, "classe"] = "FONTE_UNICA"
    per.loc[per.n_instantes > 1, "classe"] = "CONFLITO_RECEBIMENTO"
    per.loc[per.n_invalidos > 0, "classe"] = "BRUTO_INVALIDO"
    summary = (per.reset_index().groupby(["sg_uf", "nr_turno", "classe"]).size()
               .rename("secoes").reset_index())
    conflicts = per[per.classe != "MESMO_EVENTO"].reset_index()
    return summary, conflicts


def _resolve_ceft_from_manifest(
    raw_dir: Path | None,
    uf: str,
    turno: int,
) -> tuple[set[tuple[str, str, str]] | None, dict[str, str], str, str]:
    """Resolve e valida a CEFT de `(uf, turno)` via `data/raw/manifest.json`.

    Retorna `(special_sections_or_None, insumos_sha256, status_ceft, motivo_ceft)`.
    `status_ceft` ∈ {"OK", "NAO_VERIFICADO", "FAIL"}.
    Nunca escolhe arquivo por glob lexicográfico (`R18-2`).
    """
    insumos: dict[str, str] = {}
    if raw_dir is None or not raw_dir.exists():
        return None, insumos, "NAO_VERIFICADO", "raw_dir ausente"
    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.exists():
        return None, insumos, "NAO_VERIFICADO", "manifest.json ausente em data/raw"
    try:
        manifest_sha = _sha256_file(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        registros = manifest.get("registros")
        if not isinstance(registros, dict):
            return None, insumos, "FAIL", "manifest.json sem mapa 'registros' válido"
    except (OSError, json.JSONDecodeError) as exc:
        return None, insumos, "FAIL", f"manifest.json ilegível ({exc})"

    insumos["data/raw/manifest.json"] = manifest_sha
    candidatos = []
    for stem, reg in registros.items():
        if not isinstance(reg, dict):
            continue
        arq_nome = str(reg.get("arquivo") or "")
        if (reg.get("fonte") == "correspondencia_efetivada"
                and str(reg.get("uf", "")).upper() == uf
                and turno in (reg.get("turnos") or [])
                and arq_nome.lower().endswith(".zip")):
            candidatos.append((stem, reg))
    if not candidatos:
        return None, insumos, "NAO_VERIFICADO", f"CEFT ausente do manifesto para {uf}/T{turno}"
    if len(candidatos) > 1:
        stems = [c[0] for c in candidatos]
        return None, insumos, "FAIL", f"múltiplos registros ativos de CEFT para {uf}/T{turno}: {stems}"

    _, reg = candidatos[0]
    arquivo = reg.get("arquivo")
    expected_sha = reg.get("sha256")
    if not arquivo or not expected_sha:
        return None, insumos, "FAIL", f"registro CEFT incompleto no manifesto para {uf}/T{turno}"
    zip_path = raw_dir / arquivo
    if not zip_path.exists():
        return None, insumos, "FAIL", f"arquivo CEFT registrado no manifesto não encontrado: {arquivo}"
    actual_sha = _sha256_file(zip_path)
    insumos[f"data/raw/{arquivo}"] = actual_sha
    if actual_sha != expected_sha:
        return (
            None,
            insumos,
            "FAIL",
            f"SHA-256 divergente em {arquivo} (esperado {expected_sha[:12]}…, obtido {actual_sha[:12]}…)",
        )

    membro_esperado = (reg.get("conteudo") or {}).get("membro_validado")
    special: set[tuple[str, str, str]] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if membro_esperado and membro_esperado in names:
                csv_name = membro_esperado
            else:
                csvs = [m for m in names if m.lower().endswith(".csv") and m.lower().startswith("ceft_")]
                csv_name = csvs[0] if len(csvs) == 1 else None
            if csv_name is None:
                return None, insumos, "FAIL", f"ZIP {arquivo} sem membro CSV CEFT unívoco"
            with zf.open(csv_name) as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
                fieldnames = set(reader.fieldnames or [])
                missing_cols = sorted(REQUIRED_CEFT_COLS - fieldnames)
                if missing_cols:
                    return None, insumos, "FAIL", f"CEFT {arquivo} sem colunas obrigatórias: {missing_cols}"
                n_rows = 0
                for row in reader:
                    n_rows += 1
                    row_uf = (row.get("SG_UF") or "").strip().upper()
                    if row_uf != uf:
                        return None, insumos, "FAIL", f"CEFT {arquivo} contém SG_UF={row_uf!r} != {uf!r}"
                    mun = (row.get("CD_MUNICIPIO") or "").strip().zfill(5)
                    zona = (row.get("NR_ZONA") or "").strip().zfill(4)
                    sec = (row.get("NR_SECAO") or "").strip().zfill(4)
                    k = (mun, zona, sec)
                    if k in seen_keys:
                        return None, insumos, "FAIL", f"CEFT {arquivo} contém seção duplicada: {k}"
                    seen_keys.add(k)
                    td = (row.get("TP_DIVERGENCIA") or "").strip()
                    du = (row.get("NR_URNA_ESPERADA") or "").strip() != (row.get("NR_URNA_EFETIVADA") or "").strip()
                    co = (row.get("CD_ORIGEM_VOTO") or "U").strip()
                    if td or du or co != "U":
                        special.add(k)
                if n_rows == 0:
                    return None, insumos, "FAIL", f"CEFT {arquivo} vazia"
    except (zipfile.BadZipFile, OSError, KeyError, UnicodeDecodeError, csv.Error) as exc:
        return None, insumos, "FAIL", f"CEFT {arquivo} ilegível ou corrompida ({exc})"

    return special, insumos, "OK", ""


def _verify_anexo_v_provenance(
    anexo_v: pd.DataFrame,
    totals_dir: Path | None,
    ufs_esperadas: set[str],
) -> tuple[dict[str, str], list[str]]:
    """Verifica proveniência PDF → extração (`anexo_v_ocorrencias.csv`) via manifesto oficial (`R18-2`)."""
    insumos: dict[str, str] = {}
    erros: list[str] = []
    if totals_dir is None:
        return insumos, erros
    manifest_path = totals_dir / "manifest.json"
    av_path = totals_dir / "anexo_v_ocorrencias.csv"
    if av_path.exists():
        insumos["docs/sources/official_totals/anexo_v_ocorrencias.csv"] = _sha256_file(av_path)
    if not manifest_path.exists():
        erros.append("manifest.json ausente em docs/sources/official_totals")
        return insumos, erros
    try:
        insumos["docs/sources/official_totals/manifest.json"] = _sha256_file(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        registros = manifest.get("registros") or {}
    except (OSError, json.JSONDecodeError) as exc:
        erros.append(f"manifest.json de official_totals ilegível ({exc})")
        return insumos, erros

    for uf in sorted(ufs_esperadas):
        stem = f"Relatorio_Resultado_Totalizacao_2026_{uf}"
        reg = registros.get(stem)
        if not isinstance(reg, dict):
            erros.append(f"{stem} ausente do manifesto de official_totals")
            continue
        arq = reg.get("arquivo", f"{stem}.zip")
        zip_path = totals_dir / arq
        if not zip_path.exists():
            erros.append(f"PDF oficial ausente: {arq}")
            continue
        real_sha = _sha256_file(zip_path)
        insumos[f"docs/sources/official_totals/{arq}"] = real_sha
        if real_sha != reg.get("sha256"):
            erros.append(
                f"SHA-256 do PDF {arq} diverge do manifesto de official_totals "
                f"({real_sha[:12]}… != {str(reg.get('sha256'))[:12]}…)"
            )
        if "sha256_fonte" in anexo_v.columns:
            shas_uf = set(
                anexo_v.loc[anexo_v["sg_uf"].astype(str).str.strip().str.upper() == uf, "sha256_fonte"]
                .dropna().astype(str).str.strip()
            )
            if not shas_uf or shas_uf != {real_sha}:
                erros.append(
                    f"proveniência violada em anexo_v para {uf}: sha256_fonte={sorted(shas_uf)} != {real_sha[:12]}…"
                )
    return insumos, erros


def ocorrencias_urna_summary(
    closure: pd.DataFrame,
    anexo_v: pd.DataFrame | None = None,
    raw_dir: Path | None = None,
    totals_dir: Path | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Resumo de ocorrências de urna por UF × turno, integrando Anexo V e CEFT.

    Regras estritas (`R18-1` e `R18-2`):
      * CEFT ausente -> `status_conciliacao = "NAO_VERIFICADO"`, `ceft_divergencias_conciliadas_dif = pd.NA`,
        retorno booleano `False` e `summary.attrs["status"] = "BLOCKED"`.
      * Par incompleto (`Esperada` sem `Efetivada` ou vice-versa), duplicata, turno inválido,
        UF/turno órfão no Anexo V, UF sem cobertura no Anexo V, arquivo CEFT inválido/corrompido
        ou divergência de conjunto `Anexo V != CEFT` -> `status_conciliacao = "FAIL"`,
        retorno booleano `False` e `summary.attrs["status"] = "FAIL"`.
      * `PASS` (`True`) somente quando todas as UFs × turnos têm Anexo V íntegro e CEFT
        resolvida por manifesto com `dif == 0`.
    """
    if closure.empty:
        empty = pd.DataFrame()
        empty.attrs["status"] = "BLOCKED"
        empty.attrs["motivo"] = "closure vazio"
        empty.attrs["insumos_sha256"] = {}
        return empty, False

    sec = closure.groupby(KEY, as_index=False).agg(
        flag_reemissao=("flag_reemissao", "any"),
        flag_substituicao_urna=("flag_substituicao_urna", "any"),
    )
    base = sec.groupby(["sg_uf", "nr_turno"], as_index=False).agg(
        secoes_closure=("nr_secao", "size"),
        secoes_reemissao_bu=("flag_reemissao", "sum"),
        secoes_substituicao_bweb=("flag_substituicao_urna", "sum"),
    )
    if anexo_v is None or anexo_v.empty:
        base["status_conciliacao"] = "BLOCKED"
        base["ceft_divergencias_conciliadas_dif"] = pd.Series([pd.NA] * len(base), dtype="Int64")
        base.attrs["status"] = "BLOCKED"
        base.attrs["motivo"] = "ocorrências de urna sem Anexo V na raiz de execução"
        base.attrs["insumos_sha256"] = {}
        return base, False

    missing_av_cols = sorted(REQUIRED_ANEXO_V_COLS - set(anexo_v.columns))
    if missing_av_cols:
        base["status_conciliacao"] = "FAIL"
        base["ceft_divergencias_conciliadas_dif"] = pd.Series([pd.NA] * len(base), dtype="Int64")
        base.attrs["status"] = "FAIL"
        base.attrs["motivo"] = f"Anexo V sem colunas obrigatórias: {missing_av_cols}"
        base.attrs["insumos_sha256"] = {}
        return base, False

    av = anexo_v.copy()
    av["sg_uf_norm"] = av["sg_uf"].fillna("").astype(str).str.strip().str.upper()
    av["turno_num"] = pd.to_numeric(av["nr_turno"], errors="coerce")
    av["mun_norm"] = av["cd_municipio_tse"].fillna("").astype(str).str.strip()
    av["zona_norm"] = av["nr_zona"].fillna("").astype(str).str.strip()
    av["secao_norm"] = av["nr_secao"].fillna("").astype(str).str.strip()
    av["corresp_norm"] = av["correspondencia"].fillna("").astype(str).str.strip()

    invalid_mask = (
        ~av["turno_num"].isin([1, 2])
        | (av["sg_uf_norm"] == "")
        | (av["mun_norm"] == "")
        | (av["zona_norm"] == "")
        | (av["secao_norm"] == "")
        | ~av["corresp_norm"].isin(["Esperada", "Efetivada"])
    )
    n_invalid_global = int(invalid_mask.sum())
    valid_av = av[~invalid_mask].copy()
    valid_av["turno_int"] = valid_av["turno_num"].astype(int)
    valid_av["cd_municipio_tse"] = valid_av["mun_norm"].str.zfill(5)
    valid_av["nr_zona"] = valid_av["zona_norm"].str.zfill(4)
    valid_av["nr_secao"] = valid_av["secao_norm"].str.zfill(4)
    valid_av["sg_uf"] = valid_av["sg_uf_norm"]
    valid_av["correspondencia"] = valid_av["corresp_norm"]

    base_pairs = {(str(r["sg_uf"]).upper(), int(r["nr_turno"])) for _, r in base.iterrows()}
    av_pairs = set(zip(valid_av["sg_uf"], valid_av["turno_int"]))
    orphan_uf_turnos = sorted(av_pairs - base_pairs)

    insumos_all: dict[str, str] = {}
    prov_insumos, prov_errors = _verify_anexo_v_provenance(
        valid_av, totals_dir, {u for u, _ in base_pairs}
    )
    insumos_all.update(prov_insumos)

    rows = []
    any_fail = bool(n_invalid_global > 0 or orphan_uf_turnos or prov_errors)
    any_unverified = False
    motivos_globais: list[str] = []
    if n_invalid_global > 0:
        motivos_globais.append(f"{n_invalid_global} linha(s) inválida(s) no Anexo V (turno/chave/correspondência)")
    if orphan_uf_turnos:
        motivos_globais.append(f"UF/turno no Anexo V sem correspondente em closure: {orphan_uf_turnos}")
    if prov_errors:
        motivos_globais.extend(prov_errors)

    orfaos_detalhe: list[dict] = []
    duplicatas_detalhe: list[dict] = []

    for _, r in base.iterrows():
        uf = str(r["sg_uf"]).upper()
        turno = int(r["nr_turno"])
        sub = valid_av[(valid_av["sg_uf"] == uf) & (valid_av["turno_int"] == turno)]
        uf_invalid = int((invalid_mask & (av["sg_uf_norm"] == uf)).sum())

        # Verificar duplicatas por (mun, zona, secao, correspondencia)
        dup_mask = sub.duplicated(subset=SEC_KEY + ["correspondencia"], keep=False)
        n_duplicatas = int(dup_mask.sum())
        if n_duplicatas > 0:
            for k_dup in sub.loc[dup_mask, SEC_KEY + ["correspondencia"]].drop_duplicates().to_dict("records"):
                duplicatas_detalhe.append({"sg_uf": uf, "nr_turno": turno, **k_dup})

        # Verificar completude dos pares Esperada / Efetivada antes do join
        counts_corr = sub.groupby(SEC_KEY + ["correspondencia"]).size().unstack(fill_value=0)
        for col_c in ("Esperada", "Efetivada"):
            if col_c not in counts_corr.columns:
                counts_corr[col_c] = 0
        incomplete_idx = counts_corr[(counts_corr["Esperada"] == 0) | (counts_corr["Efetivada"] == 0)].index
        n_incompletos = len(incomplete_idx)
        for idx_inc in incomplete_idx:
            orfaos_detalhe.append({
                "sg_uf": uf, "nr_turno": turno,
                "cd_municipio_tse": idx_inc[0], "nr_zona": idx_inc[1], "nr_secao": idx_inc[2],
                "n_esperada": int(counts_corr.loc[idx_inc, "Esperada"]),
                "n_efetivada": int(counts_corr.loc[idx_inc, "Efetivada"]),
            })

        complete_keys = counts_corr[(counts_corr["Esperada"] == 1) & (counts_corr["Efetivada"] == 1)].index
        esp = (
            sub[sub["correspondencia"] == "Esperada"]
            .drop_duplicates(subset=SEC_KEY)
            .set_index(SEC_KEY)
            .loc[lambda d: d.index.intersection(complete_keys)]
        )
        efe = (
            sub[sub["correspondencia"] == "Efetivada"]
            .drop_duplicates(subset=SEC_KEY)
            .set_index(SEC_KEY)
            .loc[lambda d: d.index.intersection(complete_keys)]
        )
        joined = esp[["id_urna"]].rename(columns={"id_urna": "urna_esp"}).join(
            efe[["id_urna", "ocorrencia", "origem"]].rename(columns={"id_urna": "urna_efe"}),
            how="inner",
        )
        # seção não instalada (exterior, 2026): o Anexo V a registra, mas sem urna efetivada ela não
        # tem linha na CEFT; fica fora da conciliação e é contada à parte (handoff 26)
        nao_inst = joined["ocorrencia"].astype(str).str.lower().str.contains("instalad", na=False)
        n_nao_inst = int(nao_inst.sum())
        joined = joined[~nao_inst]
        troca = joined["urna_esp"] != joined["urna_efe"]
        red_mesma = (~troca) & joined["origem"].astype(str).str.contains("RED", na=False)
        sa = joined["origem"].astype(str).eq("SA")

        ceft_set, ceft_insumos, ceft_status, ceft_motivo = _resolve_ceft_from_manifest(raw_dir, uf, turno)
        insumos_all.update(ceft_insumos)

        av_set = set(joined.index)
        dif_ceft: int | object = pd.NA
        av_only = pd.NA
        ceft_only = pd.NA
        row_motivos: list[str] = []

        turnos_av = set(valid_av["turno_int"].unique())
        if sub.empty:
            if turno not in turnos_av and ceft_status == "NAO_VERIFICADO":
                row_status = "NAO_VERIFICADO"
                any_unverified = True
                row_motivos.append(f"Anexo V e CEFT ausentes no catálogo para {uf}/T{turno} ({ceft_motivo})")
            else:
                row_status = "FAIL"
                any_fail = True
                row_motivos.append(f"sem linhas de Anexo V para {uf}/T{turno}")
        elif uf_invalid > 0 or n_duplicatas > 0 or n_incompletos > 0:
            row_status = "FAIL"
            any_fail = True
            if uf_invalid:
                row_motivos.append(f"{uf_invalid} linha(s) inválida(s)")
            if n_duplicatas:
                row_motivos.append(f"{n_duplicatas} linha(s) em chave duplicada")
            if n_incompletos:
                row_motivos.append(f"{n_incompletos} seção(ões) com par Esperada/Efetivada incompleto")
        elif ceft_status == "NAO_VERIFICADO":
            row_status = "NAO_VERIFICADO"
            any_unverified = True
            row_motivos.append(ceft_motivo)
        elif ceft_status == "FAIL" or ceft_set is None:
            row_status = "FAIL"
            any_fail = True
            row_motivos.append(ceft_motivo or f"falha ao ler CEFT de {uf}/T{turno}")
        else:
            dif_ceft = len(av_set ^ ceft_set)
            av_only = len(av_set - ceft_set)
            ceft_only = len(ceft_set - av_set)
            if dif_ceft != 0:
                row_status = "FAIL"
                any_fail = True
                row_motivos.append(
                    f"divergência Anexo V × CEFT em {uf}/T{turno}: dif={dif_ceft} "
                    f"(só Anexo V={av_only}, só CEFT={ceft_only})"
                )
            else:
                row_status = "PASS"

        if row_motivos:
            motivos_globais.append(f"{uf}/T{turno}: " + "; ".join(row_motivos))

        rows.append({
            "sg_uf": uf,
            "nr_turno": turno,
            "secoes_closure": int(r["secoes_closure"]),
            "secoes_reemissao_bu": int(r["secoes_reemissao_bu"]),
            "anexo_v_secoes": int(len(joined)),
            "anexo_v_troca_urna": int(troca.sum()),
            "anexo_v_red_mesma_urna": int(red_mesma.sum()),
            "anexo_v_sistema_apuracao": int(sa.sum()),
            "anexo_v_nao_instalada": n_nao_inst,
            "anexo_v_pares_incompletos": int(n_incompletos),
            "anexo_v_duplicatas": int(n_duplicatas),
            "anexo_v_linhas_invalidas": int(uf_invalid),
            "anexo_v_sem_ceft": av_only,
            "ceft_sem_anexo_v": ceft_only,
            "ceft_divergencias_conciliadas_dif": dif_ceft,
            "status_conciliacao": row_status,
            "motivo_conciliacao": "; ".join(row_motivos),
        })

    out = pd.DataFrame(rows)
    for col_int in ("anexo_v_sem_ceft", "ceft_sem_anexo_v", "ceft_divergencias_conciliadas_dif"):
        out[col_int] = out[col_int].astype("Int64")

    if any_fail:
        overall_status = "FAIL"
    elif any_unverified:
        overall_status = "BLOCKED"
    else:
        overall_status = "PASS"

    out.attrs["status"] = overall_status
    out.attrs["motivo"] = "; ".join(motivos_globais) if motivos_globais else (
        "Anexo V e CEFT reconciliados sem divergências via manifesto"
    )
    out.attrs["insumos_sha256"] = insumos_all
    out.attrs["orfaos"] = orfaos_detalhe
    out.attrs["duplicatas"] = duplicatas_detalhe
    out.attrs["orfaos_uf_turno"] = orphan_uf_turnos
    return out, (overall_status == "PASS")
