"""Etapa `analyze`: orquestra as funções testadas sobre o painel aceito.

Pré-condição: `panel` com reconciliação PASS. Cada bloco grava tabelas em
data/analytics/ e uma linha em `analysis_status.csv` (PASS, NAO_ESTIMADO com
motivo, ou BLOCKED). Insuficiência de dados é verificada ANTES de estimar, por
regra explícita; erros inesperados não são engolidos.

Universos: `pareado_territorial` (UFs), `pareado_exterior` (ZZ) e
`pareado_total`. Fluxos, associações e horários usam só o territorial.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from br2026.analysis import associations as assoc
from br2026.analysis.bounds import aggregate_bounds, merged_origin_bounds
from br2026.analysis.closure import band_transitions, classify
from br2026.analysis.closure_audit import ocorrencias_urna_summary, receipt_consistency
from br2026.analysis.closure_models import pairwise_comparison
from br2026.analysis.closure_tz import apply_offsets, infer_municipal_offsets, select_closure_variant
from br2026.analysis.context import municipal_features
from br2026.analysis.ecological import (cluster_bootstrap, compare_specifications,
                                        fit_constant_rates, publication_decision,
                                        unit_tables_ipf)
from br2026.analysis.margins import ENTRADA, build_margins, group_small
from br2026.analysis.metrics import (aggregate_metrics, share_contributions,
                                     turnout_flow_bounds, unit_metrics)
from br2026.analysis.profile import profile_design, unit_profile
from br2026.analysis.t1_diagnostic import (missing_for_pairs, t1_closure_raw, t1_coverage,
                                           t1_metrics, t1_profile_summary, t1_sem_perfil_breakdown)
from br2026.config import election_dates, load_config
from br2026.contract import CONTRACT_VERSION, PROJECT_ROOT, validate_parquet
from br2026.panel.build import aggregate_panel
from br2026.panel.run import staging_path

GEO = ["sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]


class Analysis:
    def __init__(self, staging: Path, analytics: Path, cfg: dict | None = None):
        self.staging, self.out = Path(staging), Path(analytics)
        self.cfg = cfg or load_config()
        self.status: list[dict] = []
        self.outputs: dict[str, int] = {}
        self.inputs: dict[str, str] = {}

    # ------------------------------------------------------------------ utilidades
    def _log(self, bloco: str, status: str, motivo: str = "") -> None:
        self.status.append({"bloco": bloco, "status": status, "motivo": motivo})

    def _write(self, df: pd.DataFrame, name: str) -> None:
        path = self.out / name
        if name.endswith(".parquet"):
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)
        self.outputs[name] = len(df)

    def _write_json(self, obj: dict, name: str) -> None:
        (self.out / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json),
                                     encoding="utf-8")
        self.outputs[name] = 1

    def _hash_input(self, path: Path) -> None:
        h = hashlib.sha256()
        files = sorted(path.rglob("*.parquet")) if path.is_dir() else [path]
        for f in files:
            h.update(f.name.encode())
            h.update(f.read_bytes())
        self.inputs[path.relative_to(path.parents[1]).as_posix()] = h.hexdigest()

    # ------------------------------------------------------------------ carga
    def load(self) -> str | None:
        """Carrega e valida insumos; devolve motivo de bloqueio ou None."""
        need = {"panel.parquet": self.out / "panel.parquet",
                "panel_membership.parquet": self.out / "panel_membership.parquet",
                "panel_reconciliation.csv": self.out / "panel_reconciliation.csv"}
        miss = [k for k, p in need.items() if not p.exists()]
        if miss:
            return f"rode `panel` antes: ausentes {miss}"
        rec = pd.read_csv(need["panel_reconciliation.csv"])
        if (rec.dif != 0).any():
            return "reconciliação do painel com dif != 0; análise não roda sobre painel não aceito"
        vl_path = staging_path(self.staging, "votes_long")
        if not vl_path.exists():
            return "staging votes_long ausente"
        self.panel = validate_parquet(need["panel.parquet"], "panel")
        self.membership = validate_parquet(need["panel_membership.parquet"], "panel_membership")
        self.votes = validate_parquet(vl_path, "votes_long")
        for p in (need["panel.parquet"], need["panel_membership.parquet"], vl_path):
            self._hash_input(p)
        # o painel deriva de section_turn: registra o insumo e, por tabela e turno, os SHA-256 dos
        # brutos oficiais (source_id) de que as linhas vieram, para o rastro chegar à fonte
        st_path = staging_path(self.staging, "section_turn")
        if st_path.exists():
            self._hash_input(st_path)
        self.fontes_brutas = []
        for nome, path in (("votes_long", vl_path), ("section_turn", st_path),
                           ("section_crosswalk", staging_path(self.staging, "section_crosswalk"))):
            if not path.exists():
                continue
            cols = ["nr_turno", "source_id"] + (["fonte"] if nome == "section_crosswalk" else [])
            src = pd.read_parquet(path, columns=cols).drop_duplicates()
            for r in src.itertuples(index=False):
                self.fontes_brutas.append({"tabela": nome, "nr_turno": int(r.nr_turno), "source_id": r.source_id,
                                           **({"fonte": r.fonte} if nome == "section_crosswalk" else {})})
        for name in ("closure", "profiles", "section_crosswalk", "municipal_context"):
            path = staging_path(self.staging, name)
            df = validate_parquet(path, name) if path.exists() else None
            if df is not None:
                self._hash_input(path)
            setattr(self, {"section_crosswalk": "crosswalk", "municipal_context": "context"}.get(name, name), df)
        zz = self.cfg["universe"]["uf_exterior"]
        par = self.panel[self.panel.status_painel == "PAREADA"]
        self.universes = {"pareado_territorial": par[par.sg_uf != zz],
                          "pareado_exterior": par[par.sg_uf == zz],
                          "pareado_total": par}
        self.terr = self.universes["pareado_territorial"].reset_index(drop=True)
        return None

    # ------------------------------------------------------------------ diagnóstico T1
    def t1_diagnostic(self) -> None:
        """Sempre produzido; é a entrega analítica quando não há pares entre turnos."""
        self.missing_pairs = missing_for_pairs(self.panel, self.crosswalk)
        self._write(t1_coverage(self.panel), "t1_coverage_uf.csv")
        m = t1_metrics(self.panel)
        self._write(m, "t1_metrics_uf.csv")
        bad = m[(m.identidade_comparecimento_dif != 0) | (m.identidade_aptos_dif != 0)]
        self._log("t1:contabilidade", "PASS" if bad.empty else "FAIL",
                  "identidades de aptos e comparecimento fecham por UF (válidos sem nulo técnico)"
                  if bad.empty else f"identidade não fecha em {list(bad.sg_uf)}")
        if self.profiles is not None and self.crosswalk is not None:
            shares, diag = unit_profile(self.profiles, self.crosswalk, self.membership, self.cfg)
            cov, prof = t1_profile_summary(shares, diag, self.panel[self.panel.qt_aptos_t1.notna()])
            self._write(cov, "t1_profile_coverage_uf.csv")
            self._write(prof, "t1_profile_uf.csv")
            proj_root = self.staging.parents[1] if self.staging.parent.name == "data" else self.staging.parent
            try:
                sem_bd = t1_sem_perfil_breakdown(
                    diag, self.panel[self.panel.qt_aptos_t1.notna()], self.membership, proj_root / "data" / "raw"
                )
                self.inputs.update(sem_bd.attrs.get("insumos_sha256", {}))
                if not sem_bd.empty:
                    self._write(sem_bd, "t1_profile_sem_perfil_uf.csv")
                self._log("t1:perfil", "PASS", "perfil cadastral dos aptos por UF; exclusões por motivo")
            except ValueError as exc:
                self._log("t1:perfil", "FAIL", f"falha de integridade no eleitorado de locais: {exc}")
        else:
            self._log("t1:perfil", "BLOCKED", "staging profiles/section_crosswalk ausente")
        if self.closure is not None:
            self._write(t1_closure_raw(self.closure), "t1_closure_raw_uf.csv")
            rs, rc = receipt_consistency(self.closure)
            self._write(rs, "t1_receipt_consistency.csv")
            self._log("t1:horarios_brutos", "PASS",
                      f"relógio bruto do encerramento por UF (sem fuso); recebimentos: {len(rc)} seção(ões) "
                      "fora de MESMO_EVENTO")
        if self.context is not None and self.cfg["context"]["variaveis"]:
            feats, cdiag = municipal_features(self.context, self.cfg)
            mun = self.panel[self.panel.qt_aptos_t1.notna()][["sg_uf", "cd_municipio_tse"]].drop_duplicates()
            j = mun.join(feats, on=["sg_uf", "cd_municipio_tse"])
            j["completo"] = j[list(feats.columns)].notna().all(axis=1)
            cov = j.groupby("sg_uf").agg(municipios_t1=("cd_municipio_tse", "size"),
                                         com_contexto_completo=("completo", "sum")).reset_index()
            self._write(cov, "t1_context_coverage_uf.csv")
            self._write(cdiag.assign(anos_referencia=cdiag.anos_referencia.astype(str)), "context_coverage.csv")
            self._log("t1:contexto", "PASS", f"{int(cov.com_contexto_completo.sum())} de "
                      f"{int(cov.municipios_t1.sum())} município(s) do T1 com contexto completo; contexto do "
                      "município, não dos eleitores")
        else:
            self._log("t1:contexto", "BLOCKED", "staging municipal_context ausente ou variáveis não definidas")
        self._log("t1:painel_entre_turnos", "BLOCKED" if self.missing_pairs else "PASS",
                  "; ".join(self.missing_pairs) or "insumos dos dois turnos presentes")

    # ------------------------------------------------------------------ B2
    def descriptive(self) -> None:
        rows = []
        for u, p in self.universes.items():
            if p.empty:
                self._log(f"descricao:{u}", "NAO_ESTIMADO", "universo vazio")
                continue
            m = aggregate_metrics(p)
            m.pop("totais")
            rows += [{"universo": u, "metrica": k, "valor": v, "n_unidades": len(p)}
                     for k, v in m.items()]
            self._log(f"descricao:{u}", "PASS")
        self._write(pd.DataFrame(rows), "metrics_aggregate.csv")
        um = unit_metrics(self.panel)
        self._write(um, "metrics_units.parquet")
        self.unit_metrics = um.set_index("id_unidade")
        if self.terr.empty:
            self._log("contribuicoes_uf", "NAO_ESTIMADO", "sem unidades pareadas territoriais")
            return

        # Métricas por UF e total do piloto (universo pareado vs. universo oficial completo)
        uf_rows = []
        for uf, grp in self.terr.groupby("sg_uf"):
            am = aggregate_metrics(grp)
            tot = am.pop("totais")
            uf_rows.append({"sg_uf": uf, "universo": "pareado_territorial", "n_unidades": len(grp), **tot, **am})
        am_tot = aggregate_metrics(self.terr)
        tot_pil = am_tot.pop("totais")
        uf_rows.append({"sg_uf": "TOTAL", "universo": "pareado_territorial", "n_unidades": len(self.terr),
                        **tot_pil, **am_tot})
        self._write(pd.DataFrame(uf_rows), "metrics_uf.csv")

        # Camadas (handoff 26): grandes regiões do IBGE, território, exterior e Brasil, com as mesmas
        # somas por unidade. O exterior não entra nas regiões nem nos modelos territoriais.
        camadas = [(f"REGIAO_{r}", self.terr[self.terr.sg_uf.isin(ufs)]) for r, ufs in REGIOES.items()]
        camadas += [("TERRITORIO", self.terr), ("EXTERIOR", self.universes["pareado_exterior"]),
                    ("BRASIL", self.universes["pareado_total"])]
        cam_rows = []
        for nome, grp in camadas:
            if grp.empty:
                continue
            am = aggregate_metrics(grp)
            tot = am.pop("totais")
            cam_rows.append({"camada": nome, "n_ufs": int(grp.sg_uf.nunique()), "n_unidades": len(grp),
                             **tot, **am})
        self._write(pd.DataFrame(cam_rows), "metrics_camadas.csv")

        # Métricas e contribuições por município (Pergunta A: concentração e decomposição municipal)
        mun_rows = []
        for (uf, mun_cd), grp in self.terr.groupby(["sg_uf", "cd_municipio_tse"]):
            am = aggregate_metrics(grp)
            tot = am.pop("totais")
            mun_rows.append({"sg_uf": uf, "cd_municipio_tse": mun_cd, "n_unidades": len(grp), **tot, **am})
        self._write(pd.DataFrame(mun_rows), "metrics_municipio.csv")

        for cand in ("lula", "flavio"):
            c = share_contributions(self.terr, cand, ["sg_uf"])
            c.insert(0, "candidato", cand)
            self._write(c, f"contributions_uf_{cand}.csv")
            cm = share_contributions(self.terr, cand, ["sg_uf", "cd_municipio_tse"])
            cm.insert(0, "candidato", cand)
            self._write(cm, f"contributions_municipio_{cand}.csv")
        self._log("contribuicoes_uf", "PASS")

        # Sensibilidade à agregação da unidade (SECAO vs LOCAL vs MUNICIPIO). Os totais agregados são
        # invariantes ao nível por construção; a linha SEM_AGREGACAO muda o universo: só unidades de
        # uma seção de origem, cuja correspondência é trivial nos dois turnos (decisão D-T2-01).
        sens_rows = []
        for nivel, df_lvl in [
            ("SECAO_UNIDADE", self.terr),
            ("LOCAL", aggregate_panel(self.terr, "LOCAL")),
            ("MUNICIPIO", aggregate_panel(self.terr, "MUNICIPIO")),
            ("SECAO_UNIDADE_SEM_AGREGACAO", self.terr[self.terr.n_secoes_origem == 1]),
        ]:
            am = aggregate_metrics(df_lvl)
            tot = am.pop("totais")
            sens_rows.append({
                "nivel_agregacao": nivel,
                "n_grupos": len(df_lvl),
                "qt_aptos_t1": tot["qt_aptos_t1"],
                "qt_aptos_t2": tot["qt_aptos_t2"],
                "qt_votos_validos_t1": tot["qt_votos_validos_t1"],
                "qt_votos_validos_t2": tot["qt_votos_validos_t2"],
                "delta_share_lula_validos": am["delta_share_lula_validos"],
                "delta_share_flavio_validos": am["delta_share_flavio_validos"],
                "delta_margem_lula_flavio_validos": am["delta_margem_lula_flavio_validos"],
                "delta_comparecimento_aptos": am["delta_comparecimento_aptos"],
            })
        self._write(pd.DataFrame(sens_rows), "panel_aggregation_sensitivity.csv")

        b = turnout_flow_bounds((self.terr.qt_aptos_t1, self.terr.qt_aptos_t2),
                                self.terr.qt_comparecimento_t1, self.terr.qt_comparecimento_t2)
        ok = b.motivo.isna()
        agg = {"universo": "pareado_territorial", "unidades": len(b),
               "unidades_com_limites": int(ok.sum()),
               "unidades_aptos_diferentes": int((~ok).sum()),
               "variacao_liquida_comparecimento": int(b.variacao_liquida.sum()),
               # mesmo universo dos limites abaixo (só unidades com aptos iguais)
               "variacao_liquida_comparecimento_com_limites": int(b.loc[ok, "variacao_liquida"].sum())}
        for c in ("ambos", "entradas", "saidas"):
            agg[f"{c}_min"] = float(b.loc[ok, f"{c}_min"].sum())
            agg[f"{c}_max"] = float(b.loc[ok, f"{c}_max"].sum())
        agg["condicao"] = ("limites válidos só sob a hipótese de MESMOS integrantes entre turnos; "
                           "aptos iguais não provam composição igual")
        self._write(pd.DataFrame([agg]), "turnout_bounds.csv")
        self._log("comparecimento_limites", "PASS",
                  "limites somados só nas unidades com aptos iguais, condicionais a população idêntica")

    # ------------------------------------------------------------------ B4
    def _t1_candidates(self) -> pd.DataFrame:
        e = self.cfg["election"]
        tecnico = e.get("nulo_tecnico", {}).get("t1", [])
        # Votos "nulo técnico" já estão nos nulos do painel; não são candidatura válida de origem.
        v = self.votes[(self.votes.cd_cargo == e["cd_cargo_presidente"]) & (self.votes.nr_turno == 1)
                       & self.votes.tipo_votavel.isin(["NOMINAL", "LEGENDA"])
                       & ~self.votes.nr_votavel.isin(tecnico)]
        v = v.merge(self.membership[self.membership.nr_turno == 1], on=["nr_turno"] + GEO,
                    how="left", validate="many_to_one")
        if v.id_unidade.isna().any():
            raise ValueError("Votos do T1 sem unidade no vínculo do painel")
        names = {e["nr_votavel_lula"]: "LULA_T1", e["nr_votavel_flavio"]: "FLAVIO_T1"}
        v["origem"] = v.nr_votavel.map(lambda n: names.get(int(n), f"CAND_{int(n)}"))
        return v.pivot_table(index="id_unidade", columns="origem", values="qt_votos",
                             aggfunc="sum", fill_value=0)

    def _grouped(self, cand: pd.DataFrame, limiar: float) -> pd.DataFrame:
        share = cand.sum() / cand.to_numpy().sum()
        keep = sorted({"LULA_T1", "FLAVIO_T1"} | set(share[share >= limiar].index))
        return group_small(cand, keep)

    def flows(self) -> None:
        fc, ec = self.cfg["flows"], self.cfg["ecological"]
        if self.terr.empty:
            self._log("fluxos", "NAO_ESTIMADO", "sem unidades pareadas territoriais")
            return
        cand = self._t1_candidates().reindex(self.terr.id_unidade).fillna(0).astype("int64")
        main_lim = fc["limiar_candidato_separado"]
        equal = (self.terr.qt_aptos_t1 == self.terr.qt_aptos_t2).to_numpy()
        # (limiar, ρ, universo, principal). O principal é o cenário de rotatividade mínima.
        scenarios = [(main_lim, 0.0, "todas_pareadas", True)]
        scenarios += [(lim, 0.0, "todas_pareadas", False) for lim in fc["sensibilidade_limiares"]]
        scenarios += [(main_lim, rho, "todas_pareadas", False) for rho in fc["rotatividade_sensibilidade"]]
        scenarios += [(main_lim, 0.0, "aptos_iguais", False)]
        bounds_rows, beta_rows = [], []
        for limiar, rho, universo, principal in scenarios:
            sel = equal if universo == "aptos_iguais" else np.ones(len(self.terr), bool)
            if not sel.any():
                self._log(f"fluxos:{universo}", "NAO_ESTIMADO", "universo vazio")
                continue
            terr = self.terr[sel]
            m = build_margins(terr, self._grouped(cand.loc[terr.id_unidade], limiar), rotatividade=rho)
            X, Y = m["origens"].to_numpy(float), m["destinos"].to_numpy(float)
            O, D = m["nomes_origem"], m["nomes_destino"]
            b = aggregate_bounds(X, Y, O, D, self.cfg["identification"]["largura_pouco_informativa"])
            tags = {"limiar_candidato": limiar, "cenario_populacao": m["cenario_populacao"],
                    "universo_fluxo": universo, "principal": principal}
            for n, (k, v) in enumerate(tags.items()):
                b.insert(n, k, v)
            b["condicao"] = "limites condicionais ao cenário de população; não são fluxos observados"
            bounds_rows.append(b)
            specs = compare_specifications(X, Y, ec["lambdas_regularizacao"])
            if principal:
                strata = terr.sg_uf.to_numpy()
                counts = pd.Series(strata).value_counts()
                s_mask = np.isin(strata, counts[counts >= fc["estrato_min_unidades"]].index)
                if s_mask.any():
                    specs += compare_specifications(X[s_mask], Y[s_mask], [], strata=strata[s_mask])
            for sp in specs:
                for i, o in enumerate(O):
                    for j, d in enumerate(D):
                        beta_rows.append({**tags, "especificacao": sp["especificacao"], "origem": o,
                                          "destino": d, "taxa": sp["beta"][i, j],
                                          "taxas_constantes_identificadas_numericamente": sp["identificado"],
                                          "residuo_relativo_max": sp["residuo_relativo_max"]})
            if principal:
                self._flows_main(X, Y, O, D, b, m)
                self._flows_demais_para_lula(X, Y, O, D, terr, m)
        self._write(pd.concat(bounds_rows, ignore_index=True), "flow_bounds.csv")
        betas = pd.DataFrame(beta_rows)
        betas["publicavel"] = (betas.principal & (betas.especificacao == "global_lambda_0.0")
                               & bool(self.flow_decision["publicar_matriz_pontual"]))
        betas["transicoes_individuais_identificadas"] = False
        betas["rotulo"] = ("taxa média sob hipóteses de taxas constantes e do cenário de população; "
                           "não é voto individual observado")
        self._write(betas, "ecological_rates.csv")

    def _flows_demais_para_lula(self, X, Y, O, D, terr, m) -> None:
        """Teste "100% dos demais candidatos do T1 → Lula" (handoff 22): limites conjuntos da
        origem agregada, por UF e no piloto. Possível/necessário dizem respeito só às marginais;
        o fluxo individual não é observável (sigilo do voto)."""
        nao_cand = {"LULA_T1", "FLAVIO_T1", "ABSTENCAO", "BRANCO", "NULO", ENTRADA}
        idx = [i for i, o in enumerate(O) if o not in nao_cand]
        if not idx or "LULA" not in D:
            self._log("fluxos:demais_para_lula", "NAO_ESTIMADO", "sem origem de demais candidatos")
            return
        lo, hi = merged_origin_bounds(X, Y, idx, D.index("LULA"))
        r = X[:, idx].sum(1)
        ufs = terr.sg_uf.to_numpy()
        rows = []
        for uf in list(dict.fromkeys(ufs)) + ["TOTAL"]:
            s = np.ones(len(ufs), bool) if uf == "TOTAL" else ufs == uf
            tot, fmin, fmax = r[s].sum(), lo[s].sum(), hi[s].sum()
            rows.append({"sg_uf": uf, "cenario_populacao": m["cenario_populacao"],
                         "origens_agregadas": "+".join(O[i] for i in idx),
                         "unidades": int(s.sum()), "qt_demais_t1": int(tot),
                         "fluxo_min": fmin, "fluxo_max": fmax,
                         "taxa_min": fmin / tot if tot > 0 else np.nan,
                         "taxa_max": fmax / tot if tot > 0 else np.nan,
                         "unidades_que_impedem_100pct": int((hi[s] < r[s]).sum()),
                         "teste_100pct_possivel": bool(tot > 0 and fmax == tot),
                         "teste_100pct_necessario": bool(tot > 0 and fmin == tot),
                         "teste_100pct_observado": "NAO_IDENTIFICAVEL_POR_SIGILO"})
        self._write(pd.DataFrame(rows), "flow_demais_para_lula.csv")

    def _flows_main(self, X, Y, O, D, bounds, m) -> None:
        ec, fc = self.cfg["ecological"], self.cfg["flows"]
        fit = fit_constant_rates(X, Y, max_condition=ec["condicao_maxima"])
        dec = publication_decision(fit, bounds, max_resid=fc["residuo_maximo_publicacao"])
        dec.update({"taxas_constantes_identificadas_numericamente": fit.identificado,
                    "transicoes_individuais_identificadas": False,
                    "nota_identificacao": ("o condicionamento de X'WX só indica se as taxas MÉDIAS sob a hipótese "
                                           "de taxas constantes são recuperáveis das marginais; as transições "
                                           "individuais e a heterogeneidade intraunidade continuam não "
                                           "identificadas (ver flow_bounds.csv)"),
                    "cenario_populacao": m["cenario_populacao"], "hipotese_populacao": m["hipotese"],
                    "condicao": fit.condicao, "convergiu": fit.convergiu,
                    "residuo_relativo_max": fit.residuo_relativo_max, "avisos": fit.avisos,
                    "unidades": int(len(X)), "unidades_aptos_divergentes": m["unidades_aptos_divergentes"],
                    "origens": O, "destinos": D})
        self.flow_decision = dec
        self._write_json(dec, "ecological_decision.json")
        T, err = unit_tables_ipf(X, Y, fit.beta)
        flows = T.sum(0)
        self._write(pd.DataFrame([{"origem": o, "destino": d, "fluxo": flows[i, j],
                                   "erro_marginal_max_unidade": err,
                                   "rotulo": "conservação exata das marginais; distribuição interna "
                                             "depende da hipótese do modelo"}
                                  for i, o in enumerate(O) for j, d in enumerate(D)]),
                    "ecological_ipf_flows.csv")
        groups = (self.terr.sg_uf + "-" + self.terr.cd_municipio_tse).to_numpy()
        if len(np.unique(groups)) < 2:
            self._log("fluxos:bootstrap", "NAO_ESTIMADO", "menos de 2 municípios")
        else:
            bs = cluster_bootstrap(X, Y, groups, reps=ec["bootstrap_reps"], seed=ec["bootstrap_seed"])
            self._write(pd.DataFrame([{"origem": o, "destino": d, "inf": bs["inf"][i, j],
                                       "sup": bs["sup"][i, j], "reps": bs["reps"],
                                       "grupos": bs["grupos"],
                                       "reps_nao_identificadas": bs["reps_nao_identificadas"],
                                       "rotulo": bs["rotulo"]}
                                      for i, o in enumerate(O) for j, d in enumerate(D)]),
                        "ecological_bootstrap.csv")
            self._log("fluxos:bootstrap", "PASS", "incerteza condicional ao modelo")
        self._log("fluxos:limites", "PASS")
        self._log("fluxos:matriz_pontual", "PASS" if dec["publicar_matriz_pontual"] else "NAO_ESTIMADO",
                  "; ".join(dec["motivos"]) or "publicável pela regra pré-registrada")

    # ------------------------------------------------------------------ B3
    def _t1_shares(self) -> pd.DataFrame:
        cand = self._t1_candidates().reindex(self.terr.id_unidade).fillna(0)
        g = self._grouped(cand, self.cfg["flows"]["limiar_candidato_separado"])
        t = self.terr.set_index("id_unidade")
        comp = g.copy()
        comp["BRANCO"] = t.qt_votos_brancos_t1
        comp["NULO"] = t.qt_votos_nulos_t1
        comp["ABSTENCAO"] = t.qt_abstencoes_t1
        return comp.div(t.qt_aptos_t1.astype(float), axis=0)

    def _profile_block(self):
        """(desenho do perfil por unidade ou None, motivo da ausência)."""
        if hasattr(self, "_profile_cache"):
            return self._profile_cache
        if self.profiles is None or self.crosswalk is None:
            self._profile_cache = (None, "staging profiles/section_crosswalk ausente")
            return self._profile_cache
        if self.terr.empty:  # perfil do T1 sem pares é tratado em t1_diagnostic
            self._profile_cache = (None, "sem unidades pareadas entre turnos")
            return self._profile_cache
        pc = self.cfg["profile"]
        shares, diag = unit_profile(self.profiles, self.crosswalk, self.membership, self.cfg)
        t = self.terr.set_index("id_unidade")
        cov = t[["sg_uf", "qt_aptos_t1"]].join(diag.set_index("id_unidade"), how="left")
        # Unidade pareada sem nenhuma origem no vínculo do perfil também é SEM_PERFIL.
        cov["motivo_exclusao"] = cov.motivo_exclusao.where(cov.n_origens.notna(), "SEM_PERFIL")
        cov["razao_cadastro_aptos_t1"] = cov.total_cadastro / cov.qt_aptos_t1.astype(float)
        diverge = (cov.razao_cadastro_aptos_t1 - 1).abs() > pc["divergencia_max_aptos"]
        cov.loc[cov.motivo_exclusao.isna() & diverge, "motivo_exclusao"] = "DIVERGENCIA_CADASTRO_APTOS"
        cov["motivo_exclusao"] = cov.motivo_exclusao.fillna("ELEGIVEL")
        summary = (cov.groupby(["sg_uf", "motivo_exclusao"]).agg(
            unidades=("qt_aptos_t1", "size"), aptos_t1=("qt_aptos_t1", "sum")).reset_index())
        summary["linhas_perfil_sem_unidade"] = diag.attrs["linhas_sem_unidade"]
        self._write(summary, "profile_coverage.csv")
        self._write(cov.reset_index()[["id_unidade", "sg_uf", "motivo_exclusao", "n_origens",
                                       "n_origens_com_perfil", "dimensoes_faltantes", "total_cadastro",
                                       "razao_cadastro_aptos_t1"]], "profile_unit_diagnostics.parquet")
        ok = cov.index[cov.motivo_exclusao == "ELEGIVEL"]
        kept = shares.loc[shares.index.intersection(ok)]
        self._write(kept.reset_index(), "profile_units.parquet")
        if kept.empty:
            self._log("perfil:integracao", "NAO_ESTIMADO", "nenhuma unidade com perfil completo; ver profile_coverage.csv")
            self._profile_cache = (None, "nenhuma unidade com perfil completo (ver profile_coverage.csv)")
            return self._profile_cache
        self._log("perfil:integracao", "PASS",
                  "perfil cadastral dos aptos (data de geração do arquivo), não dos votantes; só unidades com "
                  "todas as origens e dimensões e divergência cadastro/aptos ≤ "
                  f"{pc['divergencia_max_aptos']:.0%}; exclusões por motivo em profile_coverage.csv")
        self._profile_cache = (profile_design(kept, self.cfg), None)
        return self._profile_cache

    def _context_block(self):
        vars_ = self.cfg["context"]["variaveis"]
        if not vars_:
            return None, "nenhuma variável de contexto municipal definida (config [context])"
        if self.context is None:
            return None, "staging municipal_context ausente"
        feats, diag = municipal_features(self.context, self.cfg)
        self._write(diag.assign(anos_referencia=diag.anos_referencia.astype(str)), "context_coverage.csv")
        t = self.terr.set_index("id_unidade")[["sg_uf", "cd_municipio_tse"]]
        out = t.join(feats, on=["sg_uf", "cd_municipio_tse"]).drop(columns=["sg_uf", "cd_municipio_tse"])
        n_ok = int(out.notna().all(axis=1).sum())
        self._log("contexto:integracao", "PASS" if n_ok else "NAO_ESTIMADO",
                  f"{n_ok} de {len(out)} unidade(s) com todos os indicadores municipais; contexto do município, "
                  "não dos eleitores")
        return (out.add_prefix("contexto_"), None) if n_ok else (None, "nenhuma unidade com contexto completo")

    def _term_reference(self, termo: str, comp_cols) -> str:
        if termo in comp_cols:
            return self.cfg["associations"]["referencia"]
        for dim, ref in self.cfg["profile"]["referencias"].items():
            if termo.startswith(f"perfil_{dim.lower()}_"):
                return ref
        return ""

    def associations(self) -> None:
        if self.terr.empty:
            self._log("associacao", "NAO_ESTIMADO", "sem unidades pareadas territoriais")
            return
        ac, inf = self.cfg["associations"], self.cfg["inference"]
        t = self.terr.set_index("id_unidade")
        shares = self._t1_shares()
        ok = (t.qt_aptos_t1 > 0) & (t.qt_votos_validos_t1 > 0) & (t.qt_votos_validos_t2 > 0)
        comp = assoc.compositional_design(shares[ok].astype(float), ac["referencia"])
        prof, why_p = self._profile_block()
        ctx, why_c = self._context_block()
        blocks = {"composicao": comp, "perfil": prof, "contexto": ctx}
        why = {"perfil": why_p, "contexto": why_c}
        # Contexto municipal é colinear com EF de município: só entra na família com EF de UF.
        families = {
            "ef_municipio": ("municipio", [["composicao"], ["composicao", "perfil"]]),
            "ef_uf": ("uf", [["composicao"], ["composicao", "perfil"], ["composicao", "perfil", "contexto"]]),
        }
        muni = t.sg_uf + "-" + t.cd_municipio_tse
        fe_series = {"municipio": muni, "uf": t.sg_uf}
        weights = {"aptos_t1": t.qt_aptos_t1.astype(float), "validos_t1": t.qt_votos_validos_t1.astype(float),
                   "sem_pesos": pd.Series(1.0, index=t.index)}
        rows = []
        simple_rows = []
        for fam, (fe_name, specs) in families.items():
            usable = [sp for sp in specs if all(blocks[b] is not None for b in sp)]
            for sp in specs:
                if sp not in usable:
                    falta = next(b for b in sp if blocks[b] is None)
                    self._log(f"associacao:{fam}:{'+'.join(sp)}",
                              "BLOCKED" if "ausente" in why[falta] else "NAO_ESTIMADO", why[falta])
            if not usable:
                continue
            idx = comp.index
            for b in {x for sp in usable for x in sp}:
                idx = idx.intersection(blocks[b].dropna().index)
            recortes = {"territorial": pd.Series(True, index=idx)}
            if fam == "ef_municipio":
                n_mun = t.loc[idx].groupby("sg_uf").cd_municipio_tse.nunique()
                recortes.update({f"uf_{uf}": t.loc[idx, "sg_uf"] == uf
                                 for uf, n in n_mun.items() if n >= ac["min_municipios_uf"]})
            for sp in usable:
                X = pd.concat([blocks[b].loc[idx] for b in sp], axis=1)
                X = X.loc[:, X.std() > 0]
                spec = "+".join(sp)
                for desfecho in ac["desfechos"]:
                    y_all = self.unit_metrics.loc[idx, desfecho].astype(float).to_numpy()
                    for recorte, mask in recortes.items():
                        for wname, wser in weights.items():
                            if wname != "aptos_t1" and (recorte != "territorial" or fam != "ef_municipio"):
                                continue
                            sel = mask.to_numpy() & np.isfinite(y_all)
                            g = fe_series[fe_name].loc[idx].to_numpy()[sel]
                            gc = muni.loc[idx].to_numpy()[sel]
                            w = wser.loc[idx].to_numpy()[sel]
                            Xs, y = X.to_numpy(float)[sel], y_all[sel]
                            G, Gc = len(np.unique(g)), len(np.unique(gc))
                            bloco = f"associacao:{fam}:{spec}:{desfecho}:{recorte}:{wname}"
                            if Gc < 2 or sel.sum() <= Xs.shape[1] + G:
                                self._log(bloco, "NAO_ESTIMADO",
                                          f"grupos ({Gc}) ou graus de liberdade insuficientes")
                                continue
                            Xd = assoc.demean(Xs, w, g)
                            try:
                                f = assoc.clustered_fit(Xd, assoc.demean(y, w, g), w, gc,
                                                        absorbed=G, level=inf["nivel_confianca"])
                            except ValueError as e:
                                if "colinear" not in str(e):
                                    raise
                                # no recorte, um termo pode não variar dentro dos efeitos fixos
                                # (filtro de variância acima é do universo inteiro): não estima
                                sem_var = [c for c, v in zip(X.columns, np.average(Xd ** 2, axis=0, weights=w))
                                           if v < 1e-12]
                                self._log(bloco, "NAO_ESTIMADO",
                                          "desenho colinear no recorte; termos sem variação dentro dos "
                                          f"efeitos fixos: {', '.join(sem_var) or 'combinação linear'}")
                                continue
                            aviso = assoc.few_clusters_warning(Gc, inf["poucos_grupos"]) or ""
                            for j, termo in enumerate(X.columns):
                                rows.append({
                                    "familia": fam, "especificacao": spec, "desfecho": desfecho,
                                    "recorte": recorte, "pesos": wname, "termo": termo,
                                    "bloco_termo": ("composicao" if termo in comp.columns else
                                                    "perfil" if termo.startswith("perfil_") else "contexto"),
                                    "referencia": self._term_reference(termo, comp.columns),
                                    "beta": f["beta"][j], "ep": f["se"][j], "inf": f["inf"][j],
                                    "sup": f["sup"][j], "n": f["n"], "universo_familia": len(idx),
                                    "grupos_cluster": Gc, "efeitos_fixos": fe_name,
                                    "erros_agrupados": "municipio", "aviso": aviso})
                            self._log(bloco, "PASS", aviso)

                            # Associações bivariadas simples na especificação máxima de cada família (Pergunta C)
                            if sp == usable[-1] and wname == "aptos_t1":
                                yd = assoc.demean(y, w, g)
                                for j, termo in enumerate(X.columns):
                                    xj = assoc.demean(Xs[:, [j]], w, g)
                                    if np.std(xj) <= 1e-12:
                                        continue
                                    fs = assoc.clustered_fit(xj, yd, w, gc, absorbed=G,
                                                             level=inf["nivel_confianca"])
                                    bloco_t = ("composicao" if termo in comp.columns else
                                               "perfil" if termo.startswith("perfil_") else "contexto")
                                    unid_t = "proporcao" if bloco_t in ("composicao", "perfil") else "log_contexto"
                                    scale_10pp = 10.0 if unid_t == "proporcao" else np.nan
                                    simple_rows.append({
                                        "familia": fam, "especificacao": "simples_bivariada",
                                        "especificacao_ajustada": spec,
                                        "desfecho": desfecho, "recorte": recorte, "pesos": wname,
                                        "termo": termo,
                                        "bloco_termo": bloco_t,
                                        "unidade_termo": unid_t,
                                        "referencia": self._term_reference(termo, comp.columns),
                                        "beta_simples": fs["beta"][0], "ep_simples": fs["se"][0],
                                        "inf_simples": fs["inf"][0], "sup_simples": fs["sup"][0],
                                        "beta_ajustado": f["beta"][j], "ep_ajustado": f["se"][j],
                                        "inf_ajustado": f["inf"][j], "sup_ajustado": f["sup"][j],
                                        "pp_por_10pp_simples": float(fs["beta"][0]) * scale_10pp,
                                        "pp_por_10pp_inf_simples": float(fs["inf"][0]) * scale_10pp,
                                        "pp_por_10pp_sup_simples": float(fs["sup"][0]) * scale_10pp,
                                        "pp_por_10pp_ajustado": float(f["beta"][j]) * scale_10pp,
                                        "pp_por_10pp_inf_ajustado": float(f["inf"][j]) * scale_10pp,
                                        "pp_por_10pp_sup_ajustado": float(f["sup"][j]) * scale_10pp,
                                        "n": fs["n"], "grupos_cluster": Gc, "efeitos_fixos": fe_name,
                                    })
        out = pd.DataFrame(rows)
        if not out.empty:
            out["rotulo"] = ("associação condicional entre unidades; perfil = cadastro dos aptos e contexto = "
                             "município, não características de quem votou; não é efeito causal nem fluxo")
        self._write(out, "associations.csv")
        if simple_rows:
            self._write(pd.DataFrame(simple_rows), "associations_simple_vs_adjusted.csv")
        self._log("associacao:dependencia_espacial", "NAO_ESTIMADO",
                  "vizinhança municipal não faz parte do contrato v1.1")

    # ------------------------------------------------------------------ B5
    def closure_analysis(self) -> None:
        """Horários (B5) com bloqueio real da conclusão temporal não sustentada (O-R2/O-R3).

        Principal: só ENCERRAMENTO_URNA com fuso documentado. A inferência pela
        abertura é cenário exploratório, salvo se a premissa legal E a semântica
        do relógio estiverem confirmadas com fonte em config [closure_tz].
        """
        if self.closure is None:
            self._log("horarios", "BLOCKED", "staging closure ausente")
            return
        cc, cz = self.cfg["closure"], self.cfg["closure_tz"]
        dates = election_dates(self.cfg)
        promoted = bool(cz["premissa_horario_unico_confirmada"] and cz["fonte_premissa"]
                        and cz["semantica_relogio_validada"] and cz["fonte_validacao_relogio"])
        off = infer_municipal_offsets(self.closure, self.cfg)
        self._write(off, "closure_tz_offsets.csv")
        conv = apply_offsets(self.closure, off, self.cfg)
        main_variant = "exploratorio_inferido" if promoted else "documental"
        roles = {"documental": "principal" if not promoted else "sensibilidade",
                 "exploratorio_inferido": "principal" if promoted else "exploratorio",
                 "exploratorio_inferido_offset_zero": "exploratorio"}
        selected = {v: select_closure_variant(conv, v) for v in roles}
        classified, counts = {}, []
        for v, data in selected.items():
            classified[v] = classify(data, dates, self.cfg)
            counts.append(classified[v].groupby(["nr_turno", "faixa"]).size().rename("secoes")
                          .reset_index().assign(variante=v, papel=roles[v]))
        for m in cc["sensibilidade_tolerancias_min"]:
            c = classify(selected[main_variant], dates, self.cfg, tolerance_min=m)
            counts.append(c.groupby(["nr_turno", "faixa"]).size().rename("secoes").reset_index()
                          .assign(variante=f"{main_variant}_tolerancia_{m}min", papel="sensibilidade"))
        main = classified[main_variant]
        self._write(main.assign(ts_brasilia=main.ts_brasilia.astype(str)), "closure_sections.csv")
        self._write(pd.concat(counts, ignore_index=True), "closure_band_counts.csv")
        self._write(band_transitions(main).reset_index(), "closure_transitions.csv")
        audit = main[main.faixa.isin(cc["faixas_auditoria"])]
        self._write(audit.assign(ts_brasilia=audit.ts_brasilia.astype(str)), "closure_audit_before_limit.csv")
        self._write(main[main.faixa == cc["classe_invalida"]].groupby(["nr_turno", "motivo_invalido"])
                    .size().rename("secoes").reset_index(), "closure_invalid.csv")

        # Cobertura temporal por turno: base da decisão de bloqueio.
        enc = conv[conv.semantica == "ENCERRAMENTO_URNA"]
        key = ["nr_turno", "sg_uf", "cd_municipio_tse", "nr_zona", "nr_secao"]
        flags = enc[key].assign(_doc=enc.status_fuso.eq("DOCUMENTADO"),
                                _inf=enc.status_fuso.astype(str).str.startswith("INFERIDO"))
        agg = flags.groupby(key)[["_doc", "_inf"]].all()
        sec_status = pd.Series(np.where(agg._doc, "DOCUMENTADO",
                                        np.where(agg._inf, "INFERIDO", "DESCONHECIDO_OU_MISTO")),
                               index=agg.index, name="status_fuso")
        cov = sec_status.groupby(level="nr_turno").value_counts().unstack(fill_value=0)
        for c in ("DOCUMENTADO", "INFERIDO", "DESCONHECIDO_OU_MISTO"):
            if c not in cov:
                cov[c] = 0
        cov["secoes_com_faixa_principal"] = main[main.faixa != cc["classe_invalida"]].groupby("nr_turno").size()
        cov = cov.fillna(0).astype(int).reset_index()
        cov["variante_principal"] = main_variant
        self._write(cov, "closure_coverage.csv")

        premissa = "confirmada" if cz["premissa_horario_unico_confirmada"] else "NÃO confirmada"
        relogio = "validada" if cz["semantica_relogio_validada"] else "NÃO validada"
        self._log("horarios:inferencia_fuso", "PASS" if promoted else "EXPLORATORIO",
                  f"deslocamento inferido pela abertura (premissa legal {premissa}; semântica do relógio {relogio}); "
                  + ("promovido a principal por confirmação documental" if promoted else
                     "cenário exploratório, não usado na conclusão principal"))

        comp_bands = [b["nome"] for b in cc["faixas"] if b["nome"] not in cc["faixas_auditoria"]]
        ref = comp_bands[0]
        prof, _ = self._profile_block()
        deltas = ["delta_share_lula_validos", "delta_margem_lula_flavio_validos", "delta_comparecimento_aptos"]
        gov_ufs = set(self.votes[(self.votes.cd_cargo == 3) & (self.votes.nr_turno == 2)].sg_uf)
        cont = ["log_aptos_t1", "comparecimento_aptos_t1", "share_lula_validos_t1"]
        other = list(prof.columns) if prof is not None else []
        raw_rows, outputs = [], {"principal": [], "exploratorio": []}
        for v, role in roles.items():
            target = "exploratorio" if role == "exploratorio" else "principal"
            if role == "sensibilidade":
                target = "principal"
            ub = self._unit_bands(classified[v])
            d = self._band_frame(ub, deltas, prof) if not ub.empty else pd.DataFrame()
            if d.empty:
                continue
            for grp in ("faixa_t1", "faixa_t2", "transicao"):
                for b, s_ in d.dropna(subset=[grp]).groupby(grp):
                    for y in deltas:
                        okm = s_[y].notna() & (s_.peso > 0)
                        raw_rows.append({
                            "variante": v, "papel": role, "agrupamento": grp, "faixa": b, "desfecho": y,
                            "unidades": int(okm.sum()),
                            "media_ponderada_aptos": float(np.average(s_.loc[okm, y], weights=s_.peso[okm]))
                            if okm.any() else np.nan})
            recortes = {"territorial": d}
            if role == "principal" and gov_ufs:
                recortes["uf_com_governador_t2"] = d[d.sg_uf.isin(gov_ufs)]
                recortes["uf_sem_governador_t2"] = d[~d.sg_uf.isin(gov_ufs)]
            for rname, dd in recortes.items():
                for grp in ("faixa_t1", "faixa_t2"):
                    extra = other + (["faixa_t1_tardia"] if grp == "faixa_t2" else [])
                    for b in comp_bands[1:]:
                        for y in deltas:
                            r = pairwise_comparison(dd, grp, ref, b, y, cont, extra, self.cfg)
                            if role == "exploratorio":
                                r["rotulo"] = "EXPLORATÓRIO: fuso inferido pela abertura, não validado"
                            outputs[target].append({"variante": v, "papel": role, "recorte": rname, **r})
        self._write(pd.DataFrame(raw_rows), "closure_raw_deltas.csv")
        adj = pd.DataFrame(outputs["principal"])
        self._write(adj, "closure_adjusted.csv")
        self._write(pd.DataFrame(outputs["exploratorio"]), "closure_exploratorio_adjusted.csv")

        main_rows = adj[adj.papel == "principal"] if not adj.empty else adj
        n_main = int(cov.secoes_com_faixa_principal.sum())
        if n_main == 0 or main_rows.empty or not (main_rows.status == "PASS").any():
            self._log("horarios:conclusao_principal", "BLOCKED",
                      f"sem suporte com fuso {'documentado' if not promoted else 'validado'}: "
                      f"{n_main} seção(ões) com faixa principal; cobertura em closure_coverage.csv. "
                      "Comparação 17h × 19h não é produzida")
        else:
            n_pass = int((main_rows.status == "PASS").sum())
            self._log("horarios:conclusao_principal", "PASS",
                      f"{n_pass} de {len(main_rows)} comparação(ões) com suporte, sobre fuso "
                      f"{'documentado' if not promoted else 'validado'}; demais com motivo em closure_adjusted.csv")
        if outputs["exploratorio"]:
            self._log("horarios:exploratorio", "EXPLORATORIO",
                      f"{len(outputs['exploratorio'])} comparação(ões) em closure_exploratorio_adjusted.csv; "
                      "não sustentam conclusão")
        rs_cl, _ = receipt_consistency(self.closure)
        self._write(rs_cl, "closure_receipt_consistency.csv")
        proj_root = self.staging.parents[1] if self.staging.parent.name == "data" else self.staging.parent
        totals_dir = proj_root / "docs" / "sources" / "official_totals"
        av_path = totals_dir / "anexo_v_ocorrencias.csv"
        av_df = pd.read_csv(av_path, dtype=str) if av_path.exists() else None
        oc_summary, oc_reconciled = ocorrencias_urna_summary(
            self.closure, av_df, proj_root / "data" / "raw",
            totals_dir=totals_dir if av_df is not None else None,
        )
        self.inputs.update(oc_summary.attrs.get("insumos_sha256", {}))
        self._write(oc_summary, "closure_ocorrencias.csv")
        oc_status = oc_summary.attrs.get("status", "PASS" if oc_reconciled else "BLOCKED")
        oc_motivo = oc_summary.attrs.get("motivo", "")
        if av_df is not None and not oc_summary.empty and oc_reconciled and oc_status == "PASS":
            n_av = int(oc_summary["anexo_v_secoes"].sum())
            n_tr = int(oc_summary["anexo_v_troca_urna"].sum())
            self._log("horarios:ocorrencias", "PASS",
                      f"Anexo V do Relatório de Totalização integrado ({n_av} seção(ões), sendo {n_tr} "
                      "substituição(ões) de urna, 100% conciliadas com CEFT via manifesto); ver closure_ocorrencias.csv")
        elif av_df is None:
            self._log("horarios:ocorrencias", "NAO_ESTIMADO", "ocorrências de urna sem Anexo V na raiz de execução")
        else:
            self._log("horarios:ocorrencias", oc_status, oc_motivo or "conciliação Anexo V × CEFT não aprovada")
        self._log("horarios:governador_t2", "PASS" if gov_ufs else "NAO_ESTIMADO",
                  "disputa de governador no T2 é constante por UF (absorvida pelo EF de município); "
                  "examinada por recorte" if gov_ufs else "sem votos de governador no T2 no staging")
        self._log("horarios:faixas", "PASS", f"classificação na variante principal ({main_variant})")

    def _band_frame(self, ub: pd.DataFrame, deltas: list[str], prof) -> pd.DataFrame:
        wide = ub.pivot_table(index="id_unidade", columns="nr_turno", values="faixa_unidade",
                              aggfunc="first").rename(columns={1: "faixa_t1", 2: "faixa_t2"})
        for col in ("faixa_t1", "faixa_t2"):
            if col not in wide:
                wide[col] = np.nan
        d = self.terr.set_index("id_unidade").join(wide[["faixa_t1", "faixa_t2"]], how="inner")
        d = d.join(self.unit_metrics[deltas + ["comparecimento_aptos_t1", "share_lula_validos_t1"]])
        d["log_aptos_t1"] = np.log(d.qt_aptos_t1.astype(float).where(d.qt_aptos_t1 > 0))
        d["peso"] = d.qt_aptos_t1.astype(float)
        d["municipio"] = d.sg_uf + "-" + d.cd_municipio_tse
        d["faixa_t1_tardia"] = d.faixa_t1.isin(["18H_19H", "A_PARTIR_19H"]).astype(float)
        d["transicao"] = d.faixa_t1.astype(str) + "→" + d.faixa_t2.astype(str)
        if prof is not None:
            d = d.join(prof, how="left")
        return d

    def _unit_bands(self, classified: pd.DataFrame) -> pd.DataFrame:
        """Faixa por unidade e turno; seções da mesma unidade em faixas diferentes → MISTA."""
        if classified.empty:
            return pd.DataFrame(columns=["id_unidade", "nr_turno", "faixa_unidade"])
        c = classified.merge(self.membership, on=["nr_turno"] + GEO, how="inner")
        c = c[c.id_unidade.isin(self.terr.id_unidade)]
        g = c.groupby(["id_unidade", "nr_turno"]).faixa.agg(["first", "nunique"])
        g["faixa_unidade"] = np.where(g["nunique"] == 1, g["first"], "MISTA")
        return g[["faixa_unidade"]].reset_index()

    # ------------------------------------------------------------------ manifesto
    def manifest(self) -> None:
        cfg_bytes = (PROJECT_ROOT / "config" / "analysis.toml").read_bytes()
        commit, dirty, git_diag = git_state(PROJECT_ROOT)
        self._write(pd.DataFrame(self.status), "analysis_status.csv")
        man = {"contract_version": CONTRACT_VERSION, "config_sha256": hashlib.sha256(cfg_bytes).hexdigest(),
               "git_commit": commit, "codigo_com_alteracoes_nao_commitadas": dirty,
               "git_diagnostico": git_diag,
               "pares_entre_turnos": not self.terr.empty,
               "insumos_sha256": self.inputs, "fontes_brutas": getattr(self, "fontes_brutas", []),
               "saidas_linhas": self.outputs,
               "executado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (self.out / "analysis_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")


def git_state(root: Path) -> tuple[str | None, bool | None, str | None]:
    """(commit, alterações não commitadas, diagnóstico) do código que gerou as saídas.

    Revisão 23 (R23-5): uma consulta ao Git que falha não é evidência de árvore limpa. Qualquer
    falha (Git ausente, código de saída ≠ 0, erro na saída de erro) deixa `dirty = None`
    (desconhecido) e registra o motivo; o aceite que exige código commitado não passa nesse caso.
    """
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)

    try:
        head = _git("rev-parse", "HEAD")
    except OSError as e:
        return None, None, f"git indisponível: {e}"
    if head.returncode != 0:
        return None, None, f"git rev-parse falhou ({head.returncode}): {head.stderr.strip()[:200]}"
    commit = head.stdout.strip()
    try:
        st = _git("status", "--porcelain", "src", "config", "contracts")
    except OSError as e:
        return commit, None, f"git status indisponível: {e}"
    if st.returncode != 0:
        return commit, None, f"git status falhou ({st.returncode}): {st.stderr.strip()[:200]}"
    return commit, bool(st.stdout.strip()), None


def _json(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


# Grandes regiões do IBGE (siglas das UFs). O exterior (ZZ) fica fora.
REGIOES = {
    "NORTE": ("AC", "AM", "AP", "PA", "RO", "RR", "TO"),
    "NORDESTE": ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"),
    "CENTRO_OESTE": ("DF", "GO", "MS", "MT"),
    "SUDESTE": ("ES", "MG", "RJ", "SP"),
    "SUL": ("PR", "RS", "SC"),
}


def _pico_memoria_gb() -> float | None:
    """Pico de memória do processo em GB (mesma medição do normalize)."""
    from br2026.normalize import _pico_memoria_kb
    kb = _pico_memoria_kb()
    return round(kb / 1e6, 2) if kb else None


def run_analyze(staging: Path, analytics: Path, cfg: dict | None = None) -> dict:
    a = Analysis(staging, analytics, cfg)
    tempos: list[dict] = []

    def etapa(nome: str, f) -> object:
        t0 = time.perf_counter()
        r = f()
        tempos.append({"etapa": nome, "tempo_s": round(time.perf_counter() - t0, 1),
                       "pico_memoria_gb_acumulado": _pico_memoria_gb()})
        return r

    blocked = etapa("load", a.load)
    if blocked:
        return {"status": "BLOCKED", "motivo": blocked}
    etapa("t1_diagnostic", a.t1_diagnostic)
    if a.terr.empty:
        # Sem pares entre turnos: blocos que dependem de T1×T2 ficam BLOCKED com insumos exatos.
        motivo = "painel entre turnos sem unidades pareadas; faltam: " + "; ".join(a.missing_pairs)
        for bloco in ("descricao_entre_turnos", "contribuicoes_uf", "comparecimento_limites", "fluxos",
                      "associacao"):
            a._log(bloco, "BLOCKED", motivo)
    else:
        etapa("descriptive", a.descriptive)
        etapa("flows", a.flows)
        etapa("associations", a.associations)
    etapa("closure_analysis", a.closure_analysis)
    # custo medido de cada etapa (tempo e pico acumulado do processo), para o relatório técnico
    a._write(pd.DataFrame(tempos), "analysis_tempos.csv")
    a.manifest()
    st = pd.DataFrame(a.status)
    failed = st[st.status == "FAIL"]
    return {"status": "FAIL" if not failed.empty else "PASS", "blocos": st.status.value_counts().to_dict(),
            "saidas": len(a.outputs), "pares_entre_turnos": not a.terr.empty}
