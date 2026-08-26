import type { EditorGraph } from "./graph-mapper";

const recoveredDrafts = new Map<string, EditorGraph>();

export function preserveRecoveredDraft(name: string, graph: EditorGraph): void {
  recoveredDrafts.set(name, graph);
}

export function peekRecoveredDraft(name: string): EditorGraph | null {
  return recoveredDrafts.get(name) ?? null;
}

export function clearRecoveredDraft(name: string): void {
  recoveredDrafts.delete(name);
}
