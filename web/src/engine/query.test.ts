import { describe, expect, it } from "vitest";
import type { Filters, Municipio, RangeFilter } from "../types";
import { aggregate, derived, filterMunicipios, sortMunicipios } from "./query";

const base: Municipio = {
  cd_tse: "00001",
  cd_ibge: "1000001",
  sg_uf: "SP",
  nome: "Alfa",
  regiao: "Sudeste",
  cd_regiao_imediata: "100001",
  n_unidades: 10,
  qt_aptos_t1: 100,
  qt_aptos_t2: 100,
  qt_comparecimento_t1: 80,
  qt_comparecimento_t2: 80,
  qt_abstencoes_t1: 20,
  qt_abstencoes_t2: 20,
  qt_votos_validos_t1: 50,
  qt_votos_validos_t2: 50,
  qt_votos_brancos_t1: 5,
  qt_votos_brancos_t2: 5,
  qt_votos_nulos_t1: 5,
  qt_votos_nulos_t2: 5,
  qt_lula_t1: 30,
  qt_lula_t2: 30,
  qt_flavio_t1: 20,
  qt_flavio_t2: 20,
  renda_pc: 1000,
  baixa_renda: 30,
  desocupacao: 5,
  vinculos: 200,
  pbf: 10,
  urbana: 80,
  tem_geometria: 1,
  tem_contexto: 1,
};

const rows: Municipio[] = [
  base,
  {
    ...base,
    cd_tse: "00002",
    cd_ibge: "2000002",
    sg_uf: "BA",
    nome: "Beta",
    regiao: "Nordeste",
    n_unidades: 30,
    qt_aptos_t1: 300,
    qt_aptos_t2: 300,
    qt_comparecimento_t1: 240,
    qt_comparecimento_t2: 240,
    qt_abstencoes_t1: 60,
    qt_abstencoes_t2: 60,
    qt_votos_validos_t1: 200,
    qt_votos_validos_t2: 200,
    qt_lula_t1: 100,
    qt_lula_t2: 100,
    qt_flavio_t1: 100,
    qt_flavio_t2: 100,
    renda_pc: 500,
    baixa_renda: 60,
    desocupacao: 10,
    vinculos: 100,
    pbf: null,
    urbana: 50,
    tem_geometria: 0,
    tem_contexto: 0,
  },
  {
    ...base,
    cd_tse: "00003",
    cd_ibge: "3000003",
    nome: "Gama sem votos",
    n_unidades: 1,
    qt_aptos_t1: 0,
    qt_aptos_t2: 0,
    qt_comparecimento_t1: 0,
    qt_comparecimento_t2: 0,
    qt_abstencoes_t1: 0,
    qt_abstencoes_t2: 0,
    qt_votos_validos_t1: 0,
    qt_votos_validos_t2: 0,
    qt_votos_brancos_t1: 0,
    qt_votos_brancos_t2: 0,
    qt_votos_nulos_t1: 0,
    qt_votos_nulos_t2: 0,
    qt_lula_t1: 0,
    qt_lula_t2: 0,
    qt_flavio_t1: 0,
    qt_flavio_t2: 0,
    renda_pc: null,
    baixa_renda: null,
    desocupacao: null,
    vinculos: null,
    pbf: 50,
    urbana: null,
    tem_geometria: 1,
    tem_contexto: 0,
  },
  {
    ...base,
    cd_tse: "00004",
    cd_ibge: "4000004",
    sg_uf: "RS",
    nome: "Delta",
    regiao: "Sul",
    n_unidades: 5,
    qt_aptos_t1: 50,
    qt_aptos_t2: 50,
    qt_comparecimento_t1: 40,
    qt_comparecimento_t2: 40,
    qt_abstencoes_t1: 10,
    qt_abstencoes_t2: 10,
    qt_votos_validos_t1: 30,
    qt_votos_validos_t2: 30,
    qt_lula_t1: 10,
    qt_lula_t2: 10,
    qt_flavio_t1: 20,
    qt_flavio_t2: 20,
    renda_pc: 2000,
    baixa_renda: 10,
    desocupacao: 2,
    vinculos: 300,
    pbf: 100,
    urbana: 95,
  },
];

const emptyFilters: Filters = { regioes: [], ufs: [], municipios: [], socio: {} };
const range = (min: number | null, max: number | null, missing = false): RangeFilter => ({ min, max, missing });

const ids = (list: Municipio[]) => list.map((row) => row.cd_ibge);

describe("motor de consulta", () => {
  it("sem filtro mantém todos, inclusive ausentes", () => {
    expect(ids(filterMunicipios(rows, emptyFilters))).toEqual(["1000001", "2000002", "3000003", "4000004"]);
  });

  it("OU dentro da dimensão UF", () => {
    expect(ids(filterMunicipios(rows, { ...emptyFilters, ufs: ["SP", "BA"] }))).toEqual([
      "1000001",
      "2000002",
      "3000003",
    ]);
  });

  it("E entre dimensões: UF + renda", () => {
    const filters = { ...emptyFilters, ufs: ["SP"], socio: { renda_pc: range(500, 1500) } };
    expect(ids(filterMunicipios(rows, filters))).toEqual(["1000001"]);
  });

  it("intervalo é inclusivo nos dois extremos", () => {
    const filters = { ...emptyFilters, socio: { renda_pc: range(500, 1000) } };
    expect(ids(filterMunicipios(rows, filters))).toEqual(["1000001", "2000002"]);
  });

  it("ausente não satisfaz intervalo e pode ser consultado à parte", () => {
    expect(ids(filterMunicipios(rows, { ...emptyFilters, socio: { renda_pc: range(0, 9999) } }))).toEqual([
      "1000001",
      "2000002",
      "4000004",
    ]);
    expect(ids(filterMunicipios(rows, { ...emptyFilters, socio: { renda_pc: range(null, null, true) } }))).toEqual([
      "3000003",
    ]);
    expect(
      ids(filterMunicipios(rows, { ...emptyFilters, socio: { renda_pc: range(400, 600, true) } })),
    ).toEqual(["2000002", "3000003"]);
  });

  it("variável sem filtro não exclui nulos", () => {
    const filters = { ...emptyFilters, socio: { pbf: range(0, 60) } };
    expect(ids(filterMunicipios(rows, filters))).toEqual(["1000001", "3000003"]);
    expect(ids(filterMunicipios(rows, { ...emptyFilters, socio: { pbf: range(0, 60, true) } }))).toEqual([
      "1000001",
      "2000002",
      "3000003",
    ]);
  });

  it("seleção vazia é resultado válido, com razões nulas", () => {
    const filtered = filterMunicipios(rows, { ...emptyFilters, municipios: ["9999999"] });
    const agg = aggregate(filtered);
    expect(agg.municipios).toBe(0);
    expect(agg.participacao_lula_t2).toBeNull();
    expect(agg.comparecimento_t2).toBeNull();
    expect(agg.delta_margem_pp).toBeNull();
    expect(agg.delta_margem_votos).toBe(0);
  });

  it("razões são calculadas sobre somas, não média de percentuais", () => {
    const filtered = filterMunicipios(rows, { ...emptyFilters, ufs: ["SP", "BA"] });
    const agg = aggregate(filtered);
    expect(agg.counts.qt_lula_t2).toBe(130);
    expect(agg.counts.qt_votos_validos_t2).toBe(250);
    expect(agg.participacao_lula_t2).toBeCloseTo(130 / 250, 15);
    // média simples daria (30/50 + 100/200)/2 = 0,55, diferente de 0,52
    expect(agg.participacao_lula_t2).not.toBeCloseTo(0.55, 5);
  });

  it("denominador zero resulta em nulo, nunca zero", () => {
    const d = derived(rows[2]);
    expect(d.participacao_lula_t2).toBeNull();
    expect(d.comparecimento_t2).toBeNull();
    expect(d.margem_t2_pp).toBeNull();
  });

  it("margem e saldo de votos seguem a identidade contábil", () => {
    const agg = aggregate(rows);
    expect(agg.delta_margem_votos).toBe((30 - 20) + (100 - 100) + (10 - 20) - ((30 - 20) + (100 - 100) + (10 - 20)));
    expect(agg.delta_margem_votos).toBe(0);
  });

  it("ordenação e paginação não alteram o agregado", () => {
    const filtered = filterMunicipios(rows, emptyFilters);
    const a = aggregate(filtered);
    const sorted = sortMunicipios(filtered, "delta_margem_pp", "desc");
    const b = aggregate(sorted);
    const page = aggregate(sorted.slice(0, 1));
    expect(a.counts).toEqual(b.counts);
    expect(page.municipios).toBe(1);
    expect(page.counts.qt_lula_t2).not.toBe(a.counts.qt_lula_t2);
  });

  it("cobertura separa sem geometria e sem contexto", () => {
    const agg = aggregate(rows);
    expect(agg.cobertura.sem_geometria).toBe(1);
    expect(agg.cobertura.sem_contexto).toBe(2);
    expect(agg.cobertura.por_indicador.renda_pc).toEqual({ com_valor: 3, sem_valor: 1 });
  });
});


describe("coverage before socioeconomic filters", () => {
 it("reports overlapping missing indicators without double counting base", async () => {
  const {missingCoverage} = await import("./query");
  const source = [base, {...base, cd_ibge:"x", renda_pc:null, pbf:null}];
  const result = missingCoverage(source, {regioes:[],ufs:["SP"],municipios:[],socio:{renda_pc:{min:0,max:2000,missing:false},pbf:{min:0,max:100,missing:false}}});
  expect(result.base.municipios).toBe(2);
  expect(result.indicadores.renda_pc).toEqual({municipios:1,unidades:10,aptos_t2:100});
  expect(result.indicadores.pbf).toEqual(result.indicadores.renda_pc);
 });
 it("preserves first-turn metric in shared URL", async () => {
  const {encodeState,decodeState} = await import("./url");
  const {DEFAULT_STATE,SCHEMA_VERSION} = await import("../types");
  const index={releaseId:"p0-test",schemaVersion:SCHEMA_VERSION,regioes:new Set<string>(),ufs:new Set<string>(),municipios:new Map()};
  expect(decodeState(encodeState({...DEFAULT_STATE,metrica:"participacao_lula_t1"},index.releaseId),index).state.metrica).toBe("participacao_lula_t1");
  const {metricValue}=await import("../format");
  expect(metricValue(base,"participacao_lula_t1")).toBe(60);
 });
});
