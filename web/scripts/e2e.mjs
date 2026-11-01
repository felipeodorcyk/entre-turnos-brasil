/**
 * E2E local com Playwright e o Chrome instalado.
 *
 * Pré-requisitos:
 *   npm run build
 *   npm run preview -- --port 4173
 *   node scripts/e2e.mjs
 *
 * Gera capturas em docs/webapp/evidence/ e falha em erro de console,
 * divergência de contagem ou fluxo quebrado.
 */
import { chromium } from "playwright";
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:4173/";
const EVIDENCE = resolve("..", "docs", "webapp", "evidence");
mkdirSync(EVIDENCE, { recursive: true });

const errors = [];
const browser = await chromium.launch({ channel: "chrome", headless: true });

async function newPage(viewport, collectErrors = true) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, acceptDownloads: true });
  const page = await context.newPage();
  if (collectErrors) {
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(`console: ${message.text()}`);
    });
    page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  }
  return { context, page };
}

async function waitCards(page) {
  await page.getByRole("heading", { name: "Recorte selecionado" }).waitFor({ timeout: 20000 });
  await page.locator('[data-socio-ready="1"]').waitFor({ timeout: 30000 });
}

async function waitMap(page) {
  const placeholder = page.getByText("O mapa é carregado sob demanda ao chegar nesta seção");
  if (await placeholder.count()) await placeholder.scrollIntoViewIfNeeded();
  await page.locator(".map-section").scrollIntoViewIfNeeded();
  await page.waitForFunction(() => window.__map?.loaded?.() === true, null, { timeout: 30000 });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

// 1. Capturas responsivas.
for (const [width, height] of [
  [360, 800],
  [768, 1024],
  [1440, 1000],
]) {
  const { context, page } = await newPage({ width, height });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await waitCards(page);
  await page.screenshot({ path: resolve(EVIDENCE, `overview_${width}.png`), fullPage: false });
  await waitMap(page);
  assert(await page.locator(".maplibregl-canvas").isVisible(), "mapa não visível");
  await page.waitForTimeout(400);
  await page.screenshot({ path: resolve(EVIDENCE, `mapa_${width}.png`), fullPage: false });
  if (width === 1440) {
    await page.screenshot({ path: resolve(EVIDENCE, "overview_1440_full.png"), fullPage: true });
    await page.locator(".table-section").scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
    await page.screenshot({ path: resolve(EVIDENCE, "tabela_1440.png"), fullPage: false });
  }
  await context.close();
}

// 2. Fluxo: buscar município -> filtrar renda -> comparar turnos -> baixar -> restaurar URL.
{
  const { context, page } = await newPage({ width: 1280, height: 1000 });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await waitCards(page);

  const search = page.getByPlaceholder("Nome, UF ou código");
  await search.fill("São Paulo");
  await page.getByRole("button", { name: /São Paulo \/ SP/ }).first().click();
  await page.waitForFunction(() => location.hash.includes("mun=3550308"));
  const intro = await page.locator(".intro-strip").innerText();
  assert(intro.includes("1"), "seleção por busca não reduziu o recorte");

  // Cards T1/T2 do município selecionado.
  const lulaCard = await page.locator(".card").first().innerText();
  assert(lulaCard.includes("1º turno") && lulaCard.includes("2º turno"), "card sem T1/T2");

  // Limpa a seleção e aplica UF + renda.
  await page.getByRole("button", { name: "Limpar tudo" }).click();
  await page.getByRole("checkbox", { name: "SP", exact: true }).check();
  const rendaMin = page.getByLabel("Renda domiciliar per capita média: valor mínimo");
  const rendaMax = page.getByLabel("Renda domiciliar per capita média: valor máximo");
  await rendaMin.fill("800");
  await rendaMax.fill("1200");
  await page.waitForFunction(() => location.hash.includes("uf=SP") && location.hash.includes("renda=800:1200"));
  const intro2 = await page.locator(".intro-strip").innerText();
  assert(!intro2.includes("5.571"), "filtro de renda não alterou o recorte");

  // Download do CSV filtrado.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Baixar CSV filtrado" }).click(),
  ]);
  const csvPath = await download.path();
  const csv = readFileSync(csvPath, "utf8");
  const lines = csv.trim().split(/\r?\n/);
  assert(lines[0].startsWith("cd_ibge;cd_tse;nome"), "cabeçalho do CSV inesperado");
  assert(lines.length > 1 && lines.length < 5572, "CSV não reflete o filtro");
  assert(
    lines.slice(1).every((line) => line.split(";")[3] === '"SP"'),
    "CSV filtrado não contém apenas SP",
  );

  // Metadados.
  const [metaDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Baixar metadados" }).click(),
  ]);
  const meta = JSON.parse(readFileSync(await metaDownload.path(), "utf8"));
  assert(meta.release_id && meta.filtros.ufs.includes("SP"), "metadados sem filtros");
  assert(meta.formulas.delta_margem_pp, "metadados sem fórmulas");

  // Estado compartilhável: nova página restaura UF e renda.
  const url = page.url();
  await page.goto("about:blank");
  await page.goto(url, { waitUntil: "networkidle" });
  await waitCards(page);
  assert(await page.getByRole("checkbox", { name: "SP", exact: true }).isChecked(), "URL não restaurou UF");
  assert((await rendaMin.inputValue()) === "800", "URL não restaurou renda mínima");
  assert((await rendaMax.inputValue()) === "1200", "URL não restaurou renda máxima");

  // Voltar/avançar: limpar e voltar deve restaurar o recorte anterior.
  await page.getByRole("button", { name: "Limpar tudo" }).click();
  await page.waitForFunction(() => !location.hash.includes("uf=SP"));
  await page.goBack();
  await page.waitForFunction(() => location.hash.includes("uf=SP"));
  assert(await page.getByRole("checkbox", { name: "SP", exact: true }).isChecked(), "voltar não restaurou o estado");

  await page.screenshot({ path: resolve(EVIDENCE, "filtro_sp_renda.png"), fullPage: false });

  // Recorte vazio é estado válido, não erro.
  await rendaMin.fill("99999");
  await page.waitForFunction(() => document.body.innerText.includes("Nenhum município no recorte"));
  await page.screenshot({ path: resolve(EVIDENCE, "estado_vazio.png"), fullPage: false });

  await context.close();
}

// 3. Clique no mapa seleciona e remove o mesmo município (handler não fica obsoleto).
{
  const { context, page } = await newPage({ width: 1280, height: 900 });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await waitCards(page);
  await waitMap(page);
  const canvas = page.locator(".maplibregl-canvas");
  const box = await canvas.boundingBox();
  assert(box, "canvas do mapa sem dimensões");
  const point = { x: box.width / 2, y: box.height / 2 };
  await canvas.click({ position: point });
  await page.waitForFunction(() => location.hash.includes("mun="), null, { timeout: 10000 });
  const selected = await page.evaluate(() => new URLSearchParams(location.hash.slice(1)).get("mun"));
  assert(selected && selected.length >= 7, "clique no mapa não selecionou município");
  await canvas.click({ position: point });
  await page.waitForFunction(() => !location.hash.includes("mun="), null, { timeout: 10000 });
  await page.screenshot({ path: resolve(EVIDENCE, "mapa_clique_selecao.png"), fullPage: false });
  await context.close();
}

// 4. Falha do mapa mantém a tabela disponível.
{
  const { context, page } = await newPage({ width: 1280, height: 900 }, false);
  await page.route("**/geo/municipios_2022_intermediaria.geojson", (route) => route.abort());
  await page.goto(BASE, { waitUntil: "networkidle" });
  await waitCards(page);
  await page.locator(".map-placeholder").scrollIntoViewIfNeeded();
  await page.getByText("O mapa não carregou.").waitFor({ timeout: 20000 });
  const rows = await page.locator(".municipios-table tbody tr").count();
  assert(rows === 50, `tabela deveria manter 50 linhas com mapa falho, tem ${rows}`);
  await page.screenshot({ path: resolve(EVIDENCE, "mapa_falhou_tabela_ok.png"), fullPage: false });
  await context.close();
}

// 4. Páginas de conteúdo e acessibilidade básica.
{
  const { context, page } = await newPage({ width: 1280, height: 1000 });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await waitCards(page);

  // axe-core: complementa, não substitui, teclado e leitura manual.
  const axePath = resolve("node_modules", "axe-core", "axe.min.js");
  await page.addScriptTag({ path: axePath });
  const axe = await page.evaluate(async () => {
    const results = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
    });
    return results.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help }));
  });
  if (axe.length > 0) {
    console.error("Violações axe:", JSON.stringify(axe, null, 2));
    errors.push(`axe: ${axe.length} violação(ões)`);
  }

  await page.getByRole("button", { name: "Perguntas" }).click();
  await page.getByRole("heading", { name: "Entender os resultados" }).waitFor();
  await page.screenshot({ path: resolve(EVIDENCE, "perguntas.png"), fullPage: false });
  await page.getByRole("button", { name: "Metodologia" }).click();
  await page.getByRole("heading", { name: "Como os números são calculados" }).waitFor();
  await page.screenshot({ path: resolve(EVIDENCE, "metodologia.png"), fullPage: false });

  // Teclado: em uma página recém-carregada, o primeiro Tab foca o skip link.
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.textContent);
  assert(focused?.includes("Pular para o conteúdo"), "skip link não recebeu foco");
  await context.close();
}

await browser.close();

if (errors.length) {
  console.error("Erros de console/página:");
  for (const error of errors) console.error(" -", error);
  process.exit(1);
}
console.log(`E2E OK. Capturas em ${EVIDENCE}`);
