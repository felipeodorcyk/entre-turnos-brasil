"""Etapa `panel`: lê staging validado, constrói painel, vínculo, reconciliação e cobertura."""
from __future__ import annotations

from pathlib import Path

from br2026.config import election_numbers, load_config
from br2026.contract import validate, validate_parquet
from br2026.panel.build import build_panel, coverage, reconcile

INPUTS = ("section_turn", "votes_long", "section_crosswalk")


def staging_path(staging: Path, table: str) -> Path:
    """Arquivo `<tabela>.parquet` ou diretório particionado `<tabela>/`."""
    f = staging / f"{table}.parquet"
    return f if f.exists() else staging / table


def missing_inputs(staging: Path, tables=INPUTS) -> list[str]:
    return [t for t in tables if not staging_path(staging, t).exists()]


def run_panel(staging: Path, out: Path, cfg: dict | None = None) -> dict:
    """Retorna {'status': PASS|FAIL|BLOCKED, ...}; escreve em `out` só se não BLOCKED."""
    miss = missing_inputs(staging)
    if miss:
        return {"status": "BLOCKED", "motivo": f"staging ausente: {miss}"}
    st, vl, cw = (validate_parquet(staging_path(staging, t), t) for t in INPUTS)
    cfg = cfg or load_config()
    lula, flavio = election_numbers(cfg)
    tec = cfg["election"].get("nulo_tecnico")
    panel, mem = build_panel(st, vl, cw, lula, flavio, return_membership=True, technical_null=tec)
    validate(panel, "panel")
    validate(mem, "panel_membership")
    out.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(out / "panel.parquet", index=False)
    mem.to_parquet(out / "panel_membership.parquet", index=False)
    rec = reconcile(panel, mem, st, vl, lula, flavio, technical_null=tec)
    rec.to_csv(out / "panel_reconciliation.csv", index=False)
    coverage(panel, ["sg_uf"]).to_csv(out / "coverage_uf.csv", index=False)
    coverage(panel, ["sg_uf", "cd_municipio_tse"]).to_csv(out / "coverage_municipio.csv", index=False)
    problems = []
    if (rec.dif != 0).any():
        problems.append(f"{int((rec.dif != 0).sum())} linha(s) de reconciliação com dif != 0")
    if rec.attrs["secoes_sem_unidade"]:
        problems.append(f"{rec.attrs['secoes_sem_unidade']} seção(ões) sem unidade")
    if rec.attrs["secoes_duplicadas"]:
        problems.append(f"{rec.attrs['secoes_duplicadas']} seção(ões) duplicada(s)")
    return {"status": "FAIL" if problems else "PASS", "problemas": problems,
            "unidades": len(panel), "pareadas": int((panel.status_painel == "PAREADA").sum())}
