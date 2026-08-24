import type { Node, NodeProps } from "@xyflow/react";

import type { Checkpoint } from "@/src/entities/guardrail";

import { checkpointMeta } from "../model/catalog";
import styles from "./guardrail-editor.module.css";

export type LaneNodeData = {
  checkpoint: Checkpoint;
} & Record<string, unknown>;

export type LaneFlowNode = Node<LaneNodeData, "checkpointLane">;

export function CheckpointLane({ data }: NodeProps<LaneFlowNode>) {
  const meta = checkpointMeta[data.checkpoint];
  const isActionLane =
    data.checkpoint === "tool_result" || data.checkpoint === "tool_call";

  return (
    <section
      className={`${styles.lane} ${isActionLane ? styles.actionLane : ""}`}
      aria-label={`${meta.label} checkpoint lane`}
    >
      <header>
        <span>{meta.index}</span>
        <div>
          <strong>{meta.label}</strong>
          <small>{meta.shortLabel}</small>
        </div>
      </header>
      <p>{meta.description}</p>
    </section>
  );
}
