import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { loadRelease, requestedRelease } from "./load";
const read = (p:string) => JSON.parse(readFileSync(`public/release/${p}`, "utf8"));
const pointer = read("current.json");
afterEach(() => vi.unstubAllGlobals());
describe("snapshot loading", () => {
 it("loads requested A without consulting current B", async () => {
   const fetch = vi.fn(async (path:string) => ({ok:true, json:async () => read(path.replace(/^.*release\//,""))}));
   vi.stubGlobal("fetch",fetch);
   const data = await loadRelease(`#release=${pointer.release_id}`);
   expect(data.releaseId).toBe(pointer.release_id);
   expect(fetch.mock.calls.some(([p])=>p.includes("current.json"))).toBe(false);
 });
 it("rejects traversal and unavailable snapshots", async () => {
   expect(()=>requestedRelease("#release=../../secret")).toThrow();
   vi.stubGlobal("fetch",vi.fn(async()=>({ok:false,status:404})));
   await expect(loadRelease("#release=p0-missing")).rejects.toThrow("404");
 });
});
