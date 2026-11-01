export function validateContext(value:unknown,id:string){
 const v=value as {id:string;rows:Record<string,{populacao:number|null;agro:number|null}>;sources:{field:string;year:string;url:string;sha256:string;count:number}[]};
 if(!v||v.id!==id||!v.rows||Array.isArray(v.rows)||typeof v.rows!=="object"||!Object.keys(v.rows).length||!Array.isArray(v.sources))throw new Error("Contexto incompatível");
 for(const field of ["populacao","agro"])if(!v.sources.some(s=>s.field===field&&/^\d{4}$/.test(s.year)&&Number.isInteger(s.count)&&/^https:\/\//.test(s.url)&&/^[a-f0-9]{64}$/.test(s.sha256)))throw new Error("Fonte de contexto inválida");
 for(const [code,r] of Object.entries(v.rows))if(!/^\d{7}$/.test(code)||!r||![r.populacao,r.agro].every(x=>x===null||(typeof x==="number"&&Number.isFinite(x)))||(r.populacao!==null&&r.populacao<0))throw new Error("Campos de contexto inválidos");
 return v;
}
export async function verifyContext(bytes:ArrayBuffer,expected:string|undefined){
 const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))).map(v=>v.toString(16).padStart(2,"0")).join("");
 if(!expected||digest!==expected)throw new Error("Integridade do contexto não confirmada");
}


