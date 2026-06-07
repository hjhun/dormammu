import type { AutoApproveCandidate, AutoApproveInfo, CliCapabilities } from "./commandBuilder.js";
import type { PresetAutoApproveCandidate } from "./presets.js";
import { matchKnownPreset } from "./presets.js";

const KNOWN_PROMPT_FILE_FLAGS = ["--prompt-file", "--input-file", "--message-file"] as const;
const KNOWN_PROMPT_ARG_FLAGS = ["--prompt", "--message", "--input"] as const;
const KNOWN_WORKDIR_FLAGS = ["--workdir", "--cwd", "-C"] as const;
const AUTO_APPROVE_FLAG_PATTERN =
  /--[a-z0-9][a-z0-9-]*(?:approve|approval|permission|permissions|yes|auto|yolo)[a-z0-9-]*/gi;

export function parseHelpText(
  helpText: string,
  options: { executableName?: string | null; helpExitCode?: number } = {}
): CliCapabilities {
  const { preset, source } = matchKnownPreset(options.executableName, helpText);
  const presetCandidates = (preset?.autoApproveCandidates ?? []).map((candidate) =>
    presetAutoApproveCandidateToRuntime(candidate, preset?.key ?? "")
  );

  return {
    helpFlag: "--help",
    promptFileFlag:
      firstMatchingFlag(helpText, KNOWN_PROMPT_FILE_FLAGS) ?? preset?.promptFileFlag ?? null,
    promptArgFlag:
      firstMatchingFlag(helpText, KNOWN_PROMPT_ARG_FLAGS) ?? preset?.promptArgFlag ?? null,
    workdirFlag: firstMatchingFlag(helpText, KNOWN_WORKDIR_FLAGS) ?? preset?.workdirFlag ?? null,
    helpText,
    helpExitCode: options.helpExitCode ?? 0,
    commandPrefix: preset?.commandPrefix ?? [],
    promptPositional: preset?.promptPositional ?? false,
    presetKey: preset?.key ?? null,
    presetLabel: preset?.label ?? null,
    presetSource: source,
    autoApprove: detectAutoApprove(helpText, presetCandidates)
  };
}

function flagPresent(helpText: string, flag: string): boolean {
  return new RegExp(`(?<![A-Za-z0-9_-])${escapeRegExp(flag)}(?![A-Za-z0-9_-])`).test(
    helpText
  );
}

function firstMatchingFlag(
  helpText: string,
  candidates: readonly string[]
): string | null {
  for (const flag of candidates) {
    if (flagPresent(helpText, flag)) {
      return flag;
    }
  }
  return null;
}

function riskForCandidate(value: string): string {
  const normalized = value.toLowerCase();
  if (
    ["danger", "bypass", "skip-permissions", "yolo"].some((token) =>
      normalized.includes(token)
    )
  ) {
    return "high";
  }
  if (
    ["full-auto", "auto", "yes", "permission-mode"].some((token) =>
      normalized.includes(token)
    )
  ) {
    return "medium";
  }
  return "low";
}

function detectAutoApprove(
  helpText: string,
  presetCandidates: readonly AutoApproveCandidate[]
): AutoApproveInfo {
  const candidates = [...presetCandidates];
  const seen = new Set(candidates.map((candidate) => candidate.value));

  for (const match of helpText.matchAll(AUTO_APPROVE_FLAG_PATTERN)) {
    const value = match[0];
    if (seen.has(value)) {
      continue;
    }
    seen.add(value);
    candidates.push({
      value,
      risk: riskForCandidate(value),
      source: "help_text",
      summary: "Detected in CLI help output and requires explicit operator review."
    });
  }

  const notes: string[] = [];
  if (candidates.length) {
    notes.push("Auto-approve candidates are advisory only in this slice.");
    if (candidates.some((candidate) => candidate.risk === "high")) {
      notes.push("High-risk candidates should remain opt-in and require explicit confirmation.");
    }
  }

  return {
    supported: candidates.length > 0,
    requiresConfirmation: candidates.length > 0,
    candidates,
    notes
  };
}

function presetAutoApproveCandidateToRuntime(
  candidate: PresetAutoApproveCandidate,
  presetKey: string
): AutoApproveCandidate {
  return {
    value: candidate.value,
    risk: candidate.risk,
    source: `preset:${presetKey}`,
    summary: candidate.summary
  };
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
