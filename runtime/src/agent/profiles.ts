import path from "node:path";
import os from "node:os";

import {
  defaultAgentPermissionPolicy,
  mergePermissionPolicy,
  parsePermissionPolicyOverride,
  type AgentPermissionPolicy,
  type AgentPermissionPolicyOverride,
  type WorktreePermissionPolicy
} from "./permissions.js";

export const BUILTIN_PROFILE_SOURCE = "built_in";
export const CONFIGURED_PROFILE_SOURCE = "configured";
export const PROJECT_PROFILE_SOURCE = "project";
export const USER_PROFILE_SOURCE = "user";
export const PROFILE_RUNTIME_METADATA_KEY = "dormammu_runtime";

export type RoleTaxonomyEntry = {
  name: string;
  scope: string;
  description: string;
};

export const ROLE_TAXONOMY = [
  {
    name: "refiner",
    scope: "runtime",
    description: "Refines the raw request into explicit implementation requirements."
  },
  {
    name: "analyzer",
    scope: "goals_autonomous_only",
    description:
      "Analyzes scheduled goals or autonomous repository context before a runtime prompt is queued."
  },
  {
    name: "planner",
    scope: "runtime_and_goals_prelude",
    description: "Plans the task and updates the operator-facing workflow state."
  },
  {
    name: "designer",
    scope: "goals_prelude_only",
    description:
      "Adds optional technical design context to goals-scheduler prompts; runtime review reads its design document when present."
  },
  {
    name: "developer",
    scope: "runtime",
    description: "Implements the active product-code slice under supervisor control."
  },
  {
    name: "tester",
    scope: "runtime",
    description: "Runs black-box validation against the observable behavior of the slice."
  },
  {
    name: "reviewer",
    scope: "runtime",
    description: "Reviews changed code for regressions, bugs, and missing coverage."
  },
  {
    name: "committer",
    scope: "runtime",
    description: "Prepares validated changes for version-control handoff."
  },
  {
    name: "evaluator",
    scope: "goals_checkpoint_only",
    description: "Evaluates goals-scheduler plan checkpoints and final goal completion."
  }
] as const satisfies readonly RoleTaxonomyEntry[];

export type RoleName = (typeof ROLE_TAXONOMY)[number]["name"];
export const ROLE_NAMES = ROLE_TAXONOMY.map((entry) => entry.name) as RoleName[];
export const RUNTIME_PIPELINE_ROLE_NAMES = [
  "refiner",
  "planner",
  "developer",
  "tester",
  "reviewer",
  "committer"
] as const;
export const GOALS_PRELUDE_ROLE_NAMES = ["analyzer", "planner", "designer"] as const;
export const GOALS_OR_AUTONOMOUS_ONLY_ROLE_NAMES = [
  "analyzer",
  "designer",
  "evaluator"
] as const;

export type AgentProfile = {
  name: string;
  description: string;
  source: string;
  prompt_body: string | null;
  cli_override: string | null;
  model_override: string | null;
  permission_policy: AgentPermissionPolicy;
  preloaded_skills: string[];
  metadata: Record<string, unknown>;
};

export type RoleAgentConfig = {
  profile: string | null;
  cli: string | null;
  model: string | null;
  permission_policy: AgentPermissionPolicyOverride | null;
};

export type AgentsConfig = Record<RoleName, RoleAgentConfig>;

export function defaultRoleAgentConfig(): RoleAgentConfig {
  return {
    profile: null,
    cli: null,
    model: null,
    permission_policy: null
  };
}

export function defaultAgentsConfig(): AgentsConfig {
  return Object.fromEntries(
    ROLE_NAMES.map((role) => [role, defaultRoleAgentConfig()])
  ) as AgentsConfig;
}

export function builtInProfiles(): AgentProfile[] {
  return ROLE_TAXONOMY.map((entry) => ({
    name: entry.name,
    description: entry.description,
    source: BUILTIN_PROFILE_SOURCE,
    prompt_body: null,
    cli_override: null,
    model_override: null,
    permission_policy: defaultAgentPermissionPolicy(),
    preloaded_skills: [],
    metadata: {}
  }));
}

export function profileNameForRole(
  role: string,
  roleConfig: RoleAgentConfig | null = null
): string {
  assertRoleName(role);
  return roleConfig?.profile ?? role;
}

export function builtInProfileForRole(role: string): AgentProfile {
  const profileName = profileNameForRole(role);
  const profile = builtInProfiles().find((candidate) => candidate.name === profileName);
  if (!profile) {
    throw new Error(
      `Role ${JSON.stringify(role)} maps to profile ${JSON.stringify(profileName)}, but no built-in profile with that name is available.`
    );
  }
  return profile;
}

export function availableProfileCatalog(
  manifestProfiles: readonly AgentProfile[] = []
): Record<string, AgentProfile> {
  const profiles: Record<string, AgentProfile> = {};
  for (const profile of builtInProfiles()) {
    profiles[profile.name] = cloneAgentProfile(profile);
  }
  for (const profile of manifestProfiles) {
    if (profiles[profile.name]) {
      throw new Error(
        `Manifest-backed profile ${JSON.stringify(profile.name)} conflicts with an existing built-in profile name.`
      );
    }
    profiles[profile.name] = cloneAgentProfile(profile);
  }
  return profiles;
}

export function profileFromRoleConfig(
  role: string,
  roleConfig: RoleAgentConfig | null = null,
  options: {
    availableProfiles?: Record<string, AgentProfile> | null;
    manifestProfiles?: readonly AgentProfile[];
  } = {}
): AgentProfile {
  const baseProfileName = profileNameForRole(role, roleConfig);
  const catalog =
    options.availableProfiles ?? availableProfileCatalog(options.manifestProfiles ?? []);
  const baseProfile = catalog[baseProfileName];
  if (!baseProfile) {
    throw new Error(
      `Role ${JSON.stringify(role)} maps to profile ${JSON.stringify(baseProfileName)}, but no effective profile with that name is available.`
    );
  }
  const roleOverridePresent = roleAgentOverridePresent(roleConfig);
  const effectiveProfile = roleOverridePresent
    ? {
        ...cloneAgentProfile(baseProfile),
        source: CONFIGURED_PROFILE_SOURCE,
        cli_override: roleConfig?.cli ?? baseProfile.cli_override,
        model_override: roleConfig?.model ?? baseProfile.model_override,
        permission_policy: mergePermissionPolicy(
          baseProfile.permission_policy,
          roleConfig?.permission_policy
        )
      }
    : cloneAgentProfile(baseProfile);
  return {
    ...effectiveProfile,
    metadata: {
      ...effectiveProfile.metadata,
      [PROFILE_RUNTIME_METADATA_KEY]: runtimeResolutionMetadata({
        role,
        baseProfile,
        roleConfig
      })
    }
  };
}

export function normalizeAgentProfiles(
  options: {
    agentsConfig?: AgentsConfig | null;
    manifestProfiles?: readonly AgentProfile[];
  } = {}
): Record<RoleName, AgentProfile> {
  const catalog = availableProfileCatalog(options.manifestProfiles ?? []);
  return Object.fromEntries(
    ROLE_NAMES.map((role) => [
      role,
      profileFromRoleConfig(role, options.agentsConfig?.[role] ?? null, {
        availableProfiles: catalog,
        manifestProfiles: options.manifestProfiles ?? []
      })
    ])
  ) as Record<RoleName, AgentProfile>;
}

export function resolveRuntimeRoleProfile(
  role: string,
  options: {
    agentsConfig?: AgentsConfig | null;
    normalizedProfiles?: Partial<Record<RoleName, AgentProfile>> | null;
    manifestProfiles?: readonly AgentProfile[];
  } = {}
): AgentProfile {
  assertRoleName(role);
  const roleName = role as RoleName;
  if (options.normalizedProfiles) {
    const profile = options.normalizedProfiles[roleName];
    if (!profile) {
      const roleConfig = options.agentsConfig?.[roleName] ?? null;
      const profileName = profileNameForRole(role, roleConfig);
      throw new Error(
        `Role ${JSON.stringify(role)} maps to profile ${JSON.stringify(profileName)}, but no effective profile with that name is available.`
      );
    }
    return cloneAgentProfile(profile);
  }
  return profileFromRoleConfig(role, options.agentsConfig?.[roleName] ?? null, {
    manifestProfiles: options.manifestProfiles ?? []
  });
}

export function parseAgentsConfig(
  value: unknown,
  options: { configPath?: string | null } = {}
): AgentsConfig | null {
  if (value === undefined || value === null) {
    return null;
  }
  const source = options.configPath ?? "dormammu.json";
  const payload = coerceRecord(value, "agents", source);
  return Object.fromEntries(
    ROLE_NAMES.map((role) => [
      role,
      parseRoleAgentConfig(payload[role], {
        role,
        configPath: options.configPath ?? null
      })
    ])
  ) as AgentsConfig;
}

export function parseRoleAgentConfig(
  value: unknown,
  options: { role: RoleName; configPath?: string | null }
): RoleAgentConfig {
  if (value === undefined || value === null) {
    return defaultRoleAgentConfig();
  }
  const source = options.configPath ?? "dormammu.json";
  const payload = coerceRecord(value, `agents.${options.role}`, source);
  return {
    profile: parseOptionalString(payload.profile, `agents.${options.role}.profile`, source),
    cli: parseCli(payload.cli, options.configPath ?? null, `agents.${options.role}.cli`, source),
    model: parseOptionalString(payload.model, `agents.${options.role}.model`, source),
    permission_policy:
      payload.permission_policy === undefined || payload.permission_policy === null
        ? null
        : parsePermissionPolicyOverride(payload.permission_policy, {
            configRoot: options.configPath ? path.dirname(options.configPath) : null,
            fieldName: `agents.${options.role}.permission_policy`,
            source
          })
  };
}

export function mergeRoleAgentConfig(
  base: RoleAgentConfig,
  override: RoleAgentConfig
): RoleAgentConfig {
  return {
    profile: override.profile ?? base.profile,
    cli: override.cli ?? base.cli,
    model: override.model ?? base.model,
    permission_policy: mergePermissionPolicyOverride(base.permission_policy, override.permission_policy)
  };
}

export function mergeAgentsConfig(
  base: AgentsConfig | null,
  override: AgentsConfig | null
): AgentsConfig | null {
  if (!base) {
    return override;
  }
  if (!override) {
    return base;
  }
  return Object.fromEntries(
    ROLE_NAMES.map((role) => [role, mergeRoleAgentConfig(base[role], override[role])])
  ) as AgentsConfig;
}

export function resolveProfileCli(
  profile: AgentProfile,
  activeAgentCli: string | null
): string | null {
  return profile.cli_override ?? activeAgentCli;
}

export function profileWorktreePolicy(profile: AgentProfile): WorktreePermissionPolicy {
  return profile.permission_policy.worktree;
}

function mergePermissionPolicyOverride(
  base: AgentPermissionPolicyOverride | null,
  override: AgentPermissionPolicyOverride | null
): AgentPermissionPolicyOverride | null {
  if (!base || permissionPolicyOverrideIsEmpty(base)) {
    return override;
  }
  if (!override || permissionPolicyOverrideIsEmpty(override)) {
    return base;
  }
  return {
    tools: mergePolicyOverrideBlock(base.tools, override.tools),
    skills: mergePolicyOverrideBlock(base.skills, override.skills),
    filesystem: mergePolicyOverrideBlock(base.filesystem, override.filesystem),
    network: mergePolicyOverrideBlock(base.network, override.network),
    worktree: mergePolicyOverrideBlock(base.worktree, override.worktree)
  };
}

function mergePolicyOverrideBlock<T extends { default?: string | null; rules: unknown[] }>(
  base: T | null | undefined,
  override: T | null | undefined
): T | null {
  if (!base) {
    return override ?? null;
  }
  if (!override) {
    return base;
  }
  return {
    default: override.default ?? base.default ?? null,
    rules: [...base.rules, ...override.rules]
  } as T;
}

function runtimeResolutionMetadata(options: {
  role: string;
  baseProfile: AgentProfile;
  roleConfig: RoleAgentConfig | null;
}): Record<string, unknown> {
  const roleConfig = options.roleConfig;
  return {
    runtime_role: options.role,
    selected_profile_name: options.baseProfile.name,
    selected_profile_source: options.baseProfile.source,
    selected_via_role_config: roleConfig?.profile !== null && roleConfig?.profile !== undefined,
    role_overrides: {
      cli: roleConfig?.cli !== null && roleConfig?.cli !== undefined,
      model: roleConfig?.model !== null && roleConfig?.model !== undefined,
      permission_policy:
        roleConfig?.permission_policy !== null && roleConfig?.permission_policy !== undefined
    }
  };
}

function roleAgentOverridePresent(roleConfig: RoleAgentConfig | null): boolean {
  return Boolean(roleConfig?.cli ?? roleConfig?.model ?? roleConfig?.permission_policy);
}

function permissionPolicyOverrideIsEmpty(override: AgentPermissionPolicyOverride): boolean {
  return (
    !override.tools &&
    !override.skills &&
    !override.filesystem &&
    !override.network &&
    !override.worktree
  );
}

function cloneAgentProfile(profile: AgentProfile): AgentProfile {
  return {
    ...profile,
    permission_policy: {
      tools: { ...profile.permission_policy.tools, rules: [...profile.permission_policy.tools.rules] },
      skills: { ...profile.permission_policy.skills, rules: [...profile.permission_policy.skills.rules] },
      filesystem: {
        ...profile.permission_policy.filesystem,
        rules: [...profile.permission_policy.filesystem.rules]
      },
      network: { ...profile.permission_policy.network, rules: [...profile.permission_policy.network.rules] },
      worktree: { ...profile.permission_policy.worktree, rules: [...profile.permission_policy.worktree.rules] }
    },
    preloaded_skills: [...profile.preloaded_skills],
    metadata: { ...profile.metadata }
  };
}

function parseCli(
  value: unknown,
  configPath: string | null,
  fieldName: string,
  source: string
): string | null {
  const raw = parseOptionalString(value, fieldName, source);
  if (raw === null) {
    return null;
  }
  const candidate = expandUserPath(raw);
  const configDir = configPath ? path.dirname(configPath) : null;
  if (path.isAbsolute(candidate)) {
    return candidate;
  }
  if (configDir && (raw.includes("/") || raw.startsWith("."))) {
    return path.resolve(configDir, candidate);
  }
  return candidate;
}

function parseOptionalString(value: unknown, fieldName: string, source: string): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${fieldName} must be a non-empty string in ${source}`);
  }
  return value.trim();
}

function assertRoleName(role: string): asserts role is RoleName {
  if (!ROLE_NAMES.includes(role as RoleName)) {
    throw new Error(`Unknown role: ${JSON.stringify(role)}. Valid roles: ${ROLE_NAMES.join(",")}`);
  }
}

function coerceRecord(value: unknown, fieldName: string, source: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${fieldName} must be a JSON object in ${source}`);
  }
  return value as Record<string, unknown>;
}

function expandUserPath(value: string): string {
  if (value === "~") {
    return os.homedir();
  }
  if (value.startsWith(`~${path.sep}`) || value.startsWith("~/")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}
