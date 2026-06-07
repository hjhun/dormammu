import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, writeFile } from "node:fs/promises";
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

test("dormammu-agent-runner reports malformed JSON payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: "{",
    encoding: "utf8"
  });

  assert.equal(completed.status, 1);
  assert.equal(completed.stdout, "");
  assert.match(completed.stderr, /Invalid JSON payload/);
});
