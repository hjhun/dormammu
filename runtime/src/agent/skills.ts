import { basename, relative, resolve } from "node:path";
import { readdir, readFile } from "node:fs/promises";

export const SKILL_DOCUMENT_FILENAME = "SKILL.md";
export const SKILL_DOCUMENT_SCHEMA_VERSION = 1;
export const SKILL_CONTENT_MODE_INLINE_MARKDOWN = "inline_markdown";
export const SKILL_SOURCE_SCOPES = ["built_in", "project", "user"] as const;
export const SKILL_SOURCE_PRECEDENCE_ORDER = ["project", "user", "built_in"] as const;
export const SKILL_SOURCE_PRECEDENCE: Record<SkillSourceScope, number> = {
  project: 0,
  user: 1,
  built_in: 2
};

export type SkillSourceScope = (typeof SKILL_SOURCE_SCOPES)[number];

export class SkillDocumentError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SkillDocumentError";
  }
}

export class SkillDiscoveryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SkillDiscoveryError";
  }
}

export type SkillContent = {
  mode: typeof SKILL_CONTENT_MODE_INLINE_MARKDOWN;
  text: string;
};

export type SkillDocument = {
  schema_version: number;
  name: string;
  description: string;
  content: SkillContent;
  metadata: Record<string, unknown>;
};

export type LoadedSkillDefinition = {
  name: string;
  description: string;
  schema_version: number;
  source_scope: SkillSourceScope;
  source_precedence: number;
  source_path: string;
  content: SkillContent;
  metadata: Record<string, unknown>;
};

export type SkillSearchRoot = {
  scope: SkillSourceScope;
  path: string;
};

export type SkillCandidate = {
  scope: SkillSourceScope;
  root_dir: string;
  path: string;
  relative_path: string;
};

export type DiscoveredSkill = {
  name: string;
  scope: SkillSourceScope;
  path: string;
  relative_path: string;
  source_precedence: number;
  description: string;
  definition: LoadedSkillDefinition;
  candidate: SkillCandidate;
};

export type InvalidSkillCandidate = {
  candidate: SkillCandidate;
  error: string;
};

export type SkillDiscovery = {
  search_roots: SkillSearchRoot[];
  candidates: SkillCandidate[];
  selected: DiscoveredSkill[];
  shadowed: DiscoveredSkill[];
  invalid: InvalidSkillCandidate[];
};

export type PermissionDecision = "allow" | "deny" | "ask";

export type SkillPermissionRule = {
  skill: string;
  decision: PermissionDecision;
};

export type SkillPermissionPolicy = {
  default?: PermissionDecision;
  rules?: SkillPermissionRule[];
};

export type AgentSkillProfile = {
  name: string;
  description?: string;
  source?: string;
  preloaded_skills?: string[];
  permission_policy?: {
    skills?: SkillPermissionPolicy;
  };
  metadata?: Record<string, unknown>;
};

export type MissingSkillPreload = {
  name: string;
  reason: "not_discovered";
};

export type FilteredSkillEntry = DiscoveredSkill & {
  visibility_decision: PermissionDecision;
  visible: boolean;
  requested_preload: boolean;
  preloaded: boolean;
};

export type ProfileSkillVisibility = {
  profile_name: string;
  profile_source: string;
  default_decision: PermissionDecision;
  entries: FilteredSkillEntry[];
  visible: FilteredSkillEntry[];
  hidden: FilteredSkillEntry[];
  preloaded: FilteredSkillEntry[];
  missing_preloads: MissingSkillPreload[];
  shadowed: DiscoveredSkill[];
};

export type RuntimeSkillSummary = {
  role: string;
  profile_name: string;
  profile_source: string;
  candidate_count: number;
  selected_count: number;
  invalid_count: number;
  visible_count: number;
  hidden_count: number;
  preloaded_count: number;
  missing_preload_count: number;
  shadowed_count: number;
  custom_selected_count: number;
  custom_visible_count: number;
  interesting_for_operator: boolean;
};

export type RuntimeSkillResolution = {
  role: string;
  profile: {
    name: string;
    source: string;
    description: string;
    preloaded_skills: string[];
    runtime_metadata: Record<string, unknown>;
  };
  summary: RuntimeSkillSummary;
  discovery: Record<string, unknown>;
  visibility: Record<string, unknown>;
  prompt_lines: string[];
};

export async function loadSkillDocument(path: string): Promise<SkillDocument> {
  const normalizedPath = resolve(path);
  if (basename(normalizedPath) !== SKILL_DOCUMENT_FILENAME) {
    throw new SkillDocumentError(
      `Skill documents must be named ${SKILL_DOCUMENT_FILENAME}: ${normalizedPath}`
    );
  }
  let rawText: string;
  try {
    rawText = await readFile(normalizedPath, "utf8");
  } catch (error) {
    throw new SkillDocumentError(`Failed to read skill document ${normalizedPath}`);
  }
  return parseSkillDocumentText(rawText, { sourceName: normalizedPath });
}

export async function enumerateSkillCandidates(
  searchRoots: SkillSearchRoot[]
): Promise<SkillCandidate[]> {
  const candidates: SkillCandidate[] = [];
  for (const root of searchRoots) {
    const normalizedScope = normalizeSkillSourceScope(root.scope, {
      fieldName: "skill_search_root.scope",
      sourceName: root.path
    });
    const rootPath = resolve(root.path);
    for (const candidatePath of await findSkillDocuments(rootPath)) {
      candidates.push({
        scope: normalizedScope,
        root_dir: rootPath,
        path: candidatePath,
        relative_path: relative(rootPath, candidatePath).split("\\").join("/")
      });
    }
  }
  return candidates;
}

export async function discoverSkills(
  searchRoots: SkillSearchRoot[],
  options: { ignoreInvalid?: boolean } = {}
): Promise<SkillDiscovery> {
  const normalizedRoots = searchRoots.map((root) => ({
    scope: normalizeSkillSourceScope(root.scope, {
      fieldName: "skill_search_root.scope",
      sourceName: root.path
    }),
    path: resolve(root.path)
  }));
  const candidates = await enumerateSkillCandidates(normalizedRoots);
  const discovered: DiscoveredSkill[] = [];
  const invalid: InvalidSkillCandidate[] = [];
  for (const candidate of candidates) {
    try {
      discovered.push(await loadDiscoveredSkill(candidate));
    } catch (error) {
      if (!options.ignoreInvalid) {
        throw error;
      }
      invalid.push({
        candidate,
        error: error instanceof Error ? error.message : String(error)
      });
    }
  }
  const [selected, shadowed] = resolveSkillPrecedence(discovered);
  return {
    search_roots: normalizedRoots,
    candidates,
    selected,
    shadowed,
    invalid
  };
}

export function filterSkillsForProfile(
  discovery: SkillDiscovery,
  profile: AgentSkillProfile
): ProfileSkillVisibility {
  const requestedPreloads = normalizeRequestedPreloads(profile.preloaded_skills ?? []);
  const selectedNames = new Set(discovery.selected.map((skill) => skill.name));
  const entries = discovery.selected.map((discovered) => {
    const visibilityDecision = evaluateSkillPermission(discovered.name, profile);
    const requestedPreload = requestedPreloads.includes(discovered.name);
    const visible = visibilityDecision !== "deny";
    return {
      ...discovered,
      visibility_decision: visibilityDecision,
      visible,
      requested_preload: requestedPreload,
      preloaded: visible && requestedPreload
    };
  });
  const missingPreloads = requestedPreloads
    .filter((name) => !selectedNames.has(name))
    .map((name) => ({ name, reason: "not_discovered" as const }));
  return {
    profile_name: profile.name,
    profile_source: profile.source ?? "built_in",
    default_decision: profile.permission_policy?.skills?.default ?? "ask",
    entries,
    visible: entries.filter((entry) => entry.visible),
    hidden: entries.filter((entry) => !entry.visible),
    preloaded: entries.filter((entry) => entry.preloaded),
    missing_preloads: missingPreloads,
    shadowed: discovery.shadowed
  };
}

export function resolveRuntimeSkillResolution(
  discovery: SkillDiscovery,
  options: {
    role: string;
    profile: AgentSkillProfile;
    visibility?: ProfileSkillVisibility;
  }
): RuntimeSkillResolution {
  const role = options.role.trim();
  if (!role) {
    throw new Error("role must contain a non-empty value.");
  }
  const profile = options.profile;
  const visibility = options.visibility ?? filterSkillsForProfile(discovery, profile);
  const customSelected = discovery.selected.filter((skill) => isCustomSkillScope(skill.scope));
  const customVisible = visibility.visible.filter((entry) => isCustomSkillScope(entry.scope));
  const interestingForOperator =
    customSelected.length > 0 ||
    visibility.hidden.length > 0 ||
    visibility.preloaded.length > 0 ||
    visibility.missing_preloads.length > 0 ||
    visibility.shadowed.length > 0;
  const profileSource = profile.source ?? "built_in";
  const summary: RuntimeSkillSummary = {
    role,
    profile_name: profile.name,
    profile_source: profileSource,
    candidate_count: discovery.candidates.length,
    selected_count: discovery.selected.length,
    invalid_count: discovery.invalid.length,
    visible_count: visibility.visible.length,
    hidden_count: visibility.hidden.length,
    preloaded_count: visibility.preloaded.length,
    missing_preload_count: visibility.missing_preloads.length,
    shadowed_count: visibility.shadowed.length,
    custom_selected_count: customSelected.length,
    custom_visible_count: customVisible.length,
    interesting_for_operator: interestingForOperator
  };
  return {
    role,
    profile: {
      name: profile.name,
      source: profileSource,
      description: profile.description ?? "",
      preloaded_skills: normalizeRequestedPreloads(profile.preloaded_skills ?? []),
      runtime_metadata: runtimeMetadata(profile.metadata)
    },
    summary,
    discovery: skillDiscoveryToPayload(discovery),
    visibility: profileSkillVisibilityToPayload(visibility),
    prompt_lines: runtimeSkillResolutionPromptLines({
      role,
      profileName: profile.name,
      profileSource,
      interestingForOperator,
      customVisible,
      visibility
    })
  };
}

export function runtimeSkillPromptLines(payload: unknown): string[] {
  if (!isRecord(payload) || !Array.isArray(payload.prompt_lines)) {
    return [];
  }
  return payload.prompt_lines.filter(
    (line): line is string => typeof line === "string" && line.trim().length > 0
  );
}

export function runtimeSkillSummary(payload: unknown): Record<string, unknown> {
  if (!isRecord(payload) || !isRecord(payload.summary)) {
    return {};
  }
  return { ...payload.summary };
}

export function runtimeSkillLogLine(payload: unknown): string | null {
  const summary = runtimeSkillSummary(payload);
  if (summary.interesting_for_operator !== true) {
    return null;
  }
  return (
    "runtime skills: " +
    `visible=${summaryCount(summary.visible_count)} ` +
    `custom=${summaryCount(summary.custom_visible_count)} ` +
    `hidden=${summaryCount(summary.hidden_count)} ` +
    `preloaded=${summaryCount(summary.preloaded_count)} ` +
    `missing_preloads=${summaryCount(summary.missing_preload_count)} ` +
    `shadowed=${summaryCount(summary.shadowed_count)}`
  );
}

function isCustomSkillScope(scope: SkillSourceScope): boolean {
  return scope === "project" || scope === "user";
}

function runtimeSkillResolutionPromptLines(options: {
  role: string;
  profileName: string;
  profileSource: string;
  interestingForOperator: boolean;
  customVisible: FilteredSkillEntry[];
  visibility: ProfileSkillVisibility;
}): string[] {
  if (!options.interestingForOperator) {
    return [];
  }
  const lines = [
    `Runtime skills for ${options.role} / ${options.profileName} (${options.profileSource} profile):`
  ];
  if (options.customVisible.length) {
    lines.push(
      "Visible project/user skills: " +
        options.customVisible.map((entry) => `${entry.name} [${entry.scope}]`).join(", ")
    );
  }
  if (options.visibility.preloaded.length) {
    lines.push(
      "Preloaded skills: " +
        options.visibility.preloaded.map((entry) => entry.name).join(", ")
    );
  }
  if (options.visibility.hidden.length) {
    lines.push(
      "Hidden by profile policy: " +
        options.visibility.hidden.map((entry) => entry.name).join(", ")
    );
  }
  if (options.visibility.missing_preloads.length) {
    lines.push(
      "Missing requested preloads: " +
        options.visibility.missing_preloads.map((item) => item.name).join(", ")
    );
  }
  if (options.visibility.shadowed.length) {
    lines.push(
      "Shadowed by precedence: " +
        options.visibility.shadowed
          .map((skill) => `${skill.name} [${skill.scope}]`)
          .join(", ")
    );
  }
  return lines;
}

function skillDiscoveryToPayload(discovery: SkillDiscovery): Record<string, unknown> {
  return {
    search_roots: discovery.search_roots.map((root) => ({ ...root })),
    candidates: discovery.candidates.map(skillCandidateToPayload),
    selected: discovery.selected.map(discoveredSkillToPayload),
    shadowed: discovery.shadowed.map(discoveredSkillToPayload),
    invalid: discovery.invalid.map((candidate) => ({
      ...skillCandidateToPayload(candidate.candidate),
      error: candidate.error
    }))
  };
}

function profileSkillVisibilityToPayload(
  visibility: ProfileSkillVisibility
): Record<string, unknown> {
  return {
    profile_name: visibility.profile_name,
    profile_source: visibility.profile_source,
    default_decision: visibility.default_decision,
    entries: visibility.entries.map(filteredSkillEntryToPayload),
    visible: visibility.visible.map(filteredSkillEntryToPayload),
    hidden: visibility.hidden.map(filteredSkillEntryToPayload),
    preloaded: visibility.preloaded.map(filteredSkillEntryToPayload),
    missing_preloads: visibility.missing_preloads.map((item) => ({ ...item })),
    shadowed: visibility.shadowed.map(discoveredSkillToPayload)
  };
}

function skillCandidateToPayload(candidate: SkillCandidate): Record<string, string> {
  return {
    scope: candidate.scope,
    root_dir: candidate.root_dir,
    path: candidate.path,
    relative_path: candidate.relative_path
  };
}

function discoveredSkillToPayload(skill: DiscoveredSkill): Record<string, unknown> {
  return {
    name: skill.name,
    scope: skill.scope,
    path: skill.path,
    relative_path: skill.relative_path,
    source_precedence: skill.source_precedence,
    description: skill.description
  };
}

function filteredSkillEntryToPayload(entry: FilteredSkillEntry): Record<string, unknown> {
  return {
    ...discoveredSkillToPayload(entry),
    visibility_decision: entry.visibility_decision,
    visible: entry.visible,
    requested_preload: entry.requested_preload,
    preloaded: entry.preloaded
  };
}

function runtimeMetadata(metadata: Record<string, unknown> | undefined): Record<string, unknown> {
  const candidate = metadata?.dormammu_runtime;
  return isRecord(candidate) ? { ...candidate } : {};
}

function summaryCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export async function loadSkillDefinition(
  path: string,
  options: { sourceScope: unknown }
): Promise<LoadedSkillDefinition> {
  const document = await loadSkillDocument(path);
  return loadedSkillDefinitionFromDocument(document, {
    sourceScope: options.sourceScope,
    sourcePath: path
  });
}

export function loadedSkillDefinitionFromDocument(
  document: SkillDocument,
  options: { sourceScope: unknown; sourcePath: string }
): LoadedSkillDefinition {
  const sourceScope = normalizeSkillSourceScope(options.sourceScope, {
    fieldName: "loaded_skill.source_scope",
    sourceName: options.sourcePath
  });
  return {
    name: document.name,
    description: document.description,
    schema_version: document.schema_version,
    source_scope: sourceScope,
    source_precedence: skillSourcePrecedence(sourceScope),
    source_path: resolve(options.sourcePath),
    content: document.content,
    metadata: { ...document.metadata }
  };
}

export function parseSkillDocumentText(
  rawText: string,
  options: { sourceName: string }
): SkillDocument {
  const [frontmatterText, body] = splitFrontmatter(rawText, options);
  const payload = parseFrontmatter(frontmatterText, options);
  return parseSkillDocumentPayload(payload, {
    sourceName: options.sourceName,
    body
  });
}

export function parseSkillDocumentPayload(
  payload: unknown,
  options: { sourceName: string; body: string }
): SkillDocument {
  const fieldPrefix = "skill_document";
  const document = coerceRecord(payload, {
    fieldName: fieldPrefix,
    sourceName: options.sourceName
  });
  const allowedKeys = new Set(["schema_version", "name", "description", "metadata"]);
  const unknownKeys = Object.keys(document).filter((key) => !allowedKeys.has(key)).sort();
  if (unknownKeys.length > 0) {
    throw new SkillDocumentError(
      `${fieldPrefix} contains unsupported keys (${unknownKeys.join(", ")}) in ${options.sourceName}`
    );
  }

  const schemaVersion = parseSchemaVersion(document.schema_version, {
    fieldName: `${fieldPrefix}.schema_version`,
    sourceName: options.sourceName
  });
  const name = requireNonEmptyString(document.name, {
    fieldName: `${fieldPrefix}.name`,
    sourceName: options.sourceName
  });
  const description = requireNonEmptyString(document.description, {
    fieldName: `${fieldPrefix}.description`,
    sourceName: options.sourceName
  });
  const metadata = parseMetadata(document.metadata, {
    fieldName: `${fieldPrefix}.metadata`,
    sourceName: options.sourceName
  });
  const contentText = requireNonEmptyString(options.body, {
    fieldName: `${fieldPrefix}.content`,
    sourceName: options.sourceName
  });

  return {
    schema_version: schemaVersion,
    name,
    description,
    content: {
      mode: SKILL_CONTENT_MODE_INLINE_MARKDOWN,
      text: contentText
    },
    metadata
  };
}

export function normalizeSkillSourceScope(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): SkillSourceScope {
  const normalized = requireNonEmptyString(value, options).toLowerCase();
  if (!isSkillSourceScope(normalized)) {
    throw new SkillDocumentError(
      `${options.fieldName} must be one of (${SKILL_SOURCE_SCOPES.join(", ")}) in ${options.sourceName}`
    );
  }
  return normalized;
}

export function skillSourcePrecedence(scope: unknown): number {
  const normalizedScope = normalizeSkillSourceScope(scope, {
    fieldName: "skill.source_scope",
    sourceName: "skill source precedence"
  });
  return SKILL_SOURCE_PRECEDENCE[normalizedScope];
}

function splitFrontmatter(
  rawText: string,
  options: { sourceName: string }
): [string, string] {
  const lines = rawText.split(/\r?\n/);
  if (lines.length === 0 || lines[0].trim() !== "---") {
    throw new SkillDocumentError(
      `Skill document must begin with frontmatter delimited by --- in ${options.sourceName}`
    );
  }
  for (let index = 1; index < lines.length; index += 1) {
    if (lines[index].trim() === "---") {
      return [lines.slice(1, index).join("\n"), lines.slice(index + 1).join("\n").trim()];
    }
  }
  throw new SkillDocumentError(
    `Skill document frontmatter must terminate with --- in ${options.sourceName}`
  );
}

async function findSkillDocuments(rootPath: string): Promise<string[]> {
  let entries;
  try {
    entries = await readdir(rootPath, { withFileTypes: true });
  } catch {
    return [];
  }
  const discovered: string[] = [];
  for (const entry of entries) {
    const entryPath = resolve(rootPath, entry.name);
    if (entry.isDirectory()) {
      discovered.push(...(await findSkillDocuments(entryPath)));
    } else if (entry.isFile() && entry.name === SKILL_DOCUMENT_FILENAME) {
      discovered.push(entryPath);
    }
  }
  return discovered.sort();
}

async function loadDiscoveredSkill(candidate: SkillCandidate): Promise<DiscoveredSkill> {
  const definition = await loadSkillDefinition(candidate.path, {
    sourceScope: candidate.scope
  });
  return {
    name: definition.name,
    scope: candidate.scope,
    path: candidate.path,
    relative_path: candidate.relative_path,
    source_precedence: definition.source_precedence,
    description: definition.description,
    definition,
    candidate
  };
}

function resolveSkillPrecedence(
  discoveredSkills: DiscoveredSkill[]
): [DiscoveredSkill[], DiscoveredSkill[]] {
  const byName = new Map<string, DiscoveredSkill[]>();
  for (const discovered of discoveredSkills) {
    const existing = byName.get(discovered.name) ?? [];
    existing.push(discovered);
    byName.set(discovered.name, existing);
  }

  const selected: DiscoveredSkill[] = [];
  const shadowed: DiscoveredSkill[] = [];
  for (const name of [...byName.keys()].sort()) {
    const contenders = [...(byName.get(name) ?? [])].sort((left, right) => {
      const precedenceDelta = left.source_precedence - right.source_precedence;
      return precedenceDelta === 0 ? left.path.localeCompare(right.path) : precedenceDelta;
    });
    validateUniqueScopePerSkillName(name, contenders);
    selected.push(contenders[0]);
    shadowed.push(...contenders.slice(1));
  }
  return [selected, shadowed];
}

function validateUniqueScopePerSkillName(name: string, contenders: DiscoveredSkill[]): void {
  const seenScopes = new Map<SkillSourceScope, string>();
  for (const contender of contenders) {
    const existingPath = seenScopes.get(contender.scope);
    if (existingPath !== undefined) {
      throw new SkillDiscoveryError(
        `Duplicate skill name '${name}' in ${contender.scope} scope: ${existingPath} and ${contender.path}`
      );
    }
    seenScopes.set(contender.scope, contender.path);
  }
}

function evaluateSkillPermission(
  skill: string,
  profile: AgentSkillProfile
): PermissionDecision {
  const normalizedSkill = skill.trim();
  const policy = profile.permission_policy?.skills;
  const rules = policy?.rules ?? [];
  for (let index = rules.length - 1; index >= 0; index -= 1) {
    const rule = rules[index];
    if (rule.skill === normalizedSkill) {
      return rule.decision;
    }
  }
  return policy?.default ?? "ask";
}

function normalizeRequestedPreloads(values: string[]): string[] {
  const normalized: string[] = [];
  for (const value of values) {
    const candidate = value.trim();
    if (candidate && !normalized.includes(candidate)) {
      normalized.push(candidate);
    }
  }
  return normalized;
}

function parseFrontmatter(
  frontmatterText: string,
  options: { sourceName: string }
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  const lines = frontmatterText.split(/\r?\n/);
  for (let offset = 0; offset < lines.length; offset += 1) {
    const rawLine = lines[offset];
    const lineNumber = offset + 2;
    if (!rawLine.trim()) {
      continue;
    }
    if (/^\s/.test(rawLine)) {
      throw new SkillDocumentError(
        `Skill document frontmatter does not support nested mappings in ${options.sourceName} at line ${lineNumber}`
      );
    }
    const separatorIndex = rawLine.indexOf(":");
    if (separatorIndex < 0) {
      throw new SkillDocumentError(
        `Invalid skill document frontmatter in ${options.sourceName} at line ${lineNumber}`
      );
    }
    const normalizedKey = rawLine.slice(0, separatorIndex).trim();
    if (!normalizedKey) {
      throw new SkillDocumentError(
        `Skill document frontmatter key must be non-empty in ${options.sourceName} at line ${lineNumber}`
      );
    }
    if (Object.prototype.hasOwnProperty.call(payload, normalizedKey)) {
      throw new SkillDocumentError(
        `Duplicate skill document frontmatter key '${normalizedKey}' in ${options.sourceName}`
      );
    }
    payload[normalizedKey] = parseFrontmatterValue(rawLine.slice(separatorIndex + 1).trim(), {
      fieldName: `skill_document.${normalizedKey}`,
      sourceName: options.sourceName
    });
  }
  return payload;
}

function parseFrontmatterValue(
  rawValue: string,
  options: { fieldName: string; sourceName: string }
): unknown {
  if (!rawValue) {
    return "";
  }
  if (rawValue.startsWith("'") && rawValue.endsWith("'") && rawValue.length >= 2) {
    return rawValue.slice(1, -1);
  }
  if (rawValue.startsWith('"') && rawValue.endsWith('"') && rawValue.length >= 2) {
    try {
      return JSON.parse(rawValue);
    } catch (error) {
      throw new SkillDocumentError(
        `${options.fieldName} contains invalid quoted JSON string in ${options.sourceName}: ${jsonErrorMessage(error)}`
      );
    }
  }
  if (rawValue.startsWith("{") || rawValue.startsWith("[")) {
    try {
      return JSON.parse(rawValue);
    } catch (error) {
      throw new SkillDocumentError(
        `${options.fieldName} contains invalid JSON literal in ${options.sourceName}: ${jsonErrorMessage(error)}`
      );
    }
  }
  if (["true", "false", "null"].includes(rawValue) || /^-?\d+$/.test(rawValue)) {
    try {
      return JSON.parse(rawValue);
    } catch {
      // Fall through to treating the value as a string, matching Python.
    }
  }
  return rawValue;
}

function parseSchemaVersion(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): number {
  if (value === undefined || value === null) {
    return SKILL_DOCUMENT_SCHEMA_VERSION;
  }
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new SkillDocumentError(
      `${options.fieldName} must be the integer ${SKILL_DOCUMENT_SCHEMA_VERSION} in ${options.sourceName}`
    );
  }
  if (value !== SKILL_DOCUMENT_SCHEMA_VERSION) {
    throw new SkillDocumentError(
      `${options.fieldName} must be ${SKILL_DOCUMENT_SCHEMA_VERSION} in ${options.sourceName}`
    );
  }
  return value;
}

function parseMetadata(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): Record<string, unknown> {
  if (value === undefined || value === null) {
    return {};
  }
  return { ...coerceRecord(value, options) };
}

function coerceRecord(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new SkillDocumentError(`${options.fieldName} must be a JSON object in ${options.sourceName}`);
  }
  return value;
}

function requireNonEmptyString(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new SkillDocumentError(
      `${options.fieldName} must be a non-empty string in ${options.sourceName}`
    );
  }
  return value.trim();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSkillSourceScope(value: string): value is SkillSourceScope {
  return (SKILL_SOURCE_SCOPES as readonly string[]).includes(value);
}

function jsonErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
