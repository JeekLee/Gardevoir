import type { ReactNode } from "react";

import type {
  GuardrailAction,
  GuardrailNode,
  GuardrailTestCheckpointName,
} from "@/src/entities/guardrail";

import {
  actionForCheckpoint,
  blockedCheckpoint,
  diffText,
  firedNodeTraces,
  overallAction,
  type DiffPart,
  type PlaygroundRun,
} from "../model/playground";
import styles from "./playground.module.css";

const checkpoints: Array<{
  key: GuardrailTestCheckpointName;
  index: string;
  label: string;
}> = [
  { key: "input", index: "①", label: "입력" },
  { key: "toolResult", index: "②", label: "툴 결과" },
  { key: "output", index: "③", label: "출력" },
  { key: "toolCall", index: "④", label: "툴 호출" },
];

const nodeLabels: Record<GuardrailNode["type"], string> = {
  extract: "텍스트 추출",
  transform: "텍스트 변환",
  regex: "정규식",
  model: "MODEL 검사",
  taint: "오염 추적",
  side_effect: "부작용 툴",
  provenance: "인수 출처",
  verdict: "판정",
};

export function PlaygroundResult({ run }: { run: PlaygroundRun }) {
  const action = overallAction(run);
  const stoppedAt = blockedCheckpoint(run);
  const planned = run.mode === "dry-run" && action !== run.result.overallAction;
  const tiers = reachedTiers(run);
  const maskableText = checkpoints.flatMap(({ key, label }) => {
    const checkpoint = run.result.checkpoints[key];
    return checkpoint.rawText !== null &&
      (checkpoint.rawText || checkpoint.appliedText)
      ? [{ key, label, checkpoint }]
      : [];
  });
  const traces = checkpoints.flatMap(({ key, label }) =>
    firedNodeTraces(
      run.graph,
      run.result.checkpoints[key].checksFired,
      key,
      run.result.checkpoints[key].rawText,
    ).map((trace) => ({ checkpoint: key, checkpointLabel: label, trace })),
  );
  const evidence = checkpoints.flatMap(({ key, label }) =>
    run.result.checkpoints[key].evidence.map((item, index) => ({
      key: `${key}-${index}`,
      checkpointLabel: label,
      item,
    })),
  );
  const blockReason = stoppedAt
    ? blockReasonFor(run, stoppedAt)
    : run.result.blockedReason;

  return (
    <section className={styles.result} aria-labelledby="playground-result-title">
      <header className={styles.resultHeader}>
        <div className={styles.resultAction}>
          <span>판정</span>
          <h2 id="playground-result-title" className={styles[action]}>
            {actionLabel(action, planned)}
          </h2>
        </div>
        <dl className={styles.resultMeta}>
          <div>
            <dt>가드레일</dt>
            <dd>
              {run.result.guardrail} · v{run.result.version}
            </dd>
          </div>
          <div>
            <dt>모델</dt>
            <dd>{run.result.model}</dd>
          </div>
          <div>
            <dt>모드</dt>
            <dd>{run.mode}</dd>
          </div>
          <div>
            <dt>티어</dt>
            <dd>{tiers}</dd>
          </div>
          <div>
            <dt>지연</dt>
            <dd>{run.result.latencyMs.toFixed(1)} ms</dd>
          </div>
        </dl>
      </header>

      <section className={styles.resultSection} aria-labelledby="flow-title">
        <SectionHeader id="flow-title">체크포인트 흐름</SectionHeader>
        <ol className={styles.flow}>
          <CheckpointStep run={run} checkpointKey="input" index="①" label="입력" />
          <CheckpointStep
            run={run}
            checkpointKey="toolResult"
            index="②"
            label="툴 결과"
          />
          <UpstreamStep run={run} stoppedAt={stoppedAt} />
          <CheckpointStep run={run} checkpointKey="output" index="③" label="출력" />
          <CheckpointStep
            run={run}
            checkpointKey="toolCall"
            index="④"
            label="툴 호출"
          />
        </ol>
      </section>

      {stoppedAt ? (
        <section
          className={`${styles.blockNotice} ${planned ? styles.plannedNotice : ""}`}
          aria-label={planned ? "dry-run 차단 예정" : "차단 정보"}
        >
          <strong>{planned ? "차단 예정 · dry-run" : "차단됨"}</strong>
          <dl>
            <div>
              <dt>위치</dt>
              <dd>{checkpointLabel(stoppedAt)}</dd>
            </div>
            <div>
              <dt>이유</dt>
              <dd>{blockReason || "판정 노드"}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      {traces.length > 0 ? (
        <section className={styles.resultSection} aria-labelledby="nodes-title">
          <SectionHeader id="nodes-title">발화 노드 · 상류 체인</SectionHeader>
          <div className={styles.traceList}>
            {traces.map(({ checkpoint, checkpointLabel, trace }) => (
              <article
                className={styles.trace}
                key={`${checkpoint}-${trace.verdict.id}-${trace.code}`}
              >
                <header>
                  <span>{checkpointLabel}</span>
                  <code>{trace.code}</code>
                </header>
                <div className={styles.nodeChain}>
                  {trace.upstream.map((node) => (
                    <NodeCard key={node.id} node={node} role="상류" />
                  ))}
                  <NodeCard node={trace.verdict} role="발화" fired />
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {maskableText.length > 0 ? (
        <section className={styles.resultSection} aria-labelledby="mask-title">
          <SectionHeader id="mask-title">검사 텍스트</SectionHeader>
          <div className={styles.diffList}>
            {maskableText.map(({ key, label, checkpoint }) => (
              <TextDiffPair
                key={key}
                title={label}
                raw={checkpoint.rawText ?? ""}
                applied={checkpoint.appliedText ?? ""}
                rawLabel="rawText"
                appliedLabel="appliedText"
              />
            ))}
          </div>
          {run.result.unmaskable > 0 ? (
            <p className={styles.unmaskable} role="status">
              마스킹 불가 {run.result.unmaskable}건
            </p>
          ) : null}
        </section>
      ) : null}

      {evidence.length > 0 ? (
        <section className={styles.resultSection} aria-labelledby="evidence-title">
          <SectionHeader id="evidence-title">근거</SectionHeader>
          <ul className={styles.evidenceList}>
            {evidence.map(({ key, checkpointLabel, item }) => (
              <li key={key}>
                <span>{checkpointLabel}</span>
                <strong>{item.tool}</strong>
                <code>{item.arguments.join(", ") || "인수 없음"}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className={styles.resultSection} aria-labelledby="response-title">
        <SectionHeader id="response-title">최종 응답</SectionHeader>
        <TextDiffPair
          title="응답 본문"
          raw={run.result.rawContent}
          applied={run.result.appliedContent}
          rawLabel="rawContent"
          appliedLabel="appliedContent"
        />
        {run.result.toolCalls.length > 0 ? (
          <div className={styles.toolCalls}>
            <span>toolCalls</span>
            <pre>{JSON.stringify(run.result.toolCalls, null, 2)}</pre>
          </div>
        ) : null}
      </section>
    </section>
  );
}

function CheckpointStep({
  run,
  checkpointKey,
  index,
  label,
}: {
  run: PlaygroundRun;
  checkpointKey: GuardrailTestCheckpointName;
  index: string;
  label: string;
}) {
  const checkpoint = run.result.checkpoints[checkpointKey];
  const action = actionForCheckpoint(
    run.graph,
    checkpoint,
    run.mode,
    checkpointKey,
  );
  const planned = run.mode === "dry-run" && action !== checkpoint.action;
  const stopped = run.result.blockedAt === checkpointKey;
  return (
    <li
      className={`${styles.flowStep} ${styles[action]} ${
        stopped ? styles.stoppedStep : ""
      }`}
    >
      <span className={styles.flowIndex}>{index}</span>
      <strong>{label}</strong>
      <small>
        {!checkpoint.ran
          ? "미실행"
          : actionLabel(action, planned)}
      </small>
      <dl>
        <div>
          <dt>tier</dt>
          <dd>{checkpoint.ran ? tierLabel(checkpoint.tier) : "—"}</dd>
        </div>
        <div>
          <dt>발화</dt>
          <dd>{checkpoint.checksFired.length}</dd>
        </div>
      </dl>
      {stopped ? <b>중단</b> : null}
    </li>
  );
}

function UpstreamStep({
  run,
  stoppedAt,
}: {
  run: PlaygroundRun;
  stoppedAt: GuardrailTestCheckpointName | null;
}) {
  const skipped =
    run.mode === "enforce" &&
    (stoppedAt === "input" || stoppedAt === "toolResult");
  return (
    <li className={`${styles.flowStep} ${styles.upstreamStep}`}>
      <span className={styles.flowIndex}>↗</span>
      <strong>업스트림</strong>
      <small>{skipped ? "미호출" : "호출"}</small>
      <dl>
        <div>
          <dt>mode</dt>
          <dd>{run.mode}</dd>
        </div>
      </dl>
    </li>
  );
}

function NodeCard({
  node,
  role,
  fired = false,
}: {
  node: GuardrailNode;
  role: string;
  fired?: boolean;
}) {
  const facts = nodeFacts(node);
  const configuredLabel = node.config.label;
  const label =
    typeof configuredLabel === "string" && configuredLabel.trim()
      ? configuredLabel
      : nodeLabels[node.type];
  return (
    <div className={`${styles.nodeCard} ${fired ? styles.firedNode : ""}`}>
      <header>
        <span>{role}</span>
        <code>{node.type}</code>
      </header>
      <strong>{label}</strong>
      <dl>
        <div>
          <dt>ID</dt>
          <dd>{node.id}</dd>
        </div>
        {facts.map((fact) => (
          <div key={fact.label}>
            <dt>{fact.label}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function TextDiffPair({
  title,
  raw,
  applied,
  rawLabel,
  appliedLabel,
}: {
  title: string;
  raw: string;
  applied: string;
  rawLabel: string;
  appliedLabel: string;
}) {
  const diff = diffText(raw, applied);
  return (
    <article className={styles.diffPair}>
      <header>
        <strong>{title}</strong>
        <span className={diff.changed ? styles.changed : styles.unchanged}>
          {diff.changed ? "변경" : "동일"}
        </span>
      </header>
      <div>
        <DiffBlock label={rawLabel} parts={diff.raw} kind="raw" />
        <DiffBlock label={appliedLabel} parts={diff.applied} kind="applied" />
      </div>
    </article>
  );
}

function DiffBlock({
  label,
  parts,
  kind,
}: {
  label: string;
  parts: DiffPart[];
  kind: "raw" | "applied";
}) {
  return (
    <section className={styles.diffBlock}>
      <span>{label}</span>
      <pre>
        {parts.length === 0 ? "(없음)" : null}
        {parts.map((part, index) =>
          part.changed ? (
            <mark
              className={kind === "raw" ? styles.removedText : styles.appliedText}
              key={`${index}-${part.text}`}
            >
              {part.text || "∅"}
            </mark>
          ) : (
            <span key={`${index}-${part.text}`}>{part.text}</span>
          ),
        )}
      </pre>
    </section>
  );
}

function SectionHeader({ id, children }: { id: string; children: ReactNode }) {
  return <h3 id={id}>{children}</h3>;
}

function blockReasonFor(
  run: PlaygroundRun,
  checkpoint: GuardrailTestCheckpointName,
): string | null {
  if (run.result.blockedReason) return run.result.blockedReason;
  return (
    firedNodeTraces(
      run.graph,
      run.result.checkpoints[checkpoint].checksFired,
      checkpoint,
      run.result.checkpoints[checkpoint].rawText,
    ).find(({ verdict }) => verdict.config.action === "block")?.code ?? null
  );
}

function reachedTiers(run: PlaygroundRun): string {
  const tiers = new Set(
    checkpoints
      .map(({ key }) => run.result.checkpoints[key].tier)
      .filter(Boolean)
      .map(tierLabel),
  );
  return tiers.size > 0 ? [...tiers].join(" → ") : "—";
}

function nodeFacts(node: GuardrailNode): Array<{ label: string; value: string }> {
  const config = node.config;
  switch (node.type) {
    case "extract":
    case "taint":
      return textFact("checkpoint", config.checkpoint);
    case "transform":
      return textFact("op", config.op);
    case "regex":
      return textFact("pattern", config.pattern);
    case "model":
      return [
        ...textFact("policy", config.policy),
        ...textFact("strictness", config.strictness),
        ...textFact("checkpoint", config.checkpoint),
      ];
    case "side_effect":
      return [
        ...textFact("checkpoint", config.checkpoint),
        {
          label: "read_only",
          value: Array.isArray(config.read_only)
            ? config.read_only.filter((item) => typeof item === "string").join(", ") || "—"
            : "—",
        },
      ];
    case "provenance":
      return [
        ...textFact("checkpoint", config.checkpoint),
        {
          label: "min_length",
          value: typeof config.min_length === "number" ? String(config.min_length) : "8",
        },
      ];
    case "verdict":
      return [
        ...textFact("action", config.action),
        ...textFact("combine", config.combine ?? "any"),
      ];
  }
}

function textFact(label: string, value: unknown) {
  return typeof value === "string" && value
    ? [{ label, value }]
    : [];
}

function actionLabel(action: GuardrailAction, planned = false): string {
  if (action === "block") return planned ? "차단 예정" : "차단";
  if (action === "mask") return planned ? "마스킹 예정" : "마스킹";
  return "허용";
}

function checkpointLabel(checkpoint: GuardrailTestCheckpointName): string {
  return checkpoints.find(({ key }) => key === checkpoint)?.label ?? checkpoint;
}

function tierLabel(tier: string): string {
  if (tier === "rule" || tier === "rules") return "rules";
  if (tier === "model") return "model";
  return tier || "—";
}
