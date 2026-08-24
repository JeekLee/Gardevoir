import { Handle, Position, type NodeProps } from "@xyflow/react";

import { canEmit, checkpointMeta, incomingRange, nodeCatalogByType, nodeSummary } from "../model/catalog";
import type { GuardrailFlowNode } from "../model/graph-mapper";
import styles from "./guardrail-editor.module.css";

export function GuardrailNodeCard({ data, selected }: NodeProps<GuardrailFlowNode>) {
  const { domainNode } = data;
  const catalog = nodeCatalogByType[domainNode.type];
  const acceptsInput = incomingRange(domainNode.type).max !== 0;
  const hasError = Boolean(data.validationMessage);
  const actionNode =
    domainNode.type === "taint" ||
    domainNode.type === "side_effect" ||
    domainNode.type === "provenance";

  return (
    <article
      className={`${styles.graphNode} ${selected ? styles.selectedNode : ""} ${
        hasError ? styles.invalidNode : ""
      } ${actionNode ? styles.actionControlNode : ""}`}
      aria-label={`${catalog.label} node, ${checkpointMeta[data.checkpoint].label} checkpoint${
        hasError ? `, error: ${data.validationMessage}` : ""
      }`}
    >
      {acceptsInput ? (
        <Handle
          className={styles.targetHandle}
          type="target"
          position={Position.Left}
          aria-label={`Connect input to ${catalog.label}`}
        />
      ) : null}
      <div className={styles.nodeHeading}>
        <span className={styles.nodeType}>{catalog.category}</span>
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
          aria-label={`Connect output from ${catalog.label}`}
        />
      ) : null}
    </article>
  );
}
