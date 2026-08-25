import type { Edge, Node, XYPosition } from "@xyflow/react";

import {
  checkpoints,
  type Checkpoint,
  type GuardrailGraph,
  type GuardrailNode,
} from "@/src/entities/guardrail";

export type GuardrailNodeData = {
  checkpoint: Checkpoint;
  domainNode: GuardrailNode;
  validationMessage?: string;
  testHighlight?: "fired" | "upstream";
} & Record<string, unknown>;

export type GuardrailFlowNode = Node<GuardrailNodeData, "guardrail">;
export type GuardrailFlowEdge = Edge;

export type EditorGraph = {
  nodes: GuardrailFlowNode[];
  edges: GuardrailFlowEdge[];
};

type PositionMap = ReadonlyMap<string, XYPosition>;

export function toEditorGraph(
  graph: GuardrailGraph,
  positions?: PositionMap,
): EditorGraph {
  const resolvedCheckpoints = resolveCheckpoints(graph);
  const layout = layoutPositions(graph, resolvedCheckpoints);

  return {
    nodes: graph.nodes.map((domainNode) => {
      const checkpoint = resolvedCheckpoints.get(domainNode.id) ?? "input";

      return {
        id: domainNode.id,
        type: "guardrail",
        position:
          positions?.get(domainNode.id) ??
          layout.get(domainNode.id) ??
          { x: 80, y: 80 },
        data: {
          checkpoint,
          domainNode: cloneNode(domainNode),
        },
      } satisfies GuardrailFlowNode;
    }),
    edges: graph.edges.map((edge, index) => ({
      id: `edge-${index}-${edge.src}-${edge.dst}`,
      source: edge.src,
      target: edge.dst,
      type: "smoothstep",
    })),
  };
}

export function toGuardrailGraph(graph: EditorGraph): GuardrailGraph {
  return {
    nodes: graph.nodes.map((node) => cloneNode(node.data.domainNode)),
    edges: graph.edges.map((edge) => ({
      src: edge.source,
      dst: edge.target,
    })),
  };
}

export function mergeCanonicalGraph(
  graph: GuardrailGraph,
  current: EditorGraph,
): EditorGraph {
  const positions = new Map(
    current.nodes.map((node) => [node.id, node.position] as const),
  );
  return toEditorGraph(graph, positions);
}

export function graphFingerprint(graph: GuardrailGraph): string {
  return JSON.stringify(graph);
}

function resolveCheckpoints(graph: GuardrailGraph): Map<string, Checkpoint> {
  const incoming = new Map<string, string[]>();
  graph.nodes.forEach((node) => incoming.set(node.id, []));
  graph.edges.forEach((edge) => incoming.get(edge.dst)?.push(edge.src));

  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const resolved = new Map<string, Checkpoint>();

  function resolve(nodeId: string, visiting: Set<string>): Checkpoint | null {
    const cached = resolved.get(nodeId);
    if (cached) return cached;
    if (visiting.has(nodeId)) return null;

    const node = nodeById.get(nodeId);
    if (!node) return null;
    const configured = readCheckpoint(node.config.checkpoint);
    if (configured) {
      resolved.set(nodeId, configured);
      return configured;
    }

    const nextVisiting = new Set(visiting).add(nodeId);
    for (const sourceId of incoming.get(nodeId) ?? []) {
      const upstream = resolve(sourceId, nextVisiting);
      if (upstream) {
        resolved.set(nodeId, upstream);
        return upstream;
      }
    }

    return null;
  }

  graph.nodes.forEach((node) => {
    const checkpoint = resolve(node.id, new Set());
    if (checkpoint) resolved.set(node.id, checkpoint);
  });
  return resolved;
}

function layoutPositions(
  graph: GuardrailGraph,
  checkpointsByNode: ReadonlyMap<string, Checkpoint>,
): Map<string, XYPosition> {
  const incoming = new Map<string, string[]>();
  graph.nodes.forEach((node) => incoming.set(node.id, []));
  graph.edges.forEach((edge) => incoming.get(edge.dst)?.push(edge.src));

  const depths = new Map<string, number>();
  function depth(nodeId: string, visiting: Set<string>): number {
    const cached = depths.get(nodeId);
    if (cached !== undefined) return cached;
    if (visiting.has(nodeId)) return 0;

    const checkpoint = checkpointsByNode.get(nodeId) ?? "input";
    const upstream = (incoming.get(nodeId) ?? []).filter(
      (sourceId) =>
        (checkpointsByNode.get(sourceId) ?? "input") === checkpoint,
    );
    const nextVisiting = new Set(visiting).add(nodeId);
    const resolved =
      upstream.length === 0
        ? 0
        : Math.max(
            ...upstream.map((sourceId) => depth(sourceId, nextVisiting)),
          ) + 1;
    depths.set(nodeId, resolved);
    return resolved;
  }

  const rows = new Map<string, number>();
  const positions = new Map<string, XYPosition>();
  for (const node of graph.nodes) {
    const checkpoint = checkpointsByNode.get(node.id) ?? "input";
    const column = depth(node.id, new Set());
    const columnKey = `${checkpoint}:${column}`;
    const row = rows.get(columnKey) ?? 0;
    rows.set(columnKey, row + 1);
    positions.set(node.id, {
      x: 80 + column * 310,
      y: 80 + row * 160,
    });
  }
  return positions;
}

function readCheckpoint(value: unknown): Checkpoint | null {
  return typeof value === "string" &&
    checkpoints.some((checkpoint) => checkpoint === value)
    ? (value as Checkpoint)
    : null;
}

function cloneNode(node: GuardrailNode): GuardrailNode {
  return {
    id: node.id,
    type: node.type,
    config: { ...node.config },
  };
}
