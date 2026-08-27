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
  type AriaLabelConfig,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeMouseHandler,
  type OnNodeDrag,
  type ReactFlowInstance,
} from "@xyflow/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  guardrailKeys,
  publishGuardrail,
  updateGuardrailDraft,
  type Checkpoint,
  type GuardrailDetail,
  type GuardrailGraph,
  type GuardrailNodeType,
} from "@/src/entities/guardrail";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";
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

const flowAriaLabelConfig: Partial<AriaLabelConfig> = {
  "node.a11yDescription.default":
    "엔터 또는 스페이스 키로 노드를 선택합니다. 삭제 키로 삭제하고 이스케이프 키로 취소합니다.",
  "node.a11yDescription.keyboardDisabled":
    "엔터 또는 스페이스 키로 노드를 선택합니다. 방향키로 이동하고 삭제 키로 삭제하거나 이스케이프 키로 취소합니다.",
  "node.a11yDescription.ariaLiveMessage": ({ direction, x, y }) => {
    const directionLabel =
      { left: "왼쪽", right: "오른쪽", up: "위", down: "아래" }[direction] ??
      direction;
    return `선택한 노드를 ${directionLabel}(으)로 이동했습니다. 새 위치: 가로 ${x}, 세로 ${y}`;
  },
  "edge.a11yDescription.default":
    "엔터 또는 스페이스 키로 연결선을 선택합니다. 삭제 키로 삭제하고 이스케이프 키로 취소합니다.",
  "controls.ariaLabel": "그래프 보기 제어",
  "controls.zoomIn.ariaLabel": "확대",
  "controls.zoomOut.ariaLabel": "축소",
  "controls.fitView.ariaLabel": "화면에 맞추기",
  "controls.interactive.ariaLabel": "그래프 상호작용 전환",
  "minimap.ariaLabel": "미니맵",
  "handle.ariaLabel": "연결점",
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
  onDelete,
  onAuthorizationError,
}: {
  detail: GuardrailDetail;
  accessToken: string;
  readOnly: boolean;
  latestPublishedVersion: number | null;
  onDelete: () => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const queryClient = useQueryClient();
  const recoveredDraft = useMemo(
    () => (readOnly ? null : peekRecoveredDraft(detail.name)),
    [detail.name, readOnly],
  );
  const [graph, setGraph] = useState<EditorGraph>(() =>
    recoveredDraft?.graph ?? toEditorGraph(detail.graph),
  );
  const [description, setDescription] = useState(
    recoveredDraft?.description ?? detail.description,
  );
  const [baseline, setBaseline] = useState({
    description: detail.description,
    graph: detail.graph,
  });
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
      ? `발행 버전 ${detail.versionNumber}은 읽기 전용입니다.`
      : recoveredDraft
        ? "로그인 후 저장하지 않은 초안을 복원했습니다. 내용을 확인한 뒤 저장하세요."
        : "초안을 불러왔습니다. 저장하기 전 변경 내용은 현재 편집 세션에만 유지됩니다.",
  );
  const [publishedVersion, setPublishedVersion] = useState<number | null>(
    readOnly ? detail.versionNumber : latestPublishedVersion,
  );
  const [isChoosingTemplate, setIsChoosingTemplate] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const testOpener = useRef<HTMLElement | null>(null);
  const testDrawerWasOpen = useRef(false);
  const [pendingDestructiveAction, setPendingDestructiveAction] =
    useState<PendingDestructiveAction | null>(null);
  const [authenticationError, setAuthenticationError] =
    useState<ConsoleApiError | null>(null);
  const [testHighlight, setTestHighlight] = useState<TestHighlights>({
    fired: [],
    upstream: [],
  });

  const saveMutation = useMutation({
    mutationFn: (draft: { description: string; graph: GuardrailGraph }) =>
      updateGuardrailDraft(accessToken, detail.name, draft),
  });
  const publishMutation = useMutation({
    mutationFn: () => publishGuardrail(accessToken, detail.name),
  });

  const wireGraph = useMemo(() => toGuardrailGraph(graph), [graph]);
  const dirty = useMemo(
    () =>
      description !== baseline.description ||
      graphFingerprint(wireGraph) !== graphFingerprint(baseline.graph),
    [baseline, description, wireGraph],
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
    if (isTesting) {
      testDrawerWasOpen.current = true;
      return;
    }
    if (!testDrawerWasOpen.current) return;

    testDrawerWasOpen.current = false;
    const opener = testOpener.current;
    testOpener.current = null;
    if (opener?.isConnected) opener.focus();
  }, [isTesting]);

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
      `${nodeCatalogByType[type].label} 노드를 ${checkpointMeta[activeCheckpoint].index} ${checkpointMeta[activeCheckpoint].label} 검사 지점에 추가했습니다.`,
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
    setStatus(`${nodeId} 노드를 삭제했습니다.`);
  }

  function connectNodes(sourceId: string, targetId: string) {
    const reason = connectionError(graph, sourceId, targetId);
    if (reason) {
      setConnectionRejection(reason);
      setStatus(`연결할 수 없습니다. ${reason}`);
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
          ariaLabel: `${sourceId}에서 ${targetId}(으)로 연결`,
          domAttributes: { "aria-roledescription": "연결선" },
        },
      ],
    }));
    setSelectedNodeId(targetId);
    setConnectionRejection(null);
    setGraphError(null);
    setStatus(`${sourceId}에서 ${targetId}(으)로 연결했습니다.`);
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
      setStatus(`연결할 수 없습니다. ${reason}`);
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
    setStatus("연결을 삭제했습니다.");
  }

  function changeDescription(nextDescription: string) {
    setDescription(nextDescription);
    setGraphError(null);
    setStatus("가드레일 설명을 변경했습니다. 초안을 저장하면 그래프와 함께 반영됩니다.");
  }

  async function saveDraft(): Promise<GuardrailDetail | null> {
    setGraphError(null);
    setStatus("초안을 저장하는 중…");
    try {
      const saved = await saveMutation.mutateAsync({
        description,
        graph: toGuardrailGraph(graph),
      });
      setGraph((current) => mergeCanonicalGraph(saved.graph, current));
      setDescription(saved.description);
      setBaseline({ description: saved.description, graph: saved.graph });
      queryClient.setQueryData(guardrailKeys.draft(detail.name), saved);
      void queryClient.invalidateQueries({ queryKey: guardrailKeys.list() });
      setStatus("초안을 저장했습니다. 게이트웨이 검증을 통과했습니다.");
      return saved;
    } catch (error) {
      handleGatewayError(error, "초안을 저장하지 못했습니다.");
      return null;
    }
  }

  async function publishDraft() {
    if (dirty) {
      const saved = await saveDraft();
      if (!saved) return;
    }

    setGraphError(null);
    setStatus("검증된 초안을 발행하는 중…");
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
        `버전 ${published.versionNumber}을 발행했습니다. 초안은 계속 편집할 수 있습니다.`,
      );
    } catch (error) {
      handleGatewayError(error, "초안을 발행하지 못했습니다.");
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
      const reason = consoleErrorMessage(error, fallback);

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

      setGraphError({
        message: reason,
        reference: consoleErrorReference(error),
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
        "세션이 만료되었습니다. 계속할 방법을 선택할 때까지 저장하지 않은 변경 내용을 유지합니다.",
      );
      return;
    }
    onAuthorizationError(error);
  }

  function continueToSignIn() {
    if (!authenticationError) return;
    preserveRecoveredDraft(detail.name, { description, graph });
    onAuthorizationError(authenticationError);
  }

  function clearTestHighlight() {
    setTestHighlight({ fired: [], upstream: [] });
  }

  function openTestDrawer(opener: HTMLElement) {
    testOpener.current = opener;
    setIsTesting(true);
  }

  function closeTestDrawer() {
    setIsTesting(false);
  }

  function handleTestResult(result: GuardrailTestResult) {
    const highlights = testHighlights(wireGraph, firedCheckCodes(result));
    setTestHighlight(highlights);
    setStatus(
      highlights.fired.length > 0
        ? `판정 노드 ${highlights.fired.length}개가 실제 호출 테스트에서 발동했습니다.`
        : `실제 호출 테스트 완료: ${actionLabel(result.overallAction)}.`,
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
    domAttributes: { "aria-roledescription": "노드" },
  }));

  return (
    <section className={styles.editorPage} aria-labelledby="guardrail-name">
      <header className={styles.editorHeader}>
        <div className={styles.editorIdentity}>
          <Link href="/guardrails" aria-label="가드레일 목록으로 돌아가기">
            ←
          </Link>
          <h1 id="guardrail-name">{detail.name}</h1>
        </div>
        <div className={styles.editorActions}>
          {readOnly ? (
            <span className={styles.readOnlyBadge}>읽기 전용</span>
          ) : (
            <>
              <span className={styles.draftBadge} aria-live="polite">
                {dirty ? "저장하지 않은 변경" : "초안 저장됨"}
              </span>
              <button
                className={styles.secondaryAction}
                type="button"
                disabled={isBusy}
                onClick={(event) => openTestDrawer(event.currentTarget)}
              >
                테스트
              </button>
              <button
                className={styles.primaryAction}
                type="button"
                disabled={isBusy || !dirty}
                onClick={() => void saveDraft()}
              >
                {saveMutation.isPending ? "저장하는 중…" : "초안 저장"}
              </button>
            </>
          )}
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
          자유 배치는 현재 편집 세션에만 유지됩니다. 저장된 정책은 노드 순서를
          보존하는 하나의 그래프입니다.
        </small>
      </div>

      {graphError ? (
        <div className={styles.graphError} role="alert">
          <strong>그래프를 확인하세요</strong>
          <span>{graphError.message}</span>
          {graphError.reference ? <code>{graphError.reference}</code> : null}
          <button
            type="button"
            onClick={() => setGraphError(null)}
            aria-label="그래프 오류 닫기"
          >
            ×
          </button>
        </div>
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
            description={description}
            readOnly={readOnly}
            versionNumber={detail.versionNumber}
            publishedVersion={publishedVersion}
            dirty={dirty}
            isBusy={isBusy}
            isPublishing={publishMutation.isPending}
            onDelete={onDelete}
            onOpenCheckpoint={openCheckpoint}
            onDescriptionChange={changeDescription}
            onPublish={() => void publishDraft()}
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
                  번호는 검사 지점 ID이며, 탭 순서는 실제 요청 실행 순서입니다.
                </small>
                <strong>
                  노드 {checkpointGraph.nodes.length}개
                </strong>
              </div>

              {!readOnly ? (
                <>
                  <div
                    className={styles.nodeCatalog}
                    aria-label={`${checkpointMeta[activeTab].label} 노드 카탈로그`}
                  >
                    <div>
                      {catalogForCheckpoint(activeTab).map((item) => (
                        <button
                          key={item.type}
                          className={
                            item.category === "액션 통제"
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
                      연결할 수 없음: {connectionRejection}
                    </p>
                  ) : null}
                </>
              ) : null}

              <div
                className={styles.canvas}
                aria-label={`${checkpointMeta[activeTab].label} 검사 지점 그래프 편집기`}
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
                  ariaLabelConfig={flowAriaLabelConfig}
                  aria-label={`${checkpointMeta[activeTab].index} ${checkpointMeta[activeTab].label} 가드레일 그래프`}
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
                    <strong>이 검사 지점에 노드가 없습니다</strong>
                    <p>
                      {readOnly
                        ? "이 발행본은 해당 검사 지점을 검사하지 않습니다."
                        : "카탈로그에서 사용할 노드 유형을 선택해 시작하세요."}
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
          onClose={closeTestDrawer}
        />
      ) : null}

      {isChoosingTemplate ? (
        <TemplatePicker
          onApply={applyTemplate}
          onClose={() => setIsChoosingTemplate(false)}
        />
      ) : null}

      {pendingDestructiveAction?.kind === "node" ? (
        <ConfirmDialog
          id="delete-guardrail-node"
          eyebrow="그래프 노드 삭제"
          title={`${pendingDestructiveAction.label} 노드를 삭제할까요?`}
          description={
            <p>
              노드 <code>{pendingDestructiveAction.nodeId}</code>와 연결을 저장하지
              않은 현재 초안에서 모두 삭제합니다.
            </p>
          }
          cancelLabel="노드 유지"
          confirmLabel="노드 삭제"
          onClose={() => setPendingDestructiveAction(null)}
          onConfirm={() =>
            confirmNodeDeletion(pendingDestructiveAction.nodeId)
          }
        />
      ) : null}

      {pendingDestructiveAction?.kind === "template" ? (
        <ConfirmDialog
          id="replace-guardrail-template"
          eyebrow="초안 그래프 교체"
          title={`${pendingDestructiveAction.template.name} 템플릿을 사용할까요?`}
          description={
            <p>
              현재 노드와 연결을 이 템플릿으로 교체합니다. 저장하기 전에 결과를
              확인할 수 있지만 편집기에서 교체를 되돌릴 수는 없습니다.
            </p>
          }
          cancelLabel="현재 그래프 유지"
          confirmLabel="그래프 교체"
          onClose={() => setPendingDestructiveAction(null)}
          onConfirm={() =>
            replaceWithTemplate(pendingDestructiveAction.template)
          }
        />
      ) : null}

      {authenticationError ? (
        <ConfirmDialog
          id="reauthenticate-draft"
          eyebrow="세션 만료"
          title="저장하지 않은 초안을 유지하고 있습니다"
          description={
            <p>
              세션을 자동으로 갱신하지 못했습니다. 이 화면에서 초안을 계속
              확인하거나 다시 로그인해 현재 그래프를 복원한 뒤 돌아오세요.
            </p>
          }
          cancelLabel="초안 계속 확인"
          confirmLabel="로그인 후 초안 복원"
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

    const message =
      "초안에서 나갈까요? 저장하지 않은 설명과 그래프 변경 내용이 사라집니다.";
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

function actionLabel(action: GuardrailTestResult["overallAction"]): string {
  if (action === "block") return "차단";
  if (action === "mask") return "마스킹";
  return "허용";
}
