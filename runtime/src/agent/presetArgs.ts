import type { AgentRunRequest, CliCapabilities } from "./commandBuilder.js";
import { presetForExecutableName } from "./presets.js";

export function applyDefaultPresetExtraArgs(
  request: AgentRunRequest,
  capabilities: CliCapabilities
): AgentRunRequest {
  const preset = presetForExecutableName(executableName(request.cliPath));
  if (preset === null || !(preset.defaultExtraArgs ?? []).length) {
    return request;
  }

  const extraArgs = sanitizePresetExtraArgs(preset.key, request.extraArgs ?? []);
  const defaultArgs = defaultPresetArgsToPrepend({
    presetKey: preset.key,
    defaultExtraArgs: preset.defaultExtraArgs ?? [],
    suppressFlags: preset.suppressDefaultExtraArgsWhenPresent ?? [],
    capabilities,
    extraArgs
  });
  const mergedExtraArgs = defaultArgs.length ? [...defaultArgs, ...extraArgs] : extraArgs;
  if (sameArgs(mergedExtraArgs, request.extraArgs ?? [])) {
    return request;
  }
  return { ...request, extraArgs: mergedExtraArgs };
}

export function sanitizePresetExtraArgs(
  presetKey: string,
  extraArgs: readonly string[]
): string[] {
  if (presetKey !== "gemini" || !extraArgs.length) {
    return [...extraArgs];
  }

  const parsedArgs: string[][] = [];
  let index = 0;
  while (index < extraArgs.length) {
    const current = extraArgs[index];
    if (
      (current === "--approval-mode" || current === "--include-directories") &&
      index + 1 < extraArgs.length
    ) {
      parsedArgs.push([current, extraArgs[index + 1]]);
      index += 2;
      continue;
    }
    parsedArgs.push([current]);
    index += 1;
  }

  const lastApprovalIndex = lastIndexWhere(parsedArgs, (item) =>
    item[0] === "--approval-mode" || item[0] === "--yolo"
  );
  const lastIncludeIndex = lastIndexWhere(parsedArgs, (item) =>
    item[0] === "--include-directories"
  );

  const sanitized: string[] = [];
  parsedArgs.forEach((item, itemIndex) => {
    const flag = item[0];
    if (
      (flag === "--approval-mode" || flag === "--yolo") &&
      itemIndex !== lastApprovalIndex
    ) {
      return;
    }
    if (flag === "--include-directories" && itemIndex !== lastIncludeIndex) {
      return;
    }
    sanitized.push(...item);
  });
  return sanitized;
}

function defaultPresetArgsToPrepend(options: {
  presetKey: string;
  defaultExtraArgs: readonly string[];
  suppressFlags: readonly string[];
  capabilities: CliCapabilities;
  extraArgs: readonly string[];
}): string[] {
  const normalizedArgs = new Set(
    options.extraArgs.map((arg) => arg.trim().toLowerCase()).filter(Boolean)
  );

  if (options.presetKey === "codex") {
    const defaultArgs: string[] = [];
    if (
      ![
        "--dangerously-bypass-approvals-and-sandbox",
        "--full-auto",
        "--ask-for-approval",
        "-a",
        "--sandbox",
        "-s"
      ].some((flag) => normalizedArgs.has(flag))
    ) {
      defaultArgs.push("--dangerously-bypass-approvals-and-sandbox");
    }
    if (
      !normalizedArgs.has("--skip-git-repo-check") &&
      options.capabilities.helpText.toLowerCase().includes("--skip-git-repo-check")
    ) {
      defaultArgs.push("--skip-git-repo-check");
    }
    return defaultArgs;
  }

  if (options.presetKey === "gemini") {
    const { hasApprovalArg, hasIncludeDirectories } = geminiExplicitArgState(
      options.extraArgs
    );
    const defaultArgs: string[] = [];
    if (!hasApprovalArg) {
      defaultArgs.push("--approval-mode", "yolo");
    }
    if (!hasIncludeDirectories) {
      defaultArgs.push("--include-directories", "/");
    }
    return defaultArgs;
  }

  if (options.presetKey === "claude_code") {
    if (
      [
        "--permission-mode",
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions"
      ].some((flag) => normalizedArgs.has(flag))
    ) {
      return [];
    }
    return ["--dangerously-skip-permissions"];
  }

  if (options.suppressFlags.some((flag) => normalizedArgs.has(flag.toLowerCase()))) {
    return [];
  }
  return [...options.defaultExtraArgs];
}

function geminiExplicitArgState(extraArgs: readonly string[]): {
  hasApprovalArg: boolean;
  hasIncludeDirectories: boolean;
} {
  let hasApprovalArg = false;
  let hasIncludeDirectories = false;
  let index = 0;
  while (index < extraArgs.length) {
    const current = extraArgs[index].trim().toLowerCase();
    if (current === "--approval-mode") {
      hasApprovalArg = true;
      index += 2;
      continue;
    }
    if (current === "--yolo") {
      hasApprovalArg = true;
      index += 1;
      continue;
    }
    if (current === "--include-directories") {
      hasIncludeDirectories = true;
      index += 2;
      continue;
    }
    index += 1;
  }
  return { hasApprovalArg, hasIncludeDirectories };
}

function executableName(cliPath: string): string {
  const normalized = cliPath.replace(/\\/g, "/");
  const index = normalized.lastIndexOf("/");
  return index === -1 ? normalized : normalized.slice(index + 1);
}

function lastIndexWhere<T>(
  items: readonly T[],
  predicate: (item: T) => boolean
): number | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index])) {
      return index;
    }
  }
  return null;
}

function sameArgs(left: readonly string[], right: readonly string[]): boolean {
  return (
    left.length === right.length &&
    left.every((item, index) => item === right[index])
  );
}
