export type RuntimePathPromptInput = {
  repoRoot: string;
  repoDevDir: string;
  baseDevDir: string;
  tmpDir: string;
  resultsDir: string;
};

export type RuntimePathPromptDecision = {
  runtimePathsText: string;
  reason: "runtime_path_prompt_projected";
};

export function runtimePathPrompt(input: RuntimePathPromptInput): string {
  return [
    `- Real project root: \`${input.repoRoot}\``,
    `- Repository-local project docs root: \`${input.repoDevDir}\``,
    `- Operational state directory (\`.dev\` in workflow docs): \`${input.baseDevDir}\``,
    `- Managed temporary directory (\`.tmp\`): \`${input.tmpDir}\``,
    `- Result reports directory: \`${input.resultsDir}\``,
    (
      "Interpret any `.dev/...` reference in prompts and workflow guidance as " +
      "relative to the operational state directory above, not to the real " +
      "project root."
    )
  ].join("\n");
}

export function runtimePathPromptDecision(
  input: RuntimePathPromptInput
): RuntimePathPromptDecision {
  return {
    runtimePathsText: runtimePathPrompt(input),
    reason: "runtime_path_prompt_projected"
  };
}
