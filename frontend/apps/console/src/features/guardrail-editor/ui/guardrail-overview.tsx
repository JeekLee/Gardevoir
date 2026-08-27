import Link from "next/link";

import { AppConnectionPanel } from "@/src/entities/api-key";
import {
  guardrailActions,
  type Checkpoint,
} from "@/src/entities/guardrail";

import { checkpointMeta } from "../model/catalog";
import { summarizeCheckpointGraphs } from "../model/checkpoint-view";
import type { EditorGraph } from "../model/graph-mapper";
import styles from "./guardrail-editor.module.css";

const actionLabels = {
  block: "차단",
  mask: "마스킹",
  allow: "허용",
} as const;

export function GuardrailOverview({
  name,
  graph,
  description,
  readOnly,
  versionNumber,
  publishedVersion,
  dirty,
  isBusy,
  isPublishing,
  onDelete,
  onOpenCheckpoint,
  onDescriptionChange,
  onPublish,
  onChooseTemplate,
}: {
  name: string;
  graph: EditorGraph;
  description: string;
  readOnly: boolean;
  versionNumber: number | null;
  publishedVersion: number | null;
  dirty: boolean;
  isBusy: boolean;
  isPublishing: boolean;
  onDelete: () => void;
  onOpenCheckpoint: (checkpoint: Checkpoint) => void;
  onDescriptionChange: (description: string) => void;
  onPublish: () => void;
  onChooseTemplate: () => void;
}) {
  const checkpointSummaries = summarizeCheckpointGraphs(graph);
  const covered = checkpointSummaries.filter((summary) => summary.nodeCount > 0);
  const totalVerdicts = checkpointSummaries.reduce(
    (total, summary) => total + summary.verdictCount,
    0,
  );
  const actionSet = new Set(
    checkpointSummaries.flatMap((summary) => summary.actions),
  );
  const actions = guardrailActions.filter((action) => actionSet.has(action));
  const descriptionId = `guardrail-description-${readOnly ? `v${versionNumber}` : "draft"}`;
  const descriptionHelpId = `${descriptionId}-help`;

  return (
    <div className={styles.overviewGrid}>
      <section
        className={styles.overviewHero}
        aria-label="가드레일 설정"
      >
        <div className={styles.overviewHeading}>
          <div className={styles.overviewDescriptionField}>
            <label htmlFor={descriptionId}>설명</label>
            <textarea
              id={descriptionId}
              className={styles.overviewDescriptionInput}
              value={description}
              onChange={(event) => onDescriptionChange(event.target.value)}
              placeholder="이 가드레일의 목적을 설명하세요"
              aria-describedby={descriptionHelpId}
              readOnly={readOnly}
              disabled={!readOnly && isBusy}
              maxLength={2000}
              rows={3}
            />
            <small id={descriptionHelpId}>
              {description.length.toLocaleString("ko-KR")} / 2,000자
            </small>
          </div>
        </div>
        <dl className={styles.overviewMetrics}>
          <div>
            <dt>검사 지점</dt>
            <dd>{covered.length}/4</dd>
          </div>
          <div>
            <dt>노드</dt>
            <dd>{graph.nodes.length}</dd>
          </div>
          <div>
            <dt>판정</dt>
            <dd>{totalVerdicts}</dd>
          </div>
          <div className={styles.overviewOutcomeMetric}>
            <dt>결과</dt>
            <dd
              className={styles.overviewOutcomes}
              aria-label="가드레일 판정 결과"
            >
              {actions.length > 0 ? (
                actions.map((action) => (
                  <b key={action} data-action={action}>
                    {actionLabels[action]}
                  </b>
                ))
              ) : (
                <em>아직 판정 노드가 없습니다.</em>
              )}
            </dd>
          </div>
        </dl>
        <footer className={styles.overviewFooter}>
          <div className={styles.overviewActions}>
            {readOnly ? (
              <>
                <button
                  className={styles.dangerAction}
                  type="button"
                  disabled={isBusy}
                  onClick={onDelete}
                >
                  가드레일 삭제
                </button>
                <Link
                  className={styles.primaryAction}
                  href={`/guardrails/${encodeURIComponent(name)}`}
                >
                  초안으로 돌아가기
                </Link>
              </>
            ) : (
              <>
                <button
                  className={styles.dangerAction}
                  type="button"
                  disabled={isBusy}
                  onClick={onDelete}
                >
                  가드레일 삭제
                </button>
                <button
                  className={styles.secondaryAction}
                  type="button"
                  disabled={isBusy}
                  onClick={onChooseTemplate}
                  aria-label="템플릿에서 가드레일 시작"
                >
                  템플릿에서 시작
                </button>
                <button
                  className={styles.primaryAction}
                  type="button"
                  disabled={isBusy}
                  onClick={onPublish}
                  aria-busy={isPublishing}
                  aria-label={dirty ? "초안을 저장한 뒤 발행" : "저장된 초안 발행"}
                >
                  {isPublishing
                    ? "발행하는 중…"
                    : dirty
                      ? "저장 후 발행"
                      : "발행"}
                </button>
              </>
            )}
          </div>
          {!readOnly ? (
            <div className={styles.publishedState} aria-label="발행 상태">
              {publishedVersion !== null ? (
                <Link
                  href={`/guardrails/${encodeURIComponent(name)}/versions/${publishedVersion}`}
                >
                  발행 v{publishedVersion} 보기
                </Link>
              ) : (
                <strong>아직 발행되지 않음</strong>
              )}
            </div>
          ) : null}
        </footer>
      </section>

      <section
        className={styles.checkpointOverview}
        aria-labelledby="checkpoint-overview-title"
      >
        <div className={styles.overviewSectionTitle}>
          <h2 id="checkpoint-overview-title">검사 지점</h2>
        </div>
        <div className={styles.checkpointCards}>
          {checkpointSummaries.map((summary) => {
            const meta = checkpointMeta[summary.checkpoint];
            return (
              <button
                key={summary.checkpoint}
                type="button"
                onClick={() => onOpenCheckpoint(summary.checkpoint)}
                aria-label={`${meta.index} ${meta.label}, 노드 ${summary.nodeCount}개, 판정 ${summary.verdictCount}개`}
              >
                <span className={styles.checkpointNumber}>{meta.index}</span>
                <div>
                  <p>{meta.shortLabel}</p>
                  <h3>{meta.label}</h3>
                </div>
                <dl>
                  <div>
                    <dt>노드</dt>
                    <dd>{summary.nodeCount}</dd>
                  </div>
                  <div>
                    <dt>판정</dt>
                    <dd>{summary.verdictCount}</dd>
                  </div>
                </dl>
                <div className={styles.checkpointActions}>
                  {summary.actions.length > 0 ? (
                    summary.actions.map((action) => (
                      <b key={action} data-action={action}>
                        {actionLabels[action]}
                      </b>
                    ))
                  ) : (
                    <em>
                      {summary.nodeCount > 0 ? "판정 없음" : "미구성"}
                    </em>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <div className={styles.connectionOverview}>
        <AppConnectionPanel
          initialGuardrailName={name}
          isGuardrailReady={readOnly || publishedVersion !== null}
          title="앱 연결"
        />
      </div>
    </div>
  );
}
