export type PresetAutoApproveCandidate = {
  value: string;
  risk: string;
  summary: string;
};

export type KnownCliPreset = {
  key: string;
  label: string;
  executableNames: readonly string[];
  helpHints?: readonly string[];
  commandPrefix?: readonly string[];
  promptFileFlag?: string | null;
  promptArgFlag?: string | null;
  promptPositional?: boolean;
  workdirFlag?: string | null;
  defaultExtraArgs?: readonly string[];
  suppressDefaultExtraArgsWhenPresent?: readonly string[];
  autoApproveCandidates?: readonly PresetAutoApproveCandidate[];
};

export const KNOWN_CLI_PRESETS: readonly KnownCliPreset[] = [
  {
    key: "codex",
    label: "OpenAI Codex",
    executableNames: ["codex"],
    helpHints: [
      "codex exec",
      "--full-auto",
      "--dangerously-bypass-approvals-and-sandbox"
    ],
    commandPrefix: ["exec"],
    promptPositional: true,
    defaultExtraArgs: [
      "--dangerously-bypass-approvals-and-sandbox",
      "--skip-git-repo-check"
    ],
    suppressDefaultExtraArgsWhenPresent: [
      "--dangerously-bypass-approvals-and-sandbox",
      "--full-auto",
      "--ask-for-approval",
      "-a",
      "--sandbox",
      "-s",
      "--skip-git-repo-check"
    ],
    autoApproveCandidates: [
      {
        value: "--dangerously-bypass-approvals-and-sandbox",
        risk: "high",
        summary: "Bypasses approvals and sandboxing for fully non-interactive execution."
      },
      {
        value: "--full-auto",
        risk: "medium",
        summary: "Allows Codex to apply changes automatically in exec mode."
      }
    ]
  },
  {
    key: "gemini",
    label: "Gemini CLI",
    executableNames: ["gemini"],
    helpHints: ["--approval-mode", "--prompt-interactive", "gemini cli"],
    promptArgFlag: "--prompt",
    defaultExtraArgs: ["--approval-mode", "yolo", "--include-directories", "/"],
    suppressDefaultExtraArgsWhenPresent: [
      "--approval-mode",
      "--yolo",
      "--include-directories"
    ],
    autoApproveCandidates: [
      {
        value: "--approval-mode yolo",
        risk: "high",
        summary: "Auto-accepts all actions without confirmation and should remain opt-in."
      },
      {
        value: "--yolo",
        risk: "high",
        summary: "Auto-accepts all actions without confirmation and should remain opt-in."
      },
      {
        value: "--approval-mode auto_edit",
        risk: "medium",
        summary: "Auto-accepts edit operations without enabling full yolo mode."
      }
    ]
  },
  {
    key: "claude_code",
    label: "Claude Code",
    executableNames: ["claude", "claude-code"],
    helpHints: ["--permission-mode", "--output-format", "bypassPermissions"],
    commandPrefix: ["--print"],
    promptPositional: true,
    defaultExtraArgs: ["--dangerously-skip-permissions"],
    suppressDefaultExtraArgsWhenPresent: [
      "--permission-mode",
      "--dangerously-skip-permissions",
      "--allow-dangerously-skip-permissions"
    ],
    autoApproveCandidates: [
      {
        value: "--dangerously-skip-permissions",
        risk: "high",
        summary: "Bypasses all permission checks and should remain opt-in."
      },
      {
        value: "--permission-mode bypassPermissions",
        risk: "high",
        summary: "Bypasses permission prompts for the full session and should remain opt-in."
      },
      {
        value: "--permission-mode auto",
        risk: "medium",
        summary: "Starts Claude Code in auto permission mode."
      }
    ]
  },
  {
    key: "cline",
    label: "Cline",
    executableNames: ["cline"],
    helpHints: ["-y", "--verbose", "--cwd", "--timeout", "cline"],
    promptPositional: true,
    workdirFlag: "--cwd",
    defaultExtraArgs: ["--timeout", "1200"],
    suppressDefaultExtraArgsWhenPresent: ["--timeout"],
    autoApproveCandidates: [
      {
        value: "-y",
        risk: "high",
        summary: "Enables non-interactive plain-text mode and should remain opt-in."
      }
    ]
  },
  {
    key: "aider",
    label: "aider",
    executableNames: ["aider"],
    helpHints: ["--message-file", "--message", "--yes"],
    promptFileFlag: "--message-file",
    promptArgFlag: "--message",
    autoApproveCandidates: [
      {
        value: "--yes",
        risk: "medium",
        summary: "Accepts confirmations automatically during scripted runs."
      }
    ]
  }
];

export function matchKnownPreset(
  executableName: string | null | undefined,
  helpText: string
): { preset: KnownCliPreset | null; source: string | null } {
  const normalizedName = (executableName ?? "").trim().toLowerCase();
  const normalizedHelp = helpText.toLowerCase();

  for (const preset of KNOWN_CLI_PRESETS) {
    if (preset.executableNames.includes(normalizedName)) {
      return { preset, source: "executable_name" };
    }
  }

  for (const preset of KNOWN_CLI_PRESETS) {
    if (
      (preset.helpHints ?? []).some((hint) =>
        normalizedHelp.includes(hint.toLowerCase())
      )
    ) {
      return { preset, source: "help_text" };
    }
  }

  return { preset: null, source: null };
}

export function presetForExecutableName(
  executableName: string | null | undefined
): KnownCliPreset | null {
  const normalizedName = (executableName ?? "").trim().toLowerCase();
  for (const preset of KNOWN_CLI_PRESETS) {
    if (preset.executableNames.includes(normalizedName)) {
      return preset;
    }
  }
  return null;
}
