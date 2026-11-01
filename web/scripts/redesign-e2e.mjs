import {mkdirSync as ensureEvidenceDirectory} from "node:fs";
ensureEvidenceDirectory("../docs/webapp/evidence",{recursive:true});
import {chromium} from "playwright";import assert from "node:assert/strict";
const browser=await chromium.launch({channel:"chrome",headless:true});
try {for(const width of [1440,768,390,360]){
 const page=await browser.newPage({viewport:{width,height:1000}});const errors=[];page.on("pageerror",e=>errors.push(e.message));
 await page.goto(`${process.env.APP_URL??"http://127.0.0.1:4182"}/?view=explore`);await page.getByRole("heading",{name:"Como a mudança se distribuiu?"}).waitFor();
 await page.locator(".legend-title").filter({hasText:"Mudança da margem — votos"}).waitFor();assert.equal(await page.getByText("Comece por uma descoberta",{exact:true}).count(),0);assert.equal(await page.getByText("Ver no mapa",{exact:true}).count(),0);
 const panel=page.locator("#perspectives");
 for(const name of ["Renda","Emprego formal","Desemprego","Bolsa Família","Agropecuária","Tamanho das cidades"]){
 await panel.getByRole("button",{name,exact:true}).click();await page.locator(".group-choices button").nth(1).click();
 assert.ok(page.url().includes("profile="));assert.equal(await page.locator(".group-choices button[aria-pressed=true]").count(),1);
 assert.ok(await page.locator(".profile-group").count()>0);assert.ok((await page.locator(".scope-heading").innerText()).includes(name));
 }
 const url=page.url();await page.reload();await panel.waitFor();assert.equal(page.url(),url);
 await page.waitForFunction(()=>window.__map?.querySourceFeatures("municipios")?.some(f=>f.properties.inScope===0));
 const counts=await page.evaluate(()=>{const f=window.__map.querySourceFeatures("municipios");return [f.filter(x=>x.properties.inScope===1).length,f.filter(x=>x.properties.inScope===0).length]});assert.ok(counts[0]>0&&counts[1]>0);
 await page.locator(".group-choices button").first().click();await panel.getByRole("button",{name:"Região",exact:true}).click();await page.screenshot({path:`../docs/webapp/evidence/redesign_${width}.png`,fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);console.log(`PASS ${width}: shared scope, map mask, narratives, reload, responsive`);await page.close();
}}finally{await browser.close();}



