import {
  DEFAULT_STATE,
  EMPTY_FILTERS,
  SCHEMA_VERSION,
  SOCIO_FIELDS,
  type Filters,
  type MapMetric,
  type RangeFilter,
  type SocioField,
  type SortField,
  type SortOrder,
  type ViewState,
} from "../types";

export type DatasetIndex = {
  releaseId: string;
  schemaVersion: string;
  regioes: Set<string>;
  ufs: Set<string>;
  municipios: Map<string, { sg_uf: string; regiao: string }>;
};

export type DecodeResult = {
  state: ViewState;
  warnings: string[];
  reset: boolean;
};

const METRICS: MapMetric[] = [
  "delta_comparecimento_pp",
  "participacao_lula_t1",
  "participacao_flavio_t1",
  "comparecimento_t1",
  "margem_t1",
  "delta_participacao_lula_pp",
  "delta_participacao_flavio_pp",

  "participacao_lula_t2",
  "participacao_flavio_t2",
  "comparecimento_t2",
  "margem_t2",
  "delta_margem_pp",
  "delta_margem_votos",
  "renda_pc",
  "pbf",
];

const SORT_FIELDS: SortField[] = [
  "nome",
  "sg_uf",
  "qt_aptos_t2",
  "comparecimento_t2",
  "participacao_lula_t2",
  "participacao_flavio_t2",
  "delta_margem_pp",
  "renda_pc",
  "pbf",
];

const RANGE_KEYS: Record<string, SocioField> = {
  renda: "renda_pc",
  baixa: "baixa_renda",
  desoc: "desocupacao",
  vinc: "vinculos",
  pbf: "pbf",
  urb: "urbana",
};

const SOCIO_TO_KEY: Record<SocioField, string> = {
  renda_pc: "renda",
  baixa_renda: "baixa",
  desocupacao: "desoc",
  vinculos: "vinc",
  pbf: "pbf",
  urbana: "urb",
};

const splitList = (value: string | null): string[] =>
  value
    ? value
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean)
    : [];

const parseNumber = (value: string): number | null | "invalid" => {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : "invalid";
};

const parseRange = (value: string | null): RangeFilter | null | "invalid" => {
  if (value === null || value === "") return null;
  const parts = value.split(":");
  if (parts.length !== 2) return "invalid";
  const min = parseNumber(parts[0]);
  const max = parseNumber(parts[1]);
  if (min === "invalid" || max === "invalid") return "invalid";
  if (min !== null && max !== null && min > max) return "invalid";
  if (min === null && max === null) return null;
  return { min, max, missing: false };
};

const formatNum = (value: number | null): string =>
  value === null ? "" : Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6)));

const rangeToParams = (rule: RangeFilter, key: string): string | null => {
  if (!rule.missing && rule.min === null && rule.max === null) return null;
  if (rule.missing && rule.min === null && rule.max === null) return null;
  return `${key}=${formatNum(rule.min)}:${formatNum(rule.max)}`;
};

export function encodeState(state: ViewState, releaseId: string, schemaVersion = SCHEMA_VERSION): string {
  const params = new URLSearchParams();
  params.set("release", releaseId);
  params.set("schema", schemaVersion);
  const f = state.filters;
  if (f.regioes.length) params.set("reg", [...f.regioes].sort().join(","));
  if (f.ufs.length) params.set("uf", [...f.ufs].sort().join(","));
  if (f.municipios.length) params.set("mun", [...f.municipios].sort().join(","));
  for (const field of SOCIO_FIELDS) {
    const rule = f.socio[field];
    if (!rule) continue;
    const value = rangeToParams(rule, SOCIO_TO_KEY[field]);
    if (value) params.set(value.split("=")[0], value.split("=")[1]);
  }
  const sem = SOCIO_FIELDS.filter((field) => f.socio[field]?.missing).map((field) => SOCIO_TO_KEY[field]);
  if (sem.length) params.set("sem", sem.sort().join(","));
  if (state.metrica !== DEFAULT_STATE.metrica) params.set("metrica", state.metrica);
  if (state.ordem.field !== DEFAULT_STATE.ordem.field || state.ordem.order !== DEFAULT_STATE.ordem.order) {
    params.set("ordem", `${state.ordem.field}:${state.ordem.order}`);
  }
  if (state.pag !== 1) params.set("pag", String(state.pag));
  return `#${params.toString().replace(/%2C/g, ",").replace(/%3A/g, ":")}`;
}

const validRange = (rule: RangeFilter): boolean =>
  (rule.min === null || (Number.isFinite(rule.min) && rule.min >= 0)) &&
  (rule.max === null || (Number.isFinite(rule.max) && rule.max >= 0));

export function decodeState(hash: string, index: DatasetIndex): DecodeResult {
  const warnings: string[] = [];
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const release = params.get("release");
  const schema = params.get("schema");
  if (release !== index.releaseId || (schema !== null && schema !== index.schemaVersion)) {
    return {
      state: { ...DEFAULT_STATE, filters: { ...EMPTY_FILTERS, socio: {} } },
      warnings: [
        `A URL foi criada para outro release (${release ?? "sem release"}) ou schema (${schema ?? "sem schema"}). Filtros foram limpos; o release carregado é ${index.releaseId}.`,
      ],
      reset: true,
    };
  }

  const filters: Filters = { regioes: [], ufs: [], municipios: [], socio: {} };
  const regioes = splitList(params.get("reg"));
  for (const regiao of regioes) {
    if (index.regioes.has(regiao)) filters.regioes.push(regiao);
    else warnings.push(`Região desconhecida ignorada: ${regiao}.`);
  }
  const ufs = splitList(params.get("uf"));
  for (const uf of ufs) {
    if (!index.ufs.has(uf)) {
      warnings.push(`UF desconhecida ignorada: ${uf}.`);
      continue;
    }
    if (filters.regioes.length > 0) {
      const sample = [...index.municipios.values()].find((m) => m.sg_uf === uf);
      if (sample && !filters.regioes.includes(sample.regiao)) {
        warnings.push(`UF ${uf} não pertence às regiões selecionadas; ignorada.`);
        continue;
      }
    }
    filters.ufs.push(uf);
  }
  const muns = splitList(params.get("mun"));
  for (const code of muns) {
    const meta = index.municipios.get(code);
    if (!meta) {
      warnings.push(`Município desconhecido ignorado: ${code}.`);
      continue;
    }
    if (filters.ufs.length > 0 && !filters.ufs.includes(meta.sg_uf)) {
      warnings.push(`Município ${code} fora das UFs selecionadas; ignorado.`);
      continue;
    }
    if (filters.regioes.length > 0 && !filters.regioes.includes(meta.regiao)) {
      warnings.push(`Município ${code} fora das regiões selecionadas; ignorado.`);
      continue;
    }
    filters.municipios.push(code);
  }

  const sem = new Set(splitList(params.get("sem")));
  for (const [key, field] of Object.entries(RANGE_KEYS)) {
    const parsed = parseRange(params.get(key));
    if (parsed === "invalid") {
      warnings.push(`Intervalo inválido em "${key}" ignorado.`);
      continue;
    }
    if (parsed) {
      if (!validRange(parsed)) {
        warnings.push(`Intervalo negativo em "${key}" ignorado.`);
        continue;
      }
      filters.socio[field] = { ...parsed, missing: sem.has(key) };
      sem.delete(key);
    } else if (sem.has(key)) {
      filters.socio[field] = { min: null, max: null, missing: true };
      sem.delete(key);
    }
  }
  for (const key of sem) {
    const field = RANGE_KEYS[key];
    if (field) filters.socio[field] = { min: null, max: null, missing: true };
    else warnings.push(`Categoria "sem informação" desconhecida ignorada: ${key}.`);
  }

  const metricParam = params.get("metrica");
  const metrica: MapMetric = METRICS.includes(metricParam as MapMetric)
    ? (metricParam as MapMetric)
    : DEFAULT_STATE.metrica;
  if (metricParam && metrica !== metricParam) warnings.push(`Métrica desconhecida ignorada: ${metricParam}.`);

  let ordem = DEFAULT_STATE.ordem;
  const ordemParam = params.get("ordem");
  if (ordemParam) {
    const [field, order] = ordemParam.split(":");
    if (SORT_FIELDS.includes(field as SortField) && (order === "asc" || order === "desc")) {
      ordem = { field: field as SortField, order: order as SortOrder };
    } else {
      warnings.push(`Ordenação inválida ignorada: ${ordemParam}.`);
    }
  }

  let pag = 1;
  const pagParam = params.get("pag");
  if (pagParam !== null) {
    const parsed = Number(pagParam);
    if (Number.isInteger(parsed) && parsed >= 1) pag = parsed;
    else warnings.push(`Página inválida ignorada: ${pagParam}.`);
  }

  return { state: { filters, metrica, ordem, pag }, warnings, reset: false };
}

export function stateWithoutFilters(): ViewState {
  return {
    filters: { regioes: [], ufs: [], municipios: [], socio: {} },
    metrica: DEFAULT_STATE.metrica,
    ordem: DEFAULT_STATE.ordem,
    pag: 1,
  };
}
