import { describe, expect, it } from "vitest";
import type { Municipio } from "../types";
import { EMPTY_FILTERS, type ViewState } from "../types";
import { aggregate } from "./query";
import { buildCsv, buildMetadata, csvText } from "./csv";

const row: Municipio = {
  cd_tse: "00001",
  cd_ibge: "1000001",
  sg_uf: "SP",
  nome: "=HYPERLINK(\"http://malicioso\")",
  regiao: "Sudeste",
  cd_regiao_imediata: "100001",
  n_unidades: 2,
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
  qt_lula_t2: 40,
  qt_flavio_t1: 20,
  qt_flavio_t2: 10,
  renda_pc: 1000,
  baixa_renda: 30,
  desocupacao: 5,
  vinculos: 200,
  pbf: null,
  urbana: 80,
  tem_geometria: 0,
  tem_contexto: 1,
};

describe("CSV e metadados", () => {
  it("neutraliza fórmulas em campos textuais", () => {
    expect(csvText("=1+1")).toBe('"\'=1+1"');
    expect(csvText("+55")).toBe('"\'+55"');
    expect(csvText("-10")).toBe('"\'-10"');
    expect(csvText("@cmd")).toBe('"\'@cmd"');
    expect(csvText("São Paulo")).toBe('"São Paulo"');
    expect(csvText('Nome "aspas"')).toBe('"Nome ""aspas"""');
  });

  it("mantém contagens inteiras e usa ponto decimal", () => {
    const csv = buildCsv([row]);
    const lines = csv.trim().split("\r\n");
    expect(lines[0].startsWith("cd_ibge;cd_tse;nome;sg_uf;regiao;n_unidades;qt_aptos_t1")).toBe(true);
    expect(lines[1]).toContain('"\'=HYPERLINK(""http://malicioso"")"');
    const cells = lines[1].split(";");
    expect(cells[5]).toBe("2");
    expect(cells[6]).toBe("100");
    // participacao_lula_t2 = 40/50 = 0.8
    expect(cells).toContain("0.800000");
    expect(cells).toContain("");
  });

  it("metadados trazem filtros, fórmulas, cobertura e escopo", () => {
    const state: ViewState = {
      filters: { ...EMPTY_FILTERS, ufs: ["SP"], socio: { renda_pc: { min: 500, max: 1000, missing: false } } },
      metrica: "delta_margem_pp",
      ordem: { field: "nome", order: "asc" },
      pag: 1,
    };
    const meta = buildMetadata(state, aggregate([row]), "p0-teste", "webapp-p0/1.0.0", ["aviso"]);
    expect(meta.release_id).toBe("p0-teste");
    expect((meta.filtros as { ufs: string[] }).ufs).toEqual(["SP"]);
    expect((meta.totais as { qt_lula_t2: number }).qt_lula_t2).toBe(40);
    expect((meta.formulas as Record<string, string>).delta_margem_pp).toContain("qt_lula_t2");
    expect((meta.cobertura as { sem_geometria: number }).sem_geometria).toBe(1);
    expect(meta.avisos).toEqual(["aviso"]);
  });
});
