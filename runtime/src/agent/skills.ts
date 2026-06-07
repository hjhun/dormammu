import { basename, resolve } from "node:path";
import { readdir, readFile } from "node:fs/promises";
import { relative } from "node:path";

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
