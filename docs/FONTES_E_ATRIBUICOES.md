# Fontes e atribuições

A licença MIT cobre o código original e a documentação deste projeto. Não relicencia bases, malhas, marcas ou dependências de terceiros. Cite a instituição de origem e o Entre Turnos Brasil ao reproduzir análises derivadas; preserve referências, períodos e ressalvas metodológicas.

| Fonte | Uso | Referência |
| --- | --- | --- |
| TSE | Resultados dos dois turnos e referência nacional | https://www.tse.jus.br/administracao/painel/portal-de-dados-abertos-do-tse |
| IBGE | Indicadores censitários, renda, população e VAB | https://sidra.ibge.gov.br/ e https://servicodados.ibge.gov.br/api/docs/agregados |
| MTE / RAIS | Vínculos formais; não equivalem a pessoas empregadas | https://acesso.trabalho.gov.br/portal-pdet/o-pdet/registros-administrativos/rais/ |
| MDS / Portal da Transparência | Bolsa Família agregado por município | https://portaldatransparencia.gov.br/download-de-dados |
| IBGE | Geometrias simplificadas para visualização | https://servicodados.ibge.gov.br/api/docs/malhas?versao=3 |

Os períodos e unidades de cada indicador constam na metodologia e nos manifestos incluídos. População: Censo 2022, agregado 4714, variável 93. Agropecuária: participação no VAB de 2021, agregado 5938, variável 516. As URLs exatas, contagens e hashes desses dois indicadores constam em web/src/data/profiles-context.json (sources); a identificação dos dados eleitorais está em web/public/release/current.json e no manifesto da release correspondente.

## Malhas

Crédito: IBGE, API de malhas v3, qualidade intermediária; snapshot acessado em 30/10/2026. URLs e hashes originais e distribuídos em web/public/geo/malha_manifest.json. A documentação oficial descreve expressamente o uso das malhas simplificadas em aplicações web. Não foi identificado um rótulo SPDX específico nessa documentação; não se atribui MIT ou Creative Commons à malha por inferência.

Os nomes locais dos arquivos contêm 2022, mas as URLs registradas não fixam o parâmetro periodo. Portanto esse nome não comprova a edição temporal da geometria. A referência reproduzível é o snapshot e seu hash. A malha contém 5.570 geometrias municipais; a base analítica possui 5.571 registros municipais. Ausência de geometria não implica exclusão dos totais analíticos. Não use este desenho simplificado para medir o entorno de 1 km.

## Limites da versão

Indicadores municipais de períodos distintos descrevem contextos territoriais. Não demonstram causalidade nem transferências individuais de votos. Quintis fixos contam municípios, sem ponderação pelo eleitorado. O entorno de 1 km e os horários de encerramento ainda não integram os filtros deste dashboard. Não são publicados registros individuais de beneficiários.

## Dependências

Dependências npm e Python conservam suas licenças. As versões exatas estão em web/package-lock.json e requirements.lock. Distribuições derivadas devem preservar os avisos de terceiros que acompanham essas dependências. Crédito não significa endosso institucional.

Revisão documental: 01/11/2026.

