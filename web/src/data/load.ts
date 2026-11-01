import {
  COUNT_FIELDS,
  SCHEMA_VERSION,
  SOCIO_FIELDS,
  type Dicionario,
  type Faixas,
  type Municipio,
  type Nacional,
  type ReleaseData,
  type ReleaseManifest,
  type SocioField,
  type UfRow,
} from "../types";

const BASE = import.meta.env.BASE_URL;

const asset = (path: string): string => `${BASE.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(asset(path), { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Falha ao carregar ${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

type RawTable = {
  schema_version: string;
  release_id: string;
  fields: string[];
  rows: Array<Array<string | number | null>>;
};

type Bundle = {
  schema_version: string;
  release_id: string;
  municipios: RawTable;
  uf: RawTable;
  nacional: Nacional;
  faixas: Faixas & { release_id: string; schema_version: string };
  dicionario: Dicionario & { release_id: string; schema_version: string };
};

const parseMunicipios = (raw: RawTable): Municipio[] =>
  raw.rows.map((row) => {
    const obj: Record<string, unknown> = {};
    raw.fields.forEach((field, i) => {
      obj[field] = row[i];
    });
    for (const field of COUNT_FIELDS) obj[field] = Number(obj[field]);
    for (const field of SOCIO_FIELDS) {
      obj[field] = obj[field] === undefined || obj[field] === null || obj[field] === "" ? null : Number(obj[field]);
    }
    obj.tem_geometria = Number(obj.tem_geometria) === 1 ? 1 : 0;
    obj.tem_contexto = Number(obj.tem_contexto) === 1 ? 1 : 0;
    return obj as Municipio;
  });

const parseUfs = (raw: RawTable): UfRow[] =>
  raw.rows.map((row) => {
    const obj: Record<string, unknown> = {};
    raw.fields.forEach((field, i) => {
      obj[field] = row[i];
    });
    for (const field of COUNT_FIELDS) obj[field] = Number(obj[field]);
    obj.n_municipios = Number(obj.n_municipios);
    return obj as UfRow;
  });

export function requestedRelease(hash: string): string | null {
  const id = new URLSearchParams(hash.replace(/^#/, "")).get("release");
  if (id !== null && !/^p0-[a-zA-Z0-9-]{1,100}$/.test(id)) throw new Error("Identificador de release inválido.");
  return id;
}

export async function loadRelease(hash = window.location.hash): Promise<ReleaseData> {
  const requested = requestedRelease(hash);
  const pointer = requested
    ? await fetchJson<ReleaseManifest>(`release/${requested}/manifest.json`)
    : await fetchJson<{ release_id: string; schema_version: string }>("release/current.json");
  if (requested && pointer.release_id !== requested) throw new Error("Manifesto de outro release.");
  requestedRelease(`#release=${pointer.release_id}`);
  if (pointer.schema_version !== SCHEMA_VERSION) {
    throw new Error(
      `Release ${pointer.release_id} usa schema ${pointer.schema_version}; o app espera ${SCHEMA_VERSION}.`,
    );
  }
  const bundle = await fetchJson<Bundle>(`release/${pointer.release_id}/bundle.json`);
  if ([bundle, bundle.municipios, bundle.uf, bundle.nacional, bundle.faixas, bundle.dicionario].some(
    part => part.release_id !== pointer.release_id || part.schema_version !== SCHEMA_VERSION
  )) {
    throw new Error("Arquivos do release não conferem com o ponteiro current.json.");
  }
  return {
    releaseId: pointer.release_id,
    schemaVersion: pointer.schema_version,
    municipios: parseMunicipios(bundle.municipios),
    ufs: parseUfs(bundle.uf),
    nacional: bundle.nacional,
    faixas: bundle.faixas,
    dicionario: bundle.dicionario,
    manifest: null,
    socioReady: false,
  };
}

export type SocioRow = { cd_ibge: string } & Record<SocioField, number | null>;

export async function loadSocio(releaseId: string): Promise<Map<string, SocioRow>> {
  const raw = await fetchJson<{ release_id: string; fields: string[]; rows: Array<Array<string | number | null>> }>(
    `release/${releaseId}/socio.json`,
  );
  if (raw.release_id !== releaseId) throw new Error("socio.json não confere com o release.");
  const codeIndex = raw.fields.indexOf("cd_ibge");
  const fieldIndex = Object.fromEntries(raw.fields.map((field, i) => [field, i])) as Record<string, number>;
  const out = new Map<string, SocioRow>();
  for (const row of raw.rows) {
    const record = { cd_ibge: String(row[codeIndex]) } as SocioRow;
    for (const field of SOCIO_FIELDS) {
      const value = row[fieldIndex[field]];
      record[field] = value === null || value === "" ? null : Number(value);
    }
    out.set(record.cd_ibge, record);
  }
  return out;
}

export async function loadManifest(releaseId: string): Promise<ReleaseManifest> {
  return fetchJson<ReleaseManifest>(`release/${releaseId}/manifest.json`);
}

export function datasetIndex(data: ReleaseData) {
  return {
    releaseId: data.releaseId,
    schemaVersion: data.schemaVersion,
    regioes: new Set(data.municipios.map((m) => m.regiao)),
    ufs: new Set(data.municipios.map((m) => m.sg_uf)),
    municipios: new Map(data.municipios.map((m) => [m.cd_ibge, { sg_uf: m.sg_uf, regiao: m.regiao }])),
  };
}

export const GEO_MUNICIPIOS = "geo/municipios_2022_intermediaria.geojson";
export const GEO_UFS = "geo/ufs_2022.geojson";
export const geoAsset = asset;
