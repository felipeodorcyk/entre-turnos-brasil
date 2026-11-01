"""Figuras do relatório nacional T1×T2 (handoff 26).

Com 27 UFs, as barras agrupadas do piloto ficam ilegíveis; aqui as UFs vão em barras horizontais
ordenadas, os municípios em listas nacionais e as regiões em composições lado a lado. Todas as
figuras saem das tabelas de `tabelas_nacional/`, as mesmas que o texto cita.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CAMADA_ROTULO = {"REGIAO_NORTE": "Norte", "REGIAO_NORDESTE": "Nordeste", "REGIAO_CENTRO_OESTE": "Centro-Oeste",
                 "REGIAO_SUDESTE": "Sudeste", "REGIAO_SUL": "Sul", "TERRITORIO": "Território",
                 "EXTERIOR": "Exterior", "BRASIL": "Brasil"}


def _fmt(v: float, casas: int = 2) -> str:
    return f"{v:+.{casas}f}".replace(".", ",")


def generate_national_figures(tables: dict[str, pd.DataFrame], fig_dir: Path, palette: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "axes.edgecolor": "#cbd5e1", "axes.linewidth": 0.8, "axes.grid": True,
        "grid.color": palette["grid"], "grid.linestyle": "--", "grid.linewidth": 0.6, "grid.alpha": 0.7,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "savefig.dpi": 200,
    })
    fig_dir.mkdir(parents=True, exist_ok=True)
    for old in fig_dir.glob("*.png"):
        old.unlink()
    feitas: list[str] = []
    navy = palette["navy"]

    # Figura 1: variação da margem e da abstenção por UF, ordenadas pela margem
    t1 = tables["tab01_resumo_uf_t1_t2.csv"]
    uf = t1[t1.sg_uf.astype(str) != "TOTAL"].copy()
    tot = t1[t1.sg_uf.astype(str) == "TOTAL"].iloc[0]
    uf = uf.sort_values("delta_margem_lula_flavio_validos")
    y = np.arange(len(uf))
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 8.4), sharey=True, constrained_layout=True)
    dm = 100 * uf.delta_margem_lula_flavio_validos.to_numpy(float)
    axes[0].barh(y, dm, color=[palette["lula"] if v > 0 else palette["flavio"] for v in dm], height=0.7)
    axes[0].axvline(100 * float(tot.delta_margem_lula_flavio_validos), color=navy, linestyle="--", linewidth=1,
                    label=f"Território: {_fmt(100 * float(tot.delta_margem_lula_flavio_validos))} p.p.")
    axes[0].axvline(0, color="#334155", linewidth=0.8)
    for yi, v in zip(y, dm):
        axes[0].annotate(_fmt(v), (v, yi), xytext=(3 if v >= 0 else -3, 0), textcoords="offset points",
                         ha="left" if v >= 0 else "right", va="center", fontsize=7.2)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(uf.sg_uf.astype(str), fontsize=8.5, fontweight="bold")
    axes[0].set_xlabel("Variação da margem Lula − Flávio nos válidos (p.p.)")
    axes[0].set_title("A. Margem: 2º turno − 1º turno", fontsize=10.5, fontweight="bold", color=navy)
    axes[0].legend(fontsize=8, loc="lower right")
    da = 100 * uf.delta_abstencao_aptos.to_numpy(float)
    axes[1].barh(y, da, color=palette["abstencao"], height=0.7)
    axes[1].axvline(100 * float(tot.delta_abstencao_aptos), color=navy, linestyle="--", linewidth=1,
                    label=f"Território: {_fmt(100 * float(tot.delta_abstencao_aptos))} p.p.")
    axes[1].axvline(0, color="#334155", linewidth=0.8)
    for yi, v in zip(y, da):
        axes[1].annotate(_fmt(v), (v, yi), xytext=(3 if v >= 0 else -3, 0), textcoords="offset points",
                         ha="left" if v >= 0 else "right", va="center", fontsize=7.2)
    axes[1].set_xlabel("Variação da abstenção sobre os aptos (p.p.)")
    axes[1].set_title("B. Abstenção: 2º turno − 1º turno", fontsize=10.5, fontweight="bold", color=navy)
    axes[1].legend(fontsize=8, loc="lower right")
    fig.suptitle("Figura 1 — Variação entre turnos por UF (ordenadas pela variação da margem)",
                 fontsize=12, fontweight="bold", color=navy)
    nome = "fig01_variacao_uf.png"
    fig.savefig(fig_dir / nome)
    plt.close(fig)
    feitas.append(nome)

    # Figura 2: municípios com maior variação de votos no país
    t10 = tables.get("tab10_top_municipios_brasil.csv")
    if t10 is not None and not t10.empty:
        fig, axes = plt.subplots(1, 2, figsize=(11.8, 6.0), constrained_layout=True)
        for ax, (cand, cor) in zip(axes, (("Lula (13)", palette["lula"]), ("Flávio Bolsonaro (22)", palette["flavio"]))):
            sub = t10[t10.candidato == cand].sort_values("contribuicao_delta_votos")
            from br2026.reporting.national_editorial import _titulo
            nomes = [f"{_titulo(n)} ({u})" if isinstance(n, str) else f"{c} ({u})"
                     for n, c, u in zip(sub.get("nm_municipio", sub.cd_municipio_tse), sub.cd_municipio_tse, sub.sg_uf)]
            v = sub.contribuicao_delta_votos.to_numpy(float) / 1000
            yy = np.arange(len(sub))
            ax.barh(yy, v, color=cor, height=0.65)
            ax.axvline(0, color="#334155", linewidth=0.8)
            ax.set_yticks(yy)
            ax.set_yticklabels(nomes, fontsize=8)
            ax.set_xlabel("Votos a mais no 2º turno (milhares)")
            ax.set_title(cand, fontsize=10.5, fontweight="bold", color=navy)
        fig.suptitle("Figura 2 — Municípios com maior variação de votos entre os turnos",
                     fontsize=12, fontweight="bold", color=navy)
        nome = "fig02_municipios_brasil.png"
        fig.savefig(fig_dir / nome)
        plt.close(fig)
        feitas.append(nome)

    # Figura 3: composição do eleitorado apto por camada, nos dois turnos
    cam = tables.get("tab09_camadas_regioes_exterior.csv")
    if cam is not None and not cam.empty:
        ordem = [c for c in CAMADA_ROTULO if c in set(cam.camada) and c != "TERRITORIO"]
        cam = cam.set_index("camada").loc[ordem]
        fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.8), sharey=True, constrained_layout=True)
        for ax, s in zip(axes, ("t1", "t2")):
            ap = cam[f"qt_aptos_{s}"].to_numpy(float)
            partes = [("Lula", cam[f"qt_lula_{s}"], palette["lula"]),
                      ("Flávio", cam[f"qt_flavio_{s}"], palette["flavio"])]
            if s == "t1":
                partes.append(("Demais candidatos", cam["qt_votos_validos_t1"] - cam["qt_lula_t1"] - cam["qt_flavio_t1"],
                               palette["terceiros"]))
            partes += [("Brancos e nulos", cam[f"qt_votos_brancos_{s}"] + cam[f"qt_votos_nulos_{s}"], palette["nao_validos"]),
                       ("Abstenção", cam[f"qt_abstencoes_{s}"], palette["abstencao"])]
            esq = np.zeros(len(cam))
            yy = np.arange(len(cam))
            for rot, val, cor in partes:
                w = 100 * val.to_numpy(float) / ap
                ax.barh(yy, w, left=esq, color=cor, height=0.62, label=rot)
                esq += w
            ax.set_yticks(yy)
            ax.set_yticklabels([CAMADA_ROTULO[c] for c in cam.index], fontsize=9, fontweight="bold")
            ax.set_xlim(0, 100)
            ax.set_xlabel("% dos eleitores aptos")
            ax.set_title(f"{s[1]}º turno", fontsize=10.5, fontweight="bold", color=navy)
        axes[0].invert_yaxis()   # eixo y compartilhado: inverter uma vez só
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=8.5, bbox_to_anchor=(0.5, -0.06))
        fig.suptitle("Figura 3 — Composição do eleitorado apto por região, exterior e Brasil",
                     fontsize=12, fontweight="bold", color=navy)
        nome = "fig03_composicao_camadas.png"
        fig.savefig(fig_dir / nome, bbox_inches="tight")
        plt.close(fig)
        feitas.append(nome)

    # Figura 4: municípios — votos dos eliminados no 1º turno × variação de Lula
    t11 = tables.get("tab11_municipios_bases_iniciais.csv")
    if t11 is not None and not t11.empty:
        d = t11.dropna(subset=["share_demais_validos_t1", "delta_share_lula_validos"])
        fig, ax = plt.subplots(figsize=(9.6, 6.0), constrained_layout=True)
        tam = 4 + 120 * np.sqrt(d.qt_votos_validos_t1.to_numpy(float) / d.qt_votos_validos_t1.max())
        ax.scatter(100 * d.share_demais_validos_t1, 100 * d.delta_share_lula_validos, s=tam,
                   alpha=0.35, color=palette["lula"], edgecolors="none")
        ax.axhline(0, color="#334155", linewidth=0.8)
        ax.set_xlabel("Votos dos candidatos eliminados no 1º turno (% dos válidos)")
        ax.set_ylabel("Variação da participação de Lula nos válidos (p.p.)")
        ax.set_title("Figura 4 — Municípios: votos dos eliminados no 1º turno e avanço de Lula\n"
                     "(área proporcional aos válidos; associação entre municípios, não trajetória de eleitores)",
                     fontsize=10.5, fontweight="bold", color=navy)
        nome = "fig04_bases_iniciais_municipios.png"
        fig.savefig(fig_dir / nome)
        plt.close(fig)
        feitas.append(nome)

    # Figura 5: associações simples e ajustadas (efeito fixo de município, todas as unidades)
    t5 = tables["tab05_associacoes_perfil_t1_t2.csv"]
    a = t5[(t5.unidade_termo == "proporcao") & (t5.desfecho == "delta_share_lula_validos")
           & (t5.recorte == "territorial") & (t5.familia == "ef_municipio")]
    a = a.dropna(subset=["pp_por_10pp_simples", "pp_por_10pp_ajustado"]).drop_duplicates("termo").head(14)
    if not a.empty:
        fig, ax = plt.subplots(figsize=(10.4, max(4.4, 0.5 * len(a) + 1.6)), constrained_layout=True)
        yy = np.arange(len(a))
        for col, off, cor, mk, rot in (("simples", -0.14, palette["simples"], "o", "Simples (com efeito fixo)"),
                                       ("ajustado", 0.14, palette["ajustado"], "s", "Ajustada (multivariada)")):
            b = a[f"pp_por_10pp_{col}"].to_numpy(float)
            lo = np.clip(b - a[f"pp_por_10pp_inf_{col}"].to_numpy(float), 0, None)
            hi = np.clip(a[f"pp_por_10pp_sup_{col}"].to_numpy(float) - b, 0, None)
            ax.errorbar(b, yy + off, xerr=[lo, hi], fmt=mk, color=cor, capsize=3, markersize=5, label=rot)
        ax.axvline(0, color="#334155", linewidth=0.9, linestyle="--")
        ax.set_yticks(yy)
        ax.set_yticklabels(a.termo.astype(str), fontsize=8.5)
        ax.set_xlabel("Δ participação de Lula (p.p.) associada a +10 p.p. na categoria, IC 95%")
        ax.set_title("Figura 5 — Associações entre unidades: composição do 1º turno e perfil dos aptos",
                     fontsize=10.5, fontweight="bold", color=navy)
        ax.legend(fontsize=8.5)
        nome = "fig05_associacoes.png"
        fig.savefig(fig_dir / nome)
        plt.close(fig)
        feitas.append(nome)

    # Figura 6: faixas de encerramento do 2º turno — médias brutas e diferenças ajustadas (EF município)
    t12, t13 = tables.get("tab12_horarios_faixas.csv"), tables.get("tab13_horarios_ajustado.csv")
    if t12 is not None and t13 is not None and not t12.empty and "media_delta_margem_lula_flavio_validos" in t12:
        rot = {"17H00_17H15": "17h00–17h15", "17H15_18H": "17h15–18h", "18H_19H": "18h–19h",
               "A_PARTIR_19H": "19h ou depois"}
        b = t12.set_index("faixa").reindex(list(rot)).dropna(subset=["unidades_t2"])
        fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.6), constrained_layout=True)
        x = np.arange(len(b))
        for col, off, cor, nm in (("media_delta_margem_lula_flavio_validos", -0.19, palette["lula"], "Margem Lula − Flávio"),
                                  ("media_delta_comparecimento_aptos", 0.19, "#475569", "Comparecimento")):
            v = 100 * b[col].to_numpy(float)
            axes[0].bar(x + off, v, width=0.36, color=cor, label=nm)
            for xi, vi in zip(x + off, v):
                axes[0].annotate(_fmt(vi), (xi, vi), xytext=(0, 3 if vi >= 0 else -10), textcoords="offset points",
                                 ha="center", fontsize=7.4)
        axes[0].axhline(0, color="#334155", linewidth=0.8)
        axes[0].set_xticks(x)
        axes[0].set_xticklabels([f"{rot[f]}\n{int(n):,} unid.".replace(",", ".") for f, n in b.unidades_t2.items()],
                                fontsize=8.2)
        axes[0].set_ylabel("Variação 2º − 1º turno (p.p.), média por aptos")
        axes[0].set_title("A. Médias brutas por faixa de encerramento no 2º turno", fontsize=10, fontweight="bold",
                          color=navy)
        axes[0].legend(fontsize=8)
        a = t13[(t13.recorte == "territorial")]
        fx = [f for f in rot if f != "17H00_17H15"]
        for k, (y, cor, mk, nm) in enumerate((("delta_margem_lula_flavio_validos", palette["lula"], "o", "Margem Lula − Flávio"),
                                              ("delta_comparecimento_aptos", "#475569", "s", "Comparecimento"))):
            for i, f in enumerate(fx):
                r = a[(a.faixa == f) & (a.desfecho == y)]
                if r.empty or r.status.iloc[0] != "PASS":
                    axes[1].annotate("sem suporte", (i + (k - 0.5) * 0.3, 0), fontsize=7, ha="center", color="#64748b")
                    continue
                bt, lo, hi = (100 * float(r[c].iloc[0]) for c in ("beta_ajustado", "inf", "sup"))
                axes[1].errorbar(i + (k - 0.5) * 0.3, bt, yerr=[[bt - lo], [hi - bt]], fmt=mk, color=cor, capsize=3,
                                 markersize=5, label=nm if i == 0 else None)
        axes[1].axhline(0, color="#334155", linewidth=0.9, linestyle="--")
        axes[1].set_xticks(np.arange(len(fx)))
        axes[1].set_xticklabels([rot[f] for f in fx], fontsize=8.5)
        axes[1].set_ylabel("Diferença para 17h00–17h15 (p.p.), IC 95%")
        axes[1].set_title("B. Ajustada: mesmo município, perfil e 1º turno", fontsize=10, fontweight="bold", color=navy)
        axes[1].legend(fontsize=8)
        fig.suptitle("Figura 6 — Seções por horário de encerramento no 2º turno (associação, não efeito do horário)",
                     fontsize=11.5, fontweight="bold", color=navy)
        nome = "fig06_horarios_encerramento.png"
        fig.savefig(fig_dir / nome)
        plt.close(fig)
        feitas.append(nome)

    # Figuras 7 e 8: contexto socioeconômico (handoff 37)
    rot_ind = {"renda_pc": "Renda domiciliar per capita", "baixa_renda": "Pessoas com até ½ SM (%)",
               "desocupacao": "Desocupação (%)", "vinculos": "Vínculos formais por mil hab.",
               "pbf": "Registros PBF por 100 dom.", "urbana": "População urbana (%)"}
    t15 = tables.get("tab15_socio_faixas.csv")
    if t15 is not None and not t15.empty:
        fig, axes = plt.subplots(2, 3, figsize=(12.4, 7.2), constrained_layout=True, sharey=True)
        for ax, (ind, rot) in zip(axes.ravel(), rot_ind.items()):
            s = t15[t15.indicador == ind].sort_values("faixa")
            x = s.faixa.astype(int).to_numpy()
            ax.bar(x - 0.19, 100 * s.delta_share_lula.to_numpy(float), width=0.36, color=palette["lula"],
                   label="Δ participação de Lula")
            ax.bar(x + 0.19, 100 * s.delta_comparecimento.to_numpy(float), width=0.36, color="#475569",
                   label="Δ comparecimento")
            ax.axhline(0, color="#334155", linewidth=0.8)
            ax.set_xticks(x)
            ax.set_xticklabels([f"Q{k}" for k in x], fontsize=8.5)
            ax.set_title(rot, fontsize=9.5, fontweight="bold", color=navy)
        axes[0, 0].set_ylabel("2º − 1º turno (p.p.)")
        axes[1, 0].set_ylabel("2º − 1º turno (p.p.)")
        axes[0, 0].set_ylim(top=max(axes[0, 0].get_ylim()[1], 9.5))      # espaço para a legenda acima das barras
        axes[0, 0].legend(fontsize=7.5, loc="upper left", ncol=2)
        fig.suptitle("Figura 7 — Variação por quintil de municípios (Q1 = menor valor do indicador; razão de somas)",
                     fontsize=11.5, fontweight="bold", color=navy)
        nome = "fig07_socio_faixas.png"
        fig.savefig(fig_dir / nome)
        plt.close(fig)
        feitas.append(nome)
    t17 = tables.get("tab17_socio_modelos_municipais.csv")
    if t17 is not None and not t17.empty:
        p = t17[t17.papel == "principal"]
        fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.9), constrained_layout=True, sharey=True)
        inds = list(rot_ind)
        yy = np.arange(len(inds))[::-1]
        for ax, (y, tit) in zip(axes, (("delta_share_lula_validos", "A. Δ participação de Lula nos válidos"),
                                       ("delta_comparecimento_aptos", "B. Δ comparecimento sobre os aptos"))):
            for off, esp, mk, cor in ((0.15, "bruto", "o", "#94a3b8"), (-0.15, "ajustado", "s", navy)):
                r = p[(p.desfecho == y) & (p.especificacao == esp)].set_index("indicador").reindex(inds)
                b = r.efeito_pp.to_numpy(float)
                ax.errorbar(b, yy + off, xerr=[b - r.inf_pp.to_numpy(float), r.sup_pp.to_numpy(float) - b],
                            fmt=mk, color=cor, capsize=3, markersize=5,
                            label={"bruto": "Bruto (só EF de UF)", "ajustado": "Ajustado"}[esp])
            ax.axvline(0, color="#334155", linewidth=0.9, linestyle="--")
            ax.set_title(tit, fontsize=10, fontweight="bold", color=navy)
            ax.set_xlabel("p.p. por incremento do indicador (IC 95%)")
        axes[0].set_yticks(yy)
        esc = {"renda_pc": "por duplicação", "baixa_renda": "por +10 p.p.", "desocupacao": "por +5 p.p.",
               "vinculos": "por +100/mil", "pbf": "por +10/100 dom.", "urbana": "por +10 p.p."}
        axes[0].set_yticklabels([rot_ind[i] + "\n(" + esc[i] + ")" for i in inds], fontsize=8.2)
        axes[0].legend(fontsize=8)
        fig.suptitle("Figura 8 — Associação entre municípios, um indicador por vez (mesma amostra; não é efeito causal)",
                     fontsize=11.5, fontweight="bold", color=navy)
        nome = "fig08_socio_modelos.png"
        fig.savefig(fig_dir / nome)
        plt.close(fig)
        feitas.append(nome)
    return feitas
