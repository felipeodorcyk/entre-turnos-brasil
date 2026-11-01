import { useEffect, useMemo, useRef, useState } from "react";
import type { ExpressionSpecification, Map as MapLibreMap, MapGeoJSONFeature } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import type { MapMetric, Municipio } from "../types";
import { GEO_MUNICIPIOS, GEO_UFS, geoAsset } from "../data/load";
import { METRIC_LABEL, METRIC_UNIT, fmtMetric, int, metricValue, pct } from "../format";
import {geographicRows,type Granularity} from "../engine/geography";
import { derived } from "../engine/query";

const METRICS: MapMetric[] = [
  "delta_comparecimento_pp",
  "participacao_lula_t1",
  "participacao_flavio_t1",
  "comparecimento_t1",
  "margem_t1",
  "delta_participacao_lula_pp",
  "delta_participacao_flavio_pp",

  "delta_margem_pp",
  "delta_margem_votos",
  "participacao_lula_t2",
  "participacao_flavio_t2",
  "comparecimento_t2",
  "margem_t2",
  "renda_pc",
  "pbf",
];

const SEQUENTIAL = ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c"];
const DIVERGING = ["#086434", "#28935a", "#78bb91", "#c8e5d2", "#f7f7f7", "#f6d0d2", "#e88b91", "#d74b55", "#a71927"];

type Scale = {
  breaks: number[];
  colors: string[];
  diverging: boolean;
};

function quantile(values: number[], q: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] !== undefined ? sorted[base] + rest * (sorted[base + 1] - sorted[base]) : sorted[base];
}

export function scaleFor(metric: MapMetric, allRows: Municipio[]): Scale {
  const values = allRows
    .map((row) => metricValue(row, metric))
    .filter((v): v is number => v !== null && Number.isFinite(v));
  if (metric.startsWith("participacao_") || metric.startsWith("comparecimento_")) {
    const breaks = Array.from({ length: 8 }, (_, i) => (100 * i) / 7);
    return { breaks, colors: SEQUENTIAL, diverging: false };
  }
  if (metric === "delta_comparecimento_pp" || metric.startsWith("delta_participacao_") || metric === "margem_t1" || metric === "delta_margem_pp" || metric === "delta_margem_votos" || metric === "margem_t2") {
    const max = Math.max(metric.startsWith("margem_") ? 100 : 0.5, quantile(values.map(Math.abs), 0.98));
    const breaks = Array.from({ length: DIVERGING.length }, (_, i) => -max + (2 * max * i) / (DIVERGING.length - 1));
    return { breaks, colors: DIVERGING, diverging: true };
  }
  const max = Math.max(1, quantile(values, 0.95));
  const breaks = Array.from({ length: SEQUENTIAL.length }, (_, i) => (max * i) / (SEQUENTIAL.length - 1));
  return { breaks, colors: SEQUENTIAL, diverging: false };
}

function legendLabel(metric: MapMetric, value: number): string {
  if (metric === "delta_margem_votos") return int(Math.round(value));
  if (metric === "renda_pc") return `R$ ${Math.round(value).toLocaleString("pt-BR")}`;
  if (metric === "pbf") return Math.round(value).toLocaleString("pt-BR");
  if (metric === "delta_comparecimento_pp" || metric.startsWith("delta_participacao_") || metric === "margem_t1" || metric === "delta_margem_pp" || metric === "margem_t2") {
    return `${value.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} p.p.`;
  }
  return `${value.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}%`;
}

type Tooltip = {
  x: number;
  y: number;
  title: string;
  metric: string;
  detail: string;
};

type Props = {
  inspectMode?: boolean;
  granularity?: Granularity;
  rows: Municipio[];
  allRows: Municipio[];
  metric: MapMetric;
  onMetric: (metric: MapMetric) => void;
  selected: string[];
  onToggle: (code: string) => void;
  onClear: () => void;
};

export default function MapView({ inspectMode = false, granularity="municipal", rows, allRows, metric, onMetric, selected, onToggle, onClear }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const baseGeoRef = useRef<{ features: Array<{ properties?: Record<string, unknown>; [key: string]: unknown }> } | null>(null);
  const loadedRef = useRef(false);
  const hoverRef = useRef<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);

  const displayRows=useMemo(()=>geographicRows(rows,allRows,granularity),[rows,allRows,granularity]);
  const scaleRows=useMemo(()=>{const rs=geographicRows(allRows,allRows,granularity);return granularity==="municipal"?rs:[...new Map(rs.map(r=>[r.nome,r])).values()];},[allRows,granularity]);
  const scale = useMemo(() => scaleFor(metric, scaleRows), [metric, scaleRows]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const rowsByCode = useMemo(() => new Map(displayRows.map((row) => [row.cd_ibge, row])), [displayRows]);
  const allByCode = useMemo(() => new Map(allRows.map((row) => [row.cd_ibge, row])), [allRows]);

  // Handlers do mapa são registrados uma vez; refs mantêm o estado mais recente.
  const onToggleRef = useRef(onToggle);
  const metricRef = useRef(metric);
  const rowsByCodeRef = useRef(rowsByCode);
  const allByCodeRef = useRef(allByCode);
  useEffect(() => {
    onToggleRef.current = onToggle;
  }, [onToggle]);
  useEffect(() => {
    metricRef.current = metric;
  }, [metric]);
  useEffect(() => {
    rowsByCodeRef.current = rowsByCode;
  }, [rowsByCode]);
  useEffect(() => {
    allByCodeRef.current = allByCode;
  }, [allByCode]);

  // Inicialização única (por tentativa): importa MapLibre sob demanda.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);
    loadedRef.current = false;
    const controller = new AbortController();

    (async () => {
      try {
        const maplibregl = await import("maplibre-gl");
        if (cancelled || !containerRef.current) return;
        maplibregl.setWorkerUrl(workerUrl);
        const [muniGeo, ufGeo] = await Promise.all([
          fetch(geoAsset(GEO_MUNICIPIOS), { signal: controller.signal }).then((r) => {
            if (!r.ok) throw new Error(`malha municipal: HTTP ${r.status}`);
            return r.json();
          }),
          fetch(geoAsset(GEO_UFS), { signal: controller.signal }).then((r) => {
            if (!r.ok) throw new Error(`malha de UFs: HTTP ${r.status}`);
            return r.json();
          }),
        ]);
        if (cancelled || !containerRef.current) return;

        baseGeoRef.current = muniGeo;
        const map = new maplibregl.Map({
          container: containerRef.current,
          cooperativeGestures: inspectMode,
          style: {
            version: 8,
            sources: {},
            layers: [{ id: "bg", type: "background", paint: { "background-color": "#f2f3ef" } }],
          },
          center: [-54, -15],
          zoom: 3,
          minZoom: 2,
          maxZoom: 9,
          renderWorldCopies: false,
          attributionControl: false,
        });
        mapRef.current = map;
        (window as unknown as { __map?: MapLibreMap }).__map = map;
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        map.addControl(new maplibregl.ScaleControl({ unit: "metric", maxWidth: 110 }), "bottom-left");

        map.on("load", () => {
          if (cancelled) return;
          map.addSource("municipios", { type: "geojson", data: muniGeo });
          map.addSource("ufs", { type: "geojson", data: ufGeo });
          map.addLayer({
            id: "muni-fill",
            type: "fill",
            source: "municipios",
            paint: { "fill-color": "#dddddd", "fill-opacity": 0.92 },
          });
          map.addLayer({
            id: "muni-border",
            type: "line",
            source: "municipios",
            paint: { "line-color": "rgba(255,255,255,0.65)", "line-width": 0.35 },
          });
          map.addLayer({
            id: "uf-border",
            type: "line",
            source: "ufs",
            paint: { "line-color": "#4a4a4a", "line-width": 1.2 },
          });
          map.addLayer({
            id: "selected-line",
            type: "line",
            source: "municipios",
            paint: { "line-color": "#111111", "line-width": 2.4 },
            filter: ["==", ["get", "cd"], ""],
          });
          map.fitBounds(
            [
              [-74.5, -34.5],
              [-33.5, 6.5],
            ],
            { padding: 18, animate: false },
          );
          loadedRef.current = true;
          setStatus("ready");

          map.on("mousemove", "muni-fill", (event) => {
            const feature = event.features?.[0] as MapGeoJSONFeature | undefined;
            if (!feature) return;
            map.getCanvas().style.cursor = "pointer";
            hoverRef.current = String(feature.properties?.cd ?? "");
            const code = hoverRef.current;
            const row = rowsByCodeRef.current.get(code);
            if (!row) {
              setTooltip(null);
              return;
            }
            const d = derived(row);
            const value = metricValue(row, metricRef.current);
            setTooltip({
              x: event.point.x,
              y: event.point.y,
              title: `${row.nome}${row.nome===row.regiao||row.nome===row.sg_uf?"":` / ${row.sg_uf}`}`,
              metric: `${METRIC_LABEL[metricRef.current]}: ${fmtMetric(metricRef.current, value)}`,
              detail: `Aptos no 2º turno ${int(row.qt_aptos_t2)} · comparecimento ${pct(d.comparecimento_t2)} · Lula ${pct(
                d.participacao_lula_t2,
              )} · Flávio ${pct(d.participacao_flavio_t2)}`,
            });
          });
          map.on("mouseleave", "muni-fill", () => {
            map.getCanvas().style.cursor = "";
            hoverRef.current = null;
            setTooltip(null);
          });
          map.on("click", "muni-fill", (event) => {
            const feature = event.features?.[0] as MapGeoJSONFeature | undefined;
            const code = feature?.properties?.cd;
            if (code) onToggleRef.current(String(code));
          });
        });
        map.on("error", (event) => {
          // Erros de tile não existem aqui; falhas de malha já são tratadas no fetch.
          if (!loadedRef.current) setError(event.error?.message ?? "Falha ao inicializar o mapa.");
        });
      } catch (err) {
        if (cancelled) return;
        setStatus("error");
        setError(err instanceof Error ? err.message : String(err));
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      mapRef.current?.remove();
      mapRef.current = null;
      loadedRef.current = false;
    };
    // onToggle é estável o suficiente para o ciclo de vida do mapa; recriar a cada render seria pior.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  // Atualiza valores e escopo sem recriar o mapa.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || status !== "ready") return;
    const source = map.getSource("municipios");
    if (!source || !("setData" in source)) return;
    const base = baseGeoRef.current;
    if (!base) return;
    const features = base.features.map((feature) => {
      const cd = String((feature.properties as Record<string, unknown>)?.codarea ?? "");
      const row = rowsByCode.get(cd) ?? allByCode.get(cd);
      const inScope = rowsByCode.has(cd) ? 1 : 0;
      const value = row ? metricValue(row, metric) : null;
      return {
        ...feature,
        properties: {
          ...(feature.properties ?? {}),
          cd,
          inScope,
          novalue: value === null ? 1 : 0,
          value: value === null ? 0 : value,
        },
      };
    });
    (source as unknown as { setData: (data: unknown) => void }).setData({ type: "FeatureCollection", features });

    const colorExpression: ExpressionSpecification = [
      "case",
      ["==", ["get", "inScope"], 0],
      "#e4e4e0",
      ["==", ["get", "novalue"], 1],
      "#b8b8b4",
      [
        "interpolate",
        ["linear"],
        ["get", "value"],
        ...scale.breaks.flatMap((b, i) => [b, scale.colors[Math.min(i, scale.colors.length - 1)]]),
      ],
    ];
    map.setPaintProperty("muni-fill", "fill-color", colorExpression);
    map.setLayoutProperty("muni-border","visibility",granularity==="municipal"?"visible":"none");
    map.setLayoutProperty("uf-border","visibility",granularity==="regional"?"none":"visible");
  }, [rows, allByCode, rowsByCode, metric, scale, status,granularity]);

  // Seleção: apenas contorno; zoom e pan nunca alteram a amostra.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || status !== "ready") return;
    const expression: ExpressionSpecification = [
      "in",
      ["get", "cd"],
      ["literal", selected],
    ];
    if (map.getLayer("selected-line")) map.setFilter("selected-line", expression);
  }, [selected, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (!inspectMode || !map || status !== "ready" || selected.length !== 1) return;
    const feature = baseGeoRef.current?.features.find(f => String(f.properties?.cd) === selected[0]);
    if (!feature) return;
    const points: number[][] = [];
    const visit = (v: unknown): void => { if (!Array.isArray(v)) return; if (typeof v[0] === "number") points.push(v as number[]); else v.forEach(visit); };
    visit((feature.geometry as {coordinates: unknown})?.coordinates);
    if (points.length) map.fitBounds([[Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1]))],[Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))]], {padding:55,maxZoom:8,duration:matchMedia("(prefers-reduced-motion: reduce)").matches?0:500});
  }, [inspectMode, selected, status]);

  const legend = useMemo(
    () =>
      scale.colors.map((color, i) => ({
        color,
        label: legendLabel(metric, scale.breaks[i]),
      })),
    [scale, metric],
  );

  const missingGeometry = allRows.filter((row) => row.tem_geometria === 0 && selectedSet.has(row.cd_ibge));

  return (
    <section className="map-section" aria-labelledby="mapa-titulo">
      <div className="section-head map-head">
        <div>
          <h2 id="mapa-titulo">Mapa municipal</h2>
          <p className="hint">
            {inspectMode ? "Toque em uma cidade para descobrir o que mudou. O clique não altera o recorte." : "Arrastar e ampliar não filtram; clicar em um município seleciona ou remove."}
          </p>
        </div>
        {!inspectMode && <label className="metric-select">
          <span>{inspectMode ? "Ver no mapa" : "Camada"}</span>
          <select value={metric} onChange={(event) => onMetric(event.target.value as MapMetric)}>
            {METRICS.map((m) => (
              <option key={m} value={m}>
                {METRIC_LABEL[m]}
              </option>
            ))}
          </select>
        </label>}
      </div>

      <div className="map-shell">
        <div
          ref={containerRef}
          className="map-canvas"
          role="region"
          aria-label={`Mapa municipal: ${METRIC_LABEL[metric]}. Use a busca e a tabela como alternativa acessível.`}
        />
        {status === "loading" && <p className="map-overlay">Carregando mapa e malha municipal…</p>}
        {status === "error" && (
          <div className="map-overlay error" role="alert">
            <strong>O mapa não carregou.</strong>
            <p>{error}</p>
            <p>A tabela abaixo continua completa e funcional.</p>
            <button type="button" onClick={() => setAttempt((n) => n + 1)}>
              Tentar novamente
            </button>
          </div>
        )}
        {tooltip && status === "ready" && (
          <div className="map-tooltip" style={{ left: tooltip.x + 14, top: tooltip.y + 14 }} role="presentation">
            <strong>{tooltip.title}</strong>
            <span>{tooltip.metric}</span>
            <small>{tooltip.detail}</small>
          </div>
        )}
        <div className="map-legend" tabIndex={0} role="region" aria-label="Legenda do mapa">
          <p className="legend-title">{METRIC_LABEL[metric]}</p>
          <ul>
            {legend.map((item) => (
              <li key={item.label}>
                <span className="swatch" style={{ background: item.color }} aria-hidden="true" />
                {item.label}
              </li>
            ))}
            <li>
              <span className="swatch nodata" aria-hidden="true" />
              sem dado
            </li>
            <li>
              <span className="swatch out" aria-hidden="true" />
              fora do recorte
            </li>
          </ul>
          <p className="legend-unit">{METRIC_UNIT[metric]}</p>
        </div>
      </div>

      <div className="map-footer">
        <p>
          Malha: IBGE, API de malhas, municípios 2022, qualidade intermediária. Licença e atribuição a confirmar
          antes de publicação externa.
        </p>
        {missingGeometry.length > 0 && (
          <p className="warning">
            {missingGeometry.length} município(s) selecionado(s) sem geometria 2022 ({missingGeometry[0].nome}/
            {missingGeometry[0].sg_uf}): continuam na tabela e nos totais, mas não aparecem no mapa.
          </p>
        )}
        {selected.length > 0 && (
          <p>
            {selected.length} município(s) selecionado(s).{" "}
            <button type="button" className="link-button" onClick={onClear}>
              Limpar seleção de municípios
            </button>
          </p>
        )}
        <p className="sr-only" aria-live="polite">
          {selected.length} municípios selecionados no mapa.
        </p>
      </div>
    </section>
  );
}
