"use client";

import { useState } from "react";

import {
  modelStrictnesses,
  type Checkpoint,
  type GuardrailNode,
  type ModelStrictness,
} from "@/src/entities/guardrail";

import {
  checkpointMeta,
  incomingRange,
  nodeCatalogByType,
} from "../model/catalog";
import {
  connectionError,
  hasUpstreamNodeType,
} from "../model/connections";
import type { EditorGraph, GuardrailFlowNode } from "../model/graph-mapper";
import styles from "./guardrail-editor.module.css";

const strictnessLabels: Record<ModelStrictness, string> = {
  strict: "strict · 엄격",
  balanced: "balanced · 균형",
  lenient: "lenient · 관대",
};

export function NodeInspector({
  graph,
  selectedNode,
  readOnly,
  onSelect,
  onConfigChange,
  onDelete,
  onConnect,
  onRemoveEdge,
}: {
  graph: EditorGraph;
  selectedNode: GuardrailFlowNode | null;
  readOnly: boolean;
  onSelect: (nodeId: string) => void;
  onConfigChange: (nodeId: string, config: Record<string, unknown>) => void;
  onDelete: (nodeId: string) => void;
  onConnect: (sourceId: string, targetId: string) => void;
  onRemoveEdge: (edgeId: string) => void;
}) {
  return (
    <aside className={styles.inspector} aria-label="노드 인스펙터">
      <div className={styles.inspectorHeader}>
        <p>그래프 인스펙터</p>
        <strong>노드 {graph.nodes.length}개</strong>
      </div>

      <div className={styles.nodeRoster}>
        <p>노드 목록</p>
        {graph.nodes.length === 0 ? (
          <span>카탈로그에서 노드를 추가해 시작하세요.</span>
        ) : (
          <div>
            {graph.nodes.map((node) => (
              <button
                key={node.id}
                className={
                  node.id === selectedNode?.id
                    ? styles.activeRosterNode
                    : undefined
                }
                type="button"
                onClick={() => onSelect(node.id)}
              >
                <span>{checkpointMeta[node.data.checkpoint].index}</span>
                <strong>
                  {nodeCatalogByType[node.data.domainNode.type].label}
                </strong>
                {node.data.validationMessage ? (
                  <i aria-label="검증 오류">!</i>
                ) : null}
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedNode ? (
        <SelectedNodeInspector
          key={selectedNode.id}
          graph={graph}
          node={selectedNode}
          readOnly={readOnly}
          onConfigChange={onConfigChange}
          onDelete={onDelete}
          onConnect={onConnect}
          onRemoveEdge={onRemoveEdge}
        />
      ) : (
        <div className={styles.inspectorEmpty}>
          <span aria-hidden="true">↖</span>
          <h2>노드를 선택하세요</h2>
          <p>
            여기서 노드와 연결을 설정하세요. 정밀하게 드래그하지 않아도 모든
            작업을 수행할 수 있습니다.
          </p>
        </div>
      )}
    </aside>
  );
}

function SelectedNodeInspector({
  graph,
  node,
  readOnly,
  onConfigChange,
  onDelete,
  onConnect,
  onRemoveEdge,
}: {
  graph: EditorGraph;
  node: GuardrailFlowNode;
  readOnly: boolean;
  onConfigChange: (nodeId: string, config: Record<string, unknown>) => void;
  onDelete: (nodeId: string) => void;
  onConnect: (sourceId: string, targetId: string) => void;
  onRemoveEdge: (edgeId: string) => void;
}) {
  const [targetId, setTargetId] = useState("");
  const domainNode = node.data.domainNode;
  const catalog = nodeCatalogByType[domainNode.type];
  const incoming = graph.edges.filter((edge) => edge.target === node.id);
  const outgoing = graph.edges.filter((edge) => edge.source === node.id);
  const availableTargets = graph.nodes.filter(
    (target) => !connectionError(graph, node.id, target.id),
  );
  const range = incomingRange(domainNode.type);
  const modelContributesToVerdict =
    domainNode.type === "verdict" &&
    hasUpstreamNodeType(graph, domainNode.id, "model");

  function setConfig(key: string, value: unknown) {
    onConfigChange(domainNode.id, { ...domainNode.config, [key]: value });
  }

  function replaceConfig(config: Record<string, unknown>) {
    onConfigChange(domainNode.id, config);
  }

  return (
    <div className={styles.selectedInspector}>
      <div className={styles.selectedTitle}>
        <div>
          <p>{catalog.category}</p>
          <h2>{catalog.label}</h2>
        </div>
        <span>{checkpointMeta[node.data.checkpoint].index}</span>
      </div>
      <code className={styles.nodeId}>{domainNode.id}</code>

      {node.data.validationMessage ? (
        <div className={styles.nodeError} role="alert">
          <strong>노드 검증</strong>
          <span>{node.data.validationMessage}</span>
        </div>
      ) : null}

      <fieldset disabled={readOnly} className={styles.configFields}>
        <legend>설정</legend>
        <ConfigFields
          node={domainNode}
          checkpoint={node.data.checkpoint}
          setConfig={setConfig}
          replaceConfig={replaceConfig}
          modelContributesToVerdict={modelContributesToVerdict}
        />
      </fieldset>

      <section
        className={styles.connections}
        aria-labelledby={`connections-${node.id}`}
      >
        <div className={styles.sectionTitle}>
          <h3 id={`connections-${node.id}`}>연결</h3>
          <span>
            입력 {incoming.length}개
            {range.max === null ? ` · 최소 ${range.min}개` : ` · 필요 ${range.min}개`}
          </span>
        </div>

        {incoming.length > 0 || outgoing.length > 0 ? (
          <ul className={styles.edgeList}>
            {incoming.map((edge) => (
              <EdgeItem
                key={edge.id}
                label={`시작 ${edge.source}`}
                edgeId={edge.id}
                readOnly={readOnly}
                onRemove={onRemoveEdge}
              />
            ))}
            {outgoing.map((edge) => (
              <EdgeItem
                key={edge.id}
                label={`도착 ${edge.target}`}
                edgeId={edge.id}
                readOnly={readOnly}
                onRemove={onRemoveEdge}
              />
            ))}
          </ul>
        ) : (
          <p className={styles.noConnections}>아직 연결이 없습니다.</p>
        )}

        {!readOnly && availableTargets.length > 0 ? (
          <div className={styles.connectionForm}>
            <label>
              <span>출력 연결 대상</span>
              <select
                value={targetId}
                onChange={(event) => setTargetId(event.target.value)}
              >
                <option value="">노드 선택</option>
                {availableTargets.map((target) => (
                  <option key={target.id} value={target.id}>
                    {nodeCatalogByType[target.data.domainNode.type].label} ·{" "}
                    {target.id}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!targetId}
              onClick={() => {
                if (!targetId) return;
                onConnect(node.id, targetId);
                setTargetId("");
              }}
            >
              연결 추가
            </button>
          </div>
        ) : null}
      </section>

      {!readOnly ? (
        <button
          className={styles.deleteNodeButton}
          type="button"
          onClick={() => onDelete(node.id)}
        >
          노드 삭제
        </button>
      ) : null}
    </div>
  );
}

function ConfigFields({
  node,
  checkpoint,
  setConfig,
  replaceConfig,
  modelContributesToVerdict,
}: {
  node: GuardrailNode;
  checkpoint: Checkpoint;
  setConfig: (key: string, value: unknown) => void;
  replaceConfig: (config: Record<string, unknown>) => void;
  modelContributesToVerdict: boolean;
}) {
  switch (node.type) {
    case "extract": {
      const from = extractSource(node.config);
      const at = checkpointValue(node.config.at) ?? checkpointValue(node.config.checkpoint) ?? checkpoint;
      const setExtractConfig = (key: "from" | "at", value: string) => {
        const next = { ...node.config, from, at, [key]: value };
        delete next.checkpoint;
        replaceConfig(next);
      };
      return (
        <>
          <label>
            <span>추출 대상</span>
            <select
              value={from}
              onChange={(event) => setExtractConfig("from", event.target.value)}
            >
              <option value="user_text">user_text · 사용자 텍스트</option>
              <option value="tool_result">tool_result · 툴 결과</option>
              <option value="trusted_text">trusted_text · 신뢰 텍스트</option>
              <option value="output_text">output_text · 출력 텍스트</option>
            </select>
          </label>
          <label>
            <span>검사 지점</span>
            <select
              value={at}
              onChange={(event) => setExtractConfig("at", event.target.value)}
            >
              <option value="input">① input · 입력</option>
              <option value="tool_result">② tool_result · 툴 결과</option>
              <option value="output">③ output · 출력</option>
              <option value="tool_call">④ tool_call · 툴 호출</option>
            </select>
          </label>
        </>
      );
    }
    case "tool_extract": {
      const selector = toolSelector(node.config.tools);
      const field = stringValue(node.config.field);
      const fieldMode = field === "name" || field === "arguments" ? field : "path";
      return (
        <>
          <FixedCheckpoint checkpoint="tool_call" />
          <label>
            <span>툴 선택</span>
            <select
              value={selector.mode}
              onChange={(event) =>
                setConfig("tools", {
                  [event.target.value]: selector.names,
                })
              }
            >
              <option value="exclude">exclude · 제외</option>
              <option value="include">include · 포함</option>
            </select>
            <small>
              {selector.mode === "exclude"
                ? "기본값 · 목록에 없는 툴이 검사 대상입니다."
                : "목록에 있는 툴만 검사 대상입니다."}
            </small>
          </label>
          <label>
            <span>툴 이름 목록</span>
            <textarea
              value={selector.names.join("\n")}
              onChange={(event) =>
                setConfig("tools", {
                  [selector.mode]: splitToolNames(event.target.value),
                })
              }
              rows={5}
              spellCheck={false}
              placeholder={"read_file\nweb_search"}
            />
          </label>
          <label>
            <span>필드</span>
            <select
              value={fieldMode}
              onChange={(event) => {
                const value = event.target.value;
                setConfig("field", value === "path" ? "" : value);
              }}
            >
              <option value="name">name · 툴 이름</option>
              <option value="arguments">arguments · 전체 인수</option>
              <option value="path">경로 직접 입력</option>
            </select>
          </label>
          {fieldMode === "path" ? (
            <label>
              <span>인수 경로</span>
              <input
                value={field}
                onChange={(event) => setConfig("field", event.target.value)}
                spellCheck={false}
                aria-invalid={!field.trim()}
                placeholder="to · payload.meta.id · cc[*]"
              />
              {!field.trim() ? (
                <small className={styles.fieldError} role="alert">
                  인수 경로는 필수입니다.
                </small>
              ) : null}
            </label>
          ) : null}
        </>
      );
    }
    case "regex":
      return (
        <label>
          <span>RE2 패턴</span>
          <textarea
            value={stringValue(node.config.pattern)}
            onChange={(event) => setConfig("pattern", event.target.value)}
            rows={4}
            spellCheck={false}
            placeholder="(?i)secret"
          />
          <small>저장할 때 게이트웨이가 패턴 문법을 검증합니다.</small>
        </label>
      );
    case "model": {
      const policy = stringValue(node.config.policy);
      return (
        <>
          <label>
            <span>자연어 정책 질의</span>
            <textarea
              value={policy}
              onChange={(event) => setConfig("policy", event.target.value)}
              rows={7}
              required
              aria-invalid={!policy.trim()}
              placeholder="이 텍스트가 개인의 민감한 건강 정보를 노출하는가?"
            />
            {!policy.trim() ? (
              <small className={styles.fieldError} role="alert">
                정책 질의는 필수입니다.
              </small>
            ) : (
              <small>모델이 위반 여부를 판단할 수 있는 질문으로 작성하세요.</small>
            )}
          </label>
          <label>
            <span>판정 엄격도</span>
            <select
              value={stringValue(node.config.strictness) || "strict"}
              onChange={(event) => setConfig("strictness", event.target.value)}
            >
              {modelStrictnesses.map((strictness) => (
                <option key={strictness} value={strictness}>
                  {strictnessLabels[strictness]}
                </option>
              ))}
            </select>
          </label>
          <FixedCheckpoint checkpoint={checkpoint} />
        </>
      );
    }
    case "transform":
      return (
        <label>
          <span>변환 방식</span>
          <select
            value={stringValue(node.config.op) || "lower"}
            onChange={(event) => setConfig("op", event.target.value)}
          >
            <option value="lower">소문자로 변환</option>
            <option value="strip">앞뒤 공백 제거</option>
          </select>
        </label>
      );
    case "not":
      return <span>설정 없음</span>;
    case "verdict":
      return (
        <>
          <label>
            <span>판정</span>
            <select
              value={stringValue(node.config.action) || "block"}
              onChange={(event) => setConfig("action", event.target.value)}
            >
              <option value="block">차단</option>
              <option value="mask" disabled={modelContributesToVerdict}>
                마스킹
              </option>
              <option value="allow">허용</option>
            </select>
            {modelContributesToVerdict ? (
              <small>모델 판정은 위치를 제공하지 않아 마스킹할 수 없습니다.</small>
            ) : null}
          </label>
          <label>
            <span>입력 조합</span>
            <select
              value={stringValue(node.config.combine) || "any"}
              onChange={(event) => setConfig("combine", event.target.value)}
            >
              <option value="any">하나라도 충족(OR)</option>
              <option value="all">모두 충족(AND)</option>
            </select>
            <small>연결된 Check가 판정을 발동하는 방식을 선택합니다.</small>
          </label>
        </>
      );
  }
}

function FixedCheckpoint({ checkpoint }: { checkpoint: Checkpoint }) {
  return (
    <label>
      <span>검사 지점</span>
      <input
        value={`${checkpointMeta[checkpoint].index} ${checkpointMeta[checkpoint].label}`}
        readOnly
      />
    </label>
  );
}

function EdgeItem({
  label,
  edgeId,
  readOnly,
  onRemove,
}: {
  label: string;
  edgeId: string;
  readOnly: boolean;
  onRemove: (edgeId: string) => void;
}) {
  return (
    <li>
      <code>{label}</code>
      {!readOnly ? (
        <button
          type="button"
          onClick={() => onRemove(edgeId)}
          aria-label={`연결 삭제: ${label}`}
        >
          ×
        </button>
      ) : null}
    </li>
  );
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function splitToolNames(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((name) => name.trim())
    .filter(Boolean);
}

function extractSource(config: Record<string, unknown>): string {
  if (
    config.from === "user_text" ||
    config.from === "tool_result" ||
    config.from === "trusted_text" ||
    config.from === "output_text"
  ) {
    return config.from;
  }
  if (config.checkpoint === "input") return "user_text";
  if (config.checkpoint === "output") return "output_text";
  return "tool_result";
}

function checkpointValue(value: unknown): Checkpoint | null {
  return value === "input" ||
    value === "tool_result" ||
    value === "tool_call" ||
    value === "output"
    ? value
    : null;
}

function toolSelector(value: unknown): {
  mode: "exclude" | "include";
  names: string[];
} {
  if (isRecord(value) && Array.isArray(value.include)) {
    return {
      mode: "include",
      names: value.include.filter((name): name is string => typeof name === "string"),
    };
  }
  return {
    mode: "exclude",
    names:
      isRecord(value) && Array.isArray(value.exclude)
        ? value.exclude.filter((name): name is string => typeof name === "string")
        : [],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
