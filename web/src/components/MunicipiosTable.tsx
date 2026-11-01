import type { Municipio, SortField, SortOrder } from "../types";
import { derived } from "../engine/query";
import { EMPTY, fmtSocio, int, money, pct, pp, signedInt } from "../format";

const PAGE_SIZE = 50;

const COLUMNS: Array<{ field: SortField | null; label: string; numeric?: boolean; title?: string }> = [
  { field: "nome", label: "Município" },
  { field: "sg_uf", label: "UF" },
  { field: null, label: "Região" },
  { field: "qt_aptos_t2", label: "Aptos no 2º turno", numeric: true },
  { field: "comparecimento_t2", label: "Comparec. 2º turno", numeric: true },
  { field: "participacao_lula_t2", label: "Lula 2º turno", numeric: true },
  { field: "participacao_flavio_t2", label: "Flávio 2º turno", numeric: true },
  { field: null, label: "Margem 2º turno", numeric: true },
  { field: "delta_margem_pp", label: "Δ margem", numeric: true },
  { field: null, label: "Δ votos", numeric: true },
  { field: "renda_pc", label: "Renda", numeric: true },
  { field: "pbf", label: "PBF", numeric: true },
];

type Props = {
  rows: Municipio[];
  total: number;
  page: number;
  sort: { field: SortField; order: SortOrder };
  selected: string[];
  onSort: (field: SortField) => void;
  onPage: (page: number) => void;
  onToggle: (code: string) => void;
};

export default function MunicipiosTable({
  rows,
  total,
  page,
  sort,
  selected,
  onSort,
  onPage,
  onToggle,
}: Props) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const safePage = Math.min(page, pages);
  const start = (safePage - 1) * PAGE_SIZE;
  const visible = rows.slice(start, start + PAGE_SIZE);
  const selectedSet = new Set(selected);

  return (
    <section className="table-section" aria-labelledby="tabela-titulo">
      <div className="section-head">
        <h2 id="tabela-titulo">Municípios do recorte</h2>
        <p className="hint">
          A ordenação e a paginação mudam apenas a exibição; totais e cards continuam sobre todos os municípios
          filtrados. {int(total)} município(s).
        </p>
      </div>
      <div className="table-scroll">
        <table className="municipios-table">
          <caption className="sr-only">
            Municípios filtrados, com contagens e indicadores. Clique no nome para selecionar ou remover o município.
          </caption>
          <thead>
            <tr>
              {COLUMNS.map((col) => {
                const active = col.field !== null && sort.field === col.field;
                const ariaSort = active ? (sort.order === "asc" ? "ascending" : "descending") : "none";
                return (
                  <th key={col.label} scope="col" className={col.numeric ? "num" : ""} aria-sort={ariaSort}>
                    {col.field ? (
                      <button type="button" className="sort-button" onClick={() => onSort(col.field!)}>
                        {col.label}
                        <span aria-hidden="true">{active ? (sort.order === "asc" ? " ↑" : " ↓") : " ↕"}</span>
                      </button>
                    ) : (
                      col.label
                    )}
                  </th>
                );
              })}
              <th scope="col">Cobertura</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="empty">
                  Nenhum município no recorte. Limpe ou ajuste os filtros.
                </td>
              </tr>
            )}
            {visible.map((row) => {
              const d = derived(row);
              const isSelected = selectedSet.has(row.cd_ibge);
              return (
                <tr key={row.cd_ibge} className={isSelected ? "selected" : ""}>
                  <th scope="row">
                    <button
                      type="button"
                      className="row-select"
                      aria-pressed={isSelected}
                      onClick={() => onToggle(row.cd_ibge)}
                      title={isSelected ? "Remover da seleção" : "Selecionar município"}
                    >
                      {row.nome}
                    </button>
                  </th>
                  <td>{row.sg_uf}</td>
                  <td>{row.regiao}</td>
                  <td className="num">{int(row.qt_aptos_t2)}</td>
                  <td className="num">{pct(d.comparecimento_t2)}</td>
                  <td className="num">{pct(d.participacao_lula_t2)}</td>
                  <td className="num">{pct(d.participacao_flavio_t2)}</td>
                  <td className="num">{pp(d.margem_t2_pp)}</td>
                  <td className="num">{pp(d.delta_margem_pp)}</td>
                  <td className="num">{signedInt(d.delta_margem_votos)}</td>
                  <td className="num">{money(row.renda_pc)}</td>
                  <td className="num">{fmtSocio("pbf", row.pbf)}</td>
                  <td>
                    {row.tem_geometria === 0 && <span className="badge">sem geometria</span>}
                    {row.tem_contexto === 0 && <span className="badge">sem contexto</span>}
                    {row.tem_geometria === 1 && row.tem_contexto === 1 && <span className="muted">completa</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <nav className="pagination" aria-label="Paginação da tabela">
        <button type="button" onClick={() => onPage(1)} disabled={safePage <= 1}>
          Primeira
        </button>
        <button type="button" onClick={() => onPage(safePage - 1)} disabled={safePage <= 1}>
          Anterior
        </button>
        <span>
          Página {safePage} de {pages}
          {total > 0 ? ` · ${int(start + 1)}–${int(Math.min(start + PAGE_SIZE, total))}` : ""}
        </span>
        <button type="button" onClick={() => onPage(safePage + 1)} disabled={safePage >= pages}>
          Próxima
        </button>
        <button type="button" onClick={() => onPage(pages)} disabled={safePage >= pages}>
          Última
        </button>
      </nav>
      <p className="hint">{EMPTY} indica valor não calculável ou informação ausente, nunca zero.</p>
    </section>
  );
}

export { PAGE_SIZE };
