import assert from "node:assert/strict";
import test from "node:test";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import path from "node:path";
import { tmpdir } from "node:os";

import {
  SKILL_CONTENT_MODE_INLINE_MARKDOWN,
  SKILL_DOCUMENT_SCHEMA_VERSION,
  SKILL_SOURCE_PRECEDENCE,
  SkillDiscoveryError,
  SkillDocumentError,
  discoverSkills,
  enumerateSkillCandidates,
  filterSkillsForProfile,
  loadSkillDefinition,
  loadSkillDocument,
  normalizeSkillSourceScope,
  parseSkillDocumentPayload,
  parseSkillDocumentText,
  resolveRuntimeSkillResolution,
  runtimeSkillLogLine,
  runtimeSkillPromptLines,
  runtimeSkillSummary,
  skillSourcePrecedence
} from "./skills.js";

function validSkillText(): string {
  return [
    "---",
    "schema_version: 1",
    "name: phase5-custom-skill",
    "description: Project-specific skill for Phase 5 parsing tests.",
    'metadata: {"visibility": "profile_scoped", "tags": ["phase5", "skill"]}',
    "---",
    "",
    "# Phase 5 Custom Skill",
    "",
    "Use this skill to validate the runtime skill parser.",
    ""
  ].join("\n");
}

function validSkillPayload(): Record<string, unknown> {
  return {
    schema_version: SKILL_DOCUMENT_SCHEMA_VERSION,
    name: "phase5-custom-skill",
    description: "Project-specific skill for Phase 5 parsing tests.",
    metadata: { visibility: "profile_scoped", tags: ["phase5", "skill"] }
  };
}

async function writeSkill(
  root: string,
  relativePath: string,
  options: { name: string; description?: string }
): Promise<string> {
  const skillPath = path.join(root, relativePath, "SKILL.md");
  await mkdir(path.dirname(skillPath), { recursive: true });
  await writeFile(
    skillPath,
    [
      "---",
      "schema_version: 1",
      `name: ${options.name}`,
      `description: ${options.description ?? `${options.name} description`}`,
      'metadata: {"visibility": "profile_scoped"}',
      "---",
      "",
      `# ${options.name}`,
      "",
      "Use this skill in discovery tests.",
      ""
    ].join("\n"),
    "utf8"
  );
  return skillPath;
}

test("parseSkillDocumentText parses valid inline markdown skills", () => {
  const document = parseSkillDocumentText(validSkillText(), {
    sourceName: "inline skill"
  });

  assert.equal(document.schema_version, SKILL_DOCUMENT_SCHEMA_VERSION);
  assert.equal(document.name, "phase5-custom-skill");
  assert.equal(document.description, "Project-specific skill for Phase 5 parsing tests.");
  assert.equal(document.content.mode, SKILL_CONTENT_MODE_INLINE_MARKDOWN);
  assert.match(document.content.text, /^# Phase 5 Custom Skill/);
  assert.deepEqual(document.metadata, {
    visibility: "profile_scoped",
    tags: ["phase5", "skill"]
  });
});

test("parseSkillDocumentPayload reports missing required fields", () => {
  const payload = validSkillPayload();
  delete payload.description;

  assert.throws(
    () =>
      parseSkillDocumentPayload(payload, {
        sourceName: "inline skill",
        body: "# Skill\n\nBody"
      }),
    /skill_document\.description must be a non-empty string/
  );
});

test("parseSkillDocumentPayload rejects non-object metadata", () => {
  const payload = validSkillPayload();
  payload.metadata = "profile_scoped";

  assert.throws(
    () =>
      parseSkillDocumentPayload(payload, {
        sourceName: "inline skill",
        body: "# Skill\n\nBody"
      }),
    /skill_document\.metadata must be a JSON object/
  );
});

test("parseSkillDocumentText defaults omitted schema version", () => {
  const document = parseSkillDocumentText(
    [
      "---",
      "name: planning-agent",
      "description: Existing packaged skill layout.",
      "---",
      "",
      "# Planning Agent",
      ""
    ].join("\n"),
    { sourceName: "packaged skill" }
  );

  assert.equal(document.schema_version, SKILL_DOCUMENT_SCHEMA_VERSION);
  assert.equal(document.name, "planning-agent");
});

test("parseSkillDocumentText rejects malformed frontmatter", () => {
  assert.throws(
    () =>
      parseSkillDocumentText(
        [
          "---",
          "name: alpha",
          "  nested: no",
          "---",
          "# Alpha"
        ].join("\n"),
        { sourceName: "bad skill" }
      ),
    /frontmatter does not support nested mappings/
  );
});

test("parseSkillDocumentText rejects unknown frontmatter keys", () => {
  assert.throws(
    () =>
      parseSkillDocumentText(
        [
          "---",
          "name: alpha",
          "description: Alpha skill.",
          "unknown: value",
          "---",
          "# Alpha"
        ].join("\n"),
        { sourceName: "bad skill" }
      ),
    /unsupported keys \(unknown\)/
  );
});

test("loadSkillDocument rejects non-SKILL filenames", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-"));
  const agentPath = path.join(root, "AGENTS.md");
  await writeFile(agentPath, validSkillText(), "utf8");

  await assert.rejects(
    () => loadSkillDocument(agentPath),
    /Skill documents must be named SKILL\.md/
  );
});

test("loadSkillDefinition maps source scope and precedence", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-"));
  const skillPath = path.join(root, ".agents", "roles", "phase5-custom-skill", "SKILL.md");
  await mkdir(path.dirname(skillPath), { recursive: true });
  await writeFile(skillPath, validSkillText(), "utf8");

  const loaded = await loadSkillDefinition(skillPath, { sourceScope: "Project" });

  assert.equal(loaded.name, "phase5-custom-skill");
  assert.equal(loaded.source_scope, "project");
  assert.equal(loaded.source_path, path.resolve(skillPath));
  assert.equal(loaded.source_precedence, SKILL_SOURCE_PRECEDENCE.project);
  assert.equal(loaded.content.mode, SKILL_CONTENT_MODE_INLINE_MARKDOWN);
});

test("normalizeSkillSourceScope validates allowed scopes", () => {
  assert.equal(
    normalizeSkillSourceScope(" Project ", {
      fieldName: "skill.source_scope",
      sourceName: "inline skill"
    }),
    "project"
  );
  assert.throws(
    () =>
      normalizeSkillSourceScope("configured", {
        fieldName: "skill.source_scope",
        sourceName: "inline skill"
      }),
    /skill\.source_scope must be one of \(built_in, project, user\)/
  );
});

test("skillSourcePrecedence follows Python source ordering", () => {
  assert.equal(skillSourcePrecedence("project"), 0);
  assert.equal(skillSourcePrecedence("user"), 1);
  assert.equal(skillSourcePrecedence("built_in"), 2);
});

test("enumerateSkillCandidates finds sorted SKILL.md files by root", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-discovery-"));
  const projectRoot = path.join(root, "project");
  await writeSkill(projectRoot, "zeta", { name: "zeta-skill" });
  await writeSkill(projectRoot, "alpha", { name: "alpha-skill" });
  await writeFile(path.join(projectRoot, "notes.md"), "ignore", "utf8");

  const candidates = await enumerateSkillCandidates([{ scope: "project", path: projectRoot }]);

  assert.deepEqual(
    candidates.map((candidate) => candidate.relative_path),
    ["alpha/SKILL.md", "zeta/SKILL.md"]
  );
  assert.equal(candidates[0].scope, "project");
});

test("discoverSkills selects by source precedence and records shadowed skills", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-discovery-"));
  const projectRoot = path.join(root, "project");
  const userRoot = path.join(root, "user");
  const builtInRoot = path.join(root, "built-in");
  await writeSkill(projectRoot, "planner-custom", { name: "planner-custom" });
  await writeSkill(userRoot, "planner-custom", { name: "planner-custom" });
  await writeSkill(builtInRoot, "planner-custom", { name: "planner-custom" });
  await writeSkill(userRoot, "reviewer-custom", { name: "reviewer-custom" });

  const discovery = await discoverSkills([
    { scope: "project", path: projectRoot },
    { scope: "user", path: userRoot },
    { scope: "built_in", path: builtInRoot }
  ]);

  assert.deepEqual(
    discovery.selected.map((skill) => `${skill.name}:${skill.scope}`),
    ["planner-custom:project", "reviewer-custom:user"]
  );
  assert.deepEqual(
    discovery.shadowed.map((skill) => skill.scope),
    ["user", "built_in"]
  );
});

test("discoverSkills rejects duplicate names within one scope", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-discovery-"));
  const projectRoot = path.join(root, "project");
  await writeSkill(projectRoot, "one", { name: "duplicate-skill" });
  await writeSkill(projectRoot, "two", { name: "duplicate-skill" });

  await assert.rejects(
    () => discoverSkills([{ scope: "project", path: projectRoot }]),
    SkillDiscoveryError
  );
});

test("discoverSkills can collect invalid candidates when requested", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-discovery-"));
  const projectRoot = path.join(root, "project");
  await writeSkill(projectRoot, "valid", { name: "valid-skill" });
  const invalidPath = path.join(projectRoot, "invalid", "SKILL.md");
  await mkdir(path.dirname(invalidPath), { recursive: true });
  await writeFile(invalidPath, "---\nname: invalid\n---\n# Missing description\n", "utf8");

  const discovery = await discoverSkills(
    [{ scope: "project", path: projectRoot }],
    { ignoreInvalid: true }
  );

  assert.deepEqual(discovery.selected.map((skill) => skill.name), ["valid-skill"]);
  assert.equal(discovery.invalid.length, 1);
  assert.match(discovery.invalid[0].error, /skill_document\.description/);
});

test("filterSkillsForProfile defaults selected skills to ask-visible", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-visibility-"));
  const projectRoot = path.join(root, "project");
  const userRoot = path.join(root, "user");
  const builtInRoot = path.join(root, "built-in");
  await writeSkill(projectRoot, "alpha", { name: "alpha-skill" });
  await writeSkill(userRoot, "beta", { name: "beta-skill" });
  await writeSkill(builtInRoot, "planning-agent", { name: "planning-agent" });

  const visibility = filterSkillsForProfile(
    await discoverSkills([
      { scope: "project", path: projectRoot },
      { scope: "user", path: userRoot },
      { scope: "built_in", path: builtInRoot }
    ]),
    { name: "planner" }
  );

  assert.equal(visibility.default_decision, "ask");
  assert.deepEqual(
    visibility.visible.map((entry) => entry.name),
    ["alpha-skill", "beta-skill", "planning-agent"]
  );
  assert.deepEqual(visibility.hidden, []);
  assert.deepEqual(
    visibility.entries.map((entry) => entry.visibility_decision),
    ["ask", "ask", "ask"]
  );
});

test("filterSkillsForProfile can hide named skills without affecting others", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-visibility-"));
  const projectRoot = path.join(root, "project");
  const userRoot = path.join(root, "user");
  await writeSkill(projectRoot, "alpha", { name: "alpha-skill" });
  await writeSkill(userRoot, "beta", { name: "beta-skill" });

  const visibility = filterSkillsForProfile(
    await discoverSkills([
      { scope: "project", path: projectRoot },
      { scope: "user", path: userRoot }
    ]),
    {
      name: "reviewer",
      permission_policy: {
        skills: {
          rules: [{ skill: "beta-skill", decision: "deny" }]
        }
      }
    }
  );

  assert.deepEqual(visibility.visible.map((entry) => entry.name), ["alpha-skill"]);
  assert.deepEqual(visibility.hidden.map((entry) => entry.name), ["beta-skill"]);
  assert.equal(visibility.hidden[0].visibility_decision, "deny");
});

test("filterSkillsForProfile reports preloaded visible and missing skills", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-visibility-"));
  const projectRoot = path.join(root, "project");
  const builtInRoot = path.join(root, "built-in");
  await writeSkill(projectRoot, "designing-agent", { name: "designing-agent" });
  await writeSkill(builtInRoot, "planning-agent", { name: "planning-agent" });

  const visibility = filterSkillsForProfile(
    await discoverSkills([
      { scope: "project", path: projectRoot },
      { scope: "built_in", path: builtInRoot }
    ]),
    {
      name: "designer",
      preloaded_skills: ["planning-agent", "designing-agent", "missing-skill"],
      permission_policy: {
        skills: {
          rules: [{ skill: "designing-agent", decision: "deny" }]
        }
      }
    }
  );

  assert.deepEqual(visibility.preloaded.map((entry) => entry.name), ["planning-agent"]);
  assert.deepEqual(visibility.hidden.map((entry) => entry.name), ["designing-agent"]);
  assert.equal(visibility.hidden[0].requested_preload, true);
  assert.equal(visibility.hidden[0].preloaded, false);
  assert.deepEqual(visibility.missing_preloads, [
    { name: "missing-skill", reason: "not_discovered" }
  ]);
});

test("filterSkillsForProfile can allow named skills when default is denied", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-skill-visibility-"));
  const projectRoot = path.join(root, "project");
  const userRoot = path.join(root, "user");
  const builtInRoot = path.join(root, "built-in");
  await writeSkill(projectRoot, "alpha", { name: "alpha-skill" });
  await writeSkill(userRoot, "beta", { name: "beta-skill" });
  await writeSkill(builtInRoot, "planning-agent", { name: "planning-agent" });

  const visibility = filterSkillsForProfile(
    await discoverSkills([
      { scope: "project", path: projectRoot },
      { scope: "user", path: userRoot },
      { scope: "built_in", path: builtInRoot }
    ]),
    {
      name: "custom",
      permission_policy: {
        skills: {
          default: "deny",
          rules: [
            { skill: "alpha-skill", decision: "allow" },
            { skill: "planning-agent", decision: "allow" }
          ]
        }
      }
    }
  );

  assert.deepEqual(
    visibility.visible.map((entry) => entry.name),
    ["alpha-skill", "planning-agent"]
  );
  assert.deepEqual(visibility.hidden.map((entry) => entry.name), ["beta-skill"]);
  assert.deepEqual(visibility.visible.map((entry) => entry.scope), ["project", "built_in"]);
});

test("resolveRuntimeSkillResolution is quiet when only built-in visibility applies", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runtime-skills-"));
  const builtInRoot = path.join(root, "built-in");
  await writeSkill(builtInRoot, "planning-agent", { name: "planning-agent" });

  const resolution = resolveRuntimeSkillResolution(
    await discoverSkills([{ scope: "built_in", path: builtInRoot }]),
    {
      role: "planner",
      profile: {
        name: "planner",
        description: "Planner profile."
      }
    }
  );

  assert.equal(resolution.summary.custom_visible_count, 0);
  assert.equal(resolution.summary.profile_source, "built_in");
  assert.equal(resolution.summary.interesting_for_operator, false);
  assert.deepEqual(resolution.prompt_lines, []);
  assert.deepEqual(runtimeSkillPromptLines(resolution), []);
  assert.deepEqual(runtimeSkillSummary(resolution), resolution.summary);
  assert.equal(runtimeSkillLogLine(resolution), null);
});

test("resolveRuntimeSkillResolution reports custom and hidden skill visibility", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runtime-skills-"));
  const projectRoot = path.join(root, "project");
  const userRoot = path.join(root, "user");
  await writeSkill(projectRoot, "designing-agent", { name: "designing-agent" });
  await writeSkill(userRoot, "reviewer-agent", { name: "reviewer-agent" });

  const resolution = resolveRuntimeSkillResolution(
    await discoverSkills([
      { scope: "project", path: projectRoot },
      { scope: "user", path: userRoot }
    ]),
    {
      role: "designer",
      profile: {
        name: "designer",
        source: "project",
        description: "Designer profile.",
        preloaded_skills: ["designing-agent", "missing-skill"],
        metadata: {
          dormammu_runtime: {
            runtime_role: "designer",
            selected_via_role_config: false
          }
        },
        permission_policy: {
          skills: {
            rules: [{ skill: "reviewer-agent", decision: "deny" }]
          }
        }
      }
    }
  );

  assert.equal(resolution.summary.candidate_count, 2);
  assert.equal(resolution.summary.custom_selected_count, 2);
  assert.equal(resolution.summary.custom_visible_count, 1);
  assert.equal(resolution.summary.hidden_count, 1);
  assert.equal(resolution.summary.preloaded_count, 1);
  assert.equal(resolution.summary.missing_preload_count, 1);
  assert.equal(resolution.summary.interesting_for_operator, true);
  assert.deepEqual(resolution.profile.runtime_metadata, {
    runtime_role: "designer",
    selected_via_role_config: false
  });
  assert.deepEqual(resolution.prompt_lines, [
    "Runtime skills for designer / designer (project profile):",
    "Visible project/user skills: designing-agent [project]",
    "Preloaded skills: designing-agent",
    "Hidden by profile policy: reviewer-agent",
    "Missing requested preloads: missing-skill"
  ]);
  assert.equal(
    runtimeSkillLogLine(resolution),
    "runtime skills: visible=1 custom=1 hidden=1 preloaded=1 missing_preloads=1 shadowed=0"
  );
  assert.deepEqual(runtimeSkillPromptLines({ prompt_lines: ["", "  ", "one"] }), ["one"]);
  assert.deepEqual(runtimeSkillSummary({ summary: { role: "designer" } }), {
    role: "designer"
  });

  const visibility = resolution.visibility as Record<string, unknown>;
  const hidden = visibility.hidden as Record<string, unknown>[];
  assert.equal(hidden[0].name, "reviewer-agent");
  assert.equal(hidden[0].visibility_decision, "deny");
});
