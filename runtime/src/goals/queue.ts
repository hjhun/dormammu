import path from "node:path";

import { goalSourceTag, queuedGoalPromptFilename } from "./prompts.js";

export type GoalQueueProjectionInput = {
  goalFilePath: string;
  generatedPrompt: string;
  dateText: string;
};

export type GoalQueueProjection = {
  stem: string;
  filename: string;
  content: string;
};

export function goalFileStem(goalFilePath: string): string {
  return path.parse(goalFilePath).name;
}

export function queuedGoalPromptName(goalFilePath: string, dateText: string): string {
  return queuedGoalPromptFilename(dateText, goalFileStem(goalFilePath));
}

export function goalPromptAlreadyQueued(
  goalFilePath: string,
  dateText: string,
  existingPromptNames: Iterable<string>
): boolean {
  const expectedName = queuedGoalPromptName(goalFilePath, dateText);
  for (const existingName of existingPromptNames) {
    if (existingName === expectedName) {
      return true;
    }
  }
  return false;
}

export function projectQueuedGoalPrompt(
  input: GoalQueueProjectionInput
): GoalQueueProjection {
  const stem = goalFileStem(input.goalFilePath);
  return {
    stem,
    filename: queuedGoalPromptFilename(input.dateText, stem),
    content: goalSourceTag(input.goalFilePath) + input.generatedPrompt
  };
}
