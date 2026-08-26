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
import { ConfirmDialog } from "@/src/shared/ui/confirm-dialog";

import {
  catalogForCheckpoint,
  checkpointMeta,
  createCatalogNode,
  nodeCatalogByType,
} from "../model/catalog";
import {
  checkpointForNode,
  graphForCheckpoint,
  type EditorTab,
} from "../model/checkpoint-view";
import { connectionError } from "../model/connections";
import {
  clearRecoveredDraft,
  peekRecoveredDraft,
  preserveRecoveredDraft,
} from "../model/draft-recovery";
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
import { EditorTabs } from "./editor-tabs";
import styles from "./guardrail-editor.module.css";
import { GuardrailNodeCard } from "./guardrail-node";
import { GuardrailOverview } from "./guardrail-overview";
import { GuardrailTestPanel } from "./guardrail-test-panel";
import { NodeInspector } from "./node-inspector";
import { TemplatePicker } from "./template-picker";

const flowNodeTypes = {
  guardrail: GuardrailNodeCard,
};

type VisibleGraphError = {
  message: string;
  reference?: string;
};

type PendingDestructiveAction =
  | { kind: "node"; nodeId: string; label: string }
  | { kind: "template"; template: GuardrailTemplate };

export function GuardrailEditor({
  detail,
  accessToken,
  readOnly,
  latestPublishedVersion,
  onAuthorizationError,
}: {
  detail: GuardrailDetail;
  accessToken: string;
  readOnly: boolean;
  latestPublishedVersion: number | null;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const queryClient = useQueryClient();
  const recoveredDraft = useMemo(
    () => (readOnly ? null : peekRecoveredDraft(detail.name)),
    [detail.name, readOnly],
  );
  const [graph, setGraph] = useState<EditorGraph>(() =>
    recoveredDraft ?? toEditorGraph(detail.graph),
  );
  const [baseline, setBaseline] = useState<GuardrailGraph>(detail.graph);
  const [activeTab, setActiveTab] = useState<EditorTab>("overview");
  const [tabFocusRequest, setTabFocusRequest] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [pendingFocusNodeId, setPendingFocusNodeId] = useState<string | null>(
    null,
  );
  const [flowInstance, setFlowInstance] = useState<
    ReactFlowInstance<GuardrailFlowNode, GuardrailFlowEdge> | undefined
  >();
  const [graphError, setGraphError] = useState<VisibleGraphError | null>(null);
  const [connectionRejection, setConnectionRejection] = useState<string | null>(
    null,
  );
  const [status, setStatus] = useState<string>(
    readOnly
      ? `Published version ${detail.versionNumber} is read-only.`
      : recoveredDraft
        ? "Unsaved draft restored after sign-in. Save when you are ready."
        : "Draft loaded. Changes are local until you save.",
  );
  const [publishedVersion, setPublishedVersion] = useState<number | null>(
    readOnly ? detail.versionNumber : latestPublishedVersion,
  );
  const [isChoosingTemplate, setIsChoosingTemplate] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [pendingDestructiveAction, setPendingDestructiveAction] =
    useState<PendingDestructiveAction | null>(null);
  const [authenticationError, setAuthenticationError] =
    useState<ConsoleApiError | null>(null);
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
  const activeCheckpoint: Checkpoint | null =
    activeTab === "overview" ? null : activeTab;
  const checkpointGraph = useMemo(
    () =>
      activeCheckpoint
        ? graphForCheckpoint(graph, activeCheckpoint)
        : { nodes: [], edges: [] },
    [activeCheckpoint, graph],
  );
  const selectedNode =
    checkpointGraph.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const isBusy = saveMutation.isPending || publishMutation.isPending;

  useDirtyNavigationGuard(dirty && !readOnly);

  useEffect(() => {
    if (recoveredDraft) clearRecoveredDraft(detail.name);
  }, [detail.name, recoveredDraft]);

  useEffect(() => {
    if (!activeCheckpoint || !flowInstance) return;
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const frame = requestAnimationFrame(() => {
      void flowInstance.fitView({
        padding: 0.18,
        duration: reduceMotion ? 0 : 220,
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [activeCheckpoint, flowInstance]);

  useEffect(() => {
    if (!pendingFocusNodeId || !flowInstance) return;
    if (
      !checkpointGraph.nodes.some((node) => node.id === pendingFocusNodeId)
    ) {
      return;
    }
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const frame = requestAnimationFrame(() => {
      void flowInstance.fitView({
        nodes: [{ id: pendingFocusNodeId }],
        padding: 1.6,
        duration: reduceMotion ? 0 : 240,
      });
      setPendingFocusNodeId(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [checkpointGraph.nodes, flowInstance, pendingFocusNodeId]);

  const selectAndFocusNode = useCallback(
    (nodeId: string) => {
      const checkpoint = checkpointForNode(graph, nodeId);
      if (!checkpoint) return;
      setActiveTab(checkpoint);
      setSelectedNodeId(nodeId);
      setPendingFocusNodeId(nodeId);
    },
    [graph],
  );

  const onNodeClick: NodeMouseHandler<GuardrailFlowNode> = useCallback(
    (_event, node) => setSelectedNodeId(node.id),
    [],
  );

  function changeTab(tab: EditorTab) {
    setActiveTab(tab);
    setSelectedNodeId(
      tab === "overview"
        ? null
        : graphForCheckpoint(graph, tab).nodes[0]?.id ?? null,
    );
  }

  function openCheckpoint(checkpoint: Checkpoint) {
    changeTab(checkpoint);
    setTabFocusRequest((request) => request + 1);
  }

  function addNode(type: GuardrailNodeType) {
    if (!activeCheckpoint) return;
    const id = `${type.replaceAll("_", "-")}-${randomId().slice(0, 8)}`;
    const domainNode = createCatalogNode(type, activeCheckpoint, id);
    const position = nextNodePosition(checkpointGraph);

    setGraph((current) => ({
      ...current,
      nodes: [
        ...current.nodes,
        {
          id,
          type: "guardrail",
          position,
          data: { checkpoint: activeCheckpoint, domainNode },
        },
      ],
    }));
    setSelectedNodeId(id);
    setPendingFocusNodeId(id);
    setGraphError(null);
    setStatus(
      `${nodeCatalogByType[type].label} added to ${checkpointMeta[activeCheckpoint].index} ${checkpointMeta[activeCheckpoint].label}.`,
    );
  }

  function applyTemplate(template: GuardrailTemplate) {
    if (graph.nodes.length > 0) {
      setPendingDestructiveAction({ kind: "template", template });
      return;
    }

    replaceWithTemplate(template);
  }

  function replaceWithTemplate(template: GuardrailTemplate) {
    const nextGraph = toEditorGraph(template.graph);
    const firstNode = nextGraph.nodes[0] ?? null;
    setGraph(nextGraph);
    setSelectedNodeId(firstNode?.id ?? null);
    setGraphError(null);
    setStatus(
      `${template.name} 템플릿을 불러왔습니다. 저장 전 내용을 확인하세요.`,
    );
    setIsChoosingTemplate(false);
    setPendingDestructiveAction(null);
    if (firstNode) {
      setActiveTab(firstNode.data.checkpoint);
      setPendingFocusNodeId(firstNode.id);
    }
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

  function deleteNode(nodeId: string) {
    const node = graph.nodes.find((candidate) => candidate.id === nodeId);
    if (!node) return;
    setPendingDestructiveAction({
      kind: "node",
      nodeId,
      label: nodeCatalogByType[node.data.domainNode.type].label,
    });
  }

  function confirmNodeDeletion(nodeId: string) {
    setGraph((current) => ({
      nodes: current.nodes.filter((candidate) => candidate.id !== nodeId),
      edges: current.edges.filter(
        (edge) => edge.source !== nodeId && edge.target !== nodeId,
      ),
    }));
    setSelectedNodeId(null);
    setPendingDestructiveAction(null);
    setStatus(`${nodeId} deleted.`);
  }

  function connectNodes(sourceId: string, targetId: string) {
    const reason = connectionError(graph, sourceId, targetId);
    if (reason) {
      setConnectionRejection(reason);
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
    setConnectionRejection(null);
    setGraphError(null);
    setStatus(`Connected ${sourceId} to ${targetId}.`);
  }

  function onConnect(connection: Connection) {
    if (connection.source && connection.target) {
      connectNodes(connection.source, connection.target);
    }
  }

  function isConnectionValid(
    connection: Connection | GuardrailFlowEdge,
  ): boolean {
    if (!connection.source || !connection.target) return false;
    const reason = connectionError(graph, connection.source, connection.target);
    setConnectionRejection(reason);
    if (reason) {
      setStatus(`Connection rejected: ${reason}`);
      return false;
    }
    return true;
  }

  function onNodesChange(changes: NodeChange<GuardrailFlowNode>[]) {
    if (readOnly) return;
    setGraph((current) => ({
      ...current,
      nodes: applyNodeChanges(changes, current.nodes),
    }));
  }

  function onEdgesChange(changes: EdgeChange<GuardrailFlowEdge>[]) {
    if (readOnly) return;
    setGraph((current) => ({
      ...current,
      edges: applyEdgeChanges(changes, current.edges),
    }));
  }

  const onNodeDragStop: OnNodeDrag<GuardrailFlowNode> = (
    _event,
    canvasNode,
  ) => {
    setGraph((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === canvasNode.id
          ? { ...node, position: canvasNode.position }
          : node,
      ),
    }));
  };

  function removeEdge(edgeId: string) {
    setGraph((current) => ({
      ...current,
      edges: current.edges.filter((edge) => edge.id !== edgeId),
    }));
    setGraphError(null);
    setConnectionRejection(null);
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
      handleAuthorizationError(error);
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
        ? details.nodes.filter(
            (node): node is string => typeof node === "string",
          )
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

      const requestReference = error.requestId ? ` · ${error.requestId}` : "";
      setGraphError({
        message: reason,
        reference: `Reference ${error.code}${requestReference}`,
      });
      setStatus(`${fallback} ${reason}`);
      return;
    }

    setGraphError({ message: fallback });
    setStatus(fallback);
  }

  function handleAuthorizationError(error: ConsoleApiError) {
    if (error.httpStatus === 401 && dirty && !readOnly) {
      setAuthenticationError(error);
      setStatus(
        "Your session expired. Unsaved changes remain in this editor until you choose how to continue.",
      );
      return;
    }
    onAuthorizationError(error);
  }

  function continueToSignIn() {
    if (!authenticationError) return;
    preserveRecoveredDraft(detail.name, graph);
    onAuthorizationError(authenticationError);
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
        : `실제 호출 테스트 완료: ${result.overallAction}.`,
    );
  }

  const firedNodeIds = new Set(testHighlight.fired);
  const upstreamNodeIds = new Set(testHighlight.upstream);
  const canvasNodes = checkpointGraph.nodes.map((node) => ({
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
  }));

  return (
    <section className={styles.editorPage} aria-labelledby="guardrail-name">
      <header className={styles.editorHeader}>
        <div className={styles.editorIdentity}>
          <Link href="/guardrails" aria-label="Back to guardrails">
            ←
          </Link>
          <div>
            <p>{readOnly ? "Published policy graph" : "Draft policy graph"}</p>
            <h1 id="guardrail-name">{detail.name}</h1>
          </div>
        </div>
        <div className={styles.editorActions}>
          <span className={readOnly ? styles.versionBadge : styles.draftBadge}>
            {readOnly
              ? `Published v${detail.versionNumber}`
              : dirty
                ? "Unsaved changes"
                : "Draft saved"}
          </span>
          {!readOnly ? (
            <button
              className={styles.primaryAction}
              type="button"
              disabled={isBusy || !dirty}
              onClick={() => void saveDraft()}
            >
              {saveMutation.isPending ? "Saving…" : "Save draft"}
            </button>
          ) : null}
        </div>
      </header>

      <EditorTabs
        activeTab={activeTab}
        focusRequest={tabFocusRequest}
        onChange={changeTab}
      />

      <div className={styles.editorStatus} aria-live="polite">
        <span
          className={graphError ? styles.errorDot : styles.statusDot}
          aria-hidden="true"
        />
        <p>{status}</p>
        <small>
          Free layout is session-only; the saved policy remains one ordered graph.
        </small>
      </div>

      {graphError ? (
        <div className={styles.graphError} role="alert">
          <strong>Graph needs attention</strong>
          <span>{graphError.message}</span>
          {graphError.reference ? <code>{graphError.reference}</code> : null}
          <button
            type="button"
            onClick={() => setGraphError(null)}
            aria-label="Dismiss graph error"
          >
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
          onAuthorizationError={handleAuthorizationError}
          onGatewayError={(error) =>
            handleGatewayError(
              error,
              "실제 호출 테스트를 완료하지 못했습니다.",
            )
          }
          onResult={handleTestResult}
          onClear={clearTestHighlight}
          onClose={() => setIsTesting(false)}
        />
      ) : null}

      <div
        id="guardrail-tab-panel"
        role="tabpanel"
        aria-labelledby={`guardrail-tab-${activeTab}`}
        tabIndex={0}
        className={styles.tabPanel}
      >
        {activeTab === "overview" ? (
          <GuardrailOverview
            name={detail.name}
            graph={graph}
            wireGraph={wireGraph}
            readOnly={readOnly}
            versionNumber={detail.versionNumber}
            publishedVersion={publishedVersion}
            dirty={dirty}
            isBusy={isBusy}
            isPublishing={publishMutation.isPending}
            onOpenCheckpoint={openCheckpoint}
            onPublish={() => void publishDraft()}
            onTest={() => setIsTesting(true)}
            onChooseTemplate={() => setIsChoosingTemplate(true)}
          />
        ) : (
          <div className={styles.editorWorkspace}>
            <div className={styles.authoringSurface}>
              <div className={styles.checkpointContext}>
                <span>{checkpointMeta[activeTab].index}</span>
                <div>
                  <p>{checkpointMeta[activeTab].shortLabel}</p>
                  <h2>{checkpointMeta[activeTab].label}</h2>
                  <small>{checkpointMeta[activeTab].description}</small>
                </div>
                <small className={styles.checkpointOrderNote}>
                  번호는 체크포인트 ID이며, 탭 순서는 실제 요청 실행 순서입니다.
                </small>
                <strong>
                  {checkpointGraph.nodes.length} node
                  {checkpointGraph.nodes.length === 1 ? "" : "s"}
                </strong>
              </div>

              {!readOnly ? (
                <>
                  <div
                    className={styles.nodeCatalog}
                    aria-label={`${checkpointMeta[activeTab].label} node catalog`}
                  >
                    <div>
                      {catalogForCheckpoint(activeTab).map((item) => (
                        <button
                          key={item.type}
                          className={
                            item.category === "Action control"
                              ? styles.actionCatalogItem
                              : undefined
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
                  {connectionRejection ? (
                    <p className={styles.connectionRejection} role="status">
                      Connection unavailable: {connectionRejection}
                    </p>
                  ) : null}
                </>
              ) : null}

              <div
                className={styles.canvas}
                aria-label={`${checkpointMeta[activeTab].label} checkpoint graph editor`}
              >
                <ReactFlow<GuardrailFlowNode, GuardrailFlowEdge>
                  nodes={canvasNodes}
                  edges={checkpointGraph.edges}
                  nodeTypes={flowNodeTypes}
                  onInit={setFlowInstance}
                  onNodeClick={onNodeClick}
                  onPaneClick={() => setSelectedNodeId(null)}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onNodeDragStop={onNodeDragStop}
                  onConnect={onConnect}
                  isValidConnection={isConnectionValid}
                  nodesDraggable={!readOnly}
                  nodesConnectable={!readOnly}
                  edgesReconnectable={false}
                  deleteKeyCode={null}
                  minZoom={0.35}
                  maxZoom={1.65}
                  fitView
                  fitViewOptions={{ padding: 0.18 }}
                  translateExtent={[
                    [-600, -600],
                    [6_000, 6_000],
                  ]}
                  aria-label={`${checkpointMeta[activeTab].index} ${checkpointMeta[activeTab].label} guardrail graph`}
                >
                  <Background
                    variant={BackgroundVariant.Dots}
                    gap={24}
                    size={1}
                  />
                  <Controls showInteractive={!readOnly} />
                  <MiniMap
                    pannable
                    zoomable
                    nodeColor={(node) =>
                      node.data?.testHighlight === "fired"
                        ? "var(--warn)"
                        : node.data?.testHighlight === "upstream"
                          ? "var(--brand-light)"
                          : node.data?.validationMessage
                            ? "var(--danger)"
                            : "var(--brand)"
                    }
                    maskColor="color-mix(in srgb, var(--surface) 70%, transparent)"
                  />
                </ReactFlow>
                {checkpointGraph.nodes.length === 0 ? (
                  <div className={styles.emptyCanvas} role="status">
                    <span aria-hidden="true">{checkpointMeta[activeTab].index}</span>
                    <strong>No nodes at this checkpoint</strong>
                    <p>
                      {readOnly
                        ? "This published graph does not inspect this point."
                        : "Choose a valid node type from the catalog to begin."}
                    </p>
                  </div>
                ) : null}
              </div>
            </div>

            <NodeInspector
              graph={checkpointGraph}
              selectedNode={selectedNode}
              readOnly={readOnly}
              onSelect={selectAndFocusNode}
              onConfigChange={updateNodeConfig}
              onDelete={deleteNode}
              onConnect={connectNodes}
              onRemoveEdge={removeEdge}
            />
          </div>
        )}
      </div>

      {isChoosingTemplate ? (
        <TemplatePicker
          onApply={applyTemplate}
          onClose={() => setIsChoosingTemplate(false)}
        />
      ) : null}

      {pendingDestructiveAction?.kind === "node" ? (
        <ConfirmDialog
          id="delete-guardrail-node"
          eyebrow="Remove graph node"
          title={`Delete ${pendingDestructiveAction.label}?`}
          description={
            <p>
              Node <code>{pendingDestructiveAction.nodeId}</code> and all of its
              connections will be removed from this unsaved draft.
            </p>
          }
          cancelLabel="Keep node"
          confirmLabel="Delete node"
          onClose={() => setPendingDestructiveAction(null)}
          onConfirm={() =>
            confirmNodeDeletion(pendingDestructiveAction.nodeId)
          }
        />
      ) : null}

      {pendingDestructiveAction?.kind === "template" ? (
        <ConfirmDialog
          id="replace-guardrail-template"
          eyebrow="Replace draft graph"
          title={`Use ${pendingDestructiveAction.template.name}?`}
          description={
            <p>
              The current nodes and connections will be replaced by this template.
              You can review the result before saving, but this replacement cannot be
              undone in the editor.
            </p>
          }
          cancelLabel="Keep current graph"
          confirmLabel="Replace graph"
          onClose={() => setPendingDestructiveAction(null)}
          onConfirm={() =>
            replaceWithTemplate(pendingDestructiveAction.template)
          }
        />
      ) : null}

      {authenticationError ? (
        <ConfirmDialog
          id="reauthenticate-draft"
          eyebrow="Session expired"
          title="Your unsaved draft is still here"
          description={
            <p>
              Silent session refresh failed. Stay on this screen to review the draft,
              or sign in again and return to this guardrail with the current graph
              restored.
            </p>
          }
          cancelLabel="Stay with draft"
          confirmLabel="Sign in and keep draft"
          onClose={() => setAuthenticationError(null)}
          onConfirm={continueToSignIn}
        />
      ) : null}
    </section>
  );
}

function nextNodePosition(graph: EditorGraph): { x: number; y: number } {
  const index = graph.nodes.length;
  return {
    x: 80 + Math.floor(index / 4) * 310,
    y: 80 + (index % 4) * 160,
  };
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
