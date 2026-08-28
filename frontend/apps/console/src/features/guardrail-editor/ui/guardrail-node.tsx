import { Handle, Position, type NodeProps } from "@xyflow/react";

import {
  canEmit,
  checkpointMeta,
  incomingRange,
  nodeCatalogByType,
  nodeSummary,
} from "../model/catalog";
import type { GuardrailFlowNode } from "../model/graph-mapper";
import styles from "./guardrail-editor.module.css";

export function GuardrailNodeCard({
  data,
  selected,
}: NodeProps<GuardrailFlowNode>) {
  const { domainNode } = data;
  const catalog = nodeCatalogByType[domainNode.type];
  const acceptsInput = incomingRange(domainNode.type).max !== 0;
  const hasError = Boolean(data.validationMessage);
  const testHighlight = data.testHighlight;
  const actionNode = domainNode.type === "tool_extract";

  return (
    <article
      className={`${styles.graphNode} ${selected ? styles.selectedNode : ""} ${
        hasError ? styles.invalidNode : ""
      } ${actionNode ? styles.actionControlNode : ""} ${
        testHighlight === "fired"
          ? styles.firedTestNode
          : testHighlight === "upstream"
            ? styles.upstreamTestNode
            : ""
      }`}
      aria-label={`${catalog.label} 노드, ${checkpointMeta[data.checkpoint].label} 검사 지점${
        hasError ? `, 오류: ${data.validationMessage}` : ""
      }${testHighlight === "fired" ? ", 최근 테스트에서 발동" : ""}${
        testHighlight === "upstream" ? ", 발동한 판정의 상위 경로" : ""
      }`}
    >
      {acceptsInput ? (
        <Handle
          className={styles.targetHandle}
          type="target"
          position={Position.Left}
          aria-label={`${catalog.label}에 입력 연결`}
        />
      ) : null}
      <div className={styles.nodeHeading}>
        <span className={styles.nodeType}>{catalog.category}</span>
        {testHighlight ? (
          <span className={styles.testHitBadge}>
            {testHighlight === "fired" ? "테스트 발동" : "검사 경로"}
          </span>
        ) : null}
        <span className={styles.nodeCheckpoint}>
          {checkpointMeta[data.checkpoint].index}
        </span>
      </div>
      <strong>{catalog.label}</strong>
      <p title={nodeSummary(domainNode)}>{nodeSummary(domainNode)}</p>
      <code>{domainNode.id}</code>
      {canEmit(domainNode.type) ? (
        <Handle
          className={styles.sourceHandle}
          type="source"
          position={Position.Right}
          aria-label={`${catalog.label}에서 출력 연결`}
        />
      ) : null}
    </article>
  );
}
