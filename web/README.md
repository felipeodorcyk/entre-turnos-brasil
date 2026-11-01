# Web app — explorador municipal P0

React + TypeScript + Vite. Consome o release gerado por `tools/web_export/`.
Contrato: `../docs/webapp/CONTRACT.md`. Entrega: `../docs/webapp/ENTREGA_P0.md`.

O E2E usa o Chrome instalado (`channel: "chrome"`); não baixa navegador próprio.

## Comandos

```powershell
npm install
npm run typecheck
npm test              # 81 testes (motor, URL, CSV, 53 casos de oráculo)
npm run build
npm run preview -- --port 4173
npm run e2e           # Playwright + Chrome; falha em erro de console/axe
node scripts/measure.mjs
```

Gerar dados (na raiz do projeto):

```powershell
.venv\Scripts\python.exe tools\web_export\fetch_malha.py
.venv\Scripts\python.exe tools\web_export\export_web_release.py
.venv\Scripts\python.exe tools\web_export\oracle.py
```

## Estrutura

- `src/engine/query.ts` — filtros e agregação puros; razões calculadas sobre somas.
- `src/engine/url.ts` — estado serializável, validação e round-trip.
- `src/engine/csv.ts` — CSV/metadados e neutralização de fórmulas.
- `src/data/load.ts` — `current.json` → `bundle.json` (cards/tabela) → `socio.json` (filtros).
- `src/components/DeferredMap.tsx` — carrega MapLibre só quando a seção se aproxima.
- `src/components/MapView.tsx` — coroplético, tooltip, clique, legenda e falha isolada.
- `src/config/features.ts` — flags P1/P2 desligadas; nenhum botão falso.

## Dados

- `public/release/` é gerado e ignorado pelo Git; rode o exportador antes do preview.
- `public/geo/` contém a malha municipal 2022 simplificada (IBGE) e o manifesto de origem.
- O app não busca tiles externos; o mapa funciona sem rede após a malha local.
- `public/release/current.json` aponta para o release imutável atual.

## Acessibilidade

Tabela e busca são alternativas ao mapa; o gráfico tem tabela equivalente; controles
têm rótulo e foco visível; a informação não depende só de cor. O E2E roda axe-core
(WCAG 2.2 AA automatizado) e o primeiro Tab foca o skip link. Isso complementa, mas
não substitui, leitura manual e teste com leitor de tela.
