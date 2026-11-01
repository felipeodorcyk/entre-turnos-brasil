export function barDomain(values:(number|null)[]):[number,number]{const v=values.filter((x):x is number=>x!==null&&Number.isFinite(x));const lo=Math.min(0,...v),hi=Math.max(0,...v);return lo===hi?[0,1]:[lo,hi];}
export function barGeometry(value:number|null,domain:[number,number]){const [lo,hi]=domain;const span=hi-lo;return {zero:100*Math.abs(lo)/span,left:100*(Math.min(0,value??0)-lo)/span,width:100*Math.abs(value??0)/span};}

