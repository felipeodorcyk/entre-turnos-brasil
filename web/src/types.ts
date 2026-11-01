export const SCHEMA_VERSION = "webapp-p0/1.0.0";

export const COUNT_FIELDS = [
  "qt_aptos_t1",
  "qt_aptos_t2",
  "qt_comparecimento_t1",
  "qt_comparecimento_t2",
  "qt_abstencoes_t1",
  "qt_abstencoes_t2",
  "qt_votos_validos_t1",
  "qt_votos_validos_t2",
  "qt_votos_brancos_t1",
  "qt_votos_brancos_t2",
  "qt_votos_nulos_t1",
  "qt_votos_nulos_t2",
  "qt_lula_t1",
  "qt_lula_t2",
  "qt_flavio_t1",
  "qt_flavio_t2",
] as const;

export const SOCIO_FIELDS = [
  "renda_pc",
  "baixa_renda",
  "desocupacao",
  "vinculos",
  "pbf",
  "urbana",
] as const;

export type CountField = (typeof COUNT_FIELDS)[number];
export type SocioField = (typeof SOCIO_FIELDS)[number];

export type Municipio = {
  cd_tse: string;
  cd_ibge: string;
  sg_uf: string;
  nome: string;
  regiao: string;
  cd_regiao_imediata: string | null;
  n_unidades: number;
  tem_geometria: 0 | 1;
  tem_contexto: 0 | 1;
} & Record<CountField, number> &
  Record<SocioField, number | null>;

export type UfRow = {
  sg_uf: string;
  nome_uf: string;
  regiao: string | null;
  n_municipios: number;
} & Record<CountField, number>;

export type RangeFilter = {
  min: number | null;
  max: number | null;
  missing: boolean;
};

export type Filters = {
  regioes: string[];
  ufs: string[];
  municipios: string[];
  socio: Partial<Record<SocioField, RangeFilter>>;
};

export type MapMetric =
  | "delta_comparecimento_pp"
  | "participacao_lula_t1"
  | "participacao_flavio_t1"
  | "comparecimento_t1"
  | "margem_t1"
  | "delta_participacao_lula_pp"
  | "delta_participacao_flavio_pp"

  | "participacao_lula_t2"
  | "participacao_flavio_t2"
  | "comparecimento_t2"
  | "margem_t2"
  | "delta_margem_pp"
  | "delta_margem_votos"
  | "renda_pc"
  | "pbf";

export type SortField =
  | "nome"
  | "sg_uf"
  | "qt_aptos_t2"
  | "comparecimento_t2"
  | "participacao_lula_t2"
  | "participacao_flavio_t2"
  | "delta_margem_pp"
  | "renda_pc"
  | "pbf";

export type SortOrder = "asc" | "desc";

export type ViewState = {
  filters: Filters;
  metrica: MapMetric;
  ordem: { field: SortField; order: SortOrder };
  pag: number;
};

export const EMPTY_FILTERS: Filters = {
  regioes: [],
  ufs: [],
  municipios: [],
  socio: {},
};

export const DEFAULT_STATE: ViewState = {
  filters: EMPTY_FILTERS,
  metrica: "delta_margem_votos",
  ordem: { field: "delta_margem_pp", order: "desc" },
  pag: 1,
};

export type Aggregate = {
  municipios: number;
  n_unidades: number;
  counts: Record<CountField, number>;
  participacao_lula_t1: number | null;
  participacao_lula_t2: number | null;
  participacao_flavio_t1: number | null;
  participacao_flavio_t2: number | null;
  comparecimento_t1: number | null;
  comparecimento_t2: number | null;
  abstencao_t1: number | null;
  abstencao_t2: number | null;
  brancos_share_t1: number | null;
  brancos_share_t2: number | null;
  nulos_share_t1: number | null;
  nulos_share_t2: number | null;
  margem_t1_pp: number | null;
  margem_t2_pp: number | null;
  delta_participacao_lula_pp: number | null;
  delta_participacao_flavio_pp: number | null;
  delta_comparecimento_pp: number | null;
  delta_margem_pp: number | null;
  delta_margem_votos: number;
  cobertura: {
    com_geometria: number;
    sem_geometria: number;
    com_contexto: number;
    sem_contexto: number;
    por_indicador: Record<SocioField, { com_valor: number; sem_valor: number }>;
  };
};

export type ReleaseData = {
  releaseId: string;
  schemaVersion: string;
  municipios: Municipio[];
  ufs: UfRow[];
  nacional: Nacional;
  faixas: Faixas;
  dicionario: Dicionario;
  manifest: ReleaseManifest | null;
  socioReady: boolean;
};

export type Nacional = {
  release_id: string;
  schema_version: string;
  fonte: string;
  unidades: number;
  inclui_exterior: boolean;
  diferencas_nao_zero: number;
  metricas_por_unidade_turno: number;
  totais: Record<
    "t1" | "t2",
    {
      aptos: number;
      comparecimento: number;
      abstencoes: number;
      votos_brancos: number;
      votos_nulos: number;
      lula: number;
      flavio: number;
      validos_t2: number | null;
    }
  >;
  por_uf: Array<Record<string, unknown>>;
  excecoes: {
    aptos_sem_comparecimento_abstencao_t1: number;
    aptos_sem_comparecimento_abstencao_t2: number;
    unidades_sem_apuracao_nenhum_turno: number;
    aptos_unidades_sem_apuracao: number;
  };
  urls: string[];
};

export type Faixa = {
  faixa: number;
  corte_inferior: number | null;
  corte_superior: number | null;
  valor_min: number | null;
  valor_max: number | null;
  municipios: number;
  municipios_sem_indicador: number;
};

export type Faixas = {
  metodo: string;
  fonte: string;
  indicadores: Record<string, Faixa[]>;
};

export type FieldDef = {
  tipo: string;
  rotulo: string;
  agregacao: string;
  unidade?: string;
  ano_referencia?: string;
  fonte?: string;
  nota?: string;
};

export type Dicionario = {
  campos: Record<string, FieldDef>;
  derivados: Record<string, string>;
  fontes: Record<string, string>;
  nao_agregaveis: string[];
  politica_nulos: string;
  notas: string[];
};

export type ReleaseManifest = {
  release_id: string;
  schema_version: string;
  generated_at_utc: string;
  origem: Record<string, unknown>;
  universos: Record<string, unknown>;
  cobertura: {
    com_geometria: number;
    sem_geometria: string[];
    com_contexto: number;
    sem_contexto: string[];
    municipios_sem_indicador_por_campo: Record<string, number>;
  };
  excecoes: Nacional["excecoes"];
  fontes: Record<string, unknown>;
  hashes_entrada: Record<string, string>;
  validacoes: Record<string, unknown>;
  decisoes_pendentes_sol: string[];
};
