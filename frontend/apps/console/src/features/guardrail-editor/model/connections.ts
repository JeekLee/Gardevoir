import type { EditorGraph } from "./graph-mapper";
import { canEmit, incomingRange } from "./catalog";

export function connectionError(
  graph: EditorGraph,
  sourceId: string,
  targetId: string,
): string | null {
  if (sourceId === targetId) return "A node cannot connect to itself.";
  if (
    graph.edges.some(
      (edge) => edge.source === sourceId && edge.target === targetId,
    )
  ) {
    return "This connection already exists.";
  }

  const source = graph.nodes.find((node) => node.id === sourceId);
  const target = graph.nodes.find((node) => node.id === targetId);
  if (!source || !target) return "Choose two existing nodes.";
  if (!canEmit(source.data.domainNode.type)) {
    return "Verdict nodes end a policy path.";
  }

  const { max } = incomingRange(target.data.domainNode.type);
  const incomingCount = graph.edges.filter(
    (edge) => edge.target === targetId,
  ).length;
  if (max === 0) return "This source node does not accept inputs.";
  if (max !== null && incomingCount >= max) {
    return "This node already has its maximum number of inputs.";
  }
  if (reaches(graph, targetId, sourceId)) {
    return "This connection would create a cycle.";
  }
  return null;
}

function reaches(graph: EditorGraph, start: string, target: string): boolean {
  const queue = [start];
  const visited = new Set<string>();
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current || visited.has(current)) continue;
    if (current === target) return true;
    visited.add(current);
    graph.edges.forEach((edge) => {
      if (edge.source === current) queue.push(edge.target);
    });
  }
  return false;
}
