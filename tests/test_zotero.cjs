const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const code = fs.readFileSync("zotero/bootstrap.js", "utf8");

function context(items, byURI = items[0]) {
  const Zotero = {
    URI: { getURIItem: async () => byURI },
    Search: class { addCondition() {} async search() { return items.map(i => i.id); } },
    Items: { getAsync: async () => items }
  };
  const ctx = vm.createContext({ Zotero });
  vm.runInContext(code, ctx);
  return ctx;
}
function item(doi = "10.1234/abc", libraryID = 1) {
  return { id: 1, libraryID, key: "ABCD1234", deleted: false, isRegularItem: () => true,
    getField: field => field === "DOI" ? doi : "Test Paper", getAttachments: () => [] };
}
test("URI preserves exact parent; wrong library and DOI conflicts are refused", async () => {
  const parent = item();
  const ctx = context([parent]);
  const record = { title: "Test Paper", doi: "10.1234/abc", source: { id: "http://zotero.org/users/1/items/ABCD1234" } };
  assert.equal(await ctx.findParent(record, 1), parent);
  await assert.rejects(ctx.findParent(record, 2), /文献库/);
  await assert.rejects(ctx.findParent({ ...record, doi: "10.1234/other" }, 1), /冲突/);
});
test("citation-key export falls back to unique DOI and refuses duplicates", async () => {
  const parent = item();
  const record = { title: "Test Paper", doi: "https://doi.org/10.1234/ABC", source: { id: "citation-key" } };
  assert.equal(await context([parent]).findParent(record, 1), parent);
  await assert.rejects(context([parent, item()]).findParent(record, 1), /唯一/);
  await assert.rejects(context([]).findParent(record, 1), /唯一/);
});
test("without DOI exact title must be unique", async () => {
  const parent = item("");
  const record = { title: "Test Paper", doi: "", source: { id: "key" } };
  assert.equal(await context([parent]).findParent(record, 1), parent);
  await assert.rejects(context([parent, item("")]).findParent(record, 1), /唯一/);
});
test("manifest cannot access arbitrary local paths", async () => {
  await assert.rejects(context([]).importRecord({ pdf: "../secret.pdf", sha256: "a".repeat(64) }, {}, 1), /文件名/);
});
