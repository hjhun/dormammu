import path from "node:path";

export function prependCliIdentity(promptText: string, cliPath: string): string {
  const cliName = path.basename(cliPath) || cliPath.trim() || "agent";
  const header = `[${cliName}]`;
  if (promptText === header || promptText.startsWith(`${header}\n`)) {
    return promptText;
  }
  return `${header}\n${promptText}`;
}
