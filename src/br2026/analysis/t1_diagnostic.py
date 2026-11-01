"""Diagnóstico do 1º turno quando não há pares entre turnos (handoff 17, item 4.6; R18-2/R18-3).

Não inventa T2 nem deltas. Descreve, por UF e no total do universo com T1
apurado: cobertura e exclusões, contabilidade (válidos já sem "nulo técnico"),
participações nos válidos, perfil cadastral dos aptos (com motivos de exclusão
e classificação observada das unidades SEM_PERFIL) e horários BRUTOS de encerramento
(relógio sem fuso documentado: nenhuma faixa é atribuída). Razões são razões de
somas, nunca médias de percentuais.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

COUNTS_T1 = ["qt_aptos_t1", "qt_comparecimento_t1", "qt_abstencoes_t1", "qt_votos_validos_t1",
             "qt_votos_brancos_t1", "qt_votos_nulos_t1", "qt_lula_t1", "qt_flavio_t1"]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def missing_for_pairs(panel: pd.DataFrame, crosswalk: pd.DataFrame | None) -> list[str]:
    """Insumos exatos que faltam para o painel entre turnos."""
    falta = []
    if not panel.qt_aptos_t2.notna().any():
        falta.append("section_turn/votes_long do 2º turno (nr_turno=2) no staging")
    if crosswalk is None:
        falta.append("section_crosswalk")
    else:
        efet = crosswalk[crosswalk.status_correspondencia == "EFETIVADA"].groupby("nr_turno").size()
        for t in (1, 2):
            if efet.get(t, 0) == 0:
                falta.append(f"section_crosswalk EFETIVADA do {t}º turno (BU web/CEFT)")
    return falta


def t1_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.assign(t1_apurado=panel.qt_votos_validos_t1.notna(),
                     agregada=panel.tipo_unidade.eq("AGREGADO_SECOES"))
    g = p.groupby("sg_uf")
    return pd.DataFrame({
        "unidades": g.size(), "unidades_com_t1_apurado": g.t1_apurado.sum(),
        "unidades_agregadas": g.agregada.sum(), "secoes_origem": g.n_secoes_origem.sum(),
        "aptos_t1": g.qt_aptos_t1.sum(min_count=1),
    }).reset_index().merge(
        p.groupby(["sg_uf", "status_painel"]).size().unstack(fill_value=0).add_prefix("status_").reset_index(),
        on="sg_uf")


def t1_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel[panel.qt_votos_validos_t1.notna()].copy()
    # seções não instaladas (exterior, 2026): aptos sem comparecimento nem abstenção; entram na
    # identidade como parcela própria, como no Relatório de Totalização ("aptos nas seções não
    # instaladas"), e não como divergência (handoff 26)
    sem_votacao = (p.qt_comparecimento_t1 == 0) & (p.qt_abstencoes_t1 == 0)
    p["qt_aptos_sem_comparecimento_nem_abstencao_t1"] = p.qt_aptos_t1.where(sem_votacao, 0)
    g = p.groupby("sg_uf")[COUNTS_T1 + ["qt_aptos_sem_comparecimento_nem_abstencao_t1"]].sum()
    g.loc["TOTAL"] = g.sum()
    out = g.copy()
    div = lambda a, b: a / b.where(b > 0)
    out["share_lula_validos_t1"] = div(g.qt_lula_t1, g.qt_votos_validos_t1)
    out["share_flavio_validos_t1"] = div(g.qt_flavio_t1, g.qt_votos_validos_t1)
    out["margem_lula_flavio_validos_t1"] = out.share_lula_validos_t1 - out.share_flavio_validos_t1
    out["abstencao_aptos_t1"] = div(g.qt_abstencoes_t1, g.qt_aptos_t1)
    out["brancos_comparecimento_t1"] = div(g.qt_votos_brancos_t1, g.qt_comparecimento_t1)
    out["nulos_comparecimento_t1"] = div(g.qt_votos_nulos_t1, g.qt_comparecimento_t1)
    out["identidade_comparecimento_dif"] = (g.qt_comparecimento_t1 - g.qt_votos_validos_t1
                                            - g.qt_votos_brancos_t1 - g.qt_votos_nulos_t1)
    out["identidade_aptos_dif"] = (g.qt_aptos_t1 - g.qt_comparecimento_t1 - g.qt_abstencoes_t1
                                   - g.qt_aptos_sem_comparecimento_nem_abstencao_t1)
    return out.reset_index().rename(columns={"index": "sg_uf"})


def t1_profile_summary(shares: pd.DataFrame, diag: pd.DataFrame, panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(cobertura por UF × motivo, proporções cadastrais por UF ponderadas pelo cadastro)."""
    u = panel.set_index("id_unidade")[["sg_uf", "qt_aptos_t1"]]
    d = u.join(diag.set_index("id_unidade"), how="left")
    d["motivo_exclusao"] = d.motivo_exclusao.where(d.n_origens.notna(), "SEM_PERFIL").fillna("ELEGIVEL")
    cov = d.groupby(["sg_uf", "motivo_exclusao"]).agg(unidades=("qt_aptos_t1", "size"),
                                                      aptos_t1=("qt_aptos_t1", "sum")).reset_index()
    if shares.empty:
        return cov, pd.DataFrame()
    s = shares.join(d[["sg_uf", "total_cadastro"]], how="inner")
    w = s.total_cadastro.astype(float)
    cols = [c for c in shares.columns]
    agg = s[cols].mul(w, axis=0).groupby(s.sg_uf).sum().div(w.groupby(s.sg_uf).sum(), axis=0)
    long = agg.reset_index().melt(id_vars="sg_uf", var_name="categoria", value_name="proporcao_cadastro")
    long["rotulo"] = "cadastro dos aptos (data de geração do arquivo), não perfil de votantes"
    return cov, long


def _resolve_eleitorado_from_manifest(raw_dir: Path | None) -> tuple[Path | None, dict[str, str]]:
    """Resolve `eleitorado_local_votacao` pelo manifesto `data/raw/manifest.json` (`R18-2`)."""
    if raw_dir is None or not raw_dir.exists():
        return None, {}
    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.exists():
        return None, {}
    manifest_sha = _sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registros = manifest.get("registros") or {}
    candidatos = [
        (stem, reg) for stem, reg in registros.items()
        if isinstance(reg, dict) and reg.get("fonte") == "eleitorado_local_votacao"
    ]
    if len(candidatos) != 1:
        raise ValueError(
            f"manifest.json deve ter exatamente 1 registro ativo de eleitorado_local_votacao (encontrados: {len(candidatos)})"
        )
    _, reg = candidatos[0]
    arquivo = reg.get("arquivo")
    expected_sha = reg.get("sha256")
    if not arquivo or not expected_sha:
        raise ValueError("registro de eleitorado_local_votacao incompleto em manifest.json")
    zip_path = raw_dir / arquivo
    if not zip_path.exists():
        raise ValueError(f"arquivo eleitorado_local_votacao ausente em data/raw: {arquivo}")
    actual_sha = _sha256_file(zip_path)
    if actual_sha != expected_sha:
        raise ValueError(
            f"SHA-256 divergente em {arquivo} (esperado {expected_sha[:12]}…, obtido {actual_sha[:12]}…)"
        )
    insumos = {
        "data/raw/manifest.json": manifest_sha,
        f"data/raw/{arquivo}": actual_sha,
    }
    return zip_path, insumos


def t1_sem_perfil_breakdown(
    diag: pd.DataFrame,
    panel: pd.DataFrame,
    membership: pd.DataFrame,
    raw_dir: Path | None = None,
) -> pd.DataFrame:
    """Classifica as unidades SEM_PERFIL segundo CD_TIPO_LOCAL/DS_TIPO_LOCAL observados no eleitorado.

    Regras (`R18-2`, `R18-3`):
      * Resolve o ZIP de eleitorado exclusivamente via `data/raw/manifest.json` com verificação de SHA-256.
      * Agrega primeiro por `id_unidade` para que `qt_aptos_t1` da unidade nunca seja repetido/multiplicado
        quando uma unidade possui múltiplas seções em `membership`.
      * Restringe o rótulo ao fato observado nos campos consultados (`CD_TIPO_LOCAL`, `DS_TIPO_LOCAL`,
        `QT_ELEITOR_SECAO`); cronologia ou causa exigem fonte adicional e permanecem como hipótese.
    """
    u = panel.set_index("id_unidade")[["sg_uf", "qt_aptos_t1"]]
    d = u.join(diag.set_index("id_unidade"), how="left")
    d["motivo_exclusao"] = d.motivo_exclusao.where(d.n_origens.notna(), "SEM_PERFIL").fillna("ELEGIVEL")
    sem = d[d.motivo_exclusao == "SEM_PERFIL"].reset_index()
    if sem.empty or raw_dir is None:
        empty = pd.DataFrame()
        empty.attrs["insumos_sha256"] = {}
        return empty

    zip_path, insumos_sha = _resolve_eleitorado_from_manifest(raw_dir)
    if zip_path is None:
        empty = pd.DataFrame()
        empty.attrs["insumos_sha256"] = {}
        return empty

    mem_t1 = (
        membership[membership.nr_turno == 1][
            ["id_unidade", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
        ]
        .drop_duplicates()
        .merge(sem[["id_unidade", "sg_uf", "qt_aptos_t1"]], on=["id_unidade", "sg_uf"], how="inner")
    )
    if mem_t1.empty:
        empty = pd.DataFrame()
        empty.attrs["insumos_sha256"] = insumos_sha
        return empty

    lookup: dict[tuple[str, str, str, str], tuple[str, str, int]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for uf in sorted(mem_t1.sg_uf.unique()):
            csv_name = f"eleitorado_local_votacao_2026_{uf}.csv"
            if csv_name not in zf.namelist():
                continue
            with zf.open(csv_name) as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
                for row in reader:
                    if row.get("NR_TURNO", "").strip() != "1":
                        continue
                    key = (
                        row["SG_UF"].strip(),
                        row["CD_MUNICIPIO"].strip().zfill(5),
                        row["NR_ZONA"].strip().zfill(4),
                        row["NR_SECAO"].strip().zfill(4),
                    )
                    lookup[key] = (
                        row.get("CD_TIPO_LOCAL", "").strip(),
                        row.get("DS_TIPO_LOCAL", "Nao classificado").strip(),
                        int(row.get("QT_ELEITOR_SECAO", "0") or 0),
                    )
    tipos = [
        lookup.get((r.sg_uf, r.cd_municipio_tse, r.nr_zona, r.nr_secao), ("", "Nao classificado", -1))
        for _, r in mem_t1.iterrows()
    ]
    mem_t1["cd_tipo_local"] = [t[0] for t in tipos]
    mem_t1["ds_tipo_local"] = [t[1] for t in tipos]
    mem_t1["qt_eleitor_secao_permanente"] = [t[2] for t in tipos]

    # Agrega primeiro por id_unidade: qt_aptos_t1 pertence à unidade e NÃO pode ser somado por seção.
    por_unidade = (
        mem_t1.groupby(["sg_uf", "id_unidade"], as_index=False)
        .agg(
            cd_tipo_local=("cd_tipo_local", lambda s: "|".join(sorted({str(v) for v in s if str(v)})) or ""),
            ds_tipo_local=("ds_tipo_local", lambda s: "|".join(sorted({str(v) for v in s if str(v)})) or "Nao classificado"),
            secoes=("nr_secao", "size"),
            qt_aptos_t1=("qt_aptos_t1", "first"),
            qt_eleitor_secao_permanente=("qt_eleitor_secao_permanente", "sum"),
        )
    )

    out = (
        por_unidade.groupby(["sg_uf", "cd_tipo_local", "ds_tipo_local"], as_index=False)
        .agg(
            unidades=("id_unidade", "size"),
            secoes=("secoes", "sum"),
            aptos_t1=("qt_aptos_t1", "sum"),
            qt_eleitor_secao_permanente=("qt_eleitor_secao_permanente", "sum"),
        )
    )
    out["rotulo"] = (
        "observado no arquivo de locais de votação (CD_TIPO_LOCAL, DS_TIPO_LOCAL e QT_ELEITOR_SECAO=0 no campo consultado); "
        "dt_referencia_cadastro não documentada e explicação cronológica tratada apenas como hipótese"
    )
    out.attrs["insumos_sha256"] = insumos_sha
    return out


def t1_closure_raw(closure: pd.DataFrame, turno: int = 1) -> pd.DataFrame:
    """Distribuição do RELÓGIO BRUTO do encerramento por UF (hora cheia), sem fuso."""
    from br2026.analysis.closure_tz import parse_naive_series
    enc = closure[(closure.semantica == "ENCERRAMENTO_URNA") & (closure.nr_turno == turno)].copy()
    enc["hora_bruta"] = parse_naive_series(enc.ts_bruto).dt.hour
    enc["fuso"] = np.where(enc.fuso_documentado.astype(object).map(lambda v: isinstance(v, str) and bool(v)),
                           "DOCUMENTADO", "NAO_DOCUMENTADO")
    out = enc.groupby(["sg_uf", "fuso", "hora_bruta"], dropna=False).size().rename("secoes").reset_index()
    out["rotulo"] = "hora do relógio bruto do BU; sem fuso documentado não é horário de Brasília"
    return out
