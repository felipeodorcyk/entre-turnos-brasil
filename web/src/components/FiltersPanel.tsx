import { useId, useMemo, useState } from "react";
import type { Faixas, Filters, Municipio, RangeFilter, SocioField } from "../types";
import { SOCIO_FIELDS } from "../types";
import { isSocioRuleActive, searchMunicipios } from "../engine/query";
import { SOCIO_LABEL, SOCIO_SOURCE, SOCIO_UNIT, decimal, fmtSocio } from "../format";

const REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"];

const SOCIO_STEP: Record<SocioField, number> = {
  renda_pc: 0.01,
  baixa_renda: 0.01,
  desocupacao: 0.01,
  vinculos: 0.01,
  pbf: 0.01,
  urbana: 0.01,
};

type Props = {
  filters: Filters;
  municipios: Municipio[];
  faixas: Faixas;
  onChange: (next: Filters) => void;
  onClear: () => void;
  onAddMunicipio: (code: string) => void;
  onRemoveMunicipio: (code: string) => void;
  warning: string | null;
  socioReady: boolean;
};

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export default function FiltersPanel({
  filters,
  municipios,
  faixas,
  onChange,
  onClear,
  onAddMunicipio,
  onRemoveMunicipio,
  warning,
  socioReady,
}: Props) {
  const [query, setQuery] = useState("");
  const searchId = useId();
  const results = useMemo(() => searchMunicipios(municipios, query), [municipios, query]);

  const ufs = useMemo(() => {
    const all = [...new Set(municipios.map((m) => m.sg_uf))].sort();
    if (filters.regioes.length === 0) return all;
    const allowed = new Set(
      municipios.filter((m) => filters.regioes.includes(m.regiao)).map((m) => m.sg_uf),
    );
    return all.filter((uf) => allowed.has(uf));
  }, [municipios, filters.regioes]);

  const selectedMuns = useMemo(
    () =>
      filters.municipios
        .map((code) => municipios.find((m) => m.cd_ibge === code))
        .filter((m): m is Municipio => Boolean(m)),
    [filters.municipios, municipios],
  );

  const updateSocio = (field: SocioField, patch: Partial<RangeFilter> | null) => {
    const nextSocio = { ...filters.socio };
    if (patch === null) {
      delete nextSocio[field];
    } else {
      const current = nextSocio[field] ?? { min: null, max: null, missing: false };
      nextSocio[field] = { ...current, ...patch };
    }
    onChange({ ...filters, socio: nextSocio });
  };

  const activeCount =
    filters.regioes.length +
    filters.ufs.length +
    filters.municipios.length +
    SOCIO_FIELDS.filter((f) => isSocioRuleActive(filters.socio[f])).length;

  return (
    <section className="filters" aria-labelledby="filtros-titulo">
      <div className="filters-head">
        <h2 id="filtros-titulo">Filtros</h2>
        <button type="button" className="link-button" onClick={onClear} disabled={activeCount === 0}>
          Limpar tudo
        </button>
      </div>
      <p className="hint">
        Seleções múltiplas somam opções dentro do grupo (OU) e cruzam grupos diferentes (E). Sem filtro, municípios
        sem informação permanecem.
      </p>
      {warning && (
        <p className="warning" role="status">
          {warning}
        </p>
      )}

      <fieldset>
        <legend>Grande região</legend>
        <div className="check-grid">
          {REGIOES.map((regiao) => (
            <label key={regiao} className="check">
              <input
                type="checkbox"
                checked={filters.regioes.includes(regiao)}
                onChange={() => onChange({ ...filters, regioes: toggle(filters.regioes, regiao) })}
              />
              <span>{regiao}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>UF</legend>
        <div className="check-grid uf-grid">
          {ufs.map((uf) => (
            <label key={uf} className="check">
              <input
                type="checkbox"
                checked={filters.ufs.includes(uf)}
                onChange={() => onChange({ ...filters, ufs: toggle(filters.ufs, uf) })}
              />
              <span>{uf}</span>
            </label>
          ))}
        </div>
        {filters.regioes.length > 0 && <p className="hint">UFs fora das regiões escolhidas não são oferecidas.</p>}
      </fieldset>

      <fieldset>
        <legend>Buscar município</legend>
        <label className="sr-only" htmlFor={searchId}>
          Nome do município, UF ou código
        </label>
        <input
          id={searchId}
          type="search"
          value={query}
          placeholder="Nome, UF ou código"
          onChange={(event) => setQuery(event.target.value)}
          autoComplete="off"
        />
        {query.trim().length > 0 && (
          <ul className="search-results" aria-label="Resultados da busca">
            {results.length === 0 && <li className="hint">Nenhum município encontrado.</li>}
            {results.map((hit) => {
              const selected = filters.municipios.includes(hit.municipio.cd_ibge);
              return (
                <li key={hit.municipio.cd_ibge}>
                  <button
                    type="button"
                    className={selected ? "search-hit selected" : "search-hit"}
                    onClick={() => {
                      if (selected) onRemoveMunicipio(hit.municipio.cd_ibge);
                      else onAddMunicipio(hit.municipio.cd_ibge);
                    }}
                  >
                    <span>
                      {hit.municipio.nome} / {hit.municipio.sg_uf}
                    </span>
                    <small>
                      {hit.municipio.cd_ibge}
                      {selected ? " · selecionado" : ""}
                    </small>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {selectedMuns.length > 0 && (
          <ul className="chips" aria-label="Municípios selecionados">
            {selectedMuns.map((m) => (
              <li key={m.cd_ibge}>
                <span>
                  {m.nome}/{m.sg_uf}
                </span>
                <button
                  type="button"
                  aria-label={`Remover ${m.nome} da seleção`}
                  onClick={() => onRemoveMunicipio(m.cd_ibge)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      <fieldset>
        <legend>Indicadores socioeconômicos</legend>
        {!socioReady && (
          <p className="hint" role="status">
            Carregando indicadores socioeconômicos… Os cards e a tabela já podem ser usados.
          </p>
        )}
        <p className="hint">
          Intervalos fechados nos dois extremos. São atributos do município, não do eleitor; não são somados nem
          viram média do recorte.
        </p>
        {SOCIO_FIELDS.map((field) => {
          const rule = filters.socio[field];
          const active = isSocioRuleActive(rule);
          const bands = faixas.indicadores[field] ?? [];
          return (
            <div className="socio-filter" key={field}>
              <div className="socio-title">
                <span>{SOCIO_LABEL[field]}</span>
                <small>{SOCIO_UNIT[field]}</small>
              </div>
              <div className="range-row">
                <label>
                  <span>mín.</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    step={SOCIO_STEP[field]}
                    value={rule?.min ?? ""}
                    disabled={!socioReady}
                    onChange={(event) =>
                      updateSocio(field, {
                        min: event.target.value === "" ? null : Number(event.target.value),
                      })
                    }
                    aria-label={`${SOCIO_LABEL[field]}: valor mínimo`}
                  />
                </label>
                <label>
                  <span>máx.</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    step={SOCIO_STEP[field]}
                    value={rule?.max ?? ""}
                    disabled={!socioReady}
                    onChange={(event) =>
                      updateSocio(field, {
                        max: event.target.value === "" ? null : Number(event.target.value),
                      })
                    }
                    aria-label={`${SOCIO_LABEL[field]}: valor máximo`}
                  />
                </label>
                <label className="check compact">
                  <input
                    type="checkbox"
                    checked={Boolean(rule?.missing)}
                    disabled={!socioReady}
                    onChange={(event) => updateSocio(field, { missing: event.target.checked })}
                  />
                  <span>sem informação</span>
                </label>
              </div>
              {bands.length > 0 && (
                <label className="preset">
                  <span>Faixa congelada</span>
                  <select
                    value=""
                    disabled={!socioReady}
                    onChange={(event) => {
                      const band = bands.find((b) => String(b.faixa) === event.target.value);
                      if (!band) return;
                      updateSocio(field, { min: band.valor_min, max: band.valor_max, missing: false });
                    }}
                  >
                    <option value="">escolher…</option>
                    {bands.map((band) => (
                      <option key={band.faixa} value={band.faixa}>
                        {band.faixa}: {fmtSocio(field, band.valor_min)} – {fmtSocio(field, band.valor_max)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {rule?.min != null && rule?.max != null && rule.min > rule.max && (
                <p className="warning" role="status">
                  Intervalo inválido: mínimo maior que máximo; nenhum município satisfaz.
                </p>
              )}
              {active && (
                <p className="active-filter">
                  ativo: {rule?.min === null ? "sem mínimo" : decimal(rule?.min ?? null)} a{" "}
                  {rule?.max === null ? "sem máximo" : decimal(rule?.max ?? null)}
                  {rule?.missing ? " ou sem informação" : ""}
                  <button type="button" className="link-button" onClick={() => updateSocio(field, null)}>
                    remover
                  </button>
                </p>
              )}
              <p className="source-line">{SOCIO_SOURCE[field]}</p>
            </div>
          );
        })}
      </fieldset>
    </section>
  );
}
