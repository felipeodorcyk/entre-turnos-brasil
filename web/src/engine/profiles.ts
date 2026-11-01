import {validateContext,verifyContext} from "./context";
import type {Municipio,Faixas} from "../types";
import {aggregate} from "./query";
import integrity from "../data/context-integrity.json";
import context from "../data/profiles-context.json";
export let CONTEXT_ID=context.id;
export let SOURCES=context.sources;
let extra=context.rows as Record<string,{populacao:number|null;agro:number|null}>;
export const dimensions={regiao:"Região",sg_uf:"Estado",renda_pc:"Renda",vinculos:"Emprego formal",desocupacao:"Desemprego",pbf:"Bolsa Família",urbana:"Urbanização",populacao:"Tamanho das cidades",agro:"Agropecuária"};
export type Dimension=keyof typeof dimensions;
export function bucket(row:Municipio,dim:Dimension,faixas:Faixas):string {
 if(dim==="regiao"||dim==="sg_uf")return row[dim];
 const v=dim==="populacao"||dim==="agro"?extra[row.cd_ibge]?.[dim]:row[dim];
 if(v===null||v===undefined||!Number.isFinite(v))return "Sem informação";
 const cuts=dim==="populacao"?[20000,100000,500000]:dim==="agro"?[5,20,40]:null;
 if(cuts){const labels=dim==="populacao"?["Menos de 20 mil habitantes","20 mil a menos de 100 mil","100 mil a menos de 500 mil","500 mil ou mais habitantes"]:["Menos de 5% do VAB","5% a menos de 20%","20% a menos de 40%","40% ou mais do VAB"];return labels[cuts.findIndex(c=>v<c)===-1?3:cuts.findIndex(c=>v<c)];}
 const bands=faixas.indicadores[dim]??[];
 for(const b of bands)if(b.corte_superior===null||v<=b.corte_superior)return `Faixa ${b.faixa}: ${b.valor_min?.toLocaleString("pt-BR")} a ${b.valor_max?.toLocaleString("pt-BR")}`;
 return "Sem informação";
}
export function groups(rows:Municipio[],dim:Dimension,faixas:Faixas){
 const map=new Map<string,Municipio[]>();for(const row of rows){const k=bucket(row,dim,faixas);map.set(k,[...(map.get(k)??[]),row]);}
 return [...map].sort(([a],[b])=>a==="Sem informação"?1:b==="Sem informação"?-1:dim==="populacao"?(["Menos de 20 mil habitantes","20 mil a menos de 100 mil","100 mil a menos de 500 mil","500 mil ou mais habitantes"].indexOf(a)-["Menos de 20 mil habitantes","20 mil a menos de 100 mil","100 mil a menos de 500 mil","500 mil ou mais habitantes"].indexOf(b)):dim==="agro"?(["Menos de 5% do VAB","5% a menos de 20%","20% a menos de 40%","40% ou mais do VAB"].indexOf(a)-["Menos de 5% do VAB","5% a menos de 20%","20% a menos de 40%","40% ou mais do VAB"].indexOf(b)):a.localeCompare(b,"pt-BR",{numeric:true})).map(([key,rows])=>({key,rows,agg:aggregate(rows)}));
}
export function gains(a:ReturnType<typeof aggregate>,percent=false){return percent?[a.delta_participacao_lula_pp,a.delta_participacao_flavio_pp]:[a.counts.qt_lula_t2-a.counts.qt_lula_t1,a.counts.qt_flavio_t2-a.counts.qt_flavio_t1];}

export async function restoreContext(id:string){
 if(id===CONTEXT_ID)return;
 if(!/^[a-f0-9]{16}$/.test(id))throw new Error("Identificador de contexto inválido");
 const response=await fetch(`${import.meta.env.BASE_URL}context/${id}.json`);
 if(!response.ok)throw new Error("Snapshot histórico de contexto indisponível");
 const bytes=await response.arrayBuffer();
 const expected=(integrity as Record<string,string>)[id];
 await verifyContext(bytes,expected);
 const value=validateContext(JSON.parse(new TextDecoder().decode(bytes)),id);
 extra=value.rows;SOURCES=value.sources;CONTEXT_ID=id;
}

export function groupLabel(key:string,dim:Dimension):string {
 if(key==="Sem informação")return key;
 if(dim==="populacao")return ({"Menos de 20 mil habitantes":"Cidades pequenas · menos de 20 mil habitantes", "20 mil a menos de 100 mil":"Cidades de 20 mil a 100 mil habitantes", "100 mil a menos de 500 mil":"Cidades de 100 mil a 500 mil habitantes", "500 mil ou mais habitantes":"Grandes cidades · 500 mil habitantes ou mais"} as Record<string,string>)[key]??key;
 if(dim==="agro")return ({"Menos de 5% do VAB":"Pouco peso da agropecuária", "5% a menos de 20%":"Peso intermediário da agropecuária", "20% a menos de 40%":"Peso elevado da agropecuária", "40% ou mais do VAB":"Peso muito elevado da agropecuária"} as Record<string,string>)[key]??key;
 const units:Record<string,string>={renda_pc:"R$ por pessoa",vinculos:"vínculos por mil habitantes",desocupacao:"% de desocupação",pbf:"registros por 100 domicílios",urbana:"% da população urbana"};
 const levels=["Menores valores","Valores intermediários baixos","Valores intermediários","Valores intermediários altos","Maiores valores"];
 return key.replace(/^Faixa (\d+): /,(_,n)=>`${levels[Number(n)-1]??`Grupo ${n}`} · `)+(units[dim]?` ${units[dim]}`:"");
}
