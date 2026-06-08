import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  hasGoalFiles,
  listGoalFiles,
  listGoalQueueCandidates,
  listQueuedPromptNames
} from "./discovery.js";

async function tempDir(): Promise<string> {
  return mkdtemp(path.join(os.tmpdir(), "dormammu-goals-"));
}

test("listGoalFiles returns sorted markdown files only", async () => {
  const root = await tempDir();
  const goalsPath = path.join(root, "goals");
  await mkdir(goalsPath);
  await writeFile(path.join(goalsPath, "b.md"), "b", "utf-8");
  await writeFile(path.join(goalsPath, "a.md"), "a", "utf-8");
  await writeFile(path.join(goalsPath, "notes.txt"), "note", "utf-8");
  await writeFile(path.join(goalsPath, "upper.MD"), "upper", "utf-8");
  await mkdir(path.join(goalsPath, "nested.md"));

  const files = await listGoalFiles(goalsPath);

  assert.deepEqual(files.map((file) => file.name), ["a.md", "b.md"]);
  assert.deepEqual(files.map((file) => file.stem), ["a", "b"]);
});

test("goal discovery tolerates missing directories", async () => {
  const root = await tempDir();
  const missingPath = path.join(root, "missing");

  assert.equal(await hasGoalFiles(missingPath), false);
  assert.deepEqual(await listGoalFiles(missingPath), []);
});

test("listQueuedPromptNames returns sorted prompt files and tolerates missing paths", async () => {
  const root = await tempDir();
  const promptPath = path.join(root, "prompts");
  await mkdir(promptPath);
  await writeFile(path.join(promptPath, "z.txt"), "z", "utf-8");
  await writeFile(path.join(promptPath, "a.md"), "a", "utf-8");
  await mkdir(path.join(promptPath, "nested.md"));

  assert.deepEqual(await listQueuedPromptNames(promptPath), ["a.md", "z.txt"]);
  assert.deepEqual(await listQueuedPromptNames(path.join(root, "missing")), []);
});

test("listGoalQueueCandidates projects queued prompt state", async () => {
  const root = await tempDir();
  const goalsPath = path.join(root, "goals");
  const promptPath = path.join(root, "prompts");
  await mkdir(goalsPath);
  await mkdir(promptPath);
  await writeFile(path.join(goalsPath, "goal-a.md"), "Goal A", "utf-8");
  await writeFile(path.join(goalsPath, "goal-b.md"), "Goal B", "utf-8");
  await writeFile(path.join(promptPath, "20260412_goal-a.md"), "queued", "utf-8");

  const candidates = await listGoalQueueCandidates(
    goalsPath,
    promptPath,
    "20260412"
  );

  assert.deepEqual(
    candidates.map((candidate) => ({
      name: candidate.name,
      queuedPromptName: candidate.queuedPromptName,
      alreadyQueued: candidate.alreadyQueued
    })),
    [
      {
        name: "goal-a.md",
        queuedPromptName: "20260412_goal-a.md",
        alreadyQueued: true
      },
      {
        name: "goal-b.md",
        queuedPromptName: "20260412_goal-b.md",
        alreadyQueued: false
      }
    ]
  );
});
