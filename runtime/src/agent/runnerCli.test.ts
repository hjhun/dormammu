import assert from "node:assert/strict";
import { chmod, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const runnerCliPath = fileURLToPath(new URL("./runnerCli.js", import.meta.url));

test("dormammu-agent-runner reads stdin payloads and writes result JSON", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-cli-"));
  const fakeCli = path.join(root, "fake-agent.cjs");
  await writeFile(
    fakeCli,
    [
      "#!/usr/bin/env node",
      "if (process.argv.includes('--help')) {",
      "  console.log('usage: fake-agent');",
      "  process.exit(0);",
      "}",
      "let text = '';",
      "process.stdin.setEncoding('utf8');",
      "process.stdin.on('data', (chunk) => { text += chunk; });",
      "process.stdin.on('end', () => { console.log(`agent saw: ${text.trim()}`); });",
      ""
    ].join("\n"),
    "utf8"
  );
  await chmod(fakeCli, 0o755);

  const payload = {
    config: {
      active_agent_cli: fakeCli
    },
    request: {
      prompt_text: "Run via CLI.",
      repo_root: root,
      input_mode: "stdin",
      run_label: "cli-entrypoint"
    },
    logs_dir: path.join(root, ".dev", "logs"),
    include_help_text: false
  };

  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify(payload),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");

  const result = JSON.parse(completed.stdout) as {
    exit_code: number;
    cli_path: string;
    prompt_mode: string;
    artifacts: { stdout: string };
    capabilities: { help_text?: string };
  };
  assert.equal(result.exit_code, 0);
  assert.equal(result.cli_path, fakeCli);
  assert.equal(result.prompt_mode, "stdin");
  assert.equal(result.capabilities.help_text, undefined);
  assert.match(await readFile(result.artifacts.stdout, "utf8"), /Run via CLI\./);
});

test("dormammu-agent-runner can emit structured started and output events", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-events-"));
  const fakeCli = path.join(root, "fake-agent.cjs");
  await writeFile(
    fakeCli,
    [
      "#!/usr/bin/env node",
      "if (process.argv.includes('--help')) {",
      "  console.log('usage: fake-agent');",
      "  process.exit(0);",
      "}",
      "let text = '';",
      "process.stdin.setEncoding('utf8');",
      "process.stdin.on('data', (chunk) => { text += chunk; });",
      "process.stdin.on('end', () => { console.log(`event prompt: ${text.trim()}`); });",
      ""
    ].join("\n"),
    "utf8"
  );
  await chmod(fakeCli, 0o755);

  const payload = {
    config: {
      active_agent_cli: fakeCli
    },
    request: {
      prompt_text: "Stream events.",
      repo_root: root,
      input_mode: "stdin",
      run_label: "cli-events"
    },
    logs_dir: path.join(root, ".dev", "logs"),
    include_help_text: false,
    event_stream: true
  };

  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify(payload),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  const events = completed.stderr
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      assert.match(line, /^DORMAMMU_EVENT /);
      return JSON.parse(line.slice("DORMAMMU_EVENT ".length)) as {
        type: string;
        data?: string;
        started?: { run_id: string };
      };
  });
  assert.equal(events[0].type, "started");
  assert.match(events[0].started?.run_id ?? "", /cli-events$/);
  const output = events
    .filter((event) => event.type === "output")
    .map((event) => Buffer.from(event.data ?? "", "base64").toString("utf8"))
    .join("");
  assert.match(output, /Stream events\./);

  const result = JSON.parse(completed.stdout) as { run_id: string; exit_code: number };
  assert.equal(result.run_id, events[0].started?.run_id);
  assert.equal(result.exit_code, 0);
});

test("dormammu-agent-runner can project goals queue payloads", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-goals-"));
  const goalsPath = path.join(root, "goals");
  const promptPath = path.join(root, "prompts");
  await mkdir(goalsPath);
  await mkdir(promptPath);
  await writeFile(path.join(goalsPath, "goal.md"), "Goal", "utf8");
  await writeFile(path.join(promptPath, "20260412_goal.md"), "queued", "utf8");

  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_queue",
      goals_path: goalsPath,
      prompt_path: promptPath,
      date_text: "20260412"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  const result = JSON.parse(completed.stdout) as {
    entrypoint: string;
    goal_files: Array<{ name: string }>;
    candidates: Array<{ queuedPromptName: string; alreadyQueued: boolean }>;
  };
  assert.equal(result.entrypoint, "goals_queue");
  assert.deepEqual(result.goal_files, [
    {
      path: path.join(goalsPath, "goal.md"),
      name: "goal.md",
      stem: "goal"
    }
  ]);
  assert.deepEqual(result.candidates, [
    {
      path: path.join(goalsPath, "goal.md"),
      name: "goal.md",
      stem: "goal",
      queuedPromptName: "20260412_goal.md",
      alreadyQueued: true
    }
  ]);
});

test("dormammu-agent-runner can project goals prompt payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_prompt_projection",
      goal_file_path: "/repo/goals/ship-it.md",
      generated_prompt: "# Goal\n\nShip it",
      date_text: "20260412"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_prompt_projection",
    stem: "ship-it",
    filename: "20260412_ship-it.md",
    content: "<!-- dormammu:goal_source=/repo/goals/ship-it.md -->\n\n# Goal\n\nShip it"
  });
});

test("dormammu-agent-runner can project goals role document payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_role_document_projection",
      logs_dir: "/repo/.dev/logs",
      date_text: "20260412",
      role: "designer",
      stem: "ship-it",
      output: "Design output"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_role_document_projection",
    filename: "20260412_designer_ship-it.md",
    path: "/repo/.dev/logs/20260412_designer_ship-it.md",
    content: "# Designer \u2014 ship-it\n\nDesign output"
  });
});

test("dormammu-agent-runner can project goals role sequence payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_role_sequence",
      goal_text: "Ship it",
      analysis_text: "Analysis output",
      roles: {
        planner: { cli: "planner-cli", model: "careful" }
      }
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  const result = JSON.parse(completed.stdout) as {
    entrypoint: string;
    next_step: {
      role: string;
      cli: string;
      model: string;
      prompt: string;
    };
  };
  assert.equal(result.entrypoint, "goals_role_sequence");
  assert.equal(result.next_step.role, "planner");
  assert.equal(result.next_step.cli, "planner-cli");
  assert.equal(result.next_step.model, "careful");
  assert.match(result.next_step.prompt, /# Requirements Analysis/);
});

test("dormammu-agent-runner can project goals timer decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_timer_decision",
      has_goal_files: false,
      timer_active: true,
      interval_minutes: 7
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_timer_decision",
    action: "cancel",
    intervalSeconds: null,
    reason: "no_goal_files_with_active_timer"
  });
});

test("dormammu-agent-runner can project goals trigger decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_trigger_decision",
      stop_requested: false,
      has_goal_files: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_trigger_decision",
    action: "process",
    cancelTimerBeforeProcess: true,
    syncTimerAfterProcess: true,
    reason: "goal_files_present"
  });
});

test("dormammu-agent-runner can project goals process decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_process_decision",
      stop_requested: false,
      goal_file_count: 2
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_process_decision",
    action: "process",
    goalFileCount: 2,
    reason: "goal_files_present"
  });
});

test("dormammu-agent-runner can project goals timer fired decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_timer_fired_decision",
      stop_requested: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_timer_fired_decision",
    action: "process",
    clearTimerBeforeProcess: true,
    syncTimerAfterProcess: true,
    reason: "timer_fired"
  });
});

test("dormammu-agent-runner can project goals single goal decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_single_goal_decision",
      prompt_exists: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_single_goal_decision",
    action: "skip",
    reason: "queued_prompt_exists"
  });
});

test("dormammu-agent-runner reports malformed JSON payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: "{",
    encoding: "utf8"
  });

  assert.equal(completed.status, 1);
  assert.equal(completed.stdout, "");
  assert.match(completed.stderr, /Invalid JSON payload/);
});
