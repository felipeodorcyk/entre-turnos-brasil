import type {Municipio,Faixas} from "../types";
import {groups,groupLabel,dimensions,type Dimension} from "../engine/profiles";
import {signedInt,pp} from "../format";
export default function Narrative({rows,faixas,dimension}:{rows:Municipio[];faixas:Faixas;dimension:Dimension}){
 if(!rows.length)return <p role="status">Nenhum município corresponde a esta seleção. Remova um filtro para continuar.</p>;
 const regions=groups(rows,"regiao",faixas).sort((a,b)=>b.agg.delta_margem_votos-a.agg.delta_margem_votos);
 const states=groups(rows,"sg_uf",faixas).sort((a,b)=>Math.abs(b.agg.delta_margem_votos)-Math.abs(a.agg.delta_margem_votos));
 const profiles=groups(rows,dimension,faixas).filter(g=>g.key!=="Sem informação");
 const first=regions[0],last=regions.at(-1)!;
 return <div className="narrative" aria-live="polite"><p>Neste recorte, {first.key} apresenta o maior saldo da mudança Lula − Flávio ({signedInt(first.agg.delta_margem_votos)} votos){regions.length>1?`, enquanto ${last.key} registra ${signedInt(last.agg.delta_margem_votos)} votos`:""}. Entre os estados, {states.slice(0,3).map(g=>`${g.key} (${signedInt(g.agg.delta_margem_votos)} votos)`).join(", ")} se destacam pela magnitude da mudança.</p>{dimension!=="regiao"&&dimension!=="sg_uf"&&<p>Valores positivos favorecem Lula; negativos, Flávio. Na comparação por {dimensions[dimension].toLowerCase()}, {profiles.length>1?profiles.filter((_,i)=>i===0||i===profiles.length-1).map(g=>`${groupLabel(g.key,dimension)}: Lula ${pp(g.agg.delta_participacao_lula_pp)} e Flávio ${pp(g.agg.delta_participacao_flavio_pp)} de participação nos votos válidos`).join("; "):profiles.map(g=>`${groupLabel(g.key,dimension)} registra Lula ${pp(g.agg.delta_participacao_lula_pp)} e Flávio ${pp(g.agg.delta_participacao_flavio_pp)} nos votos válidos`).join("")}. São características dos municípios, não dos eleitores individualmente. A associação não demonstra causa nem transferência de votos.</p>}</div>;
}
