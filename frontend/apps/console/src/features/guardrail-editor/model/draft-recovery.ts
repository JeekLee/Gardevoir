import type { EditorGraph } from "./graph-mapper";

export type RecoveredDraft = {
  description: string;
  graph: EditorGraph;
};

const recoveredDrafts = new Map<string, RecoveredDraft>();

export function preserveRecoveredDraft(
  name: string,
  draft: RecoveredDraft,
): void {
  recoveredDrafts.set(name, draft);
}

export function peekRecoveredDraft(name: string): RecoveredDraft | null {
  return recoveredDrafts.get(name) ?? null;
}

export function clearRecoveredDraft(name: string): void {
  recoveredDrafts.delete(name);
}
