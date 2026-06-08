import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { evaluateSkillPermission } from "./permissions.js";
import {
  availableProfileCatalog,
  builtInProfileForRole,
  mergeAgentsConfig,
  normalizeAgentProfiles,
  parseAgentsConfig,
  profileFromRoleConfig,
  profileNameForRole,
  requestedManifestProfileNames,
  resolveProfileCli,
  resolveRuntimeRoleProfile,
  roleRequiresManifestResolution,
  ROLE_NAMES,
  type AgentProfile
} from "./profiles.js";

test("built-in agent profiles use role defaults", () => {
  const profile = builtInProfileForRole("planner");

  assert.equal(profile.name, "planner");
  assert.equal(profile.source, "built_in");
  assert.equal(profile.cli_override, null);
  assert.equal(profile.model_override, null);
  assert.equal(profile.permission_policy.skills.default, "ask");
  assert.equal(resolveProfileCli(profile, "codex"), "codex");
});

test("profileFromRoleConfig applies role cli model and permission overrides", () => {
  const profile = profileFromRoleConfig("planner", {
    profile: null,
    cli: "claude",
    model: "claude-opus-4-5",
    permission_policy: {
      skills: {
        default: "deny",
        rules: [{ skill: "planning-agent", decision: "allow" }]
      }
    }
  });

  assert.equal(profile.name, "planner");
  assert.equal(profile.source, "configured");
  assert.equal(profile.cli_override, "claude");
  assert.equal(profile.model_override, "claude-opus-4-5");
  assert.equal(evaluateSkillPermission(profile.permission_policy.skills, "planning-agent"), "allow");
  assert.equal(evaluateSkillPermission(profile.permission_policy.skills, "designing-agent"), "deny");
  assert.deepEqual(profile.metadata.dormammu_runtime, {
    runtime_role: "planner",
    selected_profile_name: "planner",
    selected_profile_source: "built_in",
    selected_via_role_config: false,
    role_overrides: {
      cli: true,
      model: true,
      permission_policy: true
    }
  });
});

test("parseAgentsConfig resolves relative cli paths against config directory", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-profiles-"));
  const configPath = path.join(root, ".dormammu", "config");
  const agents = parseAgentsConfig(
    {
      planner: {
        cli: "./bin/planner",
        model: "gpt-5.4"
      },
      reviewer: {
        cli: "claude"
      }
    },
    { configPath }
  );

  assert.notEqual(agents, null);
  assert.equal(agents?.planner.cli, path.resolve(path.dirname(configPath), "bin/planner"));
  assert.equal(agents?.planner.model, "gpt-5.4");
  assert.equal(agents?.reviewer.cli, "claude");
  assert.equal(agents?.developer.cli, null);
});

test("mergeAgentsConfig prefers override values and preserves base model", () => {
  const base = parseAgentsConfig({
    planner: { cli: "claude", model: "claude-opus-4-5" }
  });
  const override = parseAgentsConfig({
    planner: { cli: "codex" }
  });
  const merged = mergeAgentsConfig(base, override);

  assert.equal(merged?.planner.cli, "codex");
  assert.equal(merged?.planner.model, "claude-opus-4-5");
});

test("normalizeAgentProfiles snapshots effective profiles for all roles", () => {
  const agents = parseAgentsConfig({
    planner: {
      cli: "codex",
      model: "gpt-5.4"
    }
  });
  const profiles = normalizeAgentProfiles({ agentsConfig: agents });

  assert.deepEqual(Object.keys(profiles), ROLE_NAMES);
  assert.equal(profiles.planner.cli_override, "codex");
  assert.equal(profiles.planner.model_override, "gpt-5.4");
  assert.equal(profiles.developer.source, "built_in");
});

test("resolveRuntimeRoleProfile uses normalized profile snapshot when present", () => {
  const profiles = normalizeAgentProfiles({
    agentsConfig: parseAgentsConfig({ reviewer: { cli: "claude" } })
  });

  const reviewer = resolveRuntimeRoleProfile("reviewer", {
    normalizedProfiles: profiles
  });

  assert.equal(reviewer.cli_override, "claude");
});

test("role config can select an available manifest-backed profile", () => {
  const manifestProfile: AgentProfile = {
    name: "planner-custom",
    description: "Project planner",
    source: "project",
    prompt_body: "Plan from project context.",
    cli_override: "/repo/bin/planner",
    model_override: "gpt-5.4",
    permission_policy: builtInProfileForRole("planner").permission_policy,
    preloaded_skills: ["planning-agent"],
    metadata: {}
  };
  const profile = profileFromRoleConfig(
    "planner",
    { profile: "planner-custom", cli: null, model: null, permission_policy: null },
    { availableProfiles: availableProfileCatalog([manifestProfile]) }
  );

  assert.equal(profile.name, "planner-custom");
  assert.equal(profile.source, "project");
  assert.equal(profile.cli_override, "/repo/bin/planner");
  assert.deepEqual(profile.preloaded_skills, ["planning-agent"]);
  assert.equal(profileNameForRole("planner", { profile: "planner-custom", cli: null, model: null, permission_policy: null }), "planner-custom");
  assert.deepEqual((profile.metadata.dormammu_runtime as Record<string, unknown>).role_overrides, {
    cli: false,
    model: false,
    permission_policy: false
  });
});

test("requestedManifestProfileNames deduplicates non built-in profile requests", () => {
  const agents = parseAgentsConfig({
    planner: { profile: "shared-custom" },
    reviewer: { profile: "shared-custom" },
    developer: { profile: "developer-custom" },
    tester: { profile: "tester" }
  });

  assert.deepEqual(requestedManifestProfileNames(agents), [
    "shared-custom",
    "developer-custom"
  ]);
  assert.equal(roleRequiresManifestResolution("planner", { agentsConfig: agents }), true);
  assert.equal(roleRequiresManifestResolution("tester", { agentsConfig: agents }), false);
});

test("availableProfileCatalog rejects manifest profiles that shadow built-ins", () => {
  const planner = builtInProfileForRole("planner");

  assert.throws(
    () => availableProfileCatalog([{ ...planner }]),
    /conflicts with an existing built-in profile name/
  );
});
