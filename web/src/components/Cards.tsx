import type { Aggregate, Nacional } from "../types";
import { int, pct, pp, signedInt } from "../format";

function Delta({ value, unit = "p.p." }: { value: number | null; unit?: string }) {
  if (value === null) return <span className="delta neutral">não calculável</span>;
  const direction = value > 0 ? "aumento" : value < 0 ? "redução" : "estável";
  return (
    <span className={`delta ${value > 0 ? "up" : value < 0 ? "down" : "neutral"}`}>
      <span aria-hidden="true">{value > 0 ? "▲" : value < 0 ? "▼" : "■"}</span> {direction} de{" "}
      {unit === "votos" ? signedInt(value) : pp(Math.abs(value))}
    </span>
  );
}

export function OverviewCards({ agg }: { agg: Aggregate }) {
  const brancosNulos =
    agg.brancos_share_t2 === null || agg.nulos_share_t2 === null ? null : agg.brancos_share_t2 + agg.nulos_share_t2;
  return (
    <section aria-labelledby="cards-titulo" className="cards-section">
      <div className="section-head">
        <h2 id="cards-titulo">Recorte selecionado</h2>
        <p className="hint">
          Todos os cards usam o mesmo conjunto de municípios. Razões calculadas sobre a soma das contagens, não média
          de percentuais municipais.
        </p>
      </div>
      <div className="cards">
        <article className="card">
          <h3>Lula — válidos</h3>
          <dl>
            <div>
              <dt>1º turno</dt>
              <dd>{pct(agg.participacao_lula_t1)}</dd>
            </div>
            <div>
              <dt>2º turno</dt>
              <dd className="strong">{pct(agg.participacao_lula_t2)}</dd>
            </div>
          </dl>
          <Delta value={agg.delta_participacao_lula_pp} />
          <p className="card-note">
            {int(agg.counts.qt_lula_t2)} votos no 2º turno · denominador: {int(agg.counts.qt_votos_validos_t2)} válidos
          </p>
        </article>

        <article className="card">
          <h3>Flávio Bolsonaro — válidos</h3>
          <dl>
            <div>
              <dt>1º turno</dt>
              <dd>{pct(agg.participacao_flavio_t1)}</dd>
            </div>
            <div>
              <dt>2º turno</dt>
              <dd className="strong">{pct(agg.participacao_flavio_t2)}</dd>
            </div>
          </dl>
          <Delta value={agg.delta_participacao_flavio_pp} />
          <p className="card-note">
            {int(agg.counts.qt_flavio_t2)} votos no 2º turno · denominador: {int(agg.counts.qt_votos_validos_t2)} válidos
          </p>
        </article>

        <article className="card">
          <h3>Margem Lula − Flávio</h3>
          <dl>
            <div>
              <dt>1º turno</dt>
              <dd>{pp(agg.margem_t1_pp)}</dd>
            </div>
            <div>
              <dt>2º turno</dt>
              <dd className="strong">{pp(agg.margem_t2_pp)}</dd>
            </div>
          </dl>
          <Delta value={agg.delta_margem_pp} />
          <p className="card-note">
            Saldo de votos no 2º turno − 1º turno: {signedInt(agg.delta_margem_votos)}. É conta observável, não transferência
            individual de eleitores.
          </p>
        </article>

        <article className="card">
          <h3>Comparecimento — aptos</h3>
          <dl>
            <div>
              <dt>1º turno</dt>
              <dd>{pct(agg.comparecimento_t1)}</dd>
            </div>
            <div>
              <dt>2º turno</dt>
              <dd className="strong">{pct(agg.comparecimento_t2)}</dd>
            </div>
          </dl>
          <Delta value={agg.delta_comparecimento_pp} />
          <p className="card-note">
            {int(agg.counts.qt_comparecimento_t2)} comparecimentos · {int(agg.counts.qt_aptos_t2)} aptos no 2º turno
          </p>
        </article>

        <article className="card">
          <h3>Brancos + nulos</h3>
          <p className="big">{pct(brancosNulos)}</p>
          <p className="card-note">
            do comparecimento no 2º turno · {int(agg.counts.qt_votos_brancos_t2)} brancos e{" "}
            {int(agg.counts.qt_votos_nulos_t2)} nulos
          </p>
          <p className="card-note">Não são votos em candidato e entram no denominador do comparecimento, não no de válidos.</p>
        </article>

        <article className="card">
          <h3>Abstenção — aptos</h3>
          <p className="big">{pct(agg.abstencao_t2)}</p>
          <p className="card-note">
            {int(agg.counts.qt_abstencoes_t2)} abstenções no 2º turno · {int(agg.counts.qt_aptos_t2)} aptos
          </p>
          <p className="card-note">Nunca imputada como voto em um candidato.</p>
        </article>
      </div>
    </section>
  );
}

export function OfficialCard({ nacional }: { nacional: Nacional }) {
  const { t1, t2 } = nacional.totais;
  const turnout1 = t1.aptos > 0 ? t1.comparecimento / t1.aptos : null;
  const turnout2 = t2.aptos > 0 ? t2.comparecimento / t2.aptos : null;
  const validos = t2.validos_t2;
  const lula = validos ? t2.lula / validos : null;
  const flavio = validos ? t2.flavio / validos : null;
  const excecao = nacional.excecoes.aptos_sem_comparecimento_abstencao_t2;
  return (
    <aside className="official-card" aria-labelledby="oficial-titulo">
      <div>
        <p className="eyebrow">Referência nacional</p>
        <h2 id="oficial-titulo">Brasil oficial — inclui exterior</h2>
        <p className="hint">
          Fonte: {nacional.fonte}. {nacional.unidades} unidades, {nacional.metricas_por_unidade_turno} métricas
          conferidas com diferença zero. Este card <strong>não</strong> acompanha os filtros.
        </p>
      </div>
      <dl className="official-grid">
        <div>
          <dt>Comparecimento 1º turno</dt>
          <dd>{pct(turnout1)}</dd>
        </div>
        <div>
          <dt>Comparecimento 2º turno</dt>
          <dd className="strong">{pct(turnout2)}</dd>
        </div>
        <div>
          <dt>Lula 2º turno (válidos)</dt>
          <dd>{pct(lula)}</dd>
        </div>
        <div>
          <dt>Flávio 2º turno (válidos)</dt>
          <dd>{pct(flavio)}</dd>
        </div>
        <div>
          <dt>Aptos no 2º turno</dt>
          <dd>{int(t2.aptos)}</dd>
        </div>
        <div>
          <dt>Comparecimento 2º turno</dt>
          <dd>{int(t2.comparecimento)}</dd>
        </div>
        <div>
          <dt>Abstenções 2º turno</dt>
          <dd>{int(t2.abstencoes)}</dd>
        </div>
        <div>
          <dt>Lula / Flávio 2º turno</dt>
          <dd>
            {int(t2.lula)} / {int(t2.flavio)}
          </dd>
        </div>
      </dl>
      <p className="card-note">
        {excecao > 0
          ? `${int(excecao)} aptos do exterior em seções não instaladas não têm comparecimento nem abstenção; por isso aptos ≠ comparecimento + abstenções neste card. `
          : ""}
        O recorte do mapa e da tabela é territorial e pode diferir deste total.
      </p>
    </aside>
  );
}
