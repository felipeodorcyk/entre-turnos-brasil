import {describe,it,expect} from "vitest";
import {readFileSync} from "node:fs";
import {groups,bucket,gains,dimensions} from "./profiles";
import {aggregate} from "./query";
import type {Municipio,Faixas} from "../types";
const read=(p:string)=>JSON.parse(readFileSync(p,"utf8"));
const id=read("public/release/current.json").release_id;
const table=read(`public/release/${id}/municipios.json`);
const rows:Municipio[]=table.rows.map((r:unknown[])=>Object.fromEntries(table.fields.map((k:string,i:number)=>[k,r[i]])));
const faixas:Faixas=read(`public/release/${id}/faixas.json`);
describe("profile partitions",()=>{
 for(const dim of Object.keys(dimensions) as (keyof typeof dimensions)[])it(`reconciles all votes for ${dim}`,()=>{
  const gs=groups(rows,dim,faixas);const total=aggregate(rows);
  expect(gs.reduce((s,g)=>s+g.rows.length,0)).toBe(rows.length);
  for(const [k,v] of Object.entries(total.counts))expect(gs.reduce((s,g)=>s+g.agg.counts[k as keyof typeof total.counts],0)).toBe(v);
  expect(gs.reduce((s,g)=>s+(gains(g.agg)[0]??0),0)).toBe(gains(total)[0]);
 });
 it("keeps missing context separate",()=>expect(bucket({...rows[0],cd_ibge:"unknown"},"agro",faixas)).toBe("Sem informação"));
 it("computes shares from sums and supports reductions",()=>{
  const a={...rows[0],qt_lula_t1:20,qt_lula_t2:10,qt_flavio_t1:10,qt_flavio_t2:20,qt_votos_validos_t1:100,qt_votos_validos_t2:100};
  expect(gains(aggregate([a]))).toEqual([-10,10]);expect(gains(aggregate([a]),true)).toEqual([-10,10]);
 });
});
