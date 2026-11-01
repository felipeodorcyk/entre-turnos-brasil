import type { MapMetric, Municipio, SocioField } from "./types";
import { derived } from "./engine/query";

const intFmt = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

export const EMPTY = "—";

export const int = (value: number | null | undefined): string =>
  value === null || value === undefined ? EMPTY : intFmt.format(Math.round(value));

export const pct = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined ? EMPTY : `${(100 * value).toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;

export const pp = (value: number | null | undefined, digits = 2): string => {
  if (value === null || value === undefined) return EMPTY;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })} p.p.`;
};

export const signedInt = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return EMPTY;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${intFmt.format(Math.abs(value))}`;
};

export const money = (value: number | null | undefined): string =>
  value === null || value === undefined
    ? EMPTY
    : `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export const decimal = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined
    ? EMPTY
    : value.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const SOCIO_LABEL: Record<SocioField, string> = {
  renda_pc: "Renda domiciliar per capita média",
  baixa_renda: "Pessoas com até ½ salário mínimo",
  desocupacao: "Taxa de desocupação",
  vinculos: "Vínculos formais por mil habitantes",
  pbf: "Registros do PBF por 100 domicílios",
  urbana: "População urbana",
};

export const SOCIO_UNIT: Record<SocioField, string> = {
  renda_pc: "R$ de 2022",
  baixa_renda: "% em 2022",
  desocupacao: "% em 2022",
  vinculos: "por mil hab., 31/12/2025",
  pbf: "por 100 dom., 08/2026",
  urbana: "% em 2022",
};

export const SOCIO_SOURCE: Record<SocioField, string> = {
  renda_pc: "IBGE, Censo 2022, SIDRA 10295",
  baixa_renda: "IBGE, Censo 2022, SIDRA 10296",
  desocupacao: "IBGE, Censo 2022, SIDRA 6580",
  vinculos: "MTE, RAIS 31/12/2025",
  pbf: "MDS/PBF, folha 08/2026",
  urbana: "IBGE, Censo 2022, SIDRA 9923",
};

export const fmtSocio = (field: SocioField, value: number | null): string => {
  if (value === null) return EMPTY;
  if (field === "renda_pc") return money(value);
  return decimal(value, 2);
};

export const METRIC_LABEL: Record<MapMetric, string> = {
  delta_comparecimento_pp: "Mudança do comparecimento — 2º turno menos 1º turno",
  participacao_lula_t1: "Lula — 1º turno",
  participacao_flavio_t1: "Flávio Bolsonaro — 1º turno",
  comparecimento_t1: "Comparecimento — 1º turno",
  margem_t1: "Margem Lula − Flávio — 1º turno",
  delta_participacao_lula_pp: "Variação Lula — 2º turno menos 1º turno",
  delta_participacao_flavio_pp: "Variação Flávio — 2º turno menos 1º turno",

  participacao_lula_t2: "Lula — % dos válidos (2º turno)",
  participacao_flavio_t2: "Flávio — % dos válidos (2º turno)",
  comparecimento_t2: "Comparecimento — % dos aptos (2º turno)",
  margem_t2: "Margem Lula − Flávio — p.p. (2º turno)",
  delta_margem_pp: "Mudança da margem — p.p. (2º turno − 1º turno)",
  delta_margem_votos: "Mudança da margem — votos (2º turno − 1º turno)",
  renda_pc: "Renda domiciliar per capita — R$ (2022)",
  pbf: "Registros do PBF por 100 domicílios (08/2026)",
};

export function metricValue(row: Municipio, metric: MapMetric): number | null {
  const d = derived(row);
  switch (metric) {
    case "delta_comparecimento_pp": return d.comparecimento_t1 === null || d.comparecimento_t2 === null ? null : 100*(d.comparecimento_t2-d.comparecimento_t1);
    case "participacao_lula_t1": return d.participacao_lula_t1 === null ? null : 100 * d.participacao_lula_t1;
    case "participacao_flavio_t1": return d.participacao_flavio_t1 === null ? null : 100 * d.participacao_flavio_t1;
    case "comparecimento_t1": return d.comparecimento_t1 === null ? null : 100 * d.comparecimento_t1;
    case "margem_t1": return d.margem_t1_pp;
    case "delta_participacao_lula_pp": return d.participacao_lula_t1 === null || d.participacao_lula_t2 === null ? null : 100 * (d.participacao_lula_t2 - d.participacao_lula_t1);
    case "delta_participacao_flavio_pp": return d.participacao_flavio_t1 === null || d.participacao_flavio_t2 === null ? null : 100 * (d.participacao_flavio_t2 - d.participacao_flavio_t1);
    case "participacao_lula_t2":
      return d.participacao_lula_t2 === null ? null : 100 * d.participacao_lula_t2;
    case "participacao_flavio_t2":
      return d.participacao_flavio_t2 === null ? null : 100 * d.participacao_flavio_t2;
    case "comparecimento_t2":
      return d.comparecimento_t2 === null ? null : 100 * d.comparecimento_t2;
    case "margem_t2":
      return d.margem_t2_pp;
    case "delta_margem_pp":
      return d.delta_margem_pp;
    case "delta_margem_votos":
      return d.delta_margem_votos;
    case "renda_pc":
      return row.renda_pc;
    case "pbf":
      return row.pbf;
  }
}

export const METRIC_UNIT: Record<MapMetric, string> = {
  delta_comparecimento_pp: "p.p.",
  participacao_lula_t1: "% dos válidos",
  participacao_flavio_t1: "% dos válidos",
  comparecimento_t1: "% dos aptos",
  margem_t1: "p.p.",
  delta_participacao_lula_pp: "p.p.",
  delta_participacao_flavio_pp: "p.p.",

  participacao_lula_t2: "% dos válidos",
  participacao_flavio_t2: "% dos válidos",
  comparecimento_t2: "% dos aptos",
  margem_t2: "p.p.",
  delta_margem_pp: "p.p.",
  delta_margem_votos: "votos",
  renda_pc: "R$",
  pbf: "registros/100 dom.",
};

export const fmtMetric = (metric: MapMetric, value: number | null): string => {
  if (value === null) return EMPTY;
  if (metric === "delta_margem_votos") return signedInt(value);
  if (metric === "renda_pc") return money(value);
  if (metric === "pbf") return decimal(value, 2);
  if (metric === "delta_comparecimento_pp" || metric.startsWith("delta_participacao_") || metric === "margem_t1" || metric === "delta_margem_pp" || metric === "margem_t2") return pp(value);
  return pct(value / 100);
};
