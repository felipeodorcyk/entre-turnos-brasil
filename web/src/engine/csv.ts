import type { Aggregate, CountField, Municipio, SocioField, ViewState } from "../types";
import { COUNT_FIELDS, SOCIO_FIELDS } from "../types";
import { activeSocioFields, derived } from "./query";

const TEXT_NEUTRALIZE = /^[=+\-@\t\r]/;

export const csvText = (value: string): string => {
  const safe = TEXT_NEUTRALIZE.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
};

const csvNumber = (value: number | null): string => (value === null ? "" : String(value));

const rate = (value: number | null): string => (value === null ? "" : value.toFixed(6));

export const CSV_DELIMITER = ";";

export function buildCsv(rows: Municipio[]): string {
  const header = [
    "cd_ibge",
    "cd_tse",
    "nome",
    "sg_uf",
    "regiao",
    "n_unidades",
    ...COUNT_FIELDS,
    "participacao_lula_t1",
    "participacao_lula_t2",
    "participacao_flavio_t1",
    "participacao_flavio_t2",
    "comparecimento_t1",
    "comparecimento_t2",
    "margem_t2_pp",
    "delta_margem_pp",
    "delta_margem_votos",
    "delta_comparecimento_pp",
    ...SOCIO_FIELDS,
    "tem_geometria",
    "tem_contexto",
  ];
  const lines = [header.join(CSV_DELIMITER)];
  for (const row of rows) {
    const d = derived(row);
    const cells: string[] = [
      csvText(row.cd_ibge),
      csvText(row.cd_tse),
      csvText(row.nome),
      csvText(row.sg_uf),
      csvText(row.regiao),
      String(row.n_unidades),
      ...COUNT_FIELDS.map((f) => String(row[f])),
      rate(d.participacao_lula_t1),
      rate(d.participacao_lula_t2),
      rate(d.participacao_flavio_t1),
      rate(d.participacao_flavio_t2),
      rate(d.comparecimento_t1),
      rate(d.comparecimento_t2),
      rate(d.margem_t2_pp),
      rate(d.delta_margem_pp),
      String(d.delta_margem_votos),
      rate(d.comparecimento_t1 === null || d.comparecimento_t2 === null ? null : 100 * (d.comparecimento_t2 - d.comparecimento_t1)),
      ...SOCIO_FIELDS.map((f) => csvNumber(row[f])),
      String(row.tem_geometria),
      String(row.tem_contexto),
    ];
    lines.push(cells.join(CSV_DELIMITER));
  }
  return lines.join("\r\n") + "\r\n";
}

export const FORMULAS: Record<string, string> = {
  participacao_lula_t1: "qt_lula_t1 / qt_votos_validos_t1",
  participacao_lula_t2: "qt_lula_t2 / qt_votos_validos_t2",
  participacao_flavio_t1: "qt_flavio_t1 / qt_votos_validos_t1",
  participacao_flavio_t2: "qt_flavio_t2 / qt_votos_validos_t2",
  comparecimento_t1: "qt_comparecimento_t1 / qt_aptos_t1",
  comparecimento_t2: "qt_comparecimento_t2 / qt_aptos_t2",
  margem_t2_pp: "100 * (participacao_lula_t2 - participacao_flavio_t2)",
  delta_margem_pp:
    "100 * ((qt_lula_t2 - qt_flavio_t2)/qt_votos_validos_t2 - (qt_lula_t1 - qt_flavio_t1)/qt_votos_validos_t1)",
  delta_margem_votos: "(qt_lula_t2 - qt_flavio_t2) - (qt_lula_t1 - qt_flavio_t1)",
  delta_comparecimento_pp: "100 * (comparecimento_t2 - comparecimento_t1)",
};

export function buildMetadata(
  state: ViewState,
  agg: Aggregate,
  releaseId: string,
  schemaVersion: string,
  warnings: string[],
  missing?: unknown,
): Record<string, unknown> {
  const active = activeSocioFields(state.filters);
  return {
    release_id: releaseId,
    schema_version: schemaVersion,
    generated_at_utc: new Date().toISOString(),
    escopo: {
      universo: "pareado_territorial",
      unidade: "município do território brasileiro",
      inclui_exterior: false,
      observacao:
        "O recorte baixado é territorial. O card nacional oficial inclui o exterior e é apenas referência; não entra neste CSV.",
    },
    filtros: {
      regioes: state.filters.regioes,
      ufs: state.filters.ufs,
      municipios: state.filters.municipios,
      socio: Object.fromEntries(active.map((f) => [f, state.filters.socio[f]])),
      categoria_sem_informacao: active.filter((f) => state.filters.socio[f]?.missing),
    },
    totais: {
      municipios: agg.municipios,
      unidades_eleitorais: agg.n_unidades,
      ...agg.counts,
      participacao_lula_t2: agg.participacao_lula_t2,
      participacao_flavio_t2: agg.participacao_flavio_t2,
      comparecimento_t2: agg.comparecimento_t2,
      delta_margem_pp: agg.delta_margem_pp,
      delta_margem_votos: agg.delta_margem_votos,
    },
    cobertura: agg.cobertura,
    ausencias_antes_filtros: missing,
    formulas: FORMULAS,
    fontes: {
      eleitoral: "TSE — votação por seção 2026; painel pareado do projeto presidenciais_2026_br",
      socio: "IBGE Censo 2022; MTE RAIS 2025; MDS/PBF 08/2026",
      nomes: "IBGE — API de localidades, municípios 2022",
      malha: "IBGE — API de malhas, município 2022, qualidade intermediária",
    },
    politica_nulos: "ausente é null; não satisfaz intervalo; nunca imputado como zero",
    avisos: warnings,
  };
}

export function download(filename: string, content: string, mime: string): void {
  const body = mime.startsWith("text/csv") ? `\ufeff${content}` : content;
  const blob = new Blob([body], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export const PRESENT_LABEL: Record<SocioField, string> = {
  renda_pc: "Renda per capita",
  baixa_renda: "Até ½ salário mínimo",
  desocupacao: "Desocupação",
  vinculos: "Vínculos por mil hab.",
  pbf: "PBF por 100 domicílios",
  urbana: "População urbana",
};

export const PRESENT_UNIT: Record<SocioField, string> = {
  renda_pc: "R$/mês (2022)",
  baixa_renda: "% (2022)",
  desocupacao: "% (2022)",
  vinculos: "vínculos/1.000 hab. (2025)",
  pbf: "registros/100 dom. (08/2026)",
  urbana: "% (2022)",
};

export type CsvColumn = keyof Municipio | "participacao_lula_t2" | "delta_margem_pp";
export type { CountField };
