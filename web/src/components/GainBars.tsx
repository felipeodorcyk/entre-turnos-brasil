import {nationalContribution} from "../engine/geography";
import type {Aggregate,Nacional} from "../types";
import {gains} from "../engine/profiles";import {signedInt,pp,int} from "../format";
import {barDomain,barGeometry} from "../engine/barScale";
export default function GainBars({agg,percent=false,domain}:{agg:Aggregate;percent?:boolean;domain?:[number,number]}){
 const values=gains(agg,percent);const bounds=domain??barDomain(values);const zero=barGeometry(0,bounds).zero;
 return <div className="gain-bars"><div className="gain-axis" aria-hidden="true">{bounds[0]<0?"Redução ← 0 → Ganho":"0 → Ganho"}</div>{values.map((v,i)=>{const g=barGeometry(v,bounds);return <div key={i} className="gain-row"><span>{i===0?"Lula":"Flávio"}</span><div className="gain-track" style={{background:"#eee"}}><span style={{position:"absolute",left:`${zero}%`,height:"100%",borderLeft:"1px solid #777"}}/><i style={{background:i===0?"#c9343d":"#18804b",width:`${g.width}%`,left:`${g.left}%`}}/></div><b>{v===null?"Não calculável":percent?pp(v):signedInt(v)}</b></div>})}</div>;
}

export function VoteDetails({agg,national}:{agg:Aggregate;national:Nacional["totais"]}){
 const c=agg.counts;const contribution=nationalContribution(c,national);
 return <div className="vote-detail"><table><caption>Votos em cada turno</caption><thead><tr><th>Candidato</th><th>1º turno</th><th>2º turno</th></tr></thead><tbody><tr><th>Lula</th><td>{int(c.qt_lula_t1)}</td><td>{int(c.qt_lula_t2)}</td></tr><tr><th>Flávio</th><td>{int(c.qt_flavio_t1)}</td><td>{int(c.qt_flavio_t2)}</td></tr></tbody></table><p>Diferença no 1º turno: {signedInt(c.qt_lula_t1-c.qt_flavio_t1)} · no 2º: {signedInt(c.qt_lula_t2-c.qt_flavio_t2)} · mudança: {signedInt(agg.delta_margem_votos)} votos.</p><p><b>{pp(contribution)}</b> de contribuição à mudança da margem nacional.</p><small>Usa os votos válidos nacionais de cada turno, incluindo exterior. Positivo favorece Lula; negativo, Flávio. Veja a fórmula na metodologia.</small></div>;
}
