import {
  analyzerPrompt,
  designerPrompt,
  plannerPrompt
} from "./prompts.js";

export type GoalsPreludeRole = "analyzer" | "planner" | "designer";

export type GoalsRoleAvailability = {
  cli?: string | null;
  model?: string | null;
};

export type GoalsRoleSequenceInput = {
  goalText: string;
  analysisText?: string | null;
  planText?: string | null;
  designText?: string | null;
  roles?: Partial<Record<GoalsPreludeRole, GoalsRoleAvailability>> | null;
};

export type GoalsRoleStep = {
  role: GoalsPreludeRole;
  cli: string;
  model: string | null;
  prompt: string;
};

export function nextGoalsRoleStep(
  input: GoalsRoleSequenceInput
): GoalsRoleStep | null {
  const analyzer = availableRole(input.roles?.analyzer);
  if (analyzer !== null && !input.analysisText) {
    return {
      role: "analyzer",
      cli: analyzer.cli,
      model: analyzer.model,
      prompt: analyzerPrompt(input.goalText)
    };
  }

  const planner = availableRole(input.roles?.planner);
  if (planner !== null && !input.planText) {
    return {
      role: "planner",
      cli: planner.cli,
      model: planner.model,
      prompt: plannerPrompt(input.goalText, input.analysisText ?? null)
    };
  }

  const designer = availableRole(input.roles?.designer);
  if (designer !== null && input.planText && !input.designText) {
    return {
      role: "designer",
      cli: designer.cli,
      model: designer.model,
      prompt: designerPrompt(
        input.goalText,
        input.analysisText ?? null,
        input.planText
      )
    };
  }

  return null;
}

function availableRole(
  role: GoalsRoleAvailability | null | undefined
): { cli: string; model: string | null } | null {
  if (role === null || role === undefined) {
    return null;
  }
  if (typeof role.cli !== "string" || !role.cli.trim()) {
    return null;
  }
  return {
    cli: role.cli,
    model: typeof role.model === "string" && role.model.trim() ? role.model : null
  };
}
