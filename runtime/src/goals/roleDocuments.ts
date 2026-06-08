import path from "node:path";

export type GoalsRoleDocumentProjectionInput = {
  logsDir: string;
  dateText: string;
  role: string;
  stem: string;
  output: string;
};

export type GoalsRoleDocumentProjection = {
  filename: string;
  path: string;
  content: string;
};

export function goalsRoleDocumentFilename(
  dateText: string,
  role: string,
  stem: string
): string {
  return `${dateText}_${role}_${stem}.md`;
}

export function goalsRoleDocumentContent(
  role: string,
  stem: string,
  output: string
): string {
  return `# ${pythonCapitalize(role)} \u2014 ${stem}\n\n${output}`;
}

export function projectGoalsRoleDocument(
  input: GoalsRoleDocumentProjectionInput
): GoalsRoleDocumentProjection {
  const filename = goalsRoleDocumentFilename(
    input.dateText,
    input.role,
    input.stem
  );
  return {
    filename,
    path: path.join(input.logsDir, filename),
    content: goalsRoleDocumentContent(input.role, input.stem, input.output)
  };
}

function pythonCapitalize(value: string): string {
  if (value.length === 0) {
    return value;
  }
  return `${value.charAt(0).toUpperCase()}${value.slice(1).toLowerCase()}`;
}
