import {
  COUNT_FIELDS,
  SOCIO_FIELDS,
  type Aggregate,
  type CountField,
  type Filters,
  type Municipio,
  type RangeFilter,
  type SocioField,
  type SortField,
  type SortOrder,
} from "../types";

export const ratio = (num: number, den: number): number | null => (den > 0 ? num / den : null);

const deltaPp = (a: number | null, b: number | null): number | null =>
  a === null || b === null ? null : 100 * (a - b);

export const isSocioRuleActive = (rule: RangeFilter | undefined): rule is RangeFilter =>
  Boolean(rule) && Boolean(rule && (rule.missing || rule.min !== null || rule.max !== null));

export const activeSocioFields = (filters: Filters): SocioField[] =>
  SOCIO_FIELDS.filter((field) => isSocioRuleActive(filters.socio[field]));

const matchesRule = (value: number | null, rule: RangeFilter): boolean => {
  if (value === null) return rule.missing;
  const hasRange = rule.min !== null || rule.max !== null;
  if (!hasRange) return false;
  const lo = rule.min ?? Number.NEGATIVE_INFINITY;
  const hi = rule.max ?? Number.POSITIVE_INFINITY;
  return value >= lo && value <= hi;
};

/**
 * OU dentro de cada dimensão, E entre dimensões. Região/UF/município são
 * aplicados em conjunto; o estado da UI mantém a hierarquia compatível.
 * Variável sem filtro não exclui nulos; filtro de intervalo exclui nulos,
 * exceto quando a categoria "sem informação" está marcada.
 */
export function filterMunicipios(rows: Municipio[], filters: Filters): Municipio[] {
  const regioes = new Set(filters.regioes);
  const ufs = new Set(filters.ufs);
  const municipios = new Set(filters.municipios);
  const socio = activeSocioFields(filters).map((field) => [field, filters.socio[field]!] as const);
  return rows.filter((row) => {
    if (regioes.size > 0 && !regioes.has(row.regiao)) return false;
    if (ufs.size > 0 && !ufs.has(row.sg_uf)) return false;
    if (municipios.size > 0 && !municipios.has(row.cd_ibge)) return false;
    for (const [field, rule] of socio) {
      if (!matchesRule(row[field], rule)) return false;
    }
    return true;
  });
}

const zeroCounts = (): Record<CountField, number> =>
  Object.fromEntries(COUNT_FIELDS.map((field) => [field, 0])) as Record<CountField, number>;

export function aggregate(rows: Municipio[]): Aggregate {
  const counts = zeroCounts();
  let nUnidades = 0;
  let comGeometria = 0;
  let comContexto = 0;
  const porIndicador = Object.fromEntries(
    SOCIO_FIELDS.map((field) => [field, { com_valor: 0, sem_valor: 0 }]),
  ) as Aggregate["cobertura"]["por_indicador"];

  for (const row of rows) {
    for (const field of COUNT_FIELDS) counts[field] += row[field];
    nUnidades += row.n_unidades;
    comGeometria += row.tem_geometria;
    comContexto += row.tem_contexto;
    for (const field of SOCIO_FIELDS) {
      if (row[field] === null) porIndicador[field].sem_valor += 1;
      else porIndicador[field].com_valor += 1;
    }
  }

  const lulaT1 = counts.qt_lula_t1;
  const lulaT2 = counts.qt_lula_t2;
  const flavioT1 = counts.qt_flavio_t1;
  const flavioT2 = counts.qt_flavio_t2;
  const validosT1 = counts.qt_votos_validos_t1;
  const validosT2 = counts.qt_votos_validos_t2;
  const aptosT1 = counts.qt_aptos_t1;
  const aptosT2 = counts.qt_aptos_t2;
  const comparecimentoT1 = counts.qt_comparecimento_t1;
  const comparecimentoT2 = counts.qt_comparecimento_t2;

  const participacaoLulaT1 = ratio(lulaT1, validosT1);
  const participacaoLulaT2 = ratio(lulaT2, validosT2);
  const participacaoFlavioT1 = ratio(flavioT1, validosT1);
  const participacaoFlavioT2 = ratio(flavioT2, validosT2);
  const comparecimentoT1Pct = ratio(comparecimentoT1, aptosT1);
  const comparecimentoT2Pct = ratio(comparecimentoT2, aptosT2);
  const margemT1 = participacaoLulaT1 === null || participacaoFlavioT1 === null ? null : participacaoLulaT1 - participacaoFlavioT1;
  const margemT2 = participacaoLulaT2 === null || participacaoFlavioT2 === null ? null : participacaoLulaT2 - participacaoFlavioT2;

  return {
    municipios: rows.length,
    n_unidades: nUnidades,
    counts,
    participacao_lula_t1: participacaoLulaT1,
    participacao_lula_t2: participacaoLulaT2,
    participacao_flavio_t1: participacaoFlavioT1,
    participacao_flavio_t2: participacaoFlavioT2,
    comparecimento_t1: comparecimentoT1Pct,
    comparecimento_t2: comparecimentoT2Pct,
    abstencao_t1: ratio(counts.qt_abstencoes_t1, aptosT1),
    abstencao_t2: ratio(counts.qt_abstencoes_t2, aptosT2),
    brancos_share_t1: ratio(counts.qt_votos_brancos_t1, comparecimentoT1),
    brancos_share_t2: ratio(counts.qt_votos_brancos_t2, comparecimentoT2),
    nulos_share_t1: ratio(counts.qt_votos_nulos_t1, comparecimentoT1),
    nulos_share_t2: ratio(counts.qt_votos_nulos_t2, comparecimentoT2),
    margem_t1_pp: margemT1 === null ? null : 100 * margemT1,
    margem_t2_pp: margemT2 === null ? null : 100 * margemT2,
    delta_participacao_lula_pp: deltaPp(participacaoLulaT2, participacaoLulaT1),
    delta_participacao_flavio_pp: deltaPp(participacaoFlavioT2, participacaoFlavioT1),
    delta_comparecimento_pp: deltaPp(comparecimentoT2Pct, comparecimentoT1Pct),
    delta_margem_pp: deltaPp(margemT2, margemT1),
    delta_margem_votos: (lulaT2 - flavioT2) - (lulaT1 - flavioT1),
    cobertura: {
      com_geometria: comGeometria,
      sem_geometria: rows.length - comGeometria,
      com_contexto: comContexto,
      sem_contexto: rows.length - comContexto,
      por_indicador: porIndicador,
    },
  };
}

export type MunicipioDerived = {
  participacao_lula_t1: number | null;
  participacao_lula_t2: number | null;
  participacao_flavio_t1: number | null;
  participacao_flavio_t2: number | null;
  comparecimento_t1: number | null;
  comparecimento_t2: number | null;
  margem_t1_pp: number | null;
  margem_t2_pp: number | null;
  delta_margem_pp: number | null;
  delta_margem_votos: number;
};

export function derived(row: Municipio): MunicipioDerived {
  const lula1 = ratio(row.qt_lula_t1, row.qt_votos_validos_t1);
  const lula2 = ratio(row.qt_lula_t2, row.qt_votos_validos_t2);
  const flavio1 = ratio(row.qt_flavio_t1, row.qt_votos_validos_t1);
  const flavio2 = ratio(row.qt_flavio_t2, row.qt_votos_validos_t2);
  const margem1 = lula1 === null || flavio1 === null ? null : lula1 - flavio1;
  const margem2 = lula2 === null || flavio2 === null ? null : lula2 - flavio2;
  return {
    participacao_lula_t1: lula1,
    participacao_lula_t2: lula2,
    participacao_flavio_t1: flavio1,
    participacao_flavio_t2: flavio2,
    comparecimento_t1: ratio(row.qt_comparecimento_t1, row.qt_aptos_t1),
    comparecimento_t2: ratio(row.qt_comparecimento_t2, row.qt_aptos_t2),
    margem_t1_pp: margem1 === null ? null : 100 * margem1,
    margem_t2_pp: margem2 === null ? null : 100 * margem2,
    delta_margem_pp: deltaPp(margem2, margem1),
    delta_margem_votos: (row.qt_lula_t2 - row.qt_flavio_t2) - (row.qt_lula_t1 - row.qt_flavio_t1),
  };
}

const sortValue = (row: Municipio, field: SortField): number | string | null => {
  if (field === "nome" || field === "sg_uf") return row[field];
  if (field === "qt_aptos_t2") return row.qt_aptos_t2;
  if (field === "renda_pc" || field === "pbf") return row[field];
  const d = derived(row);
  switch (field) {
    case "comparecimento_t2":
      return d.comparecimento_t2;
    case "participacao_lula_t2":
      return d.participacao_lula_t2;
    case "participacao_flavio_t2":
      return d.participacao_flavio_t2;
    case "delta_margem_pp":
      return d.delta_margem_pp;
  }
};

export function sortMunicipios(rows: Municipio[], field: SortField, order: SortOrder): Municipio[] {
  const factor = order === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = sortValue(a, field);
    const vb = sortValue(b, field);
    if (va === null && vb === null) return a.nome.localeCompare(b.nome, "pt-BR");
    if (va === null) return 1;
    if (vb === null) return -1;
    if (typeof va === "string" || typeof vb === "string") {
      return factor * String(va).localeCompare(String(vb), "pt-BR");
    }
    if (va === vb) return a.nome.localeCompare(b.nome, "pt-BR");
    return factor * (va - vb);
  });
}

export type Group = { key: string; label: string; rows: Municipio[]; agg: Aggregate };

export function groupBy(rows: Municipio[], key: "sg_uf" | "regiao"): Group[] {
  const buckets = new Map<string, Municipio[]>();
  for (const row of rows) {
    const k = row[key];
    const list = buckets.get(k);
    if (list) list.push(row);
    else buckets.set(k, [row]);
  }
  return [...buckets.entries()]
    .map(([k, list]) => ({ key: k, label: k, rows: list, agg: aggregate(list) }))
    .sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
}

export function normalizeText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

export type SearchHit = {
  municipio: Municipio;
  reason: "nome" | "uf" | "codigo";
};

export function searchMunicipios(rows: Municipio[], query: string, limit = 12): SearchHit[] {
  const q = normalizeText(query);
  if (q.length === 0) return [];
  const hits: SearchHit[] = [];
  for (const row of rows) {
    if (normalizeText(row.nome).includes(q)) hits.push({ municipio: row, reason: "nome" });
    else if (row.cd_ibge.startsWith(q) || row.cd_tse.startsWith(q)) hits.push({ municipio: row, reason: "codigo" });
    else if (normalizeText(row.sg_uf) === q) hits.push({ municipio: row, reason: "uf" });
    if (hits.length >= limit * 8) break;
  }
  const rank = { nome: 0, codigo: 1, uf: 2 };
  return hits
    .sort((a, b) => rank[a.reason] - rank[b.reason] || a.municipio.nome.localeCompare(b.municipio.nome, "pt-BR"))
    .slice(0, limit);
}

export function missingCoverage(rows: Municipio[], filters: Filters) {
  const geographic = filterMunicipios(rows, { ...filters, socio: {} });
  const summarize = (rs: Municipio[]) => ({ municipios: rs.length, unidades: rs.reduce((s,r) => s+r.n_unidades,0), aptos_t2: rs.reduce((s,r) => s+r.qt_aptos_t2,0) });
  return {
    universo: "recorte geográfico antes de filtros socioeconômicos; ausências por indicador podem se sobrepor",
    base: summarize(geographic),
    indicadores: Object.fromEntries(activeSocioFields(filters).map(field => [field, summarize(geographic.filter(row => row[field] === null))])),
  };
}

export function describeCoverage(agg: Aggregate, filters: Filters): string[] {
  const parts = [
    `${agg.municipios.toLocaleString("pt-BR")} município(s) no recorte`,
    `${agg.n_unidades.toLocaleString("pt-BR")} unidade(s) eleitoral(is)`,
  ];
  if (agg.cobertura.sem_geometria > 0) parts.push(`${agg.cobertura.sem_geometria} sem geometria (só na tabela)`);
  if (agg.cobertura.sem_contexto > 0) parts.push(`${agg.cobertura.sem_contexto} sem contexto socioeconômico`);
  for (const field of activeSocioFields(filters)) {
    const c = agg.cobertura.por_indicador[field];
    parts.push(`${field}: ${c.com_valor} com valor, ${c.sem_valor} sem informação`);
  }
  return parts;
}
