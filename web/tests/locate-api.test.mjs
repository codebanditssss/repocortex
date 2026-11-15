import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Compile the real route for Node's test runner, resolving its Next path alias.
const source = (await readFile(new URL("../app/api/locate/route.ts", import.meta.url), "utf8"))
  .replace('"@/lib/request-body"', JSON.stringify(new URL("../lib/request-body.ts", import.meta.url).href))
  .replace('"@/lib/live"', JSON.stringify(new URL("../lib/live.ts", import.meta.url).href));
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ESNext } }).outputText;
const { POST } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("locate proxy preserves retryable service failures without exposing backend details", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ error: "private backend detail" }, { status: 503 }));
  const result = await POST(new Request("http://localhost/api/locate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report: "QuerySet ordering fails" }) }));
  assert.equal(result.status, 503);
  assert.equal(result.headers.get("Retry-After"), "5");
  assert.doesNotMatch(JSON.stringify(await result.json()), /private backend detail/);
});

test("locate proxy forwards Unicode reports and preserves upstream size errors", async (t) => {
  let forwarded;
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    forwarded = JSON.parse(options.body);
    return Response.json({ error: "report too large" }, { status: 413 });
  });
  for (const report of ["错".repeat(12000), "😀".repeat(6000)]) {
    const request = new Request("http://localhost/api/locate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report }) });
    const result = await POST(request);
    assert.equal(result.status, 413);
    assert.equal(forwarded.report, report);
    assert.match((await result.json()).error, /too large/i);
  }
});

 test("proxy rejects cross-site form-compatible content types before contacting upstream", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", () => { throw new Error("must not call upstream"); });
  const result = await POST(new Request("http://localhost/api/locate", { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify({ report: "bug" }) }));
  assert.equal(result.status, 415);
  assert.equal(fetch.mock.callCount(), 0);
});
