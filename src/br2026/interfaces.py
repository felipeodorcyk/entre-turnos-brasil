"""Interfaces entre frentes (contrato v1). Mudança exige nova versão do contrato.

Ingestão e normalização (frente A) expõem, em `br2026.ingest` e
`br2026.normalize`, funções com exatamente estas assinaturas. A CLI as chama;
painel, análise e relatório (frente B) leem apenas as tabelas de staging
validadas por `br2026.contract.validate`, nunca os brutos.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StageResult:
    """Resumo devolvido por cada etapa; não contém linhas de dados."""
    etapa: str
    arquivos: tuple[Path, ...]
    linhas: dict[str, int]
    avisos: tuple[str, ...] = ()
    bloqueios: tuple[str, ...] = ()


class Ingest(Protocol):
    def run(self, uf: str, turno: int, project_root: Path, *, force: bool = False) -> StageResult:
        """Baixa/reaproveita brutos para UF ('BR' = todas, 'ZZ' = exterior) e turno,
        atualizando data/raw/manifest.json. Promoção atômica; sem sobrescrita silenciosa."""


class Normalize(Protocol):
    def run(self, uf: str, turno: int, project_root: Path) -> StageResult:
        """Produz as cinco tabelas de staging (votes_long, section_turn,
        section_crosswalk, profiles, closure) particionadas por UF/turno em
        data/staging/, cada uma validada pelo contrato v1."""
