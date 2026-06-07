import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import {
  defaultAgentPermissionPolicy,
  evaluateFilesystemPermission,
  evaluateNetworkPermission,
  evaluateSkillPermission,
  evaluateToolPermission,
  evaluateWorktreePermission,
  mergePermissionPolicy,
  parsePermissionPolicyOverride,
  type AgentPermissionPolicy
} from "./permissions.js";

test("named permission policies use explicit allow deny ask semantics", () => {
  const policy: AgentPermissionPolicy = {
    ...defaultAgentPermissionPolicy(),
    tools: {
      default: "ask",
      rules: [
        { tool: "shell", decision: "allow" },
        { tool: "deploy", decision: "deny" }
      ]
    },
    skills: {
      default: "ask",
      rules: [{ skill: "planning-agent", decision: "deny" }]
    },
    network: {
      default: "deny",
      rules: [{ host: "api.example.com", decision: "ask" }]
    },
    worktree: {
      default: "ask",
      rules: [{ action: "create", decision: "allow" }]
    }
  };

  assert.equal(evaluateToolPermission(policy.tools, "shell"), "allow");
  assert.equal(evaluateToolPermission(policy.tools, "unknown"), "ask");
  assert.equal(evaluateSkillPermission(policy.skills, "planning-agent"), "deny");
  assert.equal(evaluateSkillPermission(policy.skills, "designing-agent"), "ask");
  assert.equal(evaluateNetworkPermission(policy.network, "api.example.com"), "ask");
  assert.equal(evaluateNetworkPermission(policy.network, "other.example.com"), "deny");
  assert.equal(evaluateWorktreePermission(policy.worktree, "create"), "allow");
  assert.equal(evaluateWorktreePermission(policy.worktree, "reuse"), "ask");
});

test("filesystem permission prefers more specific matching paths", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-permissions-"));
  const workspace = path.join(root, "workspace");
  const project = path.join(workspace, "project");
  const secret = path.join(project, "secret");
  const policy = {
    default: "ask" as const,
    rules: [
      { path: workspace, decision: "allow" as const, access: ["read"] },
      { path: project, decision: "deny" as const, access: ["write"] },
      { path: secret, decision: "allow" as const, access: ["write"] }
    ]
  };

  assert.equal(evaluateFilesystemPermission(policy, path.join(project, "notes.txt")), "allow");
  assert.equal(
    evaluateFilesystemPermission(policy, path.join(project, "notes.txt"), { access: "write" }),
    "deny"
  );
  assert.equal(
    evaluateFilesystemPermission(policy, path.join(secret, "notes.txt"), { access: "write" }),
    "allow"
  );
  assert.equal(
    evaluateFilesystemPermission(policy, path.join(root, "outside.txt"), { access: "read" }),
    "ask"
  );
});

test("filesystem permission uses last matching rule for equal specificity", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-permissions-"));
  const project = path.join(root, "project");
  const policy = {
    default: "ask" as const,
    rules: [
      { path: project, decision: "allow" as const, access: ["read"] },
      { path: project, decision: "deny" as const, access: ["read"] }
    ]
  };

  assert.equal(
    evaluateFilesystemPermission(policy, path.join(project, "notes.txt"), { access: "read" }),
    "deny"
  );
});

test("filesystem permission requires explicit root for relative requests", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-permissions-"));
  const project = path.join(root, "project");
  const policy = {
    default: "ask" as const,
    rules: [{ path: project, decision: "allow" as const, access: ["read"] }]
  };

  assert.equal(evaluateFilesystemPermission(policy, "notes.txt"), "ask");
  assert.equal(
    evaluateFilesystemPermission(policy, "notes.txt", {
      access: "read",
      evaluationRoot: project
    }),
    "allow"
  );
});

test("mergePermissionPolicy uses override defaults and rules", () => {
  const base: AgentPermissionPolicy = {
    tools: {
      default: "ask",
      rules: [{ tool: "shell", decision: "allow" }]
    },
    skills: {
      default: "ask",
      rules: [{ skill: "planning-agent", decision: "allow" }]
    },
    filesystem: { default: "deny", rules: [] },
    network: { default: "deny", rules: [] },
    worktree: { default: "ask", rules: [] }
  };
  const merged = mergePermissionPolicy(base, {
    tools: { rules: [{ tool: "shell", decision: "deny" }] },
    skills: {
      default: "deny",
      rules: [{ skill: "designing-agent", decision: "allow" }]
    },
    filesystem: { default: "ask", rules: [] },
    network: { rules: [{ host: "api.example.com", decision: "allow" }] },
    worktree: { default: "deny", rules: [] }
  });

  assert.equal(evaluateToolPermission(merged.tools, "shell"), "deny");
  assert.equal(evaluateSkillPermission(merged.skills, "planning-agent"), "allow");
  assert.equal(evaluateSkillPermission(merged.skills, "designing-agent"), "allow");
  assert.equal(evaluateSkillPermission(merged.skills, "reviewer-custom"), "deny");
  assert.equal(evaluateFilesystemPermission(merged.filesystem, "/tmp/example"), "ask");
  assert.equal(evaluateNetworkPermission(merged.network, "api.example.com"), "allow");
  assert.equal(evaluateNetworkPermission(merged.network, "other.example.com"), "deny");
  assert.equal(evaluateWorktreePermission(merged.worktree, "create"), "deny");
});

test("parsePermissionPolicyOverride resolves relative filesystem paths", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-permissions-"));
  const override = parsePermissionPolicyOverride(
    {
      tools: "deny",
      skills: {
        default: "deny",
        rules: [{ skill: "planning-agent", decision: "allow" }]
      },
      filesystem: {
        default: "ask",
        rules: [{ path: "./sandbox", access: ["read", "write"], decision: "allow" }]
      },
      network: { rules: [{ host: "api.example.com", decision: "allow" }] },
      worktree: { default: "deny" }
    },
    {
      configRoot: root,
      fieldName: "agents.developer.permission_policy",
      source: "dormammu.json"
    }
  );

  assert.equal(override.tools?.default, "deny");
  assert.equal(override.skills?.default, "deny");
  assert.equal(override.skills?.rules[0].skill, "planning-agent");
  assert.equal(override.filesystem?.rules[0].path, path.resolve(root, "sandbox"));
  assert.equal(override.filesystem?.rules[0].access.join(","), "read,write");
  assert.equal(override.network?.rules[0].host, "api.example.com");
  assert.equal(override.worktree?.default, "deny");
});

test("parsePermissionPolicyOverride rejects unknown nested policy keys", () => {
  assert.throws(
    () =>
      parsePermissionPolicyOverride(
        { tools: { bogus: true } },
        {
          configRoot: null,
          fieldName: "agents.developer.permission_policy",
          source: "dormammu.json"
        }
      ),
    /agents\.developer\.permission_policy\.tools contains unsupported keys \(bogus\)/
  );
});

test("parsePermissionPolicyOverride rejects unknown rule keys", () => {
  assert.throws(
    () =>
      parsePermissionPolicyOverride(
        {
          filesystem: {
            rules: [{ path: "/tmp/workspace", decision: "allow", unexpected: "value" }]
          }
        },
        {
          configRoot: null,
          fieldName: "agents.developer.permission_policy",
          source: "dormammu.json"
        }
      ),
    /agents\.developer\.permission_policy\.filesystem\.rules\[0\] contains unsupported keys \(unexpected\)/
  );
});
