import type { Aggregate, Nacional } from "../types";
import {int, signedInt} from "../format";

export function transition(l1:number,f1:number,l2:number,f2:number) {
 return {lula:l2-l1,flavio:f2-f1,margin1:l1-f1,margin2:l2-f2,change:(l2-f2)-(l1-f1)};
}

export default function TurnChange({agg,nacional,filtered}:{agg:Aggregate;nacional:Nacional;filtered:boolean}) {
 const t1=nacional.totais.t1, t2=nacional.totais.t2;
 const a=agg.counts;
 const l1=filtered?a.qt_lula_t1:t1.lula, f1=filtered?a.qt_flavio_t1:t1.flavio;
 const l2=filtered?a.qt_lula_t2:t2.lula, f2=filtered?a.qt_flavio_t2:t2.flavio;
 const d=transition(l1,f1,l2,f2);
 const c1=filtered?a.qt_comparecimento_t1:t1.comparecimento;
 const c2=filtered?a.qt_comparecimento_t2:t2.comparecimento;
 const invalid1=filtered?a.qt_votos_brancos_t1+a.qt_votos_nulos_t1:t1.votos_brancos+t1.votos_nulos;
 const invalid2=filtered?a.qt_votos_brancos_t2+a.qt_votos_nulos_t2:t2.votos_brancos+t2.votos_nulos;
 const others=filtered?a.qt_votos_validos_t1-l1-f1:c1-invalid1-l1-f1;
 const validChange=filtered?a.qt_votos_validos_t2-a.qt_votos_validos_t1:(l2+f2)-(c1-invalid1);
 return <section className="turn-change" aria-labelledby="turn-change-title">
  <p className="eyebrow">Do primeiro ao segundo turno</p>
  <h2 id="turn-change-title">Como mudou a disputa entre Lula e Flávio Bolsonaro?</h2>
  <p>{filtered?`Recorte atual: ${int(agg.municipios)} municípios do território, nas mesmas unidades pareadas entre turnos.`:"Resultado oficial nacional, incluindo exterior. Use os filtros para investigar onde a mudança se concentrou."}</p>
  <div className="turn-change-table"><table><caption>Votos e mudança da margem entre turnos</caption>
   <thead><tr><th scope="col">Medida</th><th scope="col">1º turno</th><th scope="col">2º turno</th><th scope="col">Diferença</th></tr></thead>
   <tbody><tr><th scope="row">Lula</th><td>{int(l1)}</td><td>{int(l2)}</td><td>{signedInt(d.lula)}</td></tr>
   <tr><th scope="row">Flávio Bolsonaro</th><td>{int(f1)}</td><td>{int(f2)}</td><td>{signedInt(d.flavio)}</td></tr>
   <tr><th scope="row">Margem Lula − Flávio</th><td>{signedInt(d.margin1)}</td><td>{signedInt(d.margin2)}</td><td>{signedInt(d.change)}</td></tr></tbody>
  </table></div>
  <p><strong>A conta da mudança:</strong> ganho de Lula ({signedInt(d.lula)}) menos ganho de Flávio ({signedInt(d.flavio)}) = {signedInt(d.change)} votos de mudança da margem. Margem negativa indica vantagem de Flávio; positiva, de Lula.</p>
  <details><summary>Comparecimento, brancos/nulos e outros candidatos: o que a conta mostra?</summary>
   <p>O comparecimento variou {signedInt(c2-c1)} e os brancos/nulos variaram {signedInt(invalid2-invalid1)}. Os demais candidatos tinham {int(others)} votos válidos no 1º turno.</p>
   <p>Outros válidos no 1º turno ({int(others)}) + variação dos válidos ({signedInt(validChange)}) = ganho conjunto dos finalistas ({signedInt(d.lula+d.flavio)}).</p>
   <p>São saldos agregados. A conta não identifica quem mudou de candidato, voltou a votar ou deixou de votar branco/nulo, nem permite atribuir todos os votos dos demais candidatos a Lula.</p>
  </details>
 </section>;
}
