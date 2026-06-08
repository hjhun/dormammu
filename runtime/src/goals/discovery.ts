import { readdir } from "node:fs/promises";
import path from "node:path";

import {
  goalFileStem,
  goalPromptAlreadyQueued,
  queuedGoalPromptName
} from "./queue.js";

export type GoalFileEntry = {
  path: string;
  name: string;
  stem: string;
};

export type GoalQueueCandidate = GoalFileEntry & {
  queuedPromptName: string;
  alreadyQueued: boolean;
};

export async function listGoalFiles(goalsPath: string): Promise<GoalFileEntry[]> {
  let entries;
  try {
    entries = await readdir(goalsPath, { withFileTypes: true });
  } catch {
    return [];
  }

  return entries
    .filter((entry) => entry.isFile() && path.extname(entry.name) === ".md")
    .map((entry) => {
      const goalPath = path.join(goalsPath, entry.name);
      return {
        path: goalPath,
        name: entry.name,
        stem: goalFileStem(goalPath)
      };
    })
    .sort((left, right) => left.name.localeCompare(right.name));
}

export async function hasGoalFiles(goalsPath: string): Promise<boolean> {
  const goalFiles = await listGoalFiles(goalsPath);
  return goalFiles.length > 0;
}

export async function listQueuedPromptNames(promptPath: string): Promise<string[]> {
  let entries;
  try {
    entries = await readdir(promptPath, { withFileTypes: true });
  } catch {
    return [];
  }

  return entries
    .filter((entry) => entry.isFile())
    .map((entry) => entry.name)
    .sort();
}

export async function listGoalQueueCandidates(
  goalsPath: string,
  promptPath: string,
  dateText: string
): Promise<GoalQueueCandidate[]> {
  const [goalFiles, queuedPromptNames] = await Promise.all([
    listGoalFiles(goalsPath),
    listQueuedPromptNames(promptPath)
  ]);

  return goalFiles.map((goalFile) => ({
    ...goalFile,
    queuedPromptName: queuedGoalPromptName(goalFile.path, dateText),
    alreadyQueued: goalPromptAlreadyQueued(
      goalFile.path,
      dateText,
      queuedPromptNames
    )
  }));
}
