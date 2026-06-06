import { readFile, writeFile } from "node:fs/promises";

export type JsonObject = Record<string, unknown>;

function isPlainObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function deepMerge(defaults: JsonObject, current: JsonObject): JsonObject {
  const merged: JsonObject = { ...defaults };
  for (const [key, value] of Object.entries(current)) {
    const defaultValue = merged[key];
    if (isPlainObject(defaultValue) && isPlainObject(value)) {
      merged[key] = deepMerge(defaultValue, value);
    } else {
      merged[key] = value;
    }
  }
  return merged;
}

export async function readJson(path: string): Promise<JsonObject> {
  const raw = await readFile(path, "utf8");
  const payload = JSON.parse(raw) as unknown;
  if (!isPlainObject(payload)) {
    throw new Error(`JSON file must contain an object: ${path}`);
  }
  return payload;
}

export async function writeJson(path: string, payload: JsonObject): Promise<void> {
  await writeFile(path, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

export async function ensureJsonFile(
  path: string,
  defaults: JsonObject
): Promise<void> {
  let merged = defaults;
  try {
    const current = await readJson(path);
    merged = deepMerge(defaults, current);
  } catch (error) {
    if (
      !(error instanceof Error) ||
      !("code" in error) ||
      (error as NodeJS.ErrnoException).code !== "ENOENT"
    ) {
      throw error;
    }
  }
  await writeJson(path, merged);
}
