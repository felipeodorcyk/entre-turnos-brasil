import type {Municipio,Nacional} from "../types";
import {aggregate} from "./query";
export type Granularity="municipal"|"estadual"|"regional";
export function geographicRows(rows:Municipio[],allRows:Municipio[],level:Granularity):Municipio[]{
 if(level==="municipal")return rows;
 const key=(r:Municipio)=>level==="estadual"?r.sg_uf:r.regiao;
 const partitions=new Map<string,Municipio[]>();for(const r of rows){const k=key(r);const a=partitions.get(k)??[];a.push(r);partitions.set(k,a);}
 const totals=new Map([...partitions].map(([k,rs])=>[k,aggregate(rs).counts]));
 return allRows.filter(r=>totals.has(key(r))).map(r=>({...r,...totals.get(key(r)),nome:key(r)}));
}
export function nationalContribution(counts:ReturnType<typeof aggregate>["counts"],national:Nacional["totais"]){
 const valid=(t:"t1"|"t2")=>national[t].comparecimento-national[t].votos_brancos-national[t].votos_nulos;
 return valid("t1")>0&&valid("t2")>0?100*((counts.qt_lula_t2-counts.qt_flavio_t2)/valid("t2")-(counts.qt_lula_t1-counts.qt_flavio_t1)/valid("t1")):null;
}
