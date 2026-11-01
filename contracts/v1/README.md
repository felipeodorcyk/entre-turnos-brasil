# Contrato v1 — v1.2.0 de 27/10/2026 (frente B)

Os esquemas desta pasta são a fonte de verdade: `br2026.contract.validate(df, tabela)` e `python -m br2026 validate` os aplicam, e `_meta.schema.json` valida os próprios arquivos de contrato. Mudança exige versão nova (`contracts/v2/`), justificativa em `docs/methodology/decisions.md` e teste de compatibilidade. As frentes A e C não alteram esta pasta.

| Tabela | Dono | Caminho | Chave |
|---|---|---|---|
| votes_long | A | data/staging/votes_long.parquet | ano, cd_eleicao, nr_turno, sg_uf, cd_municipio_tse, nr_zona, nr_secao, cd_cargo, nr_votavel |
| section_turn | A | data/staging/section_turn.parquet | ano, cd_eleicao, nr_turno, sg_uf, cd_municipio_tse, nr_zona, nr_secao, cd_cargo |
| section_crosswalk | A | data/staging/section_crosswalk.parquet | ano, nr_turno, sg_uf, cd_municipio_tse, nr_zona, nr_secao, status_correspondencia |
| profiles | A | data/staging/profiles.parquet | ano_referencia, sg_uf, cd_municipio_tse, nr_zona, nr_secao, dimensao, cd_categoria |
| closure | A | data/staging/closure.parquet | ano, nr_turno, sg_uf, cd_municipio_tse, nr_zona, nr_secao, id_registro |
| municipal_context | A | data/staging/municipal_context.parquet | sg_uf, cd_municipio_tse, variavel |
| panel | B | data/analytics/panel.parquet | id_unidade |
| panel_membership | B | data/analytics/panel_membership.parquet | nr_turno, sg_uf, cd_municipio_tse, nr_zona, nr_secao |

O particionamento físico por UF/turno é livre (diretório Parquet com partições `sg_uf=`/`nr_turno=`), desde que a leitura do caminho reproduza a tabela lógica acima.

## Regras gerais

- Identificadores são texto com zeros à esquerda: `cd_municipio_tse` 5 dígitos, `nr_zona` 4, `nr_secao` 4, `nr_local_votacao` 4. O TSE publica esses campos sem preenchimento.
- Contagens são `int64` não negativas. Ausência é nulo (`Int64` com `<NA>`), nunca zero. Zero observado continua sendo zero.
- `ano`, `cd_eleicao`, `nr_turno` e `cd_cargo` vêm do conteúdo, nunca do nome do arquivo. Ano ou turno inesperado vai para erro ou quarentena explícita.
- Exterior: `sg_uf = "ZZ"`, com o código TSE do município; nenhum código IBGE é inventado.
- `source_id` é o SHA-256 do arquivo bruto registrado no manifesto.
- Brancos (95) e nulos (96) são `tipo_votavel` próprios e não são candidatos. Para presidente, `sq_candidato` vem do cadastro de 2026 (`consulta_cand_2026`, `CD_ELEICAO` do turno), nunca do de 2022.

## Mapeamento das fontes TSE (cabeçalhos verificados nos arquivos de 2026 do T1)

| Contrato | Fonte e campo |
|---|---|
| section_turn.qt_* | detalhe_votacao_secao: QT_APTOS, QT_COMPARECIMENTO, QT_ABSTENCOES, QT_VOTOS_NOMINAIS, QT_VOTOS_LEGENDA, QT_VOTOS_BRANCOS, QT_VOTOS_NULOS, QT_VOTOS_ANULADOS_APU_SEP |
| section_turn.st_* / ds_origem_voto | ST_SECAO_INSTALADA, ST_SECAO_ANULADA ("Sim"/"Não" → bool), DS_ORIGEM_VOTO |
| votes_long | votacao_secao: NR_VOTAVEL, QT_VOTOS, SQ_CANDIDATO |
| section_crosswalk | eleitorado_local_votacao: CD_TIPO_SECAO_AGREGADA, NR_SECAO_PRINCIPAL, NR_LOCAL_VOTACAO, NR_LOCAL_VOTACAO_ORIGINAL; secoes_agregadas do turno |
| profiles | perfil_eleitor_secao: CD/DS_GENERO, CD/DS_FAIXA_ETARIA, CD/DS_GRAU_ESCOLARIDADE, CD/DS_ESTADO_CIVIL, CD/DS_RACA_COR, QT_ELEITORES |
| closure | BU web (`bweb_<t>t_<UF>_*.csv`): DT_ABERTURA → ABERTURA_URNA, DT_ENCERRAMENTO → ENCERRAMENTO_URNA, DT_EMISSAO_BU → EMISSAO_BU, DT_BU_RECEBIDO → RECEBIMENTO_BU_TSE, uma linha por campo e sem fuso documentado (v1.1, decisão Q1). Os campos do detalhe de apuração, DT_RECEBIMENTO_BU_HOR_TSE e DT_PRIM_TOT_PARCIAL_HOR_TSE ("Hora TSE"), nunca entram como encerramento. |

## Contabilidade

Para presidente, `qt_votos_validos = qt_votos_nominais + qt_votos_legenda`, com identidades em `section_turn.json → accounting`. As flags de identidade são calculadas por A e as linhas que falham permanecem, marcadas. O painel as classifica como `EXCLUIDA_CONTABILIDADE` e as totaliza na reconciliação.

## Histórico de versões

| Versão | Data | Mudanças | Migração |
|---|---|---|---|
| 1.0.0 | 26/10/2026 | Versão inicial (G0) | — |
| 1.1.0 | 26/10/2026 | Colunas novas: `section_crosswalk.status_correspondencia`, que passa a integrar a chave, e `profiles.dt_referencia_cadastro`. Semântica nova `ABERTURA_URNA`. Status novo `EXCLUIDA_CORRESPONDENCIA_NAO_EFETIVADA`. Tabela nova `municipal_context`. Regra provisória para anulados em separado. | `reports/analysis/DECISOES_CONTINUACAO.md`; `br2026.contract.migrate_v1_0` |
| 1.1.0 (errata) | 26/10/2026 | `municipal_context.fonte_url`: padrão `^https?://` nunca casava com o validador (fullmatch); corrigido para `https?://\S+`. Sem dados afetados (tabela ainda vazia). | — |
| 1.2.0 | 27/10/2026 | Sem mudança de esquema. Semântica de `section_crosswalk.status_correspondencia = EFETIVADA` ampliada para a falta de BU web e de CEFT do turno: presença das apuradoras no detalhe de votação do turno + agregação do eleitorado, com gate e `fonte = detalhe+eleitorado_local_votacao` (decisão D-T2-01). | Nenhuma: tabelas v1.1 continuam válidas; `docs/methodology/decisions.md` (D-T2-01) |
