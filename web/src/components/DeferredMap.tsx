import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { MapMetric, Municipio } from "../types";

const MapView = lazy(() => import("./MapView"));

type Props = {
  rows: Municipio[];
  allRows: Municipio[];
  metric: MapMetric;
  onMetric: (metric: MapMetric) => void;
  selected: string[];
  onToggle: (code: string) => void;
  onClear: () => void;
};

/**
 * Adia o chunk do MapLibre até a seção do mapa se aproximar da viewport.
 * O mapa é uma alternativa visual; a tabela e a busca funcionam sem ele.
 */
export default function DeferredMap(props: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref}>
      {visible ? (
        <Suspense fallback={<p className="map-placeholder">Carregando componente do mapa…</p>}>
          <MapView {...props} />
        </Suspense>
      ) : (
        <p className="map-placeholder">
          O mapa é carregado sob demanda ao chegar nesta seção. A busca e a tabela já estão disponíveis.
        </p>
      )}
    </div>
  );
}
