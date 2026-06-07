export type InputMode = "auto" | "file" | "arg" | "stdin" | "positional";

export type CliCapabilities = {
  helpFlag: string;
  promptFileFlag: string | null;
  promptArgFlag: string | null;
  workdirFlag: string | null;
  helpText: string;
  helpExitCode: number;
  commandPrefix?: readonly string[];
  promptPositional?: boolean;
  presetKey?: string | null;
  presetLabel?: string | null;
  presetSource?: string | null;
  autoApprove?: AutoApproveInfo;
};

export type AutoApproveCandidate = {
  value: string;
  risk: string;
  source: string;
  summary: string;
};

export type AutoApproveInfo = {
  supported: boolean;
  requiresConfirmation: boolean;
  candidates: readonly AutoApproveCandidate[];
  notes: readonly string[];
};

export type AgentRunRequest = {
  cliPath: string;
  promptText: string;
  repoRoot: string;
  workdir?: string | null;
  inputMode?: InputMode;
  promptFlag?: string | null;
  extraArgs?: readonly string[];
  runLabel?: string | null;
};

export type CommandPlan = {
  argv: string[];
  promptMode: Exclude<InputMode, "auto">;
  stdinInput: string | null;
};

function resolvePromptMode(
  request: AgentRunRequest,
  capabilities: CliCapabilities
): Exclude<InputMode, "auto"> {
  const requestedMode = request.inputMode ?? "auto";
  if (requestedMode !== "auto") {
    return requestedMode;
  }
  if (request.promptFlag || capabilities.promptFileFlag) {
    return "file";
  }
  if (capabilities.promptArgFlag) {
    return "arg";
  }
  if (capabilities.promptPositional) {
    return "positional";
  }
  return "stdin";
}

export function buildCommandPlan(
  request: AgentRunRequest,
  capabilities: CliCapabilities,
  promptPath: string
): CommandPlan {
  const promptMode = resolvePromptMode(request, capabilities);
  const argv = [
    request.cliPath,
    ...(capabilities.commandPrefix ?? [])
  ];
  let stdinInput: string | null = null;
  const trailingArgs: string[] = [];

  if (request.workdir && capabilities.workdirFlag) {
    argv.push(capabilities.workdirFlag, request.workdir);
  }

  if (promptMode === "file") {
    const promptFlag = request.promptFlag ?? capabilities.promptFileFlag;
    if (!promptFlag) {
      throw new Error("No prompt file flag is available for file mode.");
    }
    argv.push(promptFlag, promptPath);
  } else if (promptMode === "arg") {
    const promptFlag = request.promptFlag ?? capabilities.promptArgFlag;
    if (!promptFlag) {
      throw new Error("No prompt argument flag is available for arg mode.");
    }
    argv.push(promptFlag, request.promptText);
  } else if (promptMode === "stdin") {
    stdinInput = request.promptText;
  } else if (promptMode === "positional") {
    trailingArgs.push(request.promptText);
  } else {
    throw new Error(`Unsupported prompt mode: ${promptMode}`);
  }

  argv.push(...(request.extraArgs ?? []), ...trailingArgs);
  return { argv, promptMode, stdinInput };
}
