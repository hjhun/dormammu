import os from "node:os";
import path from "node:path";

export const FILESYSTEM_ACCESS_ANY = "*";
export const PERMISSION_DECISIONS = ["allow", "deny", "ask"] as const;

export type PermissionDecision = (typeof PERMISSION_DECISIONS)[number];

export type ToolPermissionRule = {
  tool: string;
  decision: PermissionDecision;
};

export type SkillPermissionRule = {
  skill: string;
  decision: PermissionDecision;
};

export type NetworkPermissionRule = {
  host: string;
  decision: PermissionDecision;
};

export type WorktreePermissionRule = {
  action: string;
  decision: PermissionDecision;
};

export type FilesystemPermissionRule = {
  path: string;
  decision: PermissionDecision;
  access: string[];
};

export type ToolPermissionPolicy = {
  default: PermissionDecision;
  rules: ToolPermissionRule[];
};

export type SkillPermissionPolicy = {
  default: PermissionDecision;
  rules: SkillPermissionRule[];
};

export type NetworkPermissionPolicy = {
  default: PermissionDecision;
  rules: NetworkPermissionRule[];
};

export type WorktreePermissionPolicy = {
  default: PermissionDecision;
  rules: WorktreePermissionRule[];
};

export type FilesystemPermissionPolicy = {
  default: PermissionDecision;
  rules: FilesystemPermissionRule[];
};

export type AgentPermissionPolicy = {
  tools: ToolPermissionPolicy;
  skills: SkillPermissionPolicy;
  filesystem: FilesystemPermissionPolicy;
  network: NetworkPermissionPolicy;
  worktree: WorktreePermissionPolicy;
};

export type ToolPermissionPolicyOverride = {
  default?: PermissionDecision | null;
  rules: ToolPermissionRule[];
};

export type SkillPermissionPolicyOverride = {
  default?: PermissionDecision | null;
  rules: SkillPermissionRule[];
};

export type NetworkPermissionPolicyOverride = {
  default?: PermissionDecision | null;
  rules: NetworkPermissionRule[];
};

export type WorktreePermissionPolicyOverride = {
  default?: PermissionDecision | null;
  rules: WorktreePermissionRule[];
};

export type FilesystemPermissionPolicyOverride = {
  default?: PermissionDecision | null;
  rules: FilesystemPermissionRule[];
};

export type AgentPermissionPolicyOverride = {
  tools?: ToolPermissionPolicyOverride | null;
  skills?: SkillPermissionPolicyOverride | null;
  filesystem?: FilesystemPermissionPolicyOverride | null;
  network?: NetworkPermissionPolicyOverride | null;
  worktree?: WorktreePermissionPolicyOverride | null;
};

type ParseOptions = {
  configRoot?: string | null;
  fieldName: string;
  source: string;
};

export function defaultAgentPermissionPolicy(): AgentPermissionPolicy {
  return {
    tools: { default: "ask", rules: [] },
    skills: { default: "ask", rules: [] },
    filesystem: { default: "ask", rules: [] },
    network: { default: "ask", rules: [] },
    worktree: { default: "ask", rules: [] }
  };
}

export function evaluateToolPermission(
  policy: ToolPermissionPolicy,
  tool: string
): PermissionDecision {
  return evaluateNamedPermission(policy, "tool", tool);
}

export function evaluateSkillPermission(
  policy: SkillPermissionPolicy,
  skill: string
): PermissionDecision {
  return evaluateNamedPermission(policy, "skill", skill);
}

export function evaluateNetworkPermission(
  policy: NetworkPermissionPolicy,
  host: string
): PermissionDecision {
  return evaluateNamedPermission(policy, "host", host);
}

export function evaluateWorktreePermission(
  policy: WorktreePermissionPolicy,
  action: string
): PermissionDecision {
  return evaluateNamedPermission(policy, "action", action);
}

export function evaluateFilesystemPermission(
  policy: FilesystemPermissionPolicy,
  requestPath: string,
  options: { access?: string; evaluationRoot?: string | null } = {}
): PermissionDecision {
  const normalizedPath = resolveFilesystemRequestPath(requestPath, options.evaluationRoot ?? null);
  if (normalizedPath === null) {
    return policy.default;
  }
  const access = (options.access ?? "read").trim().toLowerCase();
  let bestDepth = -1;
  let bestIndex = -1;
  let bestDecision: PermissionDecision | null = null;
  policy.rules.forEach((rule, index) => {
    if (!filesystemRuleMatches(rule, normalizedPath, access)) {
      return;
    }
    const depth = splitPathParts(rule.path).length;
    if (depth > bestDepth || (depth === bestDepth && index >= bestIndex)) {
      bestDepth = depth;
      bestIndex = index;
      bestDecision = rule.decision;
    }
  });
  return bestDecision ?? policy.default;
}

export function mergePermissionPolicy(
  base: AgentPermissionPolicy,
  override: AgentPermissionPolicyOverride | null | undefined
): AgentPermissionPolicy {
  if (!override || permissionPolicyOverrideIsEmpty(override)) {
    return cloneAgentPermissionPolicy(base);
  }
  return {
    tools: mergeNamedPolicy(base.tools, override.tools),
    skills: mergeNamedPolicy(base.skills, override.skills),
    filesystem: mergeFilesystemPolicy(base.filesystem, override.filesystem),
    network: mergeNamedPolicy(base.network, override.network),
    worktree: mergeNamedPolicy(base.worktree, override.worktree)
  };
}

export function parsePermissionPolicyOverride(
  value: unknown,
  options: ParseOptions
): AgentPermissionPolicyOverride {
  const payload = coerceRecord(value, options.fieldName, options.source);
  rejectUnknownKeys(payload, ["tools", "skills", "filesystem", "network", "worktree"], {
    fieldName: options.fieldName,
    source: options.source
  });
  return {
    tools: parseNamedPolicyOverride(
      payload.tools,
      "tool",
      `${options.fieldName}.tools`,
      options.source
    ) as ToolPermissionPolicyOverride | null,
    skills: parseNamedPolicyOverride(
      payload.skills,
      "skill",
      `${options.fieldName}.skills`,
      options.source
    ) as SkillPermissionPolicyOverride | null,
    filesystem: parseFilesystemPolicyOverride(payload.filesystem, {
      configRoot: options.configRoot,
      fieldName: `${options.fieldName}.filesystem`,
      source: options.source
    }),
    network: parseNamedPolicyOverride(
      payload.network,
      "host",
      `${options.fieldName}.network`,
      options.source
    ) as NetworkPermissionPolicyOverride | null,
    worktree: parseNamedPolicyOverride(
      payload.worktree,
      "action",
      `${options.fieldName}.worktree`,
      options.source
    ) as WorktreePermissionPolicyOverride | null
  };
}

export function normalizePermissionDecision(
  value: unknown,
  options: { fieldName: string; source: string }
): PermissionDecision {
  if (typeof value !== "string") {
    throw new Error(`${options.fieldName} must be one of (${PERMISSION_DECISIONS.join(", ")}) in ${options.source}`);
  }
  const normalized = value.trim().toLowerCase();
  if (!isPermissionDecision(normalized)) {
    throw new Error(`${options.fieldName} must be one of (${PERMISSION_DECISIONS.join(", ")}) in ${options.source}`);
  }
  return normalized;
}

function evaluateNamedPermission<T extends Record<string, unknown>>(
  policy: { default: PermissionDecision; rules: T[] },
  key: string,
  value: string
): PermissionDecision {
  const normalizedValue = value.trim();
  for (let index = policy.rules.length - 1; index >= 0; index -= 1) {
    const rule = policy.rules[index];
    if (rule[key] === normalizedValue) {
      return rule.decision as PermissionDecision;
    }
  }
  return policy.default;
}

function mergeNamedPolicy<
  TPolicy extends { default: PermissionDecision; rules: TRule[] },
  TOverride extends { default?: PermissionDecision | null; rules: TRule[] } | null | undefined,
  TRule
>(base: TPolicy, override: TOverride): TPolicy {
  return {
    default: override?.default ?? base.default,
    rules: [...base.rules, ...(override?.rules ?? [])]
  } as TPolicy;
}

function mergeFilesystemPolicy(
  base: FilesystemPermissionPolicy,
  override: FilesystemPermissionPolicyOverride | null | undefined
): FilesystemPermissionPolicy {
  return {
    default: override?.default ?? base.default,
    rules: [...base.rules, ...(override?.rules ?? [])]
  };
}

function parseNamedPolicyOverride(
  value: unknown,
  ruleKey: "tool" | "skill" | "host" | "action",
  fieldName: string,
  source: string
): { default?: PermissionDecision | null; rules: Record<string, string>[] } | null {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value === "string") {
    return { default: normalizePermissionDecision(value, { fieldName, source }), rules: [] };
  }
  const payload = coerceRecord(value, fieldName, source);
  rejectUnknownKeys(payload, ["default", "rules"], { fieldName, source });
  const rules = parseRuleList(payload.rules, `${fieldName}.rules`, source).map((rawRule, index) => {
    const rulePayload = coerceRecord(rawRule, `${fieldName}.rules[${index}]`, source);
    rejectUnknownKeys(rulePayload, [ruleKey, "decision"], {
      fieldName: `${fieldName}.rules[${index}]`,
      source
    });
    return {
      [ruleKey]: requireNonEmptyString(rulePayload[ruleKey], {
        fieldName: `${fieldName}.rules[${index}].${ruleKey}`,
        source
      }),
      decision: normalizePermissionDecision(rulePayload.decision, {
        fieldName: `${fieldName}.rules[${index}].decision`,
        source
      })
    };
  });
  return {
    default:
      payload.default !== undefined && payload.default !== null
        ? normalizePermissionDecision(payload.default, {
            fieldName: `${fieldName}.default`,
            source
          })
        : null,
    rules
  };
}

function parseFilesystemPolicyOverride(
  value: unknown,
  options: ParseOptions
): FilesystemPermissionPolicyOverride | null {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value === "string") {
    return {
      default: normalizePermissionDecision(value, {
        fieldName: options.fieldName,
        source: options.source
      }),
      rules: []
    };
  }
  const payload = coerceRecord(value, options.fieldName, options.source);
  rejectUnknownKeys(payload, ["default", "rules"], options);
  const rules = parseRuleList(payload.rules, `${options.fieldName}.rules`, options.source).map(
    (rawRule, index) => {
      const fieldName = `${options.fieldName}.rules[${index}]`;
      const rulePayload = coerceRecord(rawRule, fieldName, options.source);
      rejectUnknownKeys(rulePayload, ["path", "decision", "access"], {
        fieldName,
        source: options.source
      });
      const rawPath = requireNonEmptyString(rulePayload.path, {
        fieldName: `${fieldName}.path`,
        source: options.source
      });
      return {
        path: resolvePolicyPath(rawPath, options.configRoot ?? null),
        decision: normalizePermissionDecision(rulePayload.decision, {
          fieldName: `${fieldName}.decision`,
          source: options.source
        }),
        access: normalizeAccessList(rulePayload.access, {
          fieldName: `${fieldName}.access`,
          source: options.source
        })
      };
    }
  );
  return {
    default:
      payload.default !== undefined && payload.default !== null
        ? normalizePermissionDecision(payload.default, {
            fieldName: `${options.fieldName}.default`,
            source: options.source
          })
        : null,
    rules
  };
}

function filesystemRuleMatches(
  rule: FilesystemPermissionRule,
  requestPath: string,
  access: string
): boolean {
  if (!rule.access.includes(access) && !rule.access.includes(FILESYSTEM_ACCESS_ANY)) {
    return false;
  }
  return requestPath === rule.path || isSubpath(requestPath, rule.path);
}

function resolvePolicyPath(value: string, configRoot: string | null): string {
  const expanded = expandUserPath(value);
  if (path.isAbsolute(expanded)) {
    return path.resolve(expanded);
  }
  if (configRoot === null) {
    throw new Error("relative filesystem permission paths require an explicit config root");
  }
  return path.resolve(configRoot, expanded);
}

function resolveFilesystemRequestPath(value: string, evaluationRoot: string | null): string | null {
  const expanded = expandUserPath(value);
  if (path.isAbsolute(expanded)) {
    return path.resolve(expanded);
  }
  if (evaluationRoot === null) {
    return null;
  }
  if (!path.isAbsolute(evaluationRoot)) {
    throw new Error("filesystem evaluation root must be absolute");
  }
  return path.resolve(evaluationRoot, expanded);
}

function normalizeAccessList(
  value: unknown,
  options: { fieldName: string; source: string }
): string[] {
  const values =
    value === undefined || value === null
      ? [FILESYSTEM_ACCESS_ANY]
      : typeof value === "string"
        ? [value]
        : Array.isArray(value)
          ? value
          : null;
  if (values === null) {
    throw new Error(`${options.fieldName} must be a string or JSON array in ${options.source}`);
  }
  const normalized: string[] = [];
  for (const item of values) {
    const access = requireNonEmptyString(item, options).toLowerCase();
    if (!normalized.includes(access)) {
      normalized.push(access);
    }
  }
  return normalized.length ? normalized : [FILESYSTEM_ACCESS_ANY];
}

function parseRuleList(value: unknown, fieldName: string, source: string): unknown[] {
  if (value === undefined || value === null) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new Error(`${fieldName} must be a JSON array in ${source}`);
  }
  return value;
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

function cloneAgentPermissionPolicy(policy: AgentPermissionPolicy): AgentPermissionPolicy {
  return {
    tools: { default: policy.tools.default, rules: [...policy.tools.rules] },
    skills: { default: policy.skills.default, rules: [...policy.skills.rules] },
    filesystem: { default: policy.filesystem.default, rules: [...policy.filesystem.rules] },
    network: { default: policy.network.default, rules: [...policy.network.rules] },
    worktree: { default: policy.worktree.default, rules: [...policy.worktree.rules] }
  };
}

function coerceRecord(value: unknown, fieldName: string, source: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${fieldName} must be a JSON object in ${source}`);
  }
  return value;
}

function rejectUnknownKeys(
  payload: Record<string, unknown>,
  allowedKeys: string[],
  options: { fieldName: string; source: string }
): void {
  const allowed = new Set(allowedKeys);
  const unknown = Object.keys(payload).filter((key) => !allowed.has(key)).sort();
  if (unknown.length) {
    throw new Error(
      `${options.fieldName} contains unsupported keys (${unknown.join(", ")}) in ${options.source}`
    );
  }
}

function requireNonEmptyString(
  value: unknown,
  options: { fieldName: string; source: string }
): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${options.fieldName} must be a non-empty string in ${options.source}`);
  }
  return value.trim();
}

function isPermissionDecision(value: string): value is PermissionDecision {
  return (PERMISSION_DECISIONS as readonly string[]).includes(value);
}

function isSubpath(candidate: string, root: string): boolean {
  const relative = path.relative(root, candidate);
  return Boolean(relative) && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function splitPathParts(value: string): string[] {
  return path.resolve(value).split(path.sep).filter(Boolean);
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
