import {it,expect} from "vitest";import {validateContext,verifyContext} from "./context";import {readFileSync} from "node:fs";import {createHash,webcrypto} from "node:crypto";
const id="60e342117a4675f3";const raw=readFileSync(`public/context/${id}.json`);const value=JSON.parse(raw.toString());
it("accepts valid snapshot and rejects wrong identity",()=>{expect(validateContext(value,id).id).toBe(id);expect(()=>validateContext(value,"other")).toThrow();});
it.each([null,{...value,rows:[]},{...value,rows:{}},{...value,sources:[]},{...value,rows:{bad:{populacao:1,agro:2}}},{...value,rows:{"1234567":{populacao:-1,agro:1}}},{...value,rows:{"1234567":{populacao:"1",agro:1}}}])("rejects incompatible structures",v=>expect(()=>validateContext(v,id)).toThrow());
it("rejects corrupted and unregistered bytes",async()=>{Object.defineProperty(globalThis,"crypto",{value:webcrypto,configurable:true});const bytes=Uint8Array.from(raw).buffer;const hash=createHash("sha256").update(raw).digest("hex");await expect(verifyContext(bytes,hash)).resolves.toBeUndefined();await expect(verifyContext(bytes,"0".repeat(64))).rejects.toThrow();await expect(verifyContext(bytes,undefined)).rejects.toThrow();});

