import assert from "node:assert/strict";
import test from "node:test";

import { capabilitiesToDict } from "./runArtifacts.js";
import { matchKnownPreset, presetForExecutableName } from "./presets.js";
import { parseHelpText } from "./helpParser.js";

test("parseHelpText detects prompt, workdir, and auto-approve flags", () => {
  const capabilities = parseHelpText(
    `
usage: fake-agent
  --prompt-file PATH
  --prompt TEXT
  --workdir PATH
  --enable-auto
  --allow-approve
`,
    {
      executableName: "fake-agent",
      helpExitCode: 0
    }
  );

  assert.equal(capabilities.promptFileFlag, "--prompt-file");
  assert.equal(capabilities.promptArgFlag, "--prompt");
  assert.equal(capabilities.workdirFlag, "--workdir");
  assert.equal(capabilities.promptPositional, false);
  assert.equal(capabilities.presetKey, null);
  assert.equal(capabilities.autoApprove!.supported, true);
  assert.deepEqual(
    capabilities.autoApprove!.candidates.map((candidate) => ({
      value: candidate.value,
      risk: candidate.risk,
      source: candidate.source
    })),
    [
      { value: "--enable-auto", risk: "medium", source: "help_text" },
      { value: "--allow-approve", risk: "low", source: "help_text" }
    ]
  );
});

test("parseHelpText applies codex preset by executable name", () => {
  const capabilities = parseHelpText("Usage: codex [OPTIONS]", {
    executableName: "codex",
    helpExitCode: 0
  });

  assert.equal(capabilities.promptFileFlag, null);
  assert.equal(capabilities.promptArgFlag, null);
  assert.deepEqual(capabilities.commandPrefix, ["exec"]);
  assert.equal(capabilities.promptPositional, true);
  assert.equal(capabilities.presetKey, "codex");
  assert.equal(capabilities.presetLabel, "OpenAI Codex");
  assert.equal(capabilities.presetSource, "executable_name");
  assert.deepEqual(
    capabilities.autoApprove!.candidates.slice(0, 2).map((candidate) => ({
      value: candidate.value,
      risk: candidate.risk,
      source: candidate.source
    })),
    [
      {
        value: "--dangerously-bypass-approvals-and-sandbox",
        risk: "high",
        source: "preset:codex"
      },
      { value: "--full-auto", risk: "medium", source: "preset:codex" }
    ]
  );
});

test("parseHelpText applies preset flags when help text omits generic flags", () => {
  const capabilities = parseHelpText("Gemini CLI help --approval-mode --prompt-interactive", {
    executableName: "unknown",
    helpExitCode: 0
  });

  assert.equal(capabilities.presetKey, "gemini");
  assert.equal(capabilities.presetSource, "help_text");
  assert.equal(capabilities.promptArgFlag, "--prompt");
  assert.equal(capabilities.promptFileFlag, null);
});

test("matchKnownPreset and presetForExecutableName expose known presets", () => {
  const byName = matchKnownPreset("claude", "");
  assert.equal(byName.preset?.key, "claude_code");
  assert.equal(byName.source, "executable_name");

  const byHelp = matchKnownPreset("unknown", "run with --message-file and --message");
  assert.equal(byHelp.preset?.key, "aider");
  assert.equal(byHelp.source, "help_text");

  assert.equal(presetForExecutableName("cline")?.workdirFlag, "--cwd");
  assert.equal(presetForExecutableName("missing"), null);
});

test("capabilitiesToDict serializes preset and auto-approve metadata", () => {
  const capabilities = parseHelpText("usage: aider --message-file --yes", {
    executableName: "aider",
    helpExitCode: 2
  });

  assert.deepEqual(capabilitiesToDict(capabilities, { includeHelpText: true }), {
    help_flag: "--help",
    prompt_file_flag: "--message-file",
    prompt_arg_flag: "--message",
    workdir_flag: null,
    help_text: "usage: aider --message-file --yes",
    help_exit_code: 2,
    command_prefix: [],
    prompt_positional: false,
    preset: {
      key: "aider",
      label: "aider",
      source: "executable_name"
    },
    auto_approve: {
      supported: true,
      requires_confirmation: true,
      candidates: [
        {
          value: "--yes",
          risk: "medium",
          source: "preset:aider",
          summary: "Accepts confirmations automatically during scripted runs."
        }
      ],
      notes: ["Auto-approve candidates are advisory only in this slice."]
    }
  });
});
