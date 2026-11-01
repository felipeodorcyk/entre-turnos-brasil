# Entre Turnos Brasil

Exploração pública das mudanças entre o 1º e o 2º turno das eleições presidenciais de2026. Criado por [Felipe Odorcyk](https://www.linkedin.com/in/felipe-odorcyk/).

[Aplicativo publicado](https://spring-fire-4ff2.felipe-odorcyk.workers.dev/) · [Contato pelo LinkedIn](https://www.linkedin.com/in/felipe-odorcyk/)

## Rodar o dashboard

Node.js24 e npm. Os snapshots agregados necessários estão incluídos; não precisa de chave de API.

```sh
cd web
npm ci
npm test
npm run build
npm run preview
```

Abra o endereço mostrado pelo Vite. A raiz abre o Explorer; `?view=legacy` abre a consulta técnica. O build em `web/dist` pode ser publicado como arquivos estáticos; `_headers` configura Cloudflare.

## Dados e método

TSE: resultados eleitorais. IBGE: renda/urbanização/população e VAB. MTE/RAIS: vínculos formais. MDS: registros do Bolsa Família. Datas e unidades aparecem na metodologia do app e nos manifestos. Percentuais calculados depois de somar contagens. Os quintis municipais são nacionais, fixos e sem peso eleitoral. Associações municipais não identificam voto individual ou transferência entre candidatos.

Esta publicação inclui código da análise e frontend, testes e snapshots municipais agregados. Exclui microdados brutos, ambiente local e documentos internos. O entorno fixo de1km é descrito na metodologia, mas ainda não integra os filtros do dashboard. Não se deve atribuir essa escala aos indicadores municipais.

## Reprodução científica

Pipeline Python em src e tools; dependências em pyproject.toml e requirements.lock. Reconstruir os dados a partir das fontes exige obter os insumos especificados pelos scripts e manifestos; o clone permite executar imediatamente o frontend e seus testes de reconciliação contra os casos de referência. O histórico inicial é uma distribuição revisada, não o histórico interno completo de desenvolvimento.

## Transparência e uso

Código publicado para consulta e auditoria. Não foi escolhida licença de software nesta entrega; publicação pública não concede automaticamente uma licença de redistribuição. Fontes de dados mantêm seus próprios termos. Créditos não representam endosso das instituições. Não inclui credenciais ou dados pessoais de beneficiários; os arquivos publicados são agregados.
