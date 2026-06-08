export type BuildGoalsPromptInput = {
  goalText: string;
  analysisText?: string | null;
  planText?: string | null;
  designText?: string | null;
};

export function analyzerPrompt(goalText: string): string {
  return [
    "You are an analyzer agent. Analyse the goal below and produce a requirements-focused brief that a planner can immediately use.",
    "",
    "Include:",
    "1. Goal restatement",
    "2. In-scope and out-of-scope boundaries",
    "3. Concrete acceptance criteria",
    "4. Constraints and dependencies",
    "5. Risks, ambiguities, and open questions",
    "",
    "# Goal",
    "",
    goalText.trim(),
    "",
    "Output your analysis in Markdown. Write all content in English regardless of the language of the goal above."
  ].join("\n");
}

export function plannerPrompt(goalText: string, analysisText?: string | null): string {
  const sections = [
    "You are a planning agent. Use the goal and requirements analysis below to produce the authoritative execution plan for this task.",
    "",
    "Include:",
    "1. Phase breakdown with clear completion signals",
    "2. An explicit refine -> plan entry requirement for execution",
    "3. A statement that the planner decides the downstream stages after plan via .dev/WORKFLOWS.md",
    "4. Acceptance criteria and validation strategy",
    "5. Risks, blockers, and escalation points",
    "",
    "# Goal",
    "",
    goalText.trim(),
    ""
  ];
  if (analysisText) {
    sections.push("# Requirements Analysis", "", analysisText.trim(), "");
  }
  sections.push(
    "Output your plan in Markdown. Write all content in English regardless of the language of the goal above."
  );
  return sections.join("\n");
}

export function designerPrompt(
  goalText: string,
  analysisText: string | null | undefined,
  planText: string
): string {
  const sections = [
    "You are a designing agent. Based on the plan below, create a technical OOAD design.",
    "",
    "Include:",
    "1. Module/class design with responsibilities",
    "2. Interface contracts and data schemas",
    "3. State management and error handling",
    "4. Test strategy (unit, integration, system)",
    "",
    "# Original Goal",
    "",
    goalText.trim(),
    ""
  ];
  if (analysisText) {
    sections.push("# Requirements Analysis", "", analysisText.trim(), "");
  }
  sections.push(
    "# Plan",
    "",
    planText.trim(),
    "",
    "Output your design in Markdown. Write all content in English regardless of the language of the goal above."
  );
  return sections.join("\n");
}

export function buildGoalsPrompt(input: BuildGoalsPromptInput): string {
  const languageNotice = [
    "> **Language requirement:** All responses, code comments, documentation, and deliverables must be written in English."
  ].join("\n");
  const workflowContract = [
    "## Workflow Contract",
    "",
    "- Start every execution with the mandatory `refine -> plan` stages.",
    "- `refine` must produce or update `.dev/REQUIREMENTS.md`.",
    "- `plan` must produce or update `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and `.dev/DASHBOARD.md`.",
    "- After `plan`, continue with `design -> ...` according to `.dev/WORKFLOWS.md`.",
    "- Treat the planner as authoritative for the downstream stage sequence after `plan`."
  ].join("\n");
  const sections = [
    languageNotice,
    workflowContract,
    `# Goal\n\n${input.goalText.trim()}`
  ];
  if (input.analysisText) {
    sections.push(`## Requirements Analysis\n\n${input.analysisText.trim()}`);
  }
  if (input.planText) {
    sections.push(`## Plan\n\n${input.planText.trim()}`);
  }
  if (input.designText) {
    sections.push(`## Design\n\n${input.designText.trim()}`);
  }
  return sections.join("\n\n");
}

export function goalSourceTag(goalFilePath: string): string {
  return `<!-- dormammu:goal_source=${goalFilePath} -->\n\n`;
}

export function queuedGoalPromptFilename(dateText: string, stem: string): string {
  return `${dateText}_${stem}.md`;
}
