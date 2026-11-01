import { describe, expect, it } from "vitest";
import { DEFAULT_STATE, type ViewState } from "../types";
import { decodeState, encodeState, stateWithoutFilters, type DatasetIndex } from "./url";

const index: DatasetIndex = {
  releaseId: "p0-teste",
  schemaVersion: "webapp-p0/1.0.0",
  regioes: new Set(["Norte", "Sudeste"]),
  ufs: new Set(["AC", "SP"]),
  municipios: new Map([
    ["1200138", { sg_uf: "AC", regiao: "Norte" }],
    ["3550308", { sg_uf: "SP", regiao: "Sudeste" }],
  ]),
};

const state: ViewState = {
  filters: {
    regioes: ["Norte"],
    ufs: ["AC"],
    municipios: ["1200138"],
    socio: {
      renda_pc: { min: 500, max: 1000, missing: false },
      pbf: { min: null, max: null, missing: true },
      desocupacao: { min: 2.5, max: null, missing: false },
    },
  },
  metrica: "comparecimento_t2",
  ordem: { field: "renda_pc", order: "asc" },
  pag: 3,
};

describe("estado da URL", () => {
  it("faz round-trip de filtros, métrica, ordem e página", () => {
    const hash = encodeState(state, index.releaseId, index.schemaVersion);
    const decoded = decodeState(hash, index);
    expect(decoded.warnings).toEqual([]);
    expect(decoded.state).toEqual(state);
  });

  it("estado limpo não carrega filtros", () => {
    const hash = encodeState(stateWithoutFilters(), index.releaseId, index.schemaVersion);
    const decoded = decodeState(hash, index);
    expect(decoded.state.filters.regioes).toEqual([]);
    expect(decoded.state.filters.ufs).toEqual([]);
    expect(decoded.state.filters.municipios).toEqual([]);
    expect(decoded.state.filters.socio).toEqual({});
    expect(decoded.state.pag).toBe(1);
  });

  it("release ou schema diferente limpa os filtros com aviso", () => {
    const hash = `#release=outro&schema=webapp-p0/1.0.0&uf=SP`;
    const decoded = decodeState(hash, index);
    expect(decoded.reset).toBe(true);
    expect(decoded.warnings[0]).toContain("outro release");
    expect(decoded.state).toEqual(DEFAULT_STATE);
  });

  it("descarta UF desconhecida", () => {
    const decoded = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&uf=SP,XX", index);
    expect(decoded.state.filters.ufs).toEqual(["SP"]);
    expect(decoded.warnings.join(" ")).toContain("XX");
  });

  it("descarta UF incompatível com a região", () => {
    const decoded = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&reg=Norte&uf=SP", index);
    expect(decoded.state.filters.ufs).toEqual([]);
    expect(decoded.warnings.join(" ")).toContain("não pertence");
  });

  it("descarta município incompatível com UF", () => {
    const decoded = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&uf=SP&mun=1200138", index);
    expect(decoded.state.filters.municipios).toEqual([]);
    expect(decoded.warnings.join(" ")).toContain("fora das UFs");
  });

  it("intervalo inválido é ignorado", () => {
    const a = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&renda=1000:500", index);
    expect(a.state.filters.socio.renda_pc).toBeUndefined();
    expect(a.warnings.join(" ")).toContain("inválido");
    const b = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&renda=abc:10", index);
    expect(b.state.filters.socio.renda_pc).toBeUndefined();
    const c = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&renda=-1:10", index);
    expect(c.state.filters.socio.renda_pc).toBeUndefined();
  });

  it("métrica e página inválidas voltam ao padrão com aviso", () => {
    const decoded = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&metrica=foo&pag=0", index);
    expect(decoded.state.metrica).toBe(DEFAULT_STATE.metrica);
    expect(decoded.state.pag).toBe(1);
    expect(decoded.warnings).toHaveLength(2);
  });

  it("categoria sem informação sem intervalo vira filtro só de ausentes", () => {
    const decoded = decodeState("#release=p0-teste&schema=webapp-p0/1.0.0&sem=renda", index);
    expect(decoded.state.filters.socio.renda_pc).toEqual({ min: null, max: null, missing: true });
  });
});
