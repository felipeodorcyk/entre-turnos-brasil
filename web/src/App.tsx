import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Filters, MapMetric, Municipio, ReleaseData, SortField, ViewState } from "./types";
import { DEFAULT_STATE } from "./types";
import { aggregate, filterMunicipios, sortMunicipios, activeSocioFields, missingCoverage } from "./engine/query";
import { decodeState, encodeState, stateWithoutFilters, type DatasetIndex } from "./engine/url";
import { buildCsv, buildMetadata, download } from "./engine/csv";
import { datasetIndex, loadManifest, loadRelease, loadSocio } from "./data/load";
import { int, pct, pp } from "./format";
import FiltersPanel from "./components/FiltersPanel";
import { OfficialCard, OverviewCards } from "./components/Cards";
import MarginChart from "./components/MarginChart";
import MunicipiosTable, { PAGE_SIZE } from "./components/MunicipiosTable";
import Explanations from "./components/Explanations";
import Methodology from "./components/Methodology";
import DeferredMap from "./components/DeferredMap";
import TurnChange from "./components/TurnChange";

type Tab = "overview" | "perguntas" | "metodologia";

function sanitizeFilters(next: Filters, all: Municipio[]): { filters: Filters; warnings: string[] } {
  const warnings: string[] = [];
  const regions = new Set(all.map((m) => m.regiao));
  const ufs = new Set(all.map((m) => m.sg_uf));
  const byCode = new Map(all.map((m) => [m.cd_ibge, m]));
  const regioes = next.regioes.filter((r) => regions.has(r));
  if (regioes.length !== next.regioes.length) warnings.push("Região desconhecida removida.");
  const regionSet = new Set(regioes);
  const ufList = next.ufs.filter((uf) => ufs.has(uf));
  if (ufList.length !== next.ufs.length) warnings.push("UF desconhecida removida.");
  const compatibleUfs = ufList.filter((uf) => {
    if (regionSet.size === 0) return true;
    const sample = all.find((m) => m.sg_uf === uf);
    return sample ? regionSet.has(sample.regiao) : false;
  });
  if (compatibleUfs.length !== ufList.length) warnings.push("UF incompatível com a região selecionada foi removida.");
  const ufSet = new Set(compatibleUfs);
  const municipios = next.municipios.filter((code) => {
    const m = byCode.get(code);
    if (!m) return false;
    if (ufSet.size > 0 && !ufSet.has(m.sg_uf)) return false;
    if (regionSet.size > 0 && !regionSet.has(m.regiao)) return false;
    return true;
  });
  if (municipios.length !== next.municipios.length) {
    warnings.push("Município incompatível com os filtros geográficos foi removido.");
  }
  return {
    filters: { ...next, regioes, ufs: compatibleUfs, municipios },
    warnings,
  };
}

export default function App() {
  const [attempt, setAttempt] = useState(0);
  const [socioError, setSocioError] = useState<string | null>(null);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [data, setData] = useState<ReleaseData | null>(null);
  const [index, setIndex] = useState<DatasetIndex | null>(null);
  const [state, setState] = useState<ViewState>({ ...DEFAULT_STATE });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [urlWarnings, setUrlWarnings] = useState<string[]>([]);
  const [hierarchyWarning, setHierarchyWarning] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const mapRef = useRef<HTMLDivElement | null>(null);
  const lastHash = useRef<string>("");
  const firstLoad = useRef(true);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null); setSocioError(null); setManifestError(null);
    loadRelease()
      .then((release) => {
        if (cancelled) return;
        const idx = datasetIndex(release);
        setData(release);
        setIndex(idx);
        loadManifest(release.releaseId)
          .then((manifest) => setData((current) => (!cancelled && current?.releaseId === release.releaseId ? { ...current, manifest } : current)))
          .catch((error) => { if (!cancelled) setManifestError(String(error)); });
        loadSocio(release.releaseId)
          .then((socio) =>
            setData((current) => {
              if (cancelled || !current || current.releaseId !== release.releaseId) return current;
              return {
                ...current,
                socioReady: true,
                municipios: current.municipios.map((municipio) => {
                  const row = socio.get(municipio.cd_ibge);
                  if (!row) return municipio;
                  const { cd_ibge: _code, ...values } = row;
                  return { ...municipio, ...values };
                }),
              };
            }),
          )
          .catch((error) => { if (!cancelled) setSocioError(String(error)); });
        const hash = window.location.hash;
        if (hash && hash.length > 1) {
          const decoded = decodeState(hash, idx);
          setState(decoded.state);
          setUrlWarnings(decoded.warnings);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // Sincroniza estado -> URL com debounce; pushState permite voltar/avançar.
  useEffect(() => {
    if (!data || !index) return;
    const hash = encodeState(state, data.releaseId);
    const timer = window.setTimeout(() => {
      if (window.location.hash !== hash) {
        window.history.pushState(null, "", hash);
        lastHash.current = hash;
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [state, data, index]);

  // URL -> estado (voltar/avançar ou edição manual do hash).
  useEffect(() => {
    if (!index) return;
    const restore = () => {
      if (window.location.hash === lastHash.current) return;
      const requested = new URLSearchParams(window.location.hash.slice(1)).get("release");
      if (requested && requested !== index.releaseId) { window.location.reload(); return; }
      if (window.location.hash.length <= 1) {
        setState(stateWithoutFilters());
        setUrlWarnings([]);
        return;
      }
      const decoded = decodeState(window.location.hash, index);
      setState(decoded.state);
      setUrlWarnings(decoded.warnings);
    };
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    return () => {
      window.removeEventListener("popstate", restore);
      window.removeEventListener("hashchange", restore);
    };
  }, [index]);

  useEffect(() => {
    if (!firstLoad.current || !data) return;
    firstLoad.current = false;
    if (!window.location.hash) {
      window.history.replaceState(null, "", encodeState(state, data.releaseId));
    }
  }, [data, state]);

  const allRows = data?.municipios ?? [];
  const filtered = useMemo(
    () => (data ? filterMunicipios(data.municipios, state.filters) : []),
    [data, state.filters],
  );
  const missing = useMemo(() => missingCoverage(allRows, state.filters), [allRows, state.filters]);
  const queryPending = !data?.socioReady && activeSocioFields(state.filters).length > 0;
  const agg = useMemo(() => aggregate(filtered), [filtered]);
  const sorted = useMemo(
    () => sortMunicipios(filtered, state.ordem.field, state.ordem.order),
    [filtered, state.ordem],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const page = Math.min(state.pag, pages);

  useEffect(() => {
    if (state.pag > pages) setState((s) => ({ ...s, pag: pages }));
  }, [state.pag, pages]);

  const updateFilters = useCallback(
    (next: Filters) => {
      const result = sanitizeFilters(next, allRows);
      setHierarchyWarning(result.warnings.length > 0 ? result.warnings.join(" ") : null);
      setState((s) => ({ ...s, filters: result.filters, pag: 1 }));
    },
    [allRows],
  );

  const addMunicipio = useCallback(
    (code: string) => {
      const m = allRows.find((row) => row.cd_ibge === code);
      if (!m) return;
      const extra: string[] = [];
      let ufs = state.filters.ufs;
      let regioes = state.filters.regioes;
      if (ufs.length > 0 && !ufs.includes(m.sg_uf)) {
        ufs = [];
        extra.push("Filtro de UF incompatível removido");
      }
      if (regioes.length > 0 && !regioes.includes(m.regiao)) {
        regioes = [];
        extra.push("Filtro de região incompatível removido");
      }
      setHierarchyWarning(extra.length > 0 ? `${extra.join("; ")} para selecionar ${m.nome}/${m.sg_uf}.` : null);
      setState((s) => ({
        ...s,
        filters: {
          ...s.filters,
          ufs,
          regioes,
          municipios: s.filters.municipios.includes(code) ? s.filters.municipios : [...s.filters.municipios, code],
        },
        pag: 1,
      }));
    },
    [allRows, state.filters],
  );

  const removeMunicipio = useCallback((code: string) => {
    setState((s) => ({
      ...s,
      filters: { ...s.filters, municipios: s.filters.municipios.filter((c) => c !== code) },
      pag: 1,
    }));
  }, []);

  const toggleMunicipio = useCallback(
    (code: string) => {
      if (state.filters.municipios.includes(code)) removeMunicipio(code);
      else addMunicipio(code);
    },
    [state.filters.municipios, addMunicipio, removeMunicipio],
  );

  const selectUf = useCallback(
    (uf: string) => {
      const ufs = state.filters.ufs.includes(uf)
        ? state.filters.ufs.filter((u) => u !== uf)
        : [...state.filters.ufs, uf];
      updateFilters({ ...state.filters, ufs });
    },
    [state.filters, updateFilters],
  );

  const clearAll = useCallback(() => {
    setHierarchyWarning(null);
    setUrlWarnings([]);
    setState(stateWithoutFilters());
  }, []);

  const copyLink = async () => {
    if (!data) return;
    const link = `${window.location.origin}${window.location.pathname}${encodeState(state, data.releaseId, data.schemaVersion)}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopyStatus("Link copiado.");
    } catch {
      setCopyStatus("Não foi possível copiar automaticamente. Copie o endereço da barra do navegador.");
    }
    window.setTimeout(() => setCopyStatus(null), 4000);
  };

  const exportCsv = () => {
    if (!data) return;
    download(`presidenciais-2026-municipios-${data.releaseId}.csv`, buildCsv(sorted), "text/csv");
  };

  const exportMetadata = () => {
    if (!data) return;
    const metadata = buildMetadata(
      state,
      agg,
      data.releaseId,
      data.schemaVersion,
      [...urlWarnings, ...(hierarchyWarning ? [hierarchyWarning] : [])],
      missing,
    );
    download(
      `presidenciais-2026-metadados-${data.releaseId}.json`,
      JSON.stringify(metadata, null, 2),
      "application/json",
    );
  };

  const showMap = (metric: MapMetric) => {
    setState((s) => ({ ...s, metrica: metric }));
    setTab("overview");
    window.setTimeout(() => mapRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };

  if (loadError) {
    return (
      <main className="center-state">
        <h1>Não foi possível carregar o release</h1>
        <p>{loadError}</p>
        <p>
          O snapshot solicitado não está disponível. Você pode tentar novamente ou abrir explicitamente a versão atual.
          <button onClick={() => setAttempt(a => a+1)}>Tentar novamente</button>
          <a href={window.location.pathname}>Abrir versão atual</a>
        </p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="center-state" aria-live="polite">
        <h1>Carregando o release municipal…</h1>
        <p>Lendo manifesto, municípios, faixas e referência nacional.</p>
      </main>
    );
  }

  const missingGeo = filtered.filter((m) => m.tem_geometria === 0);
  const allWarnings = [...urlWarnings, ...(hierarchyWarning ? [hierarchyWarning] : [])];

  return (
    <div className="app-shell" data-socio-ready={data.socioReady ? "1" : "0"}>
      <a className="skip-link" href="#conteudo">
        Pular para o conteúdo
      </a>
      <header className="app-header">
        <div className="brand">
          <p className="eyebrow">Explorador público · P0 municipal</p>
          <h1>Como mudou a eleição entre os turnos?</h1>
          <p className="subtitle">
            Lula × Flávio Bolsonaro, 1º e 2º turnos. Dados observados; nenhuma identificação individual.
          </p>
        </div>
        <div className="header-meta">
          <span className="release-badge" title={`Schema ${data.schemaVersion}`}>
            {data.releaseId}
          </span>
          <nav aria-label="Seções">
            {(
              [
                ["overview", "Visão geral"],
                ["perguntas", "Perguntas"],
                ["metodologia", "Metodologia"],
              ] as Array<[Tab, string]>
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={tab === id ? "nav-item active" : "nav-item"}
                aria-current={tab === id ? "page" : undefined}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {allWarnings.length > 0 && (
        <div className="warning-banner" role="status">
          <div>
            {allWarnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
          <button
            type="button"
            className="link-button"
            onClick={() => {
              setUrlWarnings([]);
              setHierarchyWarning(null);
            }}
          >
            fechar avisos
          </button>
        </div>
      )}

      {!data.socioReady && (
        <div className="loading-banner" role="status">
          {socioError ? `Falha ao carregar indicadores: ${socioError}` : "Carregando indicadores socioeconômicos…"}
          {socioError && <button onClick={() => setAttempt(a => a+1)}>Tentar novamente</button>}
        </div>
      )}

      {tab === "overview" && !queryPending && <TurnChange agg={agg} nacional={data.nacional} filtered={state.filters.regioes.length + state.filters.ufs.length + state.filters.municipios.length + activeSocioFields(state.filters).length > 0} />}
      <div className="app-body" id="conteudo">
        {tab === "overview" && (
          <>
            <aside className="sidebar">
              <FiltersPanel
                filters={state.filters}
                municipios={allRows}
                faixas={data.faixas}
                onChange={updateFilters}
                onClear={clearAll}
                onAddMunicipio={addMunicipio}
                onRemoveMunicipio={removeMunicipio}
                warning={null}
                socioReady={data.socioReady}
              />
              <div className="actions">
                <button type="button" onClick={copyLink}>
                  Copiar link do recorte
                </button>
                <button type="button" onClick={exportCsv} disabled={!data.socioReady}>
                  Baixar CSV filtrado
                </button>
                <button type="button" onClick={exportMetadata} disabled={!data.socioReady}>
                  Baixar metadados
                </button>
                {!data.socioReady && (
                  <p className="hint" role="status">
                    Downloads ficam disponíveis quando os indicadores socioeconômicos terminarem de carregar.
                  </p>
                )}
                {copyStatus && (
                  <p className="copy-status" role="status">
                    {copyStatus}
                  </p>
                )}
              </div>
            </aside>

            <main className="main-content">
              {queryPending ? <p role="status">{socioError ? "Consulta indisponível até recuperar os indicadores." : "Aguardando indicadores para calcular o recorte salvo."}</p> : <>
              <section className="intro-strip" aria-label="Resumo do recorte">
                <p>
                  <strong>{int(agg.municipios)}</strong> município(s) · <strong>{int(agg.n_unidades)}</strong>{" "}
                  unidades eleitorais · {int(agg.counts.qt_aptos_t2)} aptos no 2º turno · comparecimento{" "}
                  {pct(agg.comparecimento_t2)} · mudança da margem {pp(agg.delta_margem_pp)}
                </p>
                <p className="hint">
                  Unidade: município do território. Exterior aparece só no card oficial. Filtros não alteram o card
                  nacional.
                </p>
              </section>

              <OfficialCard nacional={data.nacional} />
              <OverviewCards agg={agg} />
              <MarginChart rows={filtered} onSelectUf={selectUf} selectedUfs={state.filters.ufs} />

              <div ref={mapRef}>
                <DeferredMap
                  rows={filtered}
                  allRows={allRows}
                  metric={state.metrica}
                  onMetric={(metric) => setState((s) => ({ ...s, metrica: metric }))}
                  selected={state.filters.municipios}
                  onToggle={toggleMunicipio}
                  onClear={() => setState((s) => ({ ...s, filters: { ...s.filters, municipios: [] }, pag: 1 }))}
                />
              </div>

              <section className="coverage" aria-labelledby="cobertura-titulo">
                <h2 id="cobertura-titulo">Cobertura e ausências</h2>
                <p>{missing.universo}</p>
                <ul>{Object.entries(missing.indicadores).map(([field, item]) => <li key={field}>{field}: {int(item.municipios)} municípios, {int(item.unidades)} unidades e {int(item.aptos_t2)} aptos no 2º turno sem informação na base geográfica de {int(missing.base.municipios)} municípios.</li>)}</ul>
                <ul>
                  <li>
                    {int(agg.municipios)} município(s); {int(agg.cobertura.com_geometria)} com geometria e{" "}
                    {int(agg.cobertura.sem_geometria)} sem geometria.
                  </li>
                  <li>
                    {int(agg.cobertura.com_contexto)} com todos os indicadores socioeconômicos;{" "}
                    {int(agg.cobertura.sem_contexto)} sem contexto completo.
                  </li>
                  <li>
                    {int(agg.n_unidades)} unidade(s) eleitoral(is) pareada(s); aptos no 2º turno {int(agg.counts.qt_aptos_t2)}.
                  </li>
                  {missingGeo.length > 0 && (
                    <li className="warning">
                      Sem geometria no recorte: {missingGeo.map((m) => `${m.nome}/${m.sg_uf}`).join(", ")}. Continua
                      na tabela e nos totais.
                    </li>
                  )}
                </ul>
                <p className="hint">
                  “Sem informação” não é zero. Filtros de intervalo excluem ausentes; a categoria explícita permite
                  consultá-los.
                </p>
              </section>

              <MunicipiosTable
                rows={sorted}
                total={filtered.length}
                page={page}
                sort={state.ordem}
                selected={state.filters.municipios}
                onSort={(field: SortField) =>
                  setState((s) => ({
                    ...s,
                    ordem: {
                      field,
                      order: s.ordem.field === field && s.ordem.order === "desc" ? "asc" : "desc",
                    },
                    pag: 1,
                  }))
                }
                onPage={(p) => setState((s) => ({ ...s, pag: p }))}
                onToggle={toggleMunicipio}
              />
              </>}
            </main>
          </>
        )}

        {tab === "perguntas" && queryPending && <p role="status">Consulta aguardando recuperação dos indicadores socioeconômicos.</p>}
        {tab === "perguntas" && !queryPending && (
          <main className="main-content full">
            <Explanations
              rows={filtered}
              agg={agg}
              nacional={data.nacional}
              onShowMap={(metric) => showMap(metric)}
            />
          </main>
        )}

        {tab === "metodologia" && (
          <main className="main-content full">
            {data.manifest ? (
              <Methodology
                agg={agg}
                nacional={data.nacional}
                dicionario={data.dicionario}
                manifest={data.manifest}
                releaseId={data.releaseId}
                schemaVersion={data.schemaVersion}
              />
            ) : (
              <div role="status"><p>{manifestError ? `Falha no manifesto: ${manifestError}` : "Carregando manifesto do release…"}</p>{manifestError && <button onClick={() => setAttempt(a => a+1)}>Tentar novamente</button>}</div>
            )}
          </main>
        )}
      </div>

      <footer className="app-footer">
        <p>
          Fonte eleitoral: TSE, 2026. Socioeconômicos: IBGE Censo 2022, MTE RAIS 2025, MDS/PBF 08/2026. Malha: IBGE
          2022. Projeto descritivo; não identifica eleitores nem recomenda voto.
        </p>
        <p>
          Release {data.releaseId} · schema {data.schemaVersion} ·{" "}
          <a href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/release/${data.releaseId}/manifest.json`}>
            manifesto com hashes
          </a>
        </p>
      </footer>
    </div>
  );
}
