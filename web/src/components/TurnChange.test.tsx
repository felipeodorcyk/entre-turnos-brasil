import {describe,it,expect} from "vitest";
import {transition} from "./TurnChange";
describe("arithmetic of changes between rounds",()=>{
 it("reconciles first-round deficit, both gains and second-round margin",()=>{
  const d=transition(53879538,56104503,64256232,59826041);
  expect(d).toEqual({lula:10376694,flavio:3721538,margin1:-2224965,margin2:4430191,change:6655156});
  expect(d.lula-d.flavio).toBe(d.margin2-d.margin1);
 });
 it("does not assume every filtered area moved toward Lula",()=>{
  expect(transition(20,30,25,50).change).toBe(-15);
 });
});
