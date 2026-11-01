import { useMemo } from "react";
import type { Municipio } from "../types";
import { groupBy } from "../engine/query";
import { int, pp, signedInt } from "../format";

type Props = {
  rows: Municipio[];
  onSelectUf: (uf: string) => void;
  selectedUfs: string[];
};

export default function MarginChart({ rows, onSelectUf, selectedUfs }: Props) {
  const groups = useMemo(
    () =>
      groupBy(rows, "sg_uf")
        .filter((g) => g.agg.municipios > 0)
        .sort((a, b) => b.agg.delta_margem_votos - a.agg.delta_margem_votos),
    [rows],
  );
  const max = Math.max(1, ...groups.map((g) => Math.abs(g.agg.delta_margem_votos)));

  return (
    <section className="chart-section" aria-labelledby="grafico-margem">
      <div className="section-head">
        <h2 id="grafico-margem">Mudança da margem por UF</h2>
        <p className="hint">
          Saldo de votos: (Lula − Flávio) no 2º turno menos (Lula − Flávio) no 1º turno. Barras para a direita
          favorecem Lula; para a esquerda, Flávio. Clique em uma UF para filtrar.
        </p>
      </div>
      {groups.length === 0 ? (
        <p className="empty">Nenhum município no recorte. Ajuste ou limpe os filtros.</p>
      ) : (
        <>
          <ul className="bars" aria-label="Mudança da margem por UF, em votos">
            {groups.map((g) => {
              const value = g.agg.delta_margem_votos;
              const width = (Math.abs(value) / max) * 50;
              const active = selectedUfs.includes(g.key);
              return (
                <li key={g.key}>
                  <button
                    type="button"
                    className={`bar-row ${active ? "active" : ""}`}
                    onClick={() => onSelectUf(g.key)}
                    aria-pressed={active}
                    title={`${g.key}: ${signedInt(value)} votos; ${pp(g.agg.delta_margem_pp)}`}
                  >
                    <span className="bar-label">{g.key}</span>
                    <span className="bar-track" aria-hidden="true">
                      <span
                        className={`bar ${value >= 0 ? "positive" : "negative"}`}
                        style={{
                          width: `${width}%`,
                          left: value >= 0 ? "50%" : `${50 - width}%`,
                        }}
                      />
                      <span className="bar-zero" />
                    </span>
                    <span className="bar-value">
                      <strong>{signedInt(value)}</strong>
                      <small>{pp(g.agg.delta_margem_pp)}</small>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="caveat">
            <strong>Limite de leitura:</strong> associação territorial não identifica a decisão individual de eleitores.
            O saldo contábil não mostra de quem vieram os votos.
          </p>
          <details>
            <summary>Tabela alternativa do gráfico</summary>
            <div className="table-scroll">
              <table>
                <caption>Mudança da margem por UF no recorte</caption>
                <thead>
                  <tr>
                    <th scope="col">UF</th>
                    <th scope="col" className="num">Municípios</th>
                    <th scope="col" className="num">Δ margem (votos)</th>
                    <th scope="col" className="num">Δ margem (p.p.)</th>
                    <th scope="col" className="num">Lula 2º turno</th>
                    <th scope="col" className="num">Flávio 2º turno</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.key}>
                      <th scope="row">{g.key}</th>
                      <td className="num">{int(g.agg.municipios)}</td>
                      <td className="num">{signedInt(g.agg.delta_margem_votos)}</td>
                      <td className="num">{pp(g.agg.delta_margem_pp)}</td>
                      <td className="num">{int(g.agg.counts.qt_lula_t2)}</td>
                      <td className="num">{int(g.agg.counts.qt_flavio_t2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
