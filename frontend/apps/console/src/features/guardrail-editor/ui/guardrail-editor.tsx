"use client";

import "@xyflow/react/dist/style.css";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeMouseHandler,
  type OnNodeDrag,
  type ReactFlowInstance,
} from "@xyflow/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  checkpoints,
  describeGuardrailGraph,
  guardrailKeys,
  publishGuardrail,
  updateGuardrailDraft,
  type Checkpoint,
  type GuardrailDetail,
  type GuardrailGraph,
  type GuardrailNodeType,
} from "@/src/entities/guardrail";
import { ConsoleApiError } from "@/src/shared/api";
import { randomId } from "@/src/shared/lib";

import { checkpointMeta, nodeCatalog, nodeCatalogByType } from "../model/catalog";
import { connectionError } from "../model/connections";
import {
  firedCheckCodes,
  testHighlights,
  type GuardrailTestResult,
  type TestHighlights,
} from "../model/guardrail-test";
import {
  graphFingerprint,
  mergeCanonicalGraph,
  toEditorGraph,
  toGuardrailGraph,
  type EditorGraph,
  type GuardrailFlowEdge,
  type GuardrailFlowNode,
} from "../model/graph-mapper";
import type { GuardrailTemplate } from "../model/templates";
import { CheckpointLane, type LaneFlowNode } from "./checkpoint-lane";
import { GuardrailNodeCard } from "./guardrail-node";
import styles from "./guardrail-editor.module.css";
import { GuardrailTestPanel } from "./guardrail-test-panel";
import { NodeInspector } from "./node-inspector";
import { TemplatePicker } from "./template-picker";

type CanvasNode = GuardrailFlowNode | LaneFlowNode;

const nodeTypes = {
  checkpointLane: CheckpointLane,
  guardrail: GuardrailNodeCard,
};

const laneNodes: LaneFlowNode[] = checkpoints.map((checkpoint) => ({
  id: `lane-${checkpoint}`,
  type: "checkpointLane",
  position: { x: checkpointMeta[checkpoint].x, y: 0 },
  data: { checkpoint },
  width: 300,
  height: 850,
  draggable: false,
  selectable: false,
  connectable: false,
  deletable: false,
  focusable: false,
  zIndex: -2,
}));

export function GuardrailEditor({
  detail,
  accessToken,
  readOnly,
  onAuthorizationError,
}: {
  detail: GuardrailDetail;
  accessToken: string;
  readOnly: boolean;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const queryClient = useQueryClient();
  const [graph, setGraph] = useState<EditorGraph>(() =>
    toEditorGraph(detail.graph),
  );
  const [baseline, setBaseline] = useState<GuardrailGraph>(detail.graph);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(
    graph.nodes[0]?.id ?? null,
  );
  const [catalogCheckpoint, setCatalogCheckpoint] =
    useState<Checkpoint>("tool_result");
  const [flowInstance, setFlowInstance] = useState<
    ReactFlowInstance<CanvasNode, GuardrailFlowEdge> | undefined
  >();
  const [graphError, setGraphError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>(
    readOnly
      ? `Published version ${detail.versionNumber} is read-only.`
      : "Draft loaded. Changes are local until you save.",
  );
  const [publishedVersion, setPublishedVersion] = useState<number | null>(
    readOnly ? detail.versionNumber : null,
  );
  const [isChoosingTemplate, setIsChoosingTemplate] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testHighlight, setTestHighlight] = useState<TestHighlights>({
    fired: [],
    upstream: [],
  });

  const saveMutation = useMutation({
    mutationFn: (wireGraph: GuardrailGraph) =>
      updateGuardrailDraft(accessToken, detail.name, wireGraph),
  });
  const publishMutation = useMutation({
    mutationFn: () => publishGuardrail(accessToken, detail.name),
  });

  const wireGraph = useMemo(() => toGuardrailGraph(graph), [graph]);
  const dirty = useMemo(
    () => graphFingerprint(wireGraph) !== graphFingerprint(baseline),
    [baseline, wireGraph],
  );
  const selectedNode =
    graph.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const isBusy = saveMutation.isPending || publishMutation.isPending;

  useDirtyNavigationGuard(dirty && !readOnly);

  const selectAndFocusNode = useCallback(
    (nodeId: string) => {
      setSelectedNodeId(nodeId);
      const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      requestAnimationFrame(() => {
        void flowInstance?.fitView({
          nodes: [{ id: nodeId }],
          padding: 1.6,
          duration: reduceMotion ? 0 : 240,
        });
      });
    },
    [flowInstance],
  );

  const onNodeClick: NodeMouseHandler<CanvasNode> = useCallback(
    (_event, node) => {
      if (node.type === "guardrail") setSelectedNodeId(node.id);
    },
    [],
  );

  function addNode(type: GuardrailNodeType) {
    const checkpoint =
      type === "side_effect" || type === "provenance"
        ? "tool_call"
        : catalogCheckpoint;
    const id = `${type.replaceAll("_", "-")}-${randomId().slice(0, 8)}`;
    const laneOrder = graph.nodes.filter(
      (node) => node.data.checkpoint === checkpoint,
    ).length;
    const domainNode = {
      id,
      type,
      config: nodeCatalogByType[type].defaultConfig(checkpoint),
    };

    setGraph((current) => ({
      ...current,
      nodes: [
        ...current.nodes,
        {
          id,
          type: "guardrail",
          position: {
            x: checkpointMeta[checkpoint].x + 30,
            y: 124 + laneOrder * 146,
          },
          data: { checkpoint, domainNode },
        },
      ],
    }));
    setSelectedNodeId(id);
    setGraphError(null);
    setStatus(`${nodeCatalogByType[type].label} added to lane ${checkpointMeta[checkpoint].index}.`);
  }

  function applyTemplate(template: GuardrailTemplate) {
    if (
      graph.nodes.length > 0 &&
      !window.confirm(
        "현재 캔버스의 노드와 연결을 선택한 템플릿으로 바꾸시겠습니까? 저장 전에는 되돌릴 수 없습니다.",
      )
    ) {
      return;
    }

    const nextGraph = toEditorGraph(template.graph);
    setGraph(nextGraph);
    setSelectedNodeId(nextGraph.nodes[0]?.id ?? null);
    setGraphError(null);
    setStatus(`${template.name} 템플릿을 불러왔습니다. 저장 전 내용을 확인하세요.`);
    setIsChoosingTemplate(false);
    requestAnimationFrame(() => {
      void flowInstance?.fitView({ padding: 0.08, duration: 240 });
    });
  }

  function updateNodeConfig(nodeId: string, config: Record<string, unknown>) {
    setGraph((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              data: {
                ...node.data,
                domainNode: { ...node.data.domainNode, config },
                validationMessage: undefined,
              },
            }
          : node,
      ),
    }));
    setGraphError(null);
  }

  function updateNodeCheckpoint(nodeId: string, checkpoint: Checkpoint) {
    setGraph((current) => ({
      ...current,
      nodes: current.nodes.map((node) => {
        if (node.id !== nodeId) return node;
        return {
          ...node,
          position: { ...node.position, x: checkpointMeta[checkpoint].x + 30 },
          data: {
            ...node.data,
            checkpoint,
            domainNode: {
              ...node.data.domainNode,
              config: { ...node.data.domainNode.config, checkpoint },
            },
            validationMessage: undefined,
          },
        };
      }),
    }));
    setGraphError(null);
  }

  function deleteNode(nodeId: string) {
    const node = graph.nodes.find((candidate) => candidate.id === nodeId);
    if (!node) return;
    if (
      !window.confirm(
        `Delete ${nodeCatalogByType[node.data.domainNode.type].label} “${nodeId}” and its connections?`,
      )
    ) {
      return;
    }

    setGraph((current) => ({
      nodes: current.nodes.filter((candidate) => candidate.id !== nodeId),
      edges: current.edges.filter(
        (edge) => edge.source !== nodeId && edge.target !== nodeId,
      ),
    }));
    setSelectedNodeId(null);
    setStatus(`${nodeId} deleted.`);
  }

  function connectNodes(sourceId: string, targetId: string) {
    const reason = connectionError(graph, sourceId, targetId);
    if (reason) {
      setGraphError(reason);
      setStatus(`Connection rejected: ${reason}`);
      return;
    }
    setGraph((current) => ({
      ...current,
      edges: [
        ...current.edges,
        {
          id: `edge-${randomId()}`,
          source: sourceId,
          target: targetId,
          type: "smoothstep",
        },
      ],
    }));
    setSelectedNodeId(targetId);
    setGraphError(null);
    setStatus(`Connected ${sourceId} to ${targetId}.`);
  }

  function onConnect(connection: Connection) {
    if (connection.source && connection.target) {
      connectNodes(connection.source, connection.target);
    }
  }

  function onNodesChange(changes: NodeChange<CanvasNode>[]) {
    if (readOnly) return;
    const domainChanges = changes.filter(
      (change) =>
        change.type === "add"
          ? change.item.type === "guardrail"
          : !change.id.startsWith("lane-"),
    ) as NodeChange<GuardrailFlowNode>[];
    setGraph((current) => ({
      ...current,
      nodes: applyNodeChanges(domainChanges, current.nodes),
    }));
  }

  function onEdgesChange(changes: EdgeChange<GuardrailFlowEdge>[]) {
    if (readOnly) return;
    setGraph((current) => ({
      ...current,
      edges: applyEdgeChanges(changes, current.edges),
    }));
  }

  const onNodeDragStop: OnNodeDrag<CanvasNode> = (_event, canvasNode) => {
    if (canvasNode.type !== "guardrail") return;
    const node = canvasNode as GuardrailFlowNode;
    const checkpoint = closestCheckpoint(node.position.x);
    const type = node.data.domainNode.type;
    const lockedCheckpoint =
      type === "side_effect" || type === "provenance" ? "tool_call" : checkpoint;

    setGraph((current) => ({
      ...current,
      nodes: current.nodes.map((candidate) => {
        if (candidate.id !== node.id) return candidate;
        const config =
          type === "extract" || type === "taint"
            ? { ...candidate.data.domainNode.config, checkpoint: lockedCheckpoint }
            : candidate.data.domainNode.config;
        return {
          ...candidate,
          position: {
            x: checkpointMeta[lockedCheckpoint].x + 30,
            y: Math.max(124, node.position.y),
          },
          data: {
            ...candidate.data,
            checkpoint: lockedCheckpoint,
            domainNode: { ...candidate.data.domainNode, config },
          },
        };
      }),
    }));
  };

  function removeEdge(edgeId: string) {
    setGraph((current) => ({
      ...current,
      edges: current.edges.filter((edge) => edge.id !== edgeId),
    }));
    setGraphError(null);
    setStatus("Connection removed.");
  }

  async function saveDraft(): Promise<GuardrailDetail | null> {
    setGraphError(null);
    setStatus("Saving draft…");
    try {
      const saved = await saveMutation.mutateAsync(toGuardrailGraph(graph));
      setGraph((current) => mergeCanonicalGraph(saved.graph, current));
      setBaseline(saved.graph);
      queryClient.setQueryData(guardrailKeys.draft(detail.name), saved);
      void queryClient.invalidateQueries({ queryKey: guardrailKeys.list() });
      setStatus("Draft saved. Gateway validation passed.");
      return saved;
    } catch (error) {
      handleGatewayError(error, "Draft could not be saved.");
      return null;
    }
  }

  async function publishDraft() {
    if (dirty) {
      const saved = await saveDraft();
      if (!saved) return;
    }

    setGraphError(null);
    setStatus("Publishing validated draft…");
    try {
      const published = await publishMutation.mutateAsync();
      if (published.versionNumber !== null) {
        setPublishedVersion(published.versionNumber);
        queryClient.setQueryData(
          guardrailKeys.version(detail.name, published.versionNumber),
          published,
        );
      }
      void queryClient.invalidateQueries({ queryKey: guardrailKeys.list() });
      setStatus(
        `Published version ${published.versionNumber}. The draft remains editable.`,
      );
    } catch (error) {
      handleGatewayError(error, "This draft could not be published.");
    }
  }

  function handleGatewayError(error: unknown, fallback: string) {
    if (
      error instanceof ConsoleApiError &&
      (error.httpStatus === 401 || error.httpStatus === 403)
    ) {
      onAuthorizationError(error);
      return;
    }

    if (error instanceof ConsoleApiError) {
      const details = error.details;
      const directNodeId =
        typeof details?.node_id === "string"
          ? details.node_id
          : typeof details?.nodeId === "string"
            ? details.nodeId
            : null;
      const cycleNodes = Array.isArray(details?.nodes)
        ? details.nodes.filter((node): node is string => typeof node === "string")
        : [];
      const affectedNodes = directNodeId ? [directNodeId] : cycleNodes;
      const reason =
        typeof details?.reason === "string" ? details.reason : error.message;

      if (affectedNodes.length > 0) {
        setGraph((current) => ({
          ...current,
          nodes: current.nodes.map((node) =>
            affectedNodes.includes(node.id)
              ? {
                  ...node,
                  data: { ...node.data, validationMessage: reason },
                }
              : node,
          ),
        }));
        selectAndFocusNode(affectedNodes[0]);
      }

      const reference = error.requestId ? ` Reference ${error.requestId}.` : "";
      setGraphError(`${error.code}: ${reason}${reference}`);
      setStatus(`${fallback} ${reason}`);
      return;
    }

    setGraphError(fallback);
    setStatus(fallback);
  }

  function clearTestHighlight() {
    setTestHighlight({ fired: [], upstream: [] });
  }

  function handleTestResult(result: GuardrailTestResult) {
    const highlights = testHighlights(wireGraph, firedCheckCodes(result));
    setTestHighlight(highlights);
    setStatus(
      highlights.fired.length > 0
        ? `${highlights.fired.length}개 verdict 노드가 실제 호출 테스트에서 발동했습니다.`
        : `실제 호출 테스트 완료: would-have ${result.overallWouldHave}.`,
    );
  }

  const firedNodeIds = new Set(testHighlight.fired);
  const upstreamNodeIds = new Set(testHighlight.upstream);
  const canvasNodes = [
    ...laneNodes,
    ...graph.nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        testHighlight: firedNodeIds.has(node.id)
          ? ("fired" as const)
          : upstreamNodeIds.has(node.id)
            ? ("upstream" as const)
            : undefined,
      },
      selected: node.id === selectedNodeId,
      draggable: !readOnly,
      connectable: !readOnly,
    })),
  ];

  return (
    <section className={styles.editorPage} aria-labelledby="guardrail-name">
      <header className={styles.editorHeader}>
        <div className={styles.editorIdentity}>
          <Link href="/guardrails" aria-label="Back to guardrails">
            ←
          </Link>
          <div>
            <p>{readOnly ? `Published version ${detail.versionNumber}` : "Draft policy graph"}</p>
            <h1 id="guardrail-name">{detail.name}</h1>
          </div>
          <span className={readOnly ? styles.versionBadge : styles.draftBadge}>
            {readOnly ? `v${detail.versionNumber}` : dirty ? "Unsaved draft" : "Draft saved"}
          </span>
        </div>

        <div className={styles.editorActions}>
          {!readOnly ? (
            <button
              className={styles.secondaryAction}
              type="button"
              disabled={isBusy}
              onClick={() => setIsTesting(true)}
            >
              Test draft
            </button>
          ) : null}
          {!readOnly ? (
            <button
              className={styles.secondaryAction}
              type="button"
              disabled={isBusy}
              onClick={() => setIsChoosingTemplate(true)}
            >
              ＋ 템플릿에서 시작
            </button>
          ) : null}
          {publishedVersion !== null && !readOnly ? (
            <Link
              className={styles.secondaryAction}
              href={`/guardrails/${encodeURIComponent(detail.name)}/versions/${publishedVersion}`}
            >
              View v{publishedVersion}
            </Link>
          ) : null}
          {readOnly ? (
            <Link
              className={styles.primaryAction}
              href={`/guardrails/${encodeURIComponent(detail.name)}`}
            >
              Return to draft
            </Link>
          ) : (
            <>
              <button
                className={styles.secondaryAction}
                type="button"
                disabled={isBusy || !dirty}
                onClick={() => void saveDraft()}
              >
                {saveMutation.isPending ? "Saving…" : "Save draft"}
              </button>
              <button
                className={styles.primaryAction}
                type="button"
                disabled={isBusy}
                onClick={() => void publishDraft()}
              >
                {publishMutation.isPending
                  ? "Publishing…"
                  : dirty
                    ? "Save & publish"
                    : "Publish"}
              </button>
            </>
          )}
        </div>
      </header>

      <div className={styles.policySummary}>
        <span>정책 요약</span>
        <p>{describeGuardrailGraph(wireGraph)}</p>
      </div>

      <div className={styles.editorStatus} aria-live="polite">
        <span className={graphError ? styles.errorDot : styles.statusDot} aria-hidden="true" />
        <p>{status}</p>
        <small>
          Lane placement is inferred from connected sources after reload; free layout is session-only.
        </small>
      </div>

      {graphError ? (
        <div className={styles.graphError} role="alert">
          <strong>Graph needs attention</strong>
          <span>{graphError}</span>
          <button type="button" onClick={() => setGraphError(null)} aria-label="Dismiss graph error">
            ×
          </button>
        </div>
      ) : null}

      {isTesting && !readOnly ? (
        <GuardrailTestPanel
          accessToken={accessToken}
          guardrailName={detail.name}
          dirty={dirty}
          onSaveDraft={async () => (await saveDraft()) !== null}
          onAuthorizationError={onAuthorizationError}
          onGatewayError={(error) =>
            handleGatewayError(error, "실제 호출 테스트를 완료하지 못했습니다.")
          }
          onResult={handleTestResult}
          onClear={clearTestHighlight}
          onClose={() => setIsTesting(false)}
        />
      ) : null}

      <div className={styles.editorWorkspace}>
        <div className={styles.authoringSurface}>
          {!readOnly ? (
            <div className={styles.nodeCatalog} aria-label="Node catalog">
              <label>
                <span>Add to checkpoint</span>
                <select
                  value={catalogCheckpoint}
                  onChange={(event) => setCatalogCheckpoint(event.target.value as Checkpoint)}
                >
                  {checkpoints.map((checkpoint) => (
                    <option key={checkpoint} value={checkpoint}>
                      {checkpointMeta[checkpoint].index} {checkpointMeta[checkpoint].label}
                    </option>
                  ))}
                </select>
              </label>
              <div>
                {nodeCatalog.map((item) => (
                  <button
                    key={item.type}
                    className={
                      item.category === "Action control" ? styles.actionCatalogItem : undefined
                    }
                    type="button"
                    onClick={() => addNode(item.type)}
                    title={item.description}
                  >
                    <span>{item.label}</span>
                    <small>{item.category}</small>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className={styles.canvas} aria-label="Guardrail checkpoint graph editor">
            <ReactFlow<CanvasNode, GuardrailFlowEdge>
              nodes={canvasNodes}
              edges={graph.edges}
              nodeTypes={nodeTypes}
              onInit={setFlowInstance}
              onNodeClick={onNodeClick}
              onPaneClick={() => setSelectedNodeId(null)}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeDragStop={onNodeDragStop}
              onConnect={onConnect}
              isValidConnection={(connection) =>
                Boolean(
                  connection.source &&
                    connection.target &&
                    !connectionError(graph, connection.source, connection.target),
                )
              }
              nodesDraggable={!readOnly}
              nodesConnectable={!readOnly}
              edgesReconnectable={false}
              deleteKeyCode={null}
              minZoom={0.45}
              maxZoom={1.35}
              fitView
              fitViewOptions={{ padding: 0.04 }}
              translateExtent={[
                [-120, -120],
                [1_440, 1_060],
              ]}
              aria-label="Guardrail graph with input, tool result, tool call, and output lanes"
            >
              <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
              <Controls showInteractive={!readOnly} />
              <MiniMap
                pannable
                zoomable
                nodeColor={(node) =>
                  node.type === "checkpointLane"
                    ? "transparent"
                    : node.data?.testHighlight === "fired"
                      ? "#d99b24"
                      : node.data?.testHighlight === "upstream"
                        ? "var(--brand-light)"
                    : node.data?.validationMessage
                      ? "var(--danger)"
                      : "var(--brand)"
                }
                maskColor="color-mix(in srgb, var(--surface) 70%, transparent)"
              />
            </ReactFlow>
          </div>
        </div>

        <NodeInspector
          graph={graph}
          selectedNode={selectedNode}
          readOnly={readOnly}
          onSelect={selectAndFocusNode}
          onConfigChange={updateNodeConfig}
          onCheckpointChange={updateNodeCheckpoint}
          onDelete={deleteNode}
          onConnect={connectNodes}
          onRemoveEdge={removeEdge}
        />
      </div>

      {isChoosingTemplate ? (
        <TemplatePicker
          onApply={applyTemplate}
          onClose={() => setIsChoosingTemplate(false)}
        />
      ) : null}
    </section>
  );
}

function closestCheckpoint(x: number): Checkpoint {
  return checkpoints.reduce((closest, checkpoint) =>
    Math.abs(checkpointMeta[checkpoint].x - x) <
    Math.abs(checkpointMeta[closest].x - x)
      ? checkpoint
      : closest,
  );
}

function useDirtyNavigationGuard(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;

    const message = "Leave this draft? Unsaved graph changes will be lost.";
    const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    const guardLink = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (anchor.origin !== window.location.origin) return;
      if (!window.confirm(message)) event.preventDefault();
    };

    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", guardLink, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", guardLink, true);
    };
  }, [enabled]);
}
