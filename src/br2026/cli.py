"""CLI comum: `python -m br2026 [--root DIR] <etapa>`.

Raiz do projeto: `--root`, senão a variável de ambiente BR2026_ROOT, senão a raiz
deste checkout. Todas as etapas leem e escrevem só sob essa raiz
(data/raw, data/staging, data/analytics, reports/analysis), o que permite rodar
a CLI inteira num diretório temporário (testes de B e de C).

Códigos de saída: 0 sucesso; 1 falha de validação; 2 uso incorreto;
3 etapa ainda não implementada pela frente dona; 4 insumo ausente (BLOCKED);
5 falha controlada da etapa (exceção capturada e reportada).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

from br2026.contract import CONTRACT_DIR, PROJECT_ROOT, TABLES, ContractError, validate_parquet

EXIT_OK, EXIT_INVALID, EXIT_USAGE, EXIT_NOT_IMPLEMENTED, EXIT_BLOCKED, EXIT_STAGE_ERROR = 0, 1, 2, 3, 4, 5


def resolve_root(arg: str | None) -> Path:
    return Path(arg or os.environ.get("BR2026_ROOT") or PROJECT_ROOT).resolve()


def _stage(module: str, args) -> int:
    try:
        mod = importlib.import_module(f"br2026.{module}")
    except ImportError as e:
        print(f"{module}: módulo indisponível ({e})", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    if not hasattr(mod, "run"):
        print(f"{module}: NAO_IMPLEMENTADO (frente A)", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    kw = {"force": args.force} if module == "ingest" else {}
    try:
        res = mod.run(args.uf, args.turno, args.root, **kw)
    except Exception as e:  # falha da etapa de outra frente: reportada, não propagada
        print(f"{module}: FALHA {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_STAGE_ERROR
    print(json.dumps({"etapa": res.etapa, "linhas": res.linhas, "avisos": list(res.avisos),
                      "bloqueios": list(res.bloqueios)}, ensure_ascii=False))
    return EXIT_BLOCKED if res.bloqueios else EXIT_OK


def _validate(args) -> int:
    from br2026.panel.run import staging_path
    tables = TABLES if args.table == "all" else (args.table,)
    invalid = blocked = False
    for t in tables:
        spec = json.loads((CONTRACT_DIR / f"{t}.json").read_text(encoding="utf-8"))
        rel = Path(spec["path"])
        path = staging_path(args.root / rel.parent, rel.stem)
        if not path.exists():
            print(f"{t}: BLOCKED - {spec['path']} ausente")
            blocked = True
            continue
        try:
            validate_parquet(path, t)
            print(f"{t}: PASS")
        except ContractError as e:
            print(f"{t}: FAIL\n{e}")
            invalid = True
    return EXIT_INVALID if invalid else EXIT_BLOCKED if blocked else EXIT_OK


def _report_stage(name: str, res: dict) -> int:
    print(f"{name}: {json.dumps(res, ensure_ascii=False)}")
    return {"PASS": EXIT_OK, "FAIL": EXIT_INVALID, "BLOCKED": EXIT_BLOCKED}[res["status"]]


def _panel(args) -> int:
    from br2026.panel.run import run_panel
    return _report_stage("panel", run_panel(args.root / "data" / "staging", args.root / "data" / "analytics"))


def _analyze(args) -> int:
    from br2026.analysis.run import run_analyze
    return _report_stage("analyze", run_analyze(args.root / "data" / "staging",
                                                args.root / "data" / "analytics"))


def _report(args) -> int:
    from br2026.reporting.build import build_report
    return _report_stage("report", build_report(args.root / "data" / "analytics",
                                                args.root / "reports" / "analysis"))


SOCIO_ETAPAS = ("ibge", "rais", "pbf", "entorno", "analise")


def _socio(args) -> int:
    """Extensão socioeconômica (handoff 37): aquisição/derivação das frentes 34–36 e análises.

    Cada etapa reaproveita o próprio cache por SHA-256 (retomada); `--offline` proíbe rede nas etapas
    que a usariam. Referências temporais e parâmetros espaciais vêm de config [socio]."""
    from br2026.config import load_config
    cfg = load_config()["socio"]
    root = str(args.root)
    etapas = [e.strip() for e in args.etapas.split(",") if e.strip()]
    if not set(etapas) <= set(SOCIO_ETAPAS):
        print(f"socio: etapas desconhecidas {sorted(set(etapas) - set(SOCIO_ETAPAS))}")
        return EXIT_USAGE
    ufs = "AC,AL,AM,AP,BA,CE,DF,ES,GO,MA,MG,MS,MT,PA,PB,PE,PI,PR,RJ,RN,RO,RR,RS,SC,SE,SP,TO"
    for e in etapas:
        if e == "ibge":
            from br2026.ingest import socio_ibge
            rc = socio_ibge.main(["--ufs", "ALL", "--project-root", root] + (["--offline"] if args.offline else []))
        elif e == "rais":
            from br2026.ingest import socio_rais
            rc = 0
            for ano in [cfg["rais_ano"], *cfg["rais_anos_auditoria"]]:
                arq = args.root / "data" / "raw" / "socio_rais" / f"RAIS_ESTAB_PUB_{ano}.7z"
                if args.offline and not arq.exists():
                    print(f"socio/rais: {arq.name} ausente e --offline")
                    return EXIT_BLOCKED
                rc |= socio_rais.main(["--project-root", root, "--ano", str(ano)])
        elif e == "pbf":
            from br2026.ingest import socio_pbf
            rc = 0
            for comp in [cfg["pbf_competencia"], *cfg["pbf_competencias_auditoria"]]:
                arq = args.root / "data" / "raw" / "socio_pbf" / f"{comp}_NovoBolsaFamilia.zip"
                if args.offline and not arq.exists():
                    print(f"socio/pbf: {arq.name} ausente e --offline")
                    return EXIT_BLOCKED
                rc |= socio_pbf.main(["--project-root", root, "--competencia", comp])
        elif e == "entorno":
            from br2026.ingest import entorno_nacional
            # versão final (handoff 40): só o raio principal; lista de sensibilidades vazia ou ausente é aceita
            sens = ",".join(str(r) for r in cfg.get("entorno_sensibilidades_m", []))
            params = ["--raio", str(cfg["entorno_raio_m"]), "--sensibilidades", sens,
                      "--cobertura-min", str(cfg["entorno_cobertura_area_min"]),
                      "--renda-min", str(cfg["entorno_cobertura_renda_min"]),
                      "--tolerancia-municipio-m", str(cfg["entorno_tolerancia_municipio_m"])]
            print(f"socio/entorno: {' '.join(params)}")
            rc = entorno_nacional.main(["--ufs", ufs] + params)
        else:
            import runpy
            mod = runpy.run_path(str(args.root / "tools" / "analise_socio.py"), run_name="br2026_socio")
            rc = mod["main"](["--offline"] if args.offline else [])
        print(f"socio/{e}: código {rc}")
        if rc:
            return EXIT_STAGE_ERROR
    return EXIT_OK


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="br2026")
    p.add_argument("--root", default=None,
                   help="raiz do projeto (padrão: BR2026_ROOT ou este checkout)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "normalize"):
        s = sub.add_parser(name)
        s.add_argument("--uf", required=True, help="UF, BR (todas) ou ZZ (exterior)")
        s.add_argument("--turno", type=int, choices=[1, 2], required=True)
        if name == "ingest":
            s.add_argument("--force", action="store_true")
        s.set_defaults(func=lambda a, n=name: _stage(n, a))
    s = sub.add_parser("validate")
    s.add_argument("--table", default="all", choices=("all",) + TABLES)
    s.set_defaults(func=_validate)
    sub.add_parser("panel").set_defaults(func=_panel)
    sub.add_parser("analyze").set_defaults(func=_analyze)
    sub.add_parser("report").set_defaults(func=_report)
    s = sub.add_parser("socio", help="extensão socioeconômica (handoff 37)")
    s.add_argument("--etapas", default=",".join(SOCIO_ETAPAS), help=f"subconjunto de {','.join(SOCIO_ETAPAS)}")
    s.add_argument("--offline", action="store_true", help="sem rede: só caches verificados por hash")
    s.set_defaults(func=_socio)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = p.parse_args(argv)
    args.root = resolve_root(args.root)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
