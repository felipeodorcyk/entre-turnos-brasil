import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  COUNT_FIELDS,
  SOCIO_FIELDS,
  type Filters,
  type Municipio,
  type Nacional,
  type RangeFilter,
  type SocioField,
} from "../types";
import { aggregate, filterMunicipios } from "./query";
import oracle from "./oracle_cases.json";

type RawTable = { release_id: string; fields: string[]; rows: Array<Array<string | number | null>> };

const read = (relative: string): unknown => {
  const path = fileURLToPath(new URL(relative, import.meta.url));
  if (!existsSync(path)) {
    throw new Error(
      `Arquivo ausente: ${path}. Gere o release com "npm run export" e o oráculo com "npm run oracle" antes de testar.`,
    );
  }
  return JSON.parse(readFileSync(path, "utf8"));
};

const pointer = read("../../public/release/current.json") as { release_id: string };
const table = read(`../../public/release/${pointer.release_id}/municipios.json`) as RawTable;
const nacional = read(`../../public/release/${pointer.release_id}/nacional.json`) as Nacional;

const rows: Municipio[] = table.rows.map((values) => {
  const obj: Record<string, unknown> = {};
  table.fields.forEach((field, i) => {
    obj[field] = values[i];
  });
  for (const field of COUNT_FIELDS) obj[field] = Number(obj[field]);
  for (const field of SOCIO_FIELDS) obj[field] = obj[field] === null ? null : Number(obj[field]);
  return obj as Municipio;
});

const toFilters = (spec: Record<string, unknown>): Filters => {
  const socioRaw = (spec.socio ?? {}) as Record<string, { min?: number; max?: number; missing?: boolean }>;
  const socio: Partial<Record<SocioField, RangeFilter>> = {};
  for (const field of SOCIO_FIELDS) {
    const rule = socioRaw[field];
    if (!rule) continue;
    socio[field] = { min: rule.min ?? null, max: rule.max ?? null, missing: Boolean(rule.missing) };
  }
  return {
    regioes: (spec.regioes as string[] | undefined) ?? [],
    ufs: (spec.ufs as string[] | undefined) ?? [],
    municipios: (spec.municipios as string[] | undefined) ?? [],
    socio,
  };
};

const INTEGER_FIELDS = new Set([
  "municipios",
  "aptos_t1",
  "aptos_t2",
  "comparecimento_t1",
  "comparecimento_t2",
  "validos_t1",
  "validos_t2",
  "lula_t1",
  "lula_t2",
  "flavio_t1",
  "flavio_t2",
  "delta_margem_votos",
  "sem_renda",
]);

describe("oráculo Python ↔ motor TypeScript", () => {
  it("o release do oráculo é o release carregado", () => {
    expect(oracle.release_id).toBe(pointer.release_id);
    expect(rows).toHaveLength(5571);
  });

  it("reconcilia somas municipais com a linha TOTAL de metrics_uf", () => {
    const agg = aggregate(rows);
    for (const [field, check] of Object.entries(oracle.reconciliation)) {
      const value = agg.counts[field as keyof typeof agg.counts];
      expect(value).toBe(check.soma_municipal);
      expect(check.igual).toBe(true);
    }
  });

  it("card nacional oficial confere com a referência independente", () => {
    const expected = oracle.official as unknown as Record<string, Record<string, number>>;
    expect(nacional.unidades).toBe(expected.unidades);
    for (const turn of ["t1", "t2"] as const) {
      for (const [field, value] of Object.entries(expected[turn])) {
        expect(nacional.totais[turn][field as keyof typeof nacional.totais.t1]).toBe(value);
      }
    }
  });

  it.each(oracle.cases.map((c) => [c.id, c] as const))("caso %s", (_id, testCase) => {
    const agg = aggregate(filterMunicipios(rows, toFilters(testCase.filters as Record<string, unknown>)));
    const actual: Record<string, number | null> = {
      municipios: agg.municipios,
      aptos_t1: agg.counts.qt_aptos_t1,
      aptos_t2: agg.counts.qt_aptos_t2,
      validos_t1: agg.counts.qt_votos_validos_t1,
      validos_t2: agg.counts.qt_votos_validos_t2,
      lula_t1: agg.counts.qt_lula_t1,
      lula_t2: agg.counts.qt_lula_t2,
      flavio_t1: agg.counts.qt_flavio_t1,
      flavio_t2: agg.counts.qt_flavio_t2,
      participacao_lula_t1: agg.participacao_lula_t1,
      participacao_lula_t2: agg.participacao_lula_t2,
      participacao_flavio_t1: agg.participacao_flavio_t1,
      participacao_flavio_t2: agg.participacao_flavio_t2,
      comparecimento_t1: agg.comparecimento_t1,
      comparecimento_t2: agg.comparecimento_t2,
      delta_margem_pp: agg.delta_margem_pp,
      delta_margem_votos: agg.delta_margem_votos,
      delta_comparecimento_pp: agg.delta_comparecimento_pp,
      sem_renda: agg.cobertura.por_indicador.renda_pc.sem_valor,
    };
    for (const [field, expected] of Object.entries(testCase.expected as Record<string, number | null>)) {
      const got = actual[field];
      if (expected === null) {
        expect(got, `${testCase.id}.${field}`).toBeNull();
      } else if (INTEGER_FIELDS.has(field)) {
        expect(got, `${testCase.id}.${field}`).toBe(expected);
      } else {
        expect(got, `${testCase.id}.${field}`).toBeCloseTo(expected, 10);
      }
    }
  });

  it("os casos cobrem filtros, ausência, vazio e município sem contexto", () => {
    expect(oracle.cases.length).toBeGreaterThanOrEqual(20);
    const ids = new Set(oracle.cases.map((c) => c.id));
    expect(ids.has("vazio")).toBe(true);
    expect(ids.has("boa_esperanca")).toBe(true);
    expect(ids.has("renda_ausente")).toBe(true);
    expect(ids.has("renda_borda_735")).toBe(true);
  });
});
