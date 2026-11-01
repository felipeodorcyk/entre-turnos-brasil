/**
 * Medições locais de carga e latência de filtro.
 * Requer build e preview em http://127.0.0.1:4173.
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:4173/";
const OUT = resolve("..", "docs", "webapp", "measurements.json");
mkdirSync(resolve("..", "docs", "webapp"), { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const page = await context.newPage();

const resourceGroups = () =>
  page.evaluate(() => {
    const entries = performance.getEntriesByType("resource");
    const groups = {};
    for (const entry of entries) {
      let group = "outros";
      if (entry.name.includes("/release/")) group = "dados_release";
      else if (entry.name.includes("/geo/")) group = "malha";
      else if (entry.name.includes("/assets/")) group = "js_css";
      groups[group] = groups[group] ?? { requests: 0, transferBytes: 0, decodedBytes: 0 };
      groups[group].requests += 1;
      groups[group].transferBytes += entry.transferSize || 0;
      groups[group].decodedBytes += entry.decodedBodySize || 0;
    }
    return groups;
  });

const t0 = Date.now();
await page.goto(BASE, { waitUntil: "domcontentloaded" });
await page.getByRole("heading", { name: "Recorte selecionado" }).waitFor({ timeout: 20000 });
const cardsReadyMs = Date.now() - t0;
const initialGroups = await resourceGroups();
const tSocio = Date.now();
await page.locator('[data-socio-ready="1"]').waitFor({ timeout: 30000 });
const socioReadyMs = Date.now() - tSocio;

// Latência de filtro: alterna UF SP e espera o React atualizar o resumo.
const latencies = [];
for (let i = 0; i < 20; i += 1) {
  const ms = await page.evaluate(async () => {
    const checkbox = [...document.querySelectorAll('input[type="checkbox"]')].find(
      (input) => input.parentElement?.textContent?.trim() === "SP",
    );
    const target = document.querySelector(".intro-strip");
    const start = performance.now();
    const changed = new Promise((resolveChange) => {
      const observer = new MutationObserver(() => {
        observer.disconnect();
        requestAnimationFrame(() => resolveChange());
      });
      observer.observe(target, { subtree: true, childList: true, characterData: true });
    });
    checkbox.click();
    await changed;
    return performance.now() - start;
  });
  latencies.push(ms);
}
latencies.sort((a, b) => a - b);
const p50 = latencies[Math.floor(latencies.length * 0.5)];
const p95 = latencies[Math.floor(latencies.length * 0.95) - 1] ?? latencies.at(-1);

// O mapa só é montado quando a seção se aproxima da viewport.
const tMap = Date.now();
await page.evaluate(() => {
  const el = document.querySelector(".map-placeholder") ?? document.querySelector(".map-section");
  el?.scrollIntoView({ block: "center" });
});
await page.waitForFunction(() => window.__map?.loaded?.() === true, null, { timeout: 30000 });
const mapReadyAfterScrollMs = Date.now() - tMap;
const totalWithMapMs = Date.now() - t0;
const finalGroups = await resourceGroups();

const nav = await page.evaluate(() => {
  const entry = performance.getEntriesByType("navigation")[0];
  return entry
    ? {
        domContentLoadedMs: Math.round(entry.domContentLoadedEventEnd),
        loadMs: Math.round(entry.loadEventEnd),
        transferBytes: entry.transferSize,
      }
    : null;
});
const env = await page.evaluate(() => ({
  userAgent: navigator.userAgent,
  hardwareConcurrency: navigator.hardwareConcurrency,
  deviceMemory: navigator.deviceMemory ?? null,
}));

const summary = {
  maquina: {
    os: process.platform,
    cpu: (await import("node:os")).cpus()[0]?.model?.trim(),
    userAgent: env.userAgent,
    hardwareConcurrency: env.hardwareConcurrency,
    deviceMemory: env.deviceMemory,
    node: process.version,
  },
  perfil: {
    viewport: "1440x1000",
    rede: "localhost, sem throttling; contexto novo, sem cache",
    data: new Date().toISOString(),
  },
  carga: {
    cardsReadyMs,
    socioReadyMs,
    navegacao: nav,
    transferenciaInicial: initialGroups,
    transferenciaComMapa: finalGroups,
    mapReadyAfterScrollMs,
    totalWithMapMs,
  },
  filtro_uf: {
    amostra: latencies.length,
    p50Ms: Number(p50.toFixed(1)),
    p95Ms: Number(p95.toFixed(1)),
    minMs: Number(Math.min(...latencies).toFixed(1)),
    maxMs: Number(Math.max(...latencies).toFixed(1)),
  },
  perfil_movel_4g: null,
};

// Perfil móvel documentado: 360x800, 4G (1,6 Mbps down / 750 kbps up, 150 ms RTT), CPU 4x.
{
  const mobile = await browser.newContext({ viewport: { width: 360, height: 800 }, deviceScaleFactor: 1 });
  const mobilePage = await mobile.newPage();
  const client = await mobile.newCDPSession(mobilePage);
  await client.send("Network.enable");
  await client.send("Network.emulateNetworkConditions", {
    offline: false,
    downloadThroughput: (1.6 * 1024 * 1024) / 8,
    uploadThroughput: (750 * 1024) / 8,
    latency: 150,
  });
  await client.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  const tm = Date.now();
  await mobilePage.goto(BASE, { waitUntil: "domcontentloaded" });
  await mobilePage.getByRole("heading", { name: "Recorte selecionado" }).waitFor({ timeout: 60000 });
  const mobileCardsReadyMs = Date.now() - tm;
  const tMobileSocio = Date.now();
  await mobilePage.locator('[data-socio-ready="1"]').waitFor({ timeout: 60000 });
  const mobileSocioReadyMs = Date.now() - tMobileSocio;
  const mobileGroups = await mobilePage.evaluate(() => {
    const entries = performance.getEntriesByType("resource");
    let transferBytes = 0;
    let requests = 0;
    for (const entry of entries) {
      transferBytes += entry.transferSize || 0;
      requests += 1;
    }
    const paints = performance.getEntriesByType("paint");
    const fcp = paints.find((p) => p.name === "first-contentful-paint");
    return { requests, transferBytes, firstContentfulPaintMs: fcp ? Math.round(fcp.startTime) : null };
  });
  const mapRequested = await mobilePage.evaluate(() =>
    performance.getEntriesByType("resource").some((entry) => entry.name.includes("maplibre-gl-")),
  );
  summary.perfil_movel_4g = {
    viewport: "360x800",
    rede: "4G emulado: 1,6 Mbps down, 750 kbps up, 150 ms RTT; CPU 4x",
    cardsReadyMs: mobileCardsReadyMs,
    socioReadyMs: mobileSocioReadyMs,
    firstContentfulPaintMs: mobileGroups.firstContentfulPaintMs,
    requests: mobileGroups.requests,
    transferBytes: mobileGroups.transferBytes,
    mapaCarregadoAntesDaSecao: mapRequested,
  };
  await mobile.close();
}

// Mesmo 4G, sem throttling de CPU, para separar rede de processamento.
{
  const mobile = await browser.newContext({ viewport: { width: 360, height: 800 }, deviceScaleFactor: 1 });
  const mobilePage = await mobile.newPage();
  const client = await mobile.newCDPSession(mobilePage);
  await client.send("Network.enable");
  await client.send("Network.emulateNetworkConditions", {
    offline: false,
    downloadThroughput: (1.6 * 1024 * 1024) / 8,
    uploadThroughput: (750 * 1024) / 8,
    latency: 150,
  });
  const tm = Date.now();
  await mobilePage.goto(BASE, { waitUntil: "domcontentloaded" });
  await mobilePage.getByRole("heading", { name: "Recorte selecionado" }).waitFor({ timeout: 60000 });
  const ms = Date.now() - tm;
  const paint = await mobilePage.evaluate(() => {
    const fcp = performance.getEntriesByType("paint").find((p) => p.name === "first-contentful-paint");
    return fcp ? Math.round(fcp.startTime) : null;
  });
  summary.perfil_movel_4g_cpu1 = {
    viewport: "360x800",
    rede: "4G emulado: 1,6 Mbps down, 750 kbps up, 150 ms RTT; CPU sem throttling",
    cardsReadyMs: ms,
    firstContentfulPaintMs: paint,
  };
  await mobile.close();
}

writeFileSync(OUT, JSON.stringify(summary, null, 2) + "\n", "utf8");
console.log(JSON.stringify(summary, null, 2));
await browser.close();
