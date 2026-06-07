import { readdir, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  defaultAgentPermissionPolicy,
  mergePermissionPolicy,
  parsePermissionPolicyOverride,
  type AgentPermissionPolicy
} from "./permissions.js";
import {
  BUILTIN_PROFILE_SOURCE,
  PROJECT_PROFILE_SOURCE,
  USER_PROFILE_SOURCE,
  type AgentProfile
} from "./profiles.js";

export const AGENT_MANIFEST_SCHEMA_VERSION = 1;
export const AGENT_MANIFEST_SOURCES = [
  BUILTIN_PROFILE_SOURCE,
  PROJECT_PROFILE_SOURCE,
  USER_PROFILE_SOURCE
] as const;
export const AGENT_MANIFEST_DISCOVERY_SCOPES = [
  PROJECT_PROFILE_SOURCE,
  USER_PROFILE_SOURCE
] as const;
export const AGENT_MANIFEST_FILENAME_SUFFIX = ".agent.json";
export const AGENT_MANIFEST_SCOPE_PRECEDENCE: Record<AgentManifestDiscoveryScope, number> = {
  [PROJECT_PROFILE_SOURCE]: 0,
  [USER_PROFILE_SOURCE]: 1
};

export type AgentManifestSource = (typeof AGENT_MANIFEST_SOURCES)[number];
export type AgentManifestDiscoveryScope = (typeof AGENT_MANIFEST_DISCOVERY_SCOPES)[number];

export class AgentManifestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AgentManifestError";
  }
}

export class AgentManifestLoadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AgentManifestLoadError";
  }
}

export type AgentManifest = {
  schema_version: number;
  name: string;
  description: string;
  prompt: string;
  source: AgentManifestSource;
  cli_override: string | null;
  model_override: string | null;
  permission_policy: AgentPermissionPolicy;
  preloaded_skills: string[];
  metadata: Record<string, unknown>;
};

export type AgentManifestSearchRoot = {
  scope: AgentManifestDiscoveryScope;
  path: string;
};

export type AgentManifestCandidate = {
  scope: AgentManifestDiscoveryScope;
  root_dir: string;
  path: string;
  relative_path: string;
};

export type DiscoveredAgentManifest = {
  name: string;
  scope: AgentManifestDiscoveryScope;
  path: string;
  relative_path: string;
  manifest_source: AgentManifestSource;
  manifest: AgentManifest;
  candidate: AgentManifestCandidate;
};

export type AgentManifestDiscovery = {
  search_roots: AgentManifestSearchRoot[];
  candidates: AgentManifestCandidate[];
  selected: DiscoveredAgentManifest[];
  shadowed: DiscoveredAgentManifest[];
};

export type LoadedAgentDefinition = {
  name: string;
  description: string;
  prompt_body: string;
  source: AgentManifestSource;
  manifest_scope: AgentManifestDiscoveryScope;
  manifest_path: string;
  cli_override: string | null;
  model_override: string | null;
  permission_policy: AgentPermissionPolicy;
  preloaded_skills: string[];
  metadata: Record<string, unknown>;
};

export type AgentManifestLoadResult = {
  discovery: AgentManifestDiscovery;
  definitions: LoadedAgentDefinition[];
};

export async function loadAgentManifest(manifestPath: string): Promise<AgentManifest> {
  const normalizedPath = path.resolve(manifestPath);
  let rawText: string;
  try {
    rawText = await readFile(normalizedPath, "utf8");
  } catch {
    throw new AgentManifestError(`Failed to read agent manifest ${normalizedPath}`);
  }
  return parseAgentManifestText(rawText, {
    sourceName: normalizedPath,
    configRoot: path.dirname(normalizedPath)
  });
}

export function parseAgentManifestText(
  rawText: string,
  options: { sourceName: string; configRoot?: string | null }
): AgentManifest {
  let payload: unknown;
  try {
    payload = JSON.parse(rawText);
  } catch (error) {
    const location = jsonParseLocation(rawText, error);
    throw new AgentManifestError(
      `Failed to parse agent manifest JSON in ${options.sourceName}: ${syntaxMessage(error)} at line ${location.line} column ${location.column}`
    );
  }
  return parseAgentManifestPayload(payload, options);
}

export function parseAgentManifestPayload(
  payload: unknown,
  options: { sourceName: string; configRoot?: string | null }
): AgentManifest {
  const fieldPrefix = "agent_manifest";
  const manifest = coerceRecord(payload, fieldPrefix, options.sourceName);
  rejectUnknownKeys(
    manifest,
    ["schema_version", "name", "description", "prompt", "source", "cli", "model", "permissions", "skills", "metadata"],
    { fieldName: fieldPrefix, sourceName: options.sourceName }
  );
  const schemaVersion = parseSchemaVersion(manifest.schema_version, {
    fieldName: `${fieldPrefix}.schema_version`,
    sourceName: options.sourceName
  });
  const name = requireNonEmptyString(manifest.name, {
    fieldName: `${fieldPrefix}.name`,
    sourceName: options.sourceName
  });
  const description = requireNonEmptyString(manifest.description, {
    fieldName: `${fieldPrefix}.description`,
    sourceName: options.sourceName
  });
  const prompt = requireNonEmptyString(manifest.prompt, {
    fieldName: `${fieldPrefix}.prompt`,
    sourceName: options.sourceName
  });
  const source = parseManifestSource(manifest.source, {
    fieldName: `${fieldPrefix}.source`,
    sourceName: options.sourceName
  });
  const cliOverride = parseCliOverride(manifest.cli, {
    fieldName: `${fieldPrefix}.cli`,
    sourceName: options.sourceName,
    configRoot: options.configRoot ?? null
  });
  const modelOverride = optionalNonEmptyString(manifest.model, {
    fieldName: `${fieldPrefix}.model`,
    sourceName: options.sourceName
  });
  const preloadedSkills = parseSkillList(manifest.skills, {
    fieldName: `${fieldPrefix}.skills`,
    sourceName: options.sourceName
  });
  const metadata = parseMetadata(manifest.metadata, {
    fieldName: `${fieldPrefix}.metadata`,
    sourceName: options.sourceName
  });

  const permissionOverride =
    manifest.permissions === undefined || manifest.permissions === null
      ? null
      : parsePermissionPolicyOverride(manifest.permissions, {
          configRoot: options.configRoot ?? null,
          fieldName: `${fieldPrefix}.permissions`,
          source: options.sourceName
        });
  return {
    schema_version: schemaVersion,
    name,
    description,
    prompt,
    source,
    cli_override: cliOverride,
    model_override: modelOverride,
    permission_policy: mergePermissionPolicy(defaultAgentPermissionPolicy(), permissionOverride),
    preloaded_skills: preloadedSkills,
    metadata
  };
}

export function agentManifestToProfile(manifest: AgentManifest): AgentProfile {
  return {
    name: manifest.name,
    description: manifest.description,
    source: manifest.source,
    prompt_body: manifest.prompt,
    cli_override: manifest.cli_override,
    model_override: manifest.model_override,
    permission_policy: manifest.permission_policy,
    preloaded_skills: [...manifest.preloaded_skills],
    metadata: { ...manifest.metadata }
  };
}

export async function enumerateAgentManifestCandidates(
  searchRoots: AgentManifestSearchRoot[]
): Promise<AgentManifestCandidate[]> {
  const candidates: AgentManifestCandidate[] = [];
  for (const root of normalizedSearchRoots(searchRoots)) {
    for (const candidatePath of await findAgentManifestFiles(root.path)) {
      candidates.push({
        scope: root.scope,
        root_dir: root.path,
        path: candidatePath,
        relative_path: path.relative(root.path, candidatePath).split("\\").join("/")
      });
    }
  }
  return candidates;
}

export async function discoverAgentManifests(
  searchRoots: AgentManifestSearchRoot[]
): Promise<AgentManifestDiscovery> {
  const roots = normalizedSearchRoots(searchRoots);
  const candidates = await enumerateAgentManifestCandidates(roots);
  const loaded: DiscoveredAgentManifest[] = [];
  for (const candidate of candidates) {
    loaded.push(await loadDiscoveredAgentManifest(candidate));
  }
  const [selected, shadowed] = resolveManifestPrecedence(loaded);
  return { search_roots: roots, candidates, selected, shadowed };
}

export async function discoverSelectedAgentManifests(
  searchRoots: AgentManifestSearchRoot[],
  options: { names: readonly string[] }
): Promise<AgentManifestDiscovery> {
  const roots = normalizedSearchRoots(searchRoots);
  const candidates = await enumerateAgentManifestCandidates(roots);
  const requestedNames = new Set(
    options.names
      .filter((name): name is string => typeof name === "string")
      .map((name) => name.trim())
      .filter(Boolean)
  );
  if (requestedNames.size === 0) {
    return { search_roots: roots, candidates, selected: [], shadowed: [] };
  }
  const loaded: DiscoveredAgentManifest[] = [];
  for (const candidate of candidates) {
    const discovered = await loadRequestedAgentManifest(candidate, requestedNames);
    if (discovered !== null) {
      loaded.push(discovered);
    }
  }
  const [selected, shadowed] = resolveManifestPrecedence(loaded);
  return { search_roots: roots, candidates, selected, shadowed };
}

export async function loadAgentManifestDefinitions(
  searchRoots: AgentManifestSearchRoot[],
  options: { names?: readonly string[] | null } = {}
): Promise<AgentManifestLoadResult> {
  try {
    const discovery =
      options.names !== undefined && options.names !== null
        ? await discoverSelectedAgentManifests(searchRoots, { names: options.names })
        : await discoverAgentManifests(searchRoots);
    const definitions = discovery.selected.map(loadedAgentDefinitionFromManifest);
    validateUniqueDefinitionNames(definitions);
    return { discovery, definitions };
  } catch (error) {
    if (error instanceof AgentManifestError) {
      throw new AgentManifestLoadError(error.message);
    }
    throw error;
  }
}

export function loadedAgentDefinitionToProfile(definition: LoadedAgentDefinition): AgentProfile {
  return {
    name: definition.name,
    description: definition.description,
    source: definition.source,
    prompt_body: definition.prompt_body,
    cli_override: definition.cli_override,
    model_override: definition.model_override,
    permission_policy: definition.permission_policy,
    preloaded_skills: [...definition.preloaded_skills],
    metadata: { ...definition.metadata }
  };
}

export function selectedAgentManifestsByName(
  discovery: AgentManifestDiscovery
): Record<string, DiscoveredAgentManifest> {
  return Object.fromEntries(discovery.selected.map((manifest) => [manifest.name, manifest]));
}

function loadedAgentDefinitionFromManifest(
  discovered: DiscoveredAgentManifest
): LoadedAgentDefinition {
  return {
    name: discovered.manifest.name,
    description: discovered.manifest.description,
    prompt_body: discovered.manifest.prompt,
    source: discovered.manifest.source,
    manifest_scope: discovered.scope,
    manifest_path: discovered.path,
    cli_override: discovered.manifest.cli_override,
    model_override: discovered.manifest.model_override,
    permission_policy: discovered.manifest.permission_policy,
    preloaded_skills: [...discovered.manifest.preloaded_skills],
    metadata: { ...discovered.manifest.metadata }
  };
}

async function loadDiscoveredAgentManifest(
  candidate: AgentManifestCandidate
): Promise<DiscoveredAgentManifest> {
  const manifest = await loadAgentManifest(candidate.path);
  const discovered = discoveredManifest(manifest, candidate);
  validateManifestScope(discovered);
  return discovered;
}

async function loadRequestedAgentManifest(
  candidate: AgentManifestCandidate,
  requestedNames: Set<string>
): Promise<DiscoveredAgentManifest | null> {
  let rawText: string;
  try {
    rawText = await readFile(candidate.path, "utf8");
  } catch {
    throw new AgentManifestError(`Failed to read agent manifest ${candidate.path}`);
  }
  const manifestName = peekManifestName(rawText);
  if (manifestName === null || !requestedNames.has(manifestName)) {
    return null;
  }
  const manifest = parseAgentManifestText(rawText, {
    sourceName: candidate.path,
    configRoot: path.dirname(candidate.path)
  });
  const discovered = discoveredManifest(manifest, candidate);
  validateManifestScope(discovered);
  return discovered;
}

function discoveredManifest(
  manifest: AgentManifest,
  candidate: AgentManifestCandidate
): DiscoveredAgentManifest {
  return {
    name: manifest.name,
    scope: candidate.scope,
    path: candidate.path,
    relative_path: candidate.relative_path,
    manifest_source: manifest.source,
    manifest,
    candidate
  };
}

function validateManifestScope(discovered: DiscoveredAgentManifest): void {
  if (discovered.manifest.source === discovered.scope) {
    return;
  }
  throw new AgentManifestError(
    `Agent manifest source/scope mismatch for ${discovered.path}: declared source '${discovered.manifest.source}' does not match discovered scope '${discovered.scope}'.`
  );
}

function resolveManifestPrecedence(
  manifests: DiscoveredAgentManifest[]
): [DiscoveredAgentManifest[], DiscoveredAgentManifest[]] {
  const selected = new Map<string, DiscoveredAgentManifest>();
  const shadowed: DiscoveredAgentManifest[] = [];
  for (const discovered of [...manifests].sort(discoveredManifestSortCompare)) {
    const current = selected.get(discovered.name);
    if (current === undefined) {
      selected.set(discovered.name, discovered);
      continue;
    }
    if (current.scope === discovered.scope) {
      throw new AgentManifestError(
        `Duplicate agent manifest name '${discovered.name}' in ${discovered.scope} scope: ${current.path} and ${discovered.path}. Use unique manifest names within the same scope.`
      );
    }
    const [winner, loser] = pickManifestWinner(current, discovered);
    selected.set(discovered.name, winner);
    shadowed.push(loser);
  }
  return [
    [...selected.keys()].sort().map((name) => selected.get(name)).filter(isPresent),
    shadowed.sort(discoveredManifestSortCompare)
  ];
}

function pickManifestWinner(
  left: DiscoveredAgentManifest,
  right: DiscoveredAgentManifest
): [DiscoveredAgentManifest, DiscoveredAgentManifest] {
  if (scopePrecedenceRank(left.scope) <= scopePrecedenceRank(right.scope)) {
    return [left, right];
  }
  return [right, left];
}

function discoveredManifestSortCompare(
  left: DiscoveredAgentManifest,
  right: DiscoveredAgentManifest
): number {
  const precedenceDelta = scopePrecedenceRank(left.scope) - scopePrecedenceRank(right.scope);
  if (precedenceDelta !== 0) {
    return precedenceDelta;
  }
  const nameDelta = left.name.localeCompare(right.name);
  return nameDelta === 0 ? left.path.localeCompare(right.path) : nameDelta;
}

function scopePrecedenceRank(scope: AgentManifestDiscoveryScope): number {
  return AGENT_MANIFEST_SCOPE_PRECEDENCE[scope];
}

function normalizedSearchRoots(
  searchRoots: AgentManifestSearchRoot[]
): AgentManifestSearchRoot[] {
  return searchRoots.map((root) => ({
    scope: parseDiscoveryScope(root.scope, {
      fieldName: "agent_manifest_search_root.scope",
      sourceName: root.path
    }),
    path: path.resolve(root.path)
  }));
}

async function findAgentManifestFiles(rootPath: string): Promise<string[]> {
  let entries;
  try {
    entries = await readdir(rootPath, { withFileTypes: true });
  } catch {
    return [];
  }
  const discovered: string[] = [];
  for (const entry of entries) {
    const entryPath = path.resolve(rootPath, entry.name);
    if (entry.isDirectory()) {
      discovered.push(...(await findAgentManifestFiles(entryPath)));
    } else if (entry.isFile() && entry.name.endsWith(AGENT_MANIFEST_FILENAME_SUFFIX)) {
      discovered.push(entryPath);
    }
  }
  return discovered.sort();
}

function validateUniqueDefinitionNames(definitions: LoadedAgentDefinition[]): void {
  const seen = new Map<string, string>();
  for (const definition of definitions) {
    const existingPath = seen.get(definition.name);
    if (existingPath !== undefined) {
      throw new AgentManifestError(
        `Duplicate loaded agent definition '${definition.name}': ${existingPath} and ${definition.manifest_path}. Loaded manifest definitions must have unique names.`
      );
    }
    seen.set(definition.name, definition.manifest_path);
  }
}

function parseSchemaVersion(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): number {
  if (!Number.isInteger(value) || value !== AGENT_MANIFEST_SCHEMA_VERSION) {
    throw new AgentManifestError(
      `${options.fieldName} must be ${AGENT_MANIFEST_SCHEMA_VERSION} in ${options.sourceName}`
    );
  }
  return value;
}

function parseManifestSource(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): AgentManifestSource {
  const normalized = requireNonEmptyString(value, options).toLowerCase();
  if (!isManifestSource(normalized)) {
    throw new AgentManifestError(
      `${options.fieldName} must be one of (${AGENT_MANIFEST_SOURCES.join(", ")}) in ${options.sourceName}`
    );
  }
  return normalized;
}

function parseDiscoveryScope(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): AgentManifestDiscoveryScope {
  const normalized = requireNonEmptyString(value, options).toLowerCase();
  if (!isDiscoveryScope(normalized)) {
    throw new AgentManifestError(
      `${options.fieldName} must be one of (${AGENT_MANIFEST_DISCOVERY_SCOPES.join(", ")}) in ${options.sourceName}`
    );
  }
  return normalized;
}

function parseCliOverride(
  value: unknown,
  options: { fieldName: string; sourceName: string; configRoot: string | null }
): string | null {
  const raw = optionalNonEmptyString(value, options);
  if (raw === null) {
    return null;
  }
  const candidate = expandUserPath(raw);
  if (path.isAbsolute(candidate)) {
    return candidate;
  }
  if (options.configRoot !== null && (raw.includes("/") || raw.startsWith("."))) {
    return path.resolve(options.configRoot, candidate);
  }
  return candidate;
}

function parseSkillList(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): string[] {
  if (value === undefined || value === null) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new AgentManifestError(`${options.fieldName} must be a JSON array in ${options.sourceName}`);
  }
  const normalized: string[] = [];
  value.forEach((item, index) => {
    const skill = requireNonEmptyString(item, {
      fieldName: `${options.fieldName}[${index}]`,
      sourceName: options.sourceName
    });
    if (!normalized.includes(skill)) {
      normalized.push(skill);
    }
  });
  return normalized;
}

function parseMetadata(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): Record<string, unknown> {
  if (value === undefined || value === null) {
    return {};
  }
  return { ...coerceRecord(value, options.fieldName, options.sourceName) };
}

function peekManifestName(rawText: string): string | null {
  let index = skipWhitespace(rawText, 0);
  if (index >= rawText.length || rawText[index] !== "{") {
    return null;
  }
  let depth = 0;
  while (index < rawText.length) {
    const char = rawText[index];
    if (char === "{") {
      depth += 1;
      index += 1;
      continue;
    }
    if (char === "}") {
      depth -= 1;
      if (depth <= 0) {
        return null;
      }
      index += 1;
      continue;
    }
    if (char === "[") {
      depth += 1;
      index += 1;
      continue;
    }
    if (char === "]") {
      depth = Math.max(depth - 1, 0);
      index += 1;
      continue;
    }
    if (depth !== 1) {
      if (char === "\"") {
        const [, nextIndex] = parseQuotedString(rawText, index);
        index = nextIndex;
        continue;
      }
      index += 1;
      continue;
    }
    if (" \t\r\n,:".includes(char)) {
      index += 1;
      continue;
    }

    let key: string | null = null;
    let nextIndex = index;
    if (char === "\"") {
      [key, nextIndex] = parseQuotedString(rawText, index);
    } else if (isIdentifierStart(char)) {
      [key, nextIndex] = parseIdentifier(rawText, index);
    } else {
      index += 1;
      continue;
    }
    if (key === null) {
      return null;
    }
    const colonIndex = skipWhitespace(rawText, nextIndex);
    if (colonIndex >= rawText.length || rawText[colonIndex] !== ":") {
      index = nextIndex;
      continue;
    }
    if (key !== "name") {
      index = colonIndex + 1;
      continue;
    }
    const valueIndex = skipWhitespace(rawText, colonIndex + 1);
    if (valueIndex >= rawText.length) {
      return null;
    }
    const [value] =
      rawText[valueIndex] === "\""
        ? parseQuotedString(rawText, valueIndex)
        : parseIdentifier(rawText, valueIndex);
    return typeof value === "string" && value.trim() ? value.trim() : null;
  }
  return null;
}

function parseQuotedString(rawText: string, index: number): [string | null, number] {
  index += 1;
  const chars: string[] = [];
  let escaping = false;
  while (index < rawText.length) {
    const char = rawText[index];
    if (escaping) {
      chars.push(char);
      escaping = false;
      index += 1;
      continue;
    }
    if (char === "\\") {
      escaping = true;
      index += 1;
      continue;
    }
    if (char === "\"") {
      return [chars.join(""), index + 1];
    }
    chars.push(char);
    index += 1;
  }
  return [null, index];
}

function parseIdentifier(rawText: string, index: number): [string | null, number] {
  if (!isIdentifierStart(rawText[index])) {
    return [null, index];
  }
  const start = index;
  index += 1;
  while (index < rawText.length && /[A-Za-z0-9_-]/.test(rawText[index])) {
    index += 1;
  }
  return [rawText.slice(start, index), index];
}

function skipWhitespace(rawText: string, index: number): number {
  while (index < rawText.length && " \t\r\n".includes(rawText[index])) {
    index += 1;
  }
  return index;
}

function jsonParseLocation(
  rawText: string,
  error: unknown
): { line: number; column: number } {
  const match = syntaxMessage(error).match(/position\s+(\d+)/i);
  const offset = match ? Number.parseInt(match[1], 10) : 0;
  const prefix = rawText.slice(0, Number.isFinite(offset) ? offset : 0);
  const lines = prefix.split(/\n/);
  return { line: lines.length, column: lines[lines.length - 1].length + 1 };
}

function syntaxMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function coerceRecord(
  value: unknown,
  fieldName: string,
  sourceName: string
): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentManifestError(`${fieldName} must be a JSON object in ${sourceName}`);
  }
  return value as Record<string, unknown>;
}

function rejectUnknownKeys(
  payload: Record<string, unknown>,
  allowedKeys: string[],
  options: { fieldName: string; sourceName: string }
): void {
  const allowed = new Set(allowedKeys);
  const unknown = Object.keys(payload).filter((key) => !allowed.has(key)).sort();
  if (unknown.length) {
    throw new AgentManifestError(
      `${options.fieldName} contains unsupported keys (${unknown.join(", ")}) in ${options.sourceName}`
    );
  }
}

function requireNonEmptyString(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new AgentManifestError(
      `${options.fieldName} must be a non-empty string in ${options.sourceName}`
    );
  }
  return value.trim();
}

function optionalNonEmptyString(
  value: unknown,
  options: { fieldName: string; sourceName: string }
): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  return requireNonEmptyString(value, options);
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

function isManifestSource(value: string): value is AgentManifestSource {
  return (AGENT_MANIFEST_SOURCES as readonly string[]).includes(value);
}

function isDiscoveryScope(value: string): value is AgentManifestDiscoveryScope {
  return (AGENT_MANIFEST_DISCOVERY_SCOPES as readonly string[]).includes(value);
}

function isIdentifierStart(value: string | undefined): boolean {
  return value !== undefined && /[A-Za-z_]/.test(value);
}

function isPresent<T>(value: T | undefined): value is T {
  return value !== undefined;
}
