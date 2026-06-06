const SECTION_HEADER_RE = /^##\s+(?<title>.+?)\s*$/;
const TASK_LINE_RE = /^- \[(?<marker>[ OXx])\] (?<text>.+?)\s*$/;

const QUEUE_SECTIONS = new Set([
  "current workflow",
  "prompt-derived development queue",
  "prompt-derived implementation plan"
]);

export type TaskSyncItem = {
  text: string;
  completed: boolean;
};

export type OperatorTaskSyncState = {
  source: string;
  resumeCheckpoint: string | null;
  items: readonly TaskSyncItem[];
};

export type OperatorTaskSyncPayload = {
  source: string;
  resume_checkpoint: string | null;
  total_tasks: number;
  completed_tasks: number;
  pending_tasks: number;
  all_completed: boolean;
  next_pending_task: string | null;
  items: TaskSyncItem[];
  synced_at: string;
};

export type ParsedTasksDocument = {
  currentWorkflow: OperatorTaskSyncState;
};

export function operatorTaskSyncToDict(
  state: OperatorTaskSyncState,
  options: { syncedAt: string }
): OperatorTaskSyncPayload {
  const totalTasks = state.items.length;
  const completedTasks = state.items.filter((item) => item.completed).length;
  const pendingTasks = totalTasks - completedTasks;
  const nextPendingTask = state.items.find((item) => !item.completed)?.text ?? null;
  return {
    source: state.source,
    resume_checkpoint: state.resumeCheckpoint,
    total_tasks: totalTasks,
    completed_tasks: completedTasks,
    pending_tasks: pendingTasks,
    all_completed: totalTasks > 0 && pendingTasks === 0,
    next_pending_task: nextPendingTask,
    items: state.items.map((item) => ({ text: item.text, completed: item.completed })),
    synced_at: options.syncedAt
  };
}

export function parseTasksDocument(
  text: string,
  options: { source?: string } = {}
): ParsedTasksDocument {
  let currentSection: string | null = null;
  const items: TaskSyncItem[] = [];
  const resumeLines: string[] = [];

  for (const rawLine of text.split(/\r?\n/)) {
    const header = SECTION_HEADER_RE.exec(rawLine);
    if (header?.groups?.title) {
      currentSection = header.groups.title.trim().toLocaleLowerCase();
      continue;
    }

    if (currentSection !== null && QUEUE_SECTIONS.has(currentSection)) {
      const taskMatch = TASK_LINE_RE.exec(rawLine);
      if (taskMatch?.groups?.marker && taskMatch.groups.text) {
        const marker = taskMatch.groups.marker;
        items.push({
          text: taskMatch.groups.text.trim(),
          completed: marker.toLocaleUpperCase() === "O" || marker.toLocaleUpperCase() === "X"
        });
      }
    } else if (currentSection === "resume checkpoint") {
      const stripped = rawLine.trim();
      if (stripped) {
        resumeLines.push(stripped);
      }
    }
  }

  return {
    currentWorkflow: {
      source: options.source ?? ".dev/PLAN.md",
      resumeCheckpoint: resumeLines.length ? resumeLines.join("\n") : null,
      items
    }
  };
}
