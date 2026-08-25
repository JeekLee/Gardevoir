"use client";

import { useState } from "react";

import { type Checkpoint, type GuardrailNode } from "@/src/entities/guardrail";

import {
  checkpointMeta,
  incomingRange,
  nodeCatalogByType,
} from "../model/catalog";
import { connectionError } from "../model/connections";
import type { EditorGraph, GuardrailFlowNode } from "../model/graph-mapper";
import styles from "./guardrail-editor.module.css";

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
    <aside className={styles.inspector} aria-label="Node inspector">
      <div className={styles.inspectorHeader}>
        <p>Graph inspector</p>
        <strong>{graph.nodes.length} nodes</strong>
      </div>

      <div className={styles.nodeRoster}>
        <p>Node list</p>
        {graph.nodes.length === 0 ? (
          <span>Add a node from the catalog to begin.</span>
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
                  <i aria-label="Validation error">!</i>
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
          <h2>Select a node</h2>
          <p>
            Configure nodes and connections here. Every operation remains
            available without precision dragging.
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
      <p className={styles.nodeDescription}>{catalog.description}</p>
      <code className={styles.nodeId}>{domainNode.id}</code>

      {node.data.validationMessage ? (
        <div className={styles.nodeError} role="alert">
          <strong>Gateway validation</strong>
          <span>{node.data.validationMessage}</span>
        </div>
      ) : null}

      <fieldset disabled={readOnly} className={styles.configFields}>
        <legend>Configuration</legend>
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
          <h3 id={`connections-${node.id}`}>Connections</h3>
          <span>
            {incoming.length} input{incoming.length === 1 ? "" : "s"}
            {range.max === null ? ` · min ${range.min}` : ` · expected ${range.min}`}
          </span>
        </div>

        {incoming.length > 0 || outgoing.length > 0 ? (
          <ul className={styles.edgeList}>
            {incoming.map((edge) => (
              <EdgeItem
                key={edge.id}
                label={`From ${edge.source}`}
                edgeId={edge.id}
                readOnly={readOnly}
                onRemove={onRemoveEdge}
              />
            ))}
            {outgoing.map((edge) => (
              <EdgeItem
                key={edge.id}
                label={`To ${edge.target}`}
                edgeId={edge.id}
                readOnly={readOnly}
                onRemove={onRemoveEdge}
              />
            ))}
          </ul>
        ) : (
          <p className={styles.noConnections}>No connections yet.</p>
        )}

        {!readOnly && availableTargets.length > 0 ? (
          <div className={styles.connectionForm}>
            <label>
              <span>Connect output to</span>
              <select
                value={targetId}
                onChange={(event) => setTargetId(event.target.value)}
              >
                <option value="">Choose a node</option>
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
              Add connection
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
          Delete node
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
          <span>RE2 pattern</span>
          <textarea
            value={stringValue(node.config.pattern)}
            onChange={(event) => setConfig("pattern", event.target.value)}
            rows={4}
            spellCheck={false}
            placeholder="(?i)secret"
          />
          <small>Pattern syntax is validated by the gateway when you save.</small>
        </label>
      );
    case "length":
      return (
        <NumberField
          label="Maximum characters"
          value={numberValue(node.config.max_chars, 1_000)}
          onChange={(value) => setConfig("max_chars", value)}
        />
      );
    case "transform":
      return (
        <label>
          <span>Operation</span>
          <select
            value={stringValue(node.config.op) || "lower"}
            onChange={(event) => setConfig("op", event.target.value)}
          >
            <option value="lower">Lowercase</option>
            <option value="strip">Strip whitespace</option>
          </select>
        </label>
      );
    case "verdict":
      return (
        <>
          <label>
            <span>Action</span>
            <select
              value={stringValue(node.config.action) || "block"}
              onChange={(event) => setConfig("action", event.target.value)}
            >
              <option value="block">Block</option>
              <option value="mask">Mask</option>
              <option value="allow">Allow</option>
            </select>
          </label>
          <label>
            <span>Decision role</span>
            <select
              value={stringValue(node.config.decision) || "conclusive"}
              onChange={(event) => setConfig("decision", event.target.value)}
            >
              <option value="conclusive">Conclusive</option>
              <option value="hint">Hint</option>
              <option value="model_only">Model only</option>
            </select>
          </label>
          <label>
            <span>Policy code</span>
            <input
              value={stringValue(node.config.code)}
              onChange={(event) => setConfig("code", event.target.value)}
              placeholder="policy-match"
            />
          </label>
        </>
      );
    case "all":
      return <p className={styles.noConfig}>This node has no configuration.</p>;
    case "side_effect":
      return (
        <>
          <FixedCheckpoint checkpoint={checkpoint} />
          <label>
            <span>Read-only tools</span>
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
              One tool per line. Unlisted tools are treated as side-effecting.
            </small>
          </label>
        </>
      );
    case "provenance":
      return (
        <>
          <FixedCheckpoint checkpoint={checkpoint} />
          <label>
            <span>Minimum argument length</span>
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
            <small>Leave blank to use the gateway default of 8.</small>
          </label>
        </>
      );
  }
}

function FixedCheckpoint({ checkpoint }: { checkpoint: Checkpoint }) {
  return (
    <label>
      <span>Checkpoint</span>
      <input
        value={`${checkpointMeta[checkpoint].index} ${checkpointMeta[checkpoint].label}`}
        readOnly
      />
      <small>체크포인트는 현재 탭에 고정됩니다.</small>
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
          aria-label={`Remove ${label}`}
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
