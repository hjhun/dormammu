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
  loadSkillDefinition,
  loadSkillDocument,
  normalizeSkillSourceScope,
  parseSkillDocumentPayload,
  parseSkillDocumentText,
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
