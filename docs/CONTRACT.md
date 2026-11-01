# CONTRACT — release web municipal P0

Versão do schema: `webapp-p0/1.0.0`.
Release de referência: `p0-5087618-8a089c1c93` (o `release_id` é derivado dos hashes no manifesto).
Este contrato descreve apenas o P0 municipal. Seções, entorno, horários e modelos não fazem parte dele.

## 1. Grão, chaves e universos

| Conceito | Regra |
|---|---|
| Unidade exportada | município do território brasileiro: `(sg_uf, cd_municipio_tse)` |
| Chave primária | `cd_ibge` (7 dígitos, texto) após lookup oficial; `cd_tse` (5 dígitos, texto) mantido para busca |
| Universo municipal/UF | `pareado_territorial`: 5.571 municípios, 497.897 unidades eleitorais, sem exterior |
| Universo do card nacional | referência oficial do TSE: 28 unidades (26 UFs + DF + `ZZ`), 392/392 métricas reconciliadas com `dif = 0` |
| Exterior | fora do mapa e da tabela; presente só no card nacional. Nenhuma geometria brasileira é atribuída ao `ZZ` |
| Referência temporal | eleição presidencial de 2026, 1º e 2º turnos; socioeconômicos com ano próprio (Censo 2022, RAIS 31/12/2025, PBF 08/2026) |
| Unidade de contagem | voto / eleitor apto / registro, sempre inteiro; nunca pessoa identificada |

## 2. Campos exportados em `municipios.json`

`fields` é a lista ordenada; `rows` são arrays na mesma ordem. Campos e semântica:

| Campo | Tipo | Conceito | Agregação |
|---|---|---|---|
| `cd_tse` | string(5) | código TSE do município, zeros à esquerda | chave, não somar |
| `cd_ibge` | string(7) | código IBGE do município | chave, não somar |
| `sg_uf` | string(2) | UF | dimensão |
| `nome` | string | nome IBGE do município | dimensão |
| `regiao` | string | grande região (Norte, Nordeste, Sudeste, Sul, Centro-Oeste) | dimensão |
| `cd_regiao_imediata` | string(6) | região imediata IBGE | dimensão |
| `n_unidades` | int | unidades eleitorais (seções) pareadas no município | soma descritiva, não denominador |
| `qt_aptos_t1`, `qt_aptos_t2` | int | eleitorado apto | soma; denominador de comparecimento |
| `qt_comparecimento_t1/t2` | int | comparecimento | soma; numerador de comparecimento |
| `qt_abstencoes_t1/t2` | int | abstenções | soma |
| `qt_votos_validos_t1/t2` | int | votos válidos para presidente | soma; denominador de participação |
| `qt_votos_brancos_t1/t2` | int | brancos | soma |
| `qt_votos_nulos_t1/t2` | int | nulos | soma |
| `qt_lula_t1/t2` | int | votos em Lula | soma |
| `qt_flavio_t1/t2` | int | votos em Flávio Bolsonaro | soma |
| `renda_pc` | float/null | renda domiciliar per capita média, R$ de 2022 (IBGE 10295) | **não agregável**; atributo único do município |
| `baixa_renda` | float/null | % de pessoas com até ½ salário mínimo, 2022 (IBGE 10296) | **não agregável** |
| `desocupacao` | float/null | taxa de desocupação, %, 2022 (IBGE 6580) | **não agregável** |
| `vinculos` | float/null | vínculos formais por mil habitantes, RAIS 31/12/2025 | **não agregável**; vínculo é do estabelecimento, não pessoa única |
| `pbf` | float/null | registros do PBF por 100 domicílios ocupados de 2022, competência 08/2026 | **não agregável**; registro não é família |
| `urbana` | float/null | % da população urbana, 2022 (IBGE 9923) | **não agregável** |
| `tem_geometria` | 0/1 | 1 se há feição municipal 2022 para o código IBGE | indicador de cobertura |
| `tem_contexto` | 0/1 | 1 se todos os seis indicadores socioeconômicos estão presentes | indicador de cobertura |

Campos derivados **não** são exportados como valores independentes; o motor web os calcula sempre a partir das somas:

```text
participacao_lula_T = soma(qt_lula_T) / soma(qt_votos_validos_T)
participacao_flavio_T = soma(qt_flavio_T) / soma(qt_votos_validos_T)
comparecimento_T = soma(qt_comparecimento_T) / soma(qt_aptos_T)
abstencao_T = soma(qt_abstencoes_T) / soma(qt_aptos_T)
brancos_share_T = soma(qt_votos_brancos_T) / soma(qt_comparecimento_T)
nulos_share_T = soma(qt_votos_nulos_T) / soma(qt_comparecimento_T)
delta_pp = 100 * (razao_T2 - razao_T1)
delta_margem_votos = (Lula_T2 - Flavio_T2) - (Lula_T1 - Flavio_T1)
```

Denominador zero ⇒ `null` ("não calculável"), nunca zero. Percentuais são exibidos com 2 casas; a conta e os testes usam o valor não arredondado.

## 3. Identidades e exceções

- No território, por município: `aptos = comparecimento + abstenções` nos dois turnos (0 divergências).
- No 2º turno: `válidos = Lula + Flávio` (0 divergências).
- No 1º turno, `válidos = Lula + Flávio + demais válidos`; o app não apresenta "outros" como candidato deste release.
- **Exceção oficial**: no exterior, 41 seções não instaladas somam 423 aptos sem comparecimento nem abstenção. O card nacional exibe a nota; nenhuma correção silenciosa é feita.
- 42 unidades do exterior sem apuração em nenhum turno (495 aptos, nenhum voto) estão fora do universo pareado. O card nacional usa a referência oficial, que as inclui no eleitorado apto.

## 4. Política de nulos e filtros

| Situação | Comportamento |
|---|---|
| Variável sem filtro | municípios com valor ausente **permanecem** na base |
| Filtro de intervalo ativo | ausente **não** satisfaz o intervalo; fica fora, com contagem explícita |
| Categoria "sem informação" | opção explícita que seleciona apenas os ausentes daquela variável |
| Intervalos | fechados nos dois extremos: `[min, max]`; unidade e ano exibidos no rótulo |
| Ausente | `null`; nunca imputado como zero |
| Seleção vazia | resultado válido com 0 municípios, razões `null`, cobertura 0 e estado vazio na UI |
| Indicador socioeconômico | filtro de atributo municipal; não cria média, soma ou percentual agregado do indicador |

Seleções múltiplas: **OU dentro da dimensão** (região, UF, município) e **E entre dimensões**. Região/UF/município são hierárquicos: ao mudar um pai, filhos incompatíveis são removidos com aviso.

## 5. Faixas congeladas

Fonte: `data/analytics/socio/faixas_nacional.csv`. São quintis nacionais calculados uma vez no universo de municípios do território com o indicador observado, **sem peso** (cada município conta igual), com empates mantidos juntos. Os cortes são exportados em `faixas.json` e **não** são recalculados ao filtrar. A UI oferece intervalo contínuo e atalhos para os cortes congelados; nenhum atalho é chamado de "quintil do recorte".

## 6. Estado compartilhável (URL)

Fragmento `#` com `URLSearchParams`:

| Chave | Formato | Validação |
|---|---|---|
| `release` | `p0-…` | se diferente do release carregado, aviso e estado seguro (filtros limpos) |
| `schema` | `webapp-p0/1.0.0` | idem |
| `reg` | `Norte,Sul` | região desconhecida é descartada com aviso |
| `uf` | `AC,SP` | UF desconhecida ou incompatível com `reg` é descartada |
| `mun` | códigos IBGE separados por `,` | município desconhecido ou incompatível é descartado |
| `renda`, `baixa`, `desoc`, `vinc`, `pbf`, `urb` | `min:max` ou `sem` | `min > max` ou não numérico ⇒ filtro descartado com aviso |
| `metrica` | id do mapa | métrica desconhecida volta ao padrão |
| `ordem` | `campo:asc\|desc` | campo desconhecido volta ao padrão |
| `pag` | inteiro ≥ 1 | inválido volta a 1 |

Voltar/avançar restaura o estado. Nenhuma URL inválida altera os totais silenciosamente.

## 7. Exportações

- `municipios.csv` (recorte filtrado): contagens, razões derivadas e socioeconômicos por município; delimitador `;`, UTF-8 com BOM, decimal com ponto.
- `metadados.json`: release, schema, filtros aplicados, escopo, fórmulas, fontes, cobertura, totais, data/hora e avisos.
- Campos textuais iniciam com `'` quando começam com `= + - @` ou tab/CR (neutralização de fórmula). Contagens permanecem numéricas.

## 8. Manifesto do release e arquivos de carga

`manifest.json` contém: `release_id`, `schema_version`, `generated_at_utc`, commit de origem e dirty state, SHA-256 de cada entrada, contagens por universo, cobertura (geometria/contexto), exclusões, raio (não aplicável no P0), fontes/licenças, partições, tamanhos e `decisoes_pendentes_sol`.

Para o carregamento do app, o release publica ainda:

| Arquivo | Conteúdo | Uso |
|---|---|---|
| `bundle.json` | municípios sem os seis indicadores socioeconômicos + UF + nacional + faixas + dicionário | primeira carga (cards, tabela, mapa) |
| `socio.json` | `cd_ibge` + os seis indicadores socioeconômicos | segunda carga (filtros socioeconômicos e colunas da tabela) |
| `current.json` (raiz de releases) | ponteiro para `release_id` e manifesto | descoberta do release |

`municipios.json` continua sendo o arquivo completo (com socio) para verificação e download; `bundle.json` e `socio.json` são a mesma informação dividida para não bloquear o conteúdo principal no celular.

## 9. Decisões para o Sol

1. **Card nacional**: adotada a referência oficial do TSE (inclui exterior) como card separado; o mapa/tabela usam `pareado_territorial`. Confirmar se o rótulo "oficial" e a nota dos 423 aptos bastam para publicação.
2. **Malha**: API de malhas do IBGE (municípios 2022, qualidade intermediária) tem 5.570 feições e não inclui Boa Esperança do Norte/MT. Confirmar licença/atribuição e se a ausência deve gerar complemento manual (não foi inventado).
3. **Nomes**: exibição pelo `municipios.json` do IBGE; o lookup TSE é só a ponte por código. Confirmar a política para nomes divergentes entre TSE e IBGE.
4. **Indicadores socioeconômicos**: tratados como atributos municipais não agregáveis. Confirmar que a UI não deve exibir mediana/contagem agregada do indicador no recorte.
5. **Quintis**: usados apenas como atalhos de intervalo congelado; a UI não os recalcula. Confirmar nomenclatura pública ("faixas congeladas", não "quintis do recorte").


## Adendo 31/10/2026
Snapshot solicitado na URL é carregado explicitamente; release ausente não migra automaticamente. Exportação reutiliza releases idênticas e preserva manifesto; colisão falha; current.json é substituído atomicamente. Identidade inclui hash do exportador. Falha de contexto/manifesto tem erro e retry; consultas dependentes aguardam contexto. Metadados incluem ausências por indicador na base geográfica anterior aos filtros socioeconômicos (sobreposições não somáveis). Mapa inclui T1 e variações de participação, serializados na URL. Detalhes em REVISAO_CORRECOES_P0.md.


## Adendo de homologação 55

Contexto adicional: população residente Censo 2022 e participação do agro no VAB municipal 2021. São indicadores municipais, nunca de entorno. Arquivos em public/context/<id>.json; hashes SHA-256 dos bytes exatos em src/data/context-integrity.json. O ID histórico de 16 caracteres identifica o payload do produtor; o checksum completo verifica o arquivo servido. Adicionar snapshots exige atualizar o manifesto e o build. Checksum verifica integridade relativa ao build, não autenticação de terceiros. Arquivo desconhecido, ausente ou corrompido não é substituído silenciosamente pelo contexto atual.

Estado compartilhado: release/schema e filtros do contrato original, mais by (ótica), profile (dimensão:chave), measure (votes/pp), geo (municipal/estadual/regional), place e context. Histórico de seleções usa pushState após normalização inicial; popstate recarrega o estado. Ordenação e expansão dos grupos são preferências locais e não fazem parte do link.

Escopos: mapa e CSV usam filtros personalizados E profile. Comparação usa somente filtros personalizados e agrupa por by. Metadados identificam csv_scope, comparison_scope e comparison_municipios; groups descreve a comparação. Resumo nacional inclui exterior, demais recortes são territoriais. As geometrias podem repetir contagens agregadas para desenho; nunca somar essas feições para obter os totais.

Contribuição nacional pp = 100*(margem_recorte2/validos_nacionais2 - margem_recorte1/validos_nacionais1). Faixas socioeconômicas são quintis nacionais sem peso, congelados com empates juntos. População usa limites 20 mil, 100 mil e 500 mil; agro usa 5%,20%,40% do VAB. Ausências são grupo próprio.


Validação final de contexto: anos das fontes são strings YYYY; count é inteiro; população não negativa; VAB agro pode ser negativo e é preservado. No snapshot atual o município5204250 tem -41,9%; não é transformado em zero. Está incluído no grupo menor que5%. Confirmar interpretações setoriais contra a fonte antes de usar esse caso como narrativa explicativa.
