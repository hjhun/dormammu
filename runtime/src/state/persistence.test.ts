import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { deepMerge, ensureJsonFile, readJson, writeJson } from "./persistence.js";

test("deepMerge overrides scalars and preserves missing defaults", () => {
  const result = deepMerge({ a: 1, b: { c: 2, d: 3 } }, { b: { c: 99 } });
  assert.deepEqual(result, { a: 1, b: { c: 99, d: 3 } });
});

test("deepMerge adds new keys without mutating defaults", () => {
  const defaults = { nested: { x: 1 } };
  const result = deepMerge(defaults, { nested: { y: 2 }, top: true });
  assert.deepEqual(result, { nested: { x: 1, y: 2 }, top: true });
  assert.deepEqual(defaults, { nested: { x: 1 } });
});

test("readJson and writeJson round-trip with stable newline", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "dormammu-runtime-"));
  try {
    const filePath = path.join(directory, "state.json");
    await writeJson(filePath, { key: "value", num: 42 });
    assert.deepEqual(await readJson(filePath), { key: "value", num: 42 });
    assert.equal((await readFile(filePath, "utf8")).endsWith("\n"), true);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("ensureJsonFile creates defaults and merges existing values", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "dormammu-runtime-"));
  try {
    const newPath = path.join(directory, "new.json");
    await ensureJsonFile(newPath, { a: 1 });
    assert.deepEqual(await readJson(newPath), { a: 1 });

    const existingPath = path.join(directory, "existing.json");
    await writeJson(existingPath, { a: 1, custom: 99 });
    await ensureJsonFile(existingPath, { a: 2, b: 3 });
    assert.deepEqual(await readJson(existingPath), { a: 1, b: 3, custom: 99 });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
