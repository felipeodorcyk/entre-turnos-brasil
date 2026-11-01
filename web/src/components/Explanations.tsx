import type { Aggregate, Municipio, Nacional } from "../types";
import { groupBy } from "../engine/query";
import { int, pct, pp, signedInt } from "../format";

type Props = {
  rows: Municipio[];
  agg: Aggregate;
  nacional: Nacional;
  onShowMap: (metric: "delta_margem_pp" | "comparecimento_t2") => void;
};

export default function Explanations({ rows, agg, nacional, onShowMap }: Props) {
  const ufs = groupBy(rows, "sg_uf").sort((a, b) => b.agg.delta_margem_votos - a.agg.delta_margem_votos);
  const topUf = ufs[0];
  const bottomUf = ufs[ufs.length - 1];
  const topMuns = [...rows]
    .sort((a, b) => (b.qt_lula_t2 - b.qt_flavio_t2 - b.qt_lula_t1 + b.qt_flavio_t1) - (a.qt_lula_t2 - a.qt_flavio_t2 - a.qt_lula_t1 + a.qt_flavio_t1))
    .slice(0, 5);

  return (
    <div className="prose-page">
      <header className="page-head">
        <p className="eyebrow">Perguntas P0</p>
        <h1>Entender a mudança entre os turnos</h1>
        <p>
          Respostas curtas, com o recorte atual, fonte e limite de leitura. Cada número é uma conta sobre contagens
          observadas; nenhuma pergunta abaixo identifica eleitores individualmente.
        </p>
      </header>

      <section aria-labelledby="p1">
        <h2 id="p1">1. Onde a margem mudou?</h2>
        <p>
          No recorte atual ({int(agg.municipios)} municípios), a margem Lula − Flávio passou de{" "}
          <strong>{pp(agg.margem_t1_pp)}</strong> no 1º turno para <strong>{pp(agg.margem_t2_pp)}</strong> no 2º,
          uma mudança de <strong>{pp(agg.delta_margem_pp)}</strong>. O saldo em votos foi de{" "}
          <strong>{signedInt(agg.delta_margem_votos)}</strong>.
        </p>
        {topUf && bottomUf && (
          <p>
            A maior contribuição absoluta veio de <strong>{topUf.key}</strong> (
            {signedInt(topUf.agg.delta_margem_votos)} votos; {pp(topUf.agg.delta_margem_pp)}); a menor, de{" "}
            <strong>{bottomUf.key}</strong> ({signedInt(bottomUf.agg.delta_margem_votos)} votos;{" "}
            {pp(bottomUf.agg.delta_margem_pp)}).
          </p>
        )}
        <button type="button" className="primary" onClick={() => onShowMap("delta_margem_pp")}>
          Ver mudança da margem no mapa
        </button>
        <p className="caveat">
          <strong>Limite:</strong> contribuição absoluta não é crescimento percentual. Um município pode contribuir
          muito em votos e pouco em pontos percentuais, ou o contrário. O mapa mostra o valor municipal; o gráfico
          mostra a soma por UF.
        </p>
        <details>
          <summary>Cinco municípios com maior contribuição para a mudança da margem entre turnos</summary>
          <ul>
            {topMuns.map((m) => (
              <li key={m.cd_ibge}>
                {m.nome}/{m.sg_uf}: {signedInt(m.qt_lula_t2 - m.qt_flavio_t2 - m.qt_lula_t1 + m.qt_flavio_t1)} votos de mudança da margem.
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section aria-labelledby="p2">
        <h2 id="p2">2. Quanto mudou o comparecimento?</h2>
        <p>
          O comparecimento sobre os aptos foi de <strong>{pct(agg.comparecimento_t1)}</strong> no 1º turno para{" "}
          <strong>{pct(agg.comparecimento_t2)}</strong> no 2º, uma mudança de{" "}
          <strong>{pp(agg.delta_comparecimento_pp)}</strong>. A abstenção no 2º turno ficou em{" "}
          <strong>{pct(agg.abstencao_t2)}</strong> dos aptos.
        </p>
        <p>
          O denominador é o eleitorado apto. Por isso o comparecimento não é a mesma coisa que a participação de um
          candidato nos válidos: brancos e nulos entram no comparecimento, mas não nos válidos.
        </p>
        <button type="button" className="primary" onClick={() => onShowMap("comparecimento_t2")}>
          Ver comparecimento no mapa
        </button>
        <p className="caveat">
          <strong>Limite:</strong> a queda da abstenção é um saldo agregado. Não é possível atribuir cada novo
          comparecimento a um candidato, nem converter a redução da abstenção em votos individuais transferidos.
        </p>
      </section>

      <section aria-labelledby="p3">
        <h2 id="p3">3. O que significam os filtros municipais?</h2>
        <p>
          Renda, desocupação, vínculos, Bolsa Família e urbanização são <strong>atributos do município</strong>, não
          do eleitor. Um município tem um valor por indicador; esse valor não é replicado por seção nem somado entre
          municípios. A interface usa esses indicadores para <em>selecionar</em> municípios, não para produzir uma
          média do indicador no recorte.
        </p>
        <ul>
          <li>Renda é a renda domiciliar per capita média do Censo 2022, em reais de 2022.</li>
          <li>Vínculos são vínculos formais no estabelecimento (RAIS 31/12/2025), não trabalhadores únicos residentes.</li>
          <li>PBF é registro de pagamento por 100 domicílios ocupados de 2022 (folha 08/2026), não família única.</li>
          <li>Urbanização é a porcentagem da população urbana no Censo 2022.</li>
          <li>
            Sem filtro, municípios sem informação permanecem. Com intervalo ativo, ausente não satisfaz o intervalo;
            marque “sem informação” para consultá-los.
          </li>
        </ul>
        <p className="caveat">
          <strong>Limite:</strong> associação territorial não identifica decisão individual. Um padrão entre
          municípios com mais PBF e voto não prova que um eleitor do programa votou de determinada forma.
        </p>
      </section>

      <section aria-labelledby="p4">
        <h2 id="p4">4. O que este P0 não responde</h2>
        <p>
          Seções eleitorais, locais de votação, entorno de 1 km, horários de encerramento, modelos ajustados e
          origens estimadas de votos são P1 e não estão incluídos nesta versão. Não há botão simulando essas análises.
        </p>
        <p>
          O card nacional oficial resume o país inteiro, incluindo o exterior ({nacional.unidades} unidades). Ele é
          referência e não muda com os filtros; os cards do recorte usam apenas municípios do território.
        </p>
      </section>
    </div>
  );
}
