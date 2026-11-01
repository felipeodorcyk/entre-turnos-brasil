import {nationalContribution} from "../engine/geography";
import type {Aggregate,Nacional} from "../types";
import {gains} from "../engine/profiles";import {signedInt,pp,int} from "../format";
import {barDomain,barGeometry} from "../engine/barScale";
export default function GainBars({agg,percent=false,domain}:{agg:Aggregate;percent?:boolean;domain?:[number,number]}){
 const values=gains(agg,percent);const bounds=domain??barDomain(values);const zero=barGeometry(0,bounds).zero;
 return <div className="gain-bars"><div className="gain-axis"><span>{percent?pp(bounds[0]):int(bounds[0])}</span><span className="sr-only">{percent?"Variação em p.p.":"Ganho de votos"}</span><span>{percent?pp(bounds[1]):int(bounds[1])}</span></div>{values.map((v,i)=>{const g=barGeometry(v,bounds);return <div key={i} className="gain-row"><span>{i===0?"Lula":"Flávio"}</span><div className="gain-track" style={{background:"#eee"}}><span style={{position:"absolute",left:`${zero}%`,height:"100%",borderLeft:"1px solid #777"}}/><i style={{background:i===0?"#c9343d":"#18804b",width:`${g.width}%`,left:`${g.left}%`}}/></div><b>{v===null?"Não calculável":percent?pp(v):signedInt(v)}</b></div>})}</div>;
}

export function VoteDetails({agg,national,compact=false}:{agg:Aggregate;national:Nacional["totais"];compact?:boolean}){
 const c=agg.counts;const contribution=nationalContribution(c,national);
 return <div className="vote-detail"><table><caption>Votos por candidato e turno</caption><colgroup><col className="candidate-col"/><col/><col/></colgroup><thead><tr><th scope="col">Candidato</th><th scope="col">1º turno</th><th scope="col">2º turno</th></tr></thead><tbody><tr><th scope="row"><span className="candidate-dot lula-dot"/>Lula</th><td>{int(c.qt_lula_t1)}</td><td>{int(c.qt_lula_t2)}</td></tr><tr><th scope="row"><span className="candidate-dot flavio-dot"/>Flávio</th><td>{int(c.qt_flavio_t1)}</td><td>{int(c.qt_flavio_t2)}</td></tr></tbody></table><dl className="margin-details"><div><dt>Diferença no 1º turno</dt><dd>{signedInt(c.qt_lula_t1-c.qt_flavio_t1)}</dd></div><div><dt>Diferença no 2º turno</dt><dd>{signedInt(c.qt_lula_t2-c.qt_flavio_t2)}</dd></div><div><dt>Mudança da diferença</dt><dd>{signedInt(agg.delta_margem_votos)} votos</dd></div></dl><div className="contribution"><strong>{pp(contribution)}</strong><span>Contribuição à mudança da margem nacional</span></div>{!compact&&<small className="contribution-note">Válidos nacionais de cada turno, incluindo exterior. Positivo favorece Lula; negativo, Flávio. Fórmula na metodologia.</small>}</div>;
}
