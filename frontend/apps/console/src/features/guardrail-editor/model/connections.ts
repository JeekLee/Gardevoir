import type { EditorGraph } from "./graph-mapper";
import { canEmit, incomingRange } from "./catalog";

export function connectionError(
  graph: EditorGraph,
  sourceId: string,
  targetId: string,
): string | null {
  if (sourceId === targetId) return "노드는 자기 자신과 연결할 수 없습니다.";
  if (
    graph.edges.some(
      (edge) => edge.source === sourceId && edge.target === targetId,
    )
  ) {
    return "이미 같은 연결이 있습니다.";
  }

  const source = graph.nodes.find((node) => node.id === sourceId);
  const target = graph.nodes.find((node) => node.id === targetId);
  if (!source || !target) return "존재하는 노드 두 개를 선택하세요.";
  if (!canEmit(source.data.domainNode.type)) {
    return "판정 노드는 정책 경로의 마지막에만 둘 수 있습니다.";
  }

  const { max } = incomingRange(target.data.domainNode.type);
  const incomingCount = graph.edges.filter(
    (edge) => edge.target === targetId,
  ).length;
  if (max === 0) return "이 소스 노드는 입력을 받을 수 없습니다.";
  if (max !== null && incomingCount >= max) {
    return "이 노드는 허용된 입력 연결 수를 모두 사용했습니다.";
  }
  if (reaches(graph, targetId, sourceId)) {
    return "이 연결을 추가하면 그래프에 순환이 생깁니다.";
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
