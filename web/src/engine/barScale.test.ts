import {it,expect} from "vitest";import {barDomain,barGeometry} from "./barScale";
it("uses whole width for positive gains",()=>{const d=barDomain([10,100]);expect(d).toEqual([0,100]);expect(barGeometry(100,d)).toEqual({zero:0,left:0,width:100});});
it("keeps proportional losses and common zero",()=>{const d=barDomain([-10,90]);expect(barGeometry(-10,d)).toEqual({zero:10,left:0,width:10});expect(barGeometry(90,d)).toEqual({zero:10,left:10,width:90});});
it("handles negative-only, zeros and missing",()=>{expect(barDomain([-30,-10])).toEqual([-30,0]);expect(barDomain([0,null])).toEqual([0,1]);expect(barGeometry(null,[0,1]).width).toBe(0);});
