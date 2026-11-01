import type { Aggregate, Dicionario, Nacional, ReleaseManifest } from "../types";
import { int, pct, pp, signedInt } from "../format";
import { FEATURES, FEATURE_LABELS } from "../config/features";

type Props = {
  agg: Aggregate;
  nacional: Nacional;
  dicionario: Dicionario;
  manifest: ReleaseManifest;
  releaseId: string;
  schemaVersion: string;
};

const GLOSSARY: Array<[string, string]> = [
  ["Aptos", "Eleitorado apto a votar no turno, incluindo quem não compareceu."],
  ["Comparecimento", "Comparecimentos somados ÷ aptos somados. Brancos e nulos entram no comparecimento."],
  ["Abstenção", "Abstenções somadas ÷ aptos somados. Nunca é imputada como voto em candidato."],
  ["Válidos", "Votos válidos para presidente no turno. No 2º turno, Lula + Flávio = válidos."],
  ["Participação", "Votos do candidato ÷ válidos. Não é % do comparecimento nem % dos aptos."],
  ["Margem", "Participação de Lula − participação de Flávio, em pontos percentuais (p.p.)."],
  ["p.p.", "Ponto percentual: diferença aritmética entre duas porcentagens. Não é variação relativa."],
  ["Universo pareado territorial", "Municípios brasileiros com unidades pareadas entre os dois turnos; exclui o exterior."],
  ["Referência oficial", "Total do TSE por UF e turno, incluindo o exterior. É um universo distinto do territorial."],
  ["Não agregável", "Indicador municipal que não deve ser somado nem virar média do recorte."],
];

export default function Methodology({ agg, nacional, dicionario, manifest, releaseId, schemaVersion }: Props) {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  const releaseUrl = `${base}/release/${releaseId}`;
  return (
    <div className="prose-page">
      <header className="page-head">
        <p className="eyebrow">Metodologia e downloads</p>
        <h1>Como os números são calculados</h1>
        <p>
          Esta versão é um explorador descritivo dos dois turnos presidenciais de 2026, no grão municipal. Não
          identifica eleitores, não estima transferência individual e não produz recomendação de campanha.
        </p>
      </header>

      <section aria-labelledby="universos">
        <h2 id="universos">Universos</h2>
        <table className="plain-table">
          <tbody>
            <tr>
              <th scope="row">Mapa e tabela</th>
              <td>
                Território brasileiro, {int(agg.municipios)} município(s) no recorte atual; {int(manifest.cobertura.com_geometria)}{" "}
                com geometria no release. Exterior fora.
              </td>
            </tr>
            <tr>
              <th scope="row">Card nacional</th>
              <td>
                {nacional.fonte}, {nacional.unidades} unidades, inclui exterior. {nacional.metricas_por_unidade_turno}{" "}
                métricas conferidas, {nacional.diferencas_nao_zero} diferença(s) não zero.
              </td>
            </tr>
            <tr>
              <th scope="row">Exceção do exterior</th>
              <td>
                {int(nacional.excecoes.aptos_sem_comparecimento_abstencao_t2)} aptos em seções não instaladas não têm
                comparecimento nem abstenção. O card nacional informa isso; o recorte territorial não é corrigido.
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section aria-labelledby="formulas">
        <h2 id="formulas">Fórmulas</h2>
        <p>
          Todas as razões são calculadas <strong>depois de somar</strong> as contagens do recorte. Nunca é feita média
          simples de percentuais municipais. Denominador zero resulta em “não calculável”, nunca zero.
        </p>
        <ul className="formula-list">
          {Object.entries(dicionario.derivados).map(([name, formula]) => (
            <li key={name}>
              <code>{name}</code> = {formula}
            </li>
          ))}
        </ul>
        <p>
          No recorte atual: participação de Lula no 2º turno {pct(agg.participacao_lula_t2)}; comparecimento 2º turno{" "}
          {pct(agg.comparecimento_t2)}; mudança da margem {pp(agg.delta_margem_pp)}; saldo de votos{" "}
          {signedInt(agg.delta_margem_votos)}.
        </p>
      </section>

      <section aria-labelledby="nulos">
        <h2 id="nulos">Nulos, ausentes e filtros</h2>
        <p>{dicionario.politica_nulos}.</p>
        <ul>
          <li>Uma variável sem filtro não exclui municípios com valor ausente.</li>
          <li>Um intervalo ativo é fechado nos dois extremos e exclui ausentes; “sem informação” é uma categoria explícita.</li>
          <li>Intervalos usam os valores observados; não há imputação de zero nem interpolação.</li>
          <li>As faixas congeladas vêm de quintis nacionais sem peso, com empates juntos, e não são recalculadas ao filtrar.</li>
        </ul>
      </section>

      <section aria-labelledby="glossario">
        <h2 id="glossario">Glossário</h2>
        <dl className="glossary">
          {GLOSSARY.map(([term, definition]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{definition}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="fontes">
        <h2 id="fontes">Fontes e proveniência</h2>
        <ul>
          <li>Votação por seção 2026: TSE; painel pareado do projeto, contrato v{String(manifest.origem.contract_version ?? "1.2.0")}.</li>
          <li>Totais oficiais: TSE, Relatório de Resultado da Totalização 2026 (28 unidades, inclui exterior).</li>
          <li>Socioeconômicos: IBGE Censo 2022 (SIDRA 10295, 10296, 6580, 9923); MTE RAIS 31/12/2025; MDS/PBF 08/2026.</li>
          <li>Nomes: IBGE, API de localidades, municípios 2022. Reconciliados por código, nunca por nome.</li>
          <li>Malha: IBGE, API de malhas, municípios 2022, qualidade intermediária; licença e atribuição a confirmar antes de publicação.</li>
        </ul>
        <p>
          O release <code>{releaseId}</code> (schema <code>{schemaVersion}</code>) foi gerado em{" "}
          {new Date(manifest.generated_at_utc).toLocaleString("pt-BR")} a partir das entradas com SHA-256 no
          manifesto. Arquivos verificáveis:{" "}
          <a href={`${releaseUrl}/manifest.json`}>manifesto</a>,{" "}
          <a href={`${releaseUrl}/dicionario.json`}>dicionário</a>,{" "}
          <a href={`${releaseUrl}/nacional.json`}>referência nacional</a>,{" "}
          <a href={`${releaseUrl}/faixas.json`}>faixas congeladas</a>.
        </p>
      </section>

      <section aria-labelledby="limites">
        <h2 id="limites">O que os dados não sustentam</h2>
        <ul>
          <li>Renda do responsável no município não é renda do eleitor nem renda per capita individual.</li>
          <li>Vínculos formais são do estabelecimento e não são trabalhadores únicos residentes.</li>
          <li>Registros do PBF não são famílias; a razão por domicílios pode passar de 100.</li>
          <li>Perfis e correlações entre bases não medem transferência de votos.</li>
          <li>Um indicador municipal repetido em várias unidades não multiplica observações.</li>
          <li>Não há inferência de voto individual, de intenção ou de causalidade nesta versão.</li>
        </ul>
      </section>

      <section aria-labelledby="acessibilidade">
        <h2 id="acessibilidade">Acessibilidade</h2>
        <p>
          A tabela e a busca são alternativas ao mapa. O gráfico tem tabela equivalente. Controles têm rótulo,
          foco visível e navegação por teclado; a informação não depende só de cor (há sinal, texto e unidade). A
          meta é WCAG 2.2 AA, sem certificação automática; leitura manual e teclado complementam os testes.
        </p>
      </section>

      <section aria-labelledby="decisoes">
        <h2 id="decisoes">Módulos fora do P0</h2>
        <p>
          Os módulos abaixo estão desligados por feature flag nesta entrega. Não há botão que simule a análise nem
          resultado apresentado como concluído.
        </p>
        <ul>
          {(Object.keys(FEATURES) as Array<keyof typeof FEATURES>).map((key) => (
            <li key={key}>
              {FEATURE_LABELS[key]}: <strong>{FEATURES[key] ? "ativo" : "desligado"}</strong>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="decisoes-sol">
        <h2 id="decisoes-sol">Decisões pendentes de revisão</h2>
        <ul>
          {manifest.decisoes_pendentes_sol.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
