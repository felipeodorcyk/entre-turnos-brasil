import {chromium} from "playwright";
import {readFileSync} from "node:fs";
import assert from "node:assert/strict";
const pointer=JSON.parse(readFileSync("public/release/current.json"));
const browser=await chromium.launch({channel:"chrome",headless:true});
try {
 const page=await browser.newPage();
 let fail=true;
 await page.route("**/socio.json",r=>fail?r.fulfill({status:503,body:"unavailable"}):r.continue());
 await page.goto(`http://127.0.0.1:4176/#release=${pointer.release_id}&renda=500:1000&metrica=participacao_lula_t1`);
 await page.getByText("Consulta indisponível até recuperar os indicadores.").waitFor();
 assert.equal(await page.getByRole("heading",{name:"Recorte selecionado"}).count(),0);
 fail=false;
 await page.getByRole("button",{name:"Tentar novamente",exact:true}).click();
 await page.getByRole("heading",{name:"Recorte selecionado"}).waitFor();
 await page.getByRole("button",{name:"Baixar CSV filtrado",exact:true}).waitFor({state:"visible"});
 assert.equal(await page.getByText("Consulta indisponível até recuperar os indicadores.").count(),0);
 // Old link succeeds even when current is unavailable: no implicit migration.
 await page.route("**/current.json",r=>r.fulfill({status:503,body:"current B unavailable"}));
 await page.reload();
 await page.getByRole("heading",{name:"Recorte selecionado"}).waitFor();
 await page.getByText("Cobertura e ausências",{exact:true}).scrollIntoViewIfNeeded();
 const metric=page.locator("select").filter({has:page.locator('option[value="participacao_lula_t1"]')});
 await metric.waitFor(); assert.equal(await metric.inputValue(),"participacao_lula_t1");
 // Manifest failure is explicit and retryable.
 await page.unroute("**/current.json");
 await page.route("**/manifest.json",r=>r.fulfill({status:503,body:"unavailable"}));
 await page.goto("http://127.0.0.1:4176/");
 await page.getByRole("button",{name:"Metodologia",exact:true}).click();
 await page.getByText(/Falha no manifesto:/).waitFor();
 await page.unroute("**/manifest.json");
 await page.getByRole("button",{name:"Tentar novamente",exact:true}).click();
 await page.getByText(/Falha no manifesto:/).waitFor({state:"hidden"});
 console.log("PASS: saved filters, failed socioeconomic request/retry, pinned release, T1 layer, manifest error/retry");
} finally {await browser.close();}
