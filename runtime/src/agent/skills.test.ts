import assert from "node:assert/strict";
import test from "node:test";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import path from "node:path";
import { tmpdir } from "node:os";

import {
  SKILL_CONTENT_MODE_INLINE_MARKDOWN,
  SKILL_DOCUMENT_SCHEMA_VERSION,
  SKILL_SOURCE_PRECEDENCE,
  SkillDocumentError,
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
