import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  AGENT_MANIFEST_SCHEMA_VERSION,
  agentManifestToProfile,
  discoverAgentManifests,
  enumerateAgentManifestCandidates,
  evaluateFilesystemPermission,
  evaluateSkillPermission,
  evaluateToolPermission,
  loadAgentManifest,
  loadAgentManifestDefinitions,
  loadedAgentDefinitionToProfile,
  parseAgentManifestPayload,
  parseAgentManifestText,
  selectedAgentManifestsByName,
  type AgentManifestSearchRoot
} from "../index.js";

function validManifestPayload(): Record<string, unknown> {
  return {
    schema_version: 1,
    name: "project-planner",
    description: "Project-specific planning agent.",
    prompt: "Plan the active slice with repository context.",
    source: "project",
    cli: "./bin/project-planner",
    model: "gpt-5.4",
    permissions: {
      tools: {
        default: "ask",
        rules: [
          { tool: "shell", decision: "deny" },
          { tool: "rg", decision: "allow" }
        ]
      },
      skills: {
        default: "deny",
        rules: [{ skill: "planning-agent", decision: "allow" }]
      },
      filesystem: {
        default: "ask",
        rules: [{ path: "./workspace", access: ["read", "write"], decision: "allow" }]
      },
      network: "deny",
      worktree: { default: "allow" }
    },
    skills: ["planning-agent", "designing-agent", "planning-agent"],
    metadata: { owner: "project", priority: 2 }
  };
}

function searchRoots(root: string): AgentManifestSearchRoot[] {
  return [
    { scope: "project", path: path.join(root, "repo", ".dormammu", "agent-manifests") },
    { scope: "user", path: path.join(root, "home", "agent-manifests") }
  ];
}

async function writeManifest(
  manifestPath: string,
  options: { name: string; source: string; description?: string; prompt?: string }
): Promise<void> {
  await mkdir(path.dirname(manifestPath), { recursive: true });
  await writeFile(
    manifestPath,
    JSON.stringify({
      schema_version: 1,
      name: options.name,
      description: options.description ?? `${options.name} description`,
      prompt: options.prompt ?? `${options.name} prompt`,
      source: options.source
    }),
    "utf8"
  );
}

test("loadAgentManifest parses valid manifest files", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const manifestPath = path.join(root, "planner.agent.json");
  await writeFile(manifestPath, JSON.stringify(validManifestPayload()), "utf8");

  const manifest = await loadAgentManifest(manifestPath);

  assert.equal(manifest.schema_version, AGENT_MANIFEST_SCHEMA_VERSION);
  assert.equal(manifest.name, "project-planner");
  assert.equal(manifest.description, "Project-specific planning agent.");
  assert.equal(manifest.prompt, "Plan the active slice with repository context.");
  assert.equal(manifest.source, "project");
  assert.equal(manifest.cli_override, path.resolve(root, "bin", "project-planner"));
  assert.equal(manifest.model_override, "gpt-5.4");
  assert.equal(evaluateToolPermission(manifest.permission_policy.tools, "shell"), "deny");
  assert.equal(evaluateToolPermission(manifest.permission_policy.tools, "rg"), "allow");
  assert.equal(evaluateSkillPermission(manifest.permission_policy.skills, "planning-agent"), "allow");
  assert.equal(evaluateSkillPermission(manifest.permission_policy.skills, "designing-agent"), "deny");
  assert.equal(
    evaluateFilesystemPermission(
      manifest.permission_policy.filesystem,
      path.resolve(root, "workspace", "notes.md"),
      { access: "write" }
    ),
    "allow"
  );
  assert.equal(manifest.permission_policy.network.default, "deny");
  assert.equal(manifest.permission_policy.worktree.default, "allow");
  assert.deepEqual(manifest.preloaded_skills, ["planning-agent", "designing-agent"]);
  assert.deepEqual(manifest.metadata, { owner: "project", priority: 2 });
});

test("parseAgentManifestPayload rejects malformed schema fields clearly", () => {
  assert.throws(
    () =>
      parseAgentManifestPayload(
        { ...validManifestPayload(), prompt: "" },
        { sourceName: "inline manifest" }
      ),
    /agent_manifest\.prompt must be a non-empty string/
  );
  assert.throws(
    () =>
      parseAgentManifestPayload(
        { ...validManifestPayload(), skills: "planning-agent" },
        { sourceName: "inline manifest" }
      ),
    /agent_manifest\.skills must be a JSON array/
  );
  assert.throws(
    () =>
      parseAgentManifestPayload(
        { ...validManifestPayload(), extra: true },
        { sourceName: "inline manifest" }
      ),
    /agent_manifest contains unsupported keys \(extra\)/
  );
  assert.throws(
    () =>
      parseAgentManifestPayload(
        { ...validManifestPayload(), source: "configured" },
        { sourceName: "inline manifest" }
      ),
    /agent_manifest\.source must be one of \(built_in, project, user\)/
  );
});

test("parseAgentManifestPayload passes permission validation context through", () => {
  const payload = validManifestPayload();
  payload.permissions = { tools: { bogus: true } };

  assert.throws(
    () => parseAgentManifestPayload(payload, { sourceName: "inline manifest" }),
    /agent_manifest\.permissions\.tools contains unsupported keys \(bogus\)/
  );
});

test("parseAgentManifestText reports JSON syntax line and column", () => {
  assert.throws(
    () => parseAgentManifestText("{", { sourceName: "inline manifest" }),
    /Failed to parse agent manifest JSON in inline manifest: .* line 1 column/
  );
});

test("manifest and loaded definition convert to agent profiles", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const manifestPath = path.join(root, "repo", ".dormammu", "agent-manifests", "planner.agent.json");
  await writeManifest(manifestPath, {
    name: "planner-custom",
    source: "project",
    description: "Project planner",
    prompt: "Plan from project context."
  });

  const manifest = await loadAgentManifest(manifestPath);
  const profile = agentManifestToProfile(manifest);
  const loadResult = await loadAgentManifestDefinitions(searchRoots(root), {
    names: ["planner-custom"]
  });
  const loadedProfile = loadedAgentDefinitionToProfile(loadResult.definitions[0]);

  assert.equal(profile.name, "planner-custom");
  assert.equal(profile.prompt_body, "Plan from project context.");
  assert.equal(loadedProfile.name, "planner-custom");
  assert.equal(loadResult.definitions[0].manifest_scope, "project");
  assert.equal(loadResult.definitions[0].manifest_path, manifestPath);
});

test("project-only manifests discover deterministically", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const [projectRoot] = searchRoots(root);
  await writeManifest(path.join(projectRoot.path, "zebra.agent.json"), {
    name: "zebra",
    source: "project"
  });
  await writeManifest(path.join(projectRoot.path, "nested", "alpha.agent.json"), {
    name: "alpha",
    source: "project"
  });

  const candidates = await enumerateAgentManifestCandidates(searchRoots(root));
  const discovery = await discoverAgentManifests(searchRoots(root));

  assert.deepEqual(candidates.map((candidate) => candidate.scope), ["project", "project"]);
  assert.deepEqual(candidates.map((candidate) => candidate.relative_path), [
    "nested/alpha.agent.json",
    "zebra.agent.json"
  ]);
  assert.deepEqual(Object.keys(selectedAgentManifestsByName(discovery)), ["alpha", "zebra"]);
  assert.equal(discovery.selected.every((manifest) => manifest.scope === "project"), true);
  assert.deepEqual(discovery.shadowed, []);
});

test("project scope overrides user scope for duplicate names", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const [projectRoot, userRoot] = searchRoots(root);
  await writeManifest(path.join(userRoot.path, "planner.agent.json"), {
    name: "planner-custom",
    source: "user",
    description: "user version"
  });
  await writeManifest(path.join(projectRoot.path, "planner.agent.json"), {
    name: "planner-custom",
    source: "project",
    description: "project version"
  });

  const discovery = await discoverAgentManifests(searchRoots(root));
  const selected = selectedAgentManifestsByName(discovery)["planner-custom"];

  assert.equal(selected.scope, "project");
  assert.equal(selected.path, path.join(projectRoot.path, "planner.agent.json"));
  assert.equal(discovery.shadowed.length, 1);
  assert.equal(discovery.shadowed[0].scope, "user");
});

test("discovery rejects scope mismatches and same-scope duplicates", async () => {
  const mismatchRoot = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const [mismatchProjectRoot] = searchRoots(mismatchRoot);
  await writeManifest(path.join(mismatchProjectRoot.path, "planner.agent.json"), {
    name: "planner-custom",
    source: "user"
  });

  await assert.rejects(
    () => discoverAgentManifests(searchRoots(mismatchRoot)),
    /Agent manifest source\/scope mismatch .* declared source 'user' does not match discovered scope 'project'/
  );

  const duplicateRoot = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const [duplicateProjectRoot] = searchRoots(duplicateRoot);
  await writeManifest(path.join(duplicateProjectRoot.path, "alpha.agent.json"), {
    name: "shared-name",
    source: "project"
  });
  await writeManifest(path.join(duplicateProjectRoot.path, "nested", "beta.agent.json"), {
    name: "shared-name",
    source: "project"
  });

  await assert.rejects(
    () => discoverAgentManifests(searchRoots(duplicateRoot)),
    /Duplicate agent manifest name 'shared-name' in project scope/
  );
});

test("selected manifest discovery ignores unrelated malformed files", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const [projectRoot, userRoot] = searchRoots(root);
  await writeManifest(path.join(projectRoot.path, "planner.agent.json"), {
    name: "planner-custom",
    source: "project",
    prompt: "Plan from the project manifest."
  });
  await mkdir(userRoot.path, { recursive: true });
  await writeFile(path.join(userRoot.path, "broken.agent.json"), "{", "utf8");

  const result = await loadAgentManifestDefinitions(searchRoots(root), {
    names: ["planner-custom"]
  });

  assert.deepEqual(result.definitions.map((definition) => definition.name), ["planner-custom"]);
  assert.equal(result.definitions[0].prompt_body, "Plan from the project manifest.");
  assert.equal(result.definitions[0].manifest_scope, "project");
});

test("selected manifest discovery reports malformed requested manifests", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-manifests-"));
  const [projectRoot, userRoot] = searchRoots(root);
  await mkdir(projectRoot.path, { recursive: true });
  const projectManifestPath = path.join(projectRoot.path, "planner.agent.json");
  await writeFile(
    projectManifestPath,
    '{"schema_version": 1, "name": "planner-custom", "description": "Broken", "prompt": ',
    "utf8"
  );
  await writeManifest(path.join(userRoot.path, "planner.agent.json"), {
    name: "planner-custom",
    source: "user",
    prompt: "Plan from the user manifest."
  });

  await assert.rejects(
    () => loadAgentManifestDefinitions(searchRoots(root), { names: ["planner-custom"] }),
    new RegExp(`Failed to parse agent manifest JSON in ${projectManifestPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}: .*line 1 column`)
  );
});
