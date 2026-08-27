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
import { connectionError } from "../model/connections";
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

  function setConfig(key: string, value: unknown) {
    onConfigChange(domainNode.id, { ...domainNode.config, [key]: value });
  }

  function removeConfig(key: string) {
    const next = { ...domainNode.config };
    delete next[key];
    onConfigChange(domainNode.id, next);
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
          removeConfig={removeConfig}
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
  removeConfig,
}: {
  node: GuardrailNode;
  checkpoint: Checkpoint;
  setConfig: (key: string, value: unknown) => void;
  removeConfig: (key: string) => void;
}) {
  switch (node.type) {
    case "extract":
    case "taint":
      return <FixedCheckpoint checkpoint={checkpoint} />;
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
    case "length":
      return (
        <NumberField
          label="최대 글자 수"
          value={numberValue(node.config.max_chars, 1_000)}
          onChange={(value) => setConfig("max_chars", value)}
        />
      );
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
    case "verdict":
      return (
        <label>
          <span>판정</span>
          <select
            value={stringValue(node.config.action) || "block"}
            onChange={(event) => setConfig("action", event.target.value)}
          >
            <option value="block">차단</option>
            <option value="mask">마스킹</option>
            <option value="allow">허용</option>
          </select>
        </label>
      );
    case "all":
      return <p className={styles.noConfig}>이 노드는 설정할 항목이 없습니다.</p>;
    case "side_effect":
      return (
        <>
          <FixedCheckpoint checkpoint={checkpoint} />
          <label>
            <span>읽기 전용 툴</span>
            <textarea
              value={stringList(node.config.read_only).join("\n")}
              onChange={(event) =>
                setConfig("read_only", splitToolNames(event.target.value))
              }
              rows={5}
              spellCheck={false}
              placeholder={"read_file\nweb_search"}
            />
            <small>
              한 줄에 툴 하나를 입력하세요. 목록에 없는 툴은 부작용이 있는
              것으로 처리합니다.
            </small>
          </label>
        </>
      );
    case "provenance":
      return (
        <>
          <FixedCheckpoint checkpoint={checkpoint} />
          <label>
            <span>최소 인수 길이</span>
            <input
              type="number"
              min={1}
              step={1}
              value={optionalNumberValue(node.config.min_length)}
              onChange={(event) => {
                if (!event.target.value) {
                  removeConfig("min_length");
                  return;
                }
                setConfig("min_length", Number(event.target.value));
              }}
              placeholder="8"
            />
            <small>비워 두면 게이트웨이 기본값인 8자를 사용합니다.</small>
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

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <input
        type="number"
        min={1}
        step={1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
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

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

function optionalNumberValue(value: unknown): number | "" {
  return typeof value === "number" ? value : "";
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : [];
}

function splitToolNames(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((name) => name.trim())
    .filter(Boolean);
}
