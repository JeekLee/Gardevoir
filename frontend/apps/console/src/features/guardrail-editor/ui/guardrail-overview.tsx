import Link from "next/link";

import { AppConnectionPanel } from "@/src/entities/api-key";
import {
  describeGuardrailGraph,
  guardrailActions,
  type Checkpoint,
  type GuardrailGraph,
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
  wireGraph,
  readOnly,
  versionNumber,
  publishedVersion,
  dirty,
  isBusy,
  isPublishing,
  onOpenCheckpoint,
  onPublish,
  onTest,
  onChooseTemplate,
}: {
  name: string;
  graph: EditorGraph;
  wireGraph: GuardrailGraph;
  readOnly: boolean;
  versionNumber: number | null;
  publishedVersion: number | null;
  dirty: boolean;
  isBusy: boolean;
  isPublishing: boolean;
  onOpenCheckpoint: (checkpoint: Checkpoint) => void;
  onPublish: () => void;
  onTest: () => void;
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

  return (
    <div className={styles.overviewGrid}>
      <section className={styles.overviewHero}>
        <div>
          <p>가드레일 개요</p>
          <h2>한 그래프, 네 검사 지점</h2>
          <span>{describeGuardrailGraph(wireGraph)}</span>
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
        </dl>
        <div className={styles.overviewOutcomes} aria-label="가드레일 판정 결과">
          <span>결과</span>
          {actions.length > 0 ? (
            actions.map((action) => (
              <b key={action} data-action={action}>
                {actionLabels[action]}
              </b>
            ))
          ) : (
            <em>아직 판정 노드가 없습니다.</em>
          )}
        </div>
      </section>

      <div className={styles.connectionOverview}>
        <AppConnectionPanel
          initialGuardrailName={name}
          isGuardrailReady={readOnly || publishedVersion !== null}
          title="앱 연결"
          description="이 가드레일 이름이 미리 입력된 curl 요청으로 실제 앱 연결 형식을 확인하세요."
        />
      </div>

      <section
        className={styles.guardrailState}
        aria-labelledby="guardrail-state-title"
      >
        <div>
          <p>가드레일 상태</p>
          <h2 id="guardrail-state-title">
            {readOnly
              ? `발행 버전 ${versionNumber}`
              : dirty
                ? "저장하지 않은 초안"
                : "초안 저장됨"}
          </h2>
          <span>
            {readOnly
              ? "이 발행본은 변경할 수 없습니다."
              : dirty
                ? "탭을 전환해도 변경 내용은 이 편집 세션에 유지됩니다."
                : "현재 전체 그래프가 게이트웨이 초안과 일치합니다."}
          </span>
        </div>

        <div className={styles.publishedState}>
          <span>발행 상태</span>
          {readOnly && versionNumber !== null ? (
            <strong>버전 {versionNumber} · 읽기 전용</strong>
          ) : publishedVersion !== null ? (
            <Link
              href={`/guardrails/${encodeURIComponent(name)}/versions/${publishedVersion}`}
            >
              발행 버전 {publishedVersion} 보기 ↗
            </Link>
          ) : (
            <strong>아직 발행되지 않음</strong>
          )}
        </div>

        <div className={styles.overviewActions}>
          {readOnly ? (
            <Link
              className={styles.primaryAction}
              href={`/guardrails/${encodeURIComponent(name)}`}
            >
              초안으로 돌아가기
            </Link>
          ) : (
            <>
              <button
                className={styles.secondaryAction}
                type="button"
                disabled={isBusy}
                onClick={onTest}
              >
                초안 테스트
              </button>
              <button
                className={styles.secondaryAction}
                type="button"
                disabled={isBusy}
                onClick={onChooseTemplate}
              >
                ＋ 템플릿에서 시작
              </button>
              <button
                className={styles.primaryAction}
                type="button"
                disabled={isBusy}
                onClick={onPublish}
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
      </section>

      <section
        className={styles.checkpointOverview}
        aria-labelledby="checkpoint-overview-title"
      >
        <div className={styles.overviewSectionTitle}>
          <div>
            <p>검사 지점 구성</p>
            <h2 id="checkpoint-overview-title">검사 지점별 정책 흐름</h2>
            <small>번호는 검사 지점 ID이며, 카드 순서는 실제 요청 실행 순서입니다.</small>
          </div>
          <span>카드를 선택해 해당 풀 캔버스로 이동합니다.</span>
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
                  <span>{meta.description}</span>
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
    </div>
  );
}
