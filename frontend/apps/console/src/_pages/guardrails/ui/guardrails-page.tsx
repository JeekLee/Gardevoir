"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  describeGuardrailSummary,
  guardrailListOptions,
  type Checkpoint,
  type GuardrailAction,
  type GuardrailSummary,
} from "@/src/entities/guardrail";
import { useSession } from "@/src/entities/session";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import { CreateGuardrailDialog } from "./create-guardrail-dialog";
import styles from "./guardrails-page.module.css";

export function GuardrailsPage() {
  const { session } = useSession();
  if (!session) return null;

  return (
    <GuardrailWorkspace
      accessToken={session.tokens.accessToken}
      operatorName={session.user.name}
    />
  );
}

function GuardrailWorkspace({
  accessToken,
  operatorName,
}: {
  accessToken: string;
  operatorName: string;
}) {
  const router = useRouter();
  const { endSession } = useSession();
  const [isCreating, setIsCreating] = useState(false);
  const query = useQuery(guardrailListOptions(accessToken));

  const handleAuthorizationError = useCallback(
    (error: ConsoleApiError) => {
      endSession();
      router.replace(
        error.httpStatus === 403
          ? "/login?reason=forbidden"
          : "/login?reason=expired",
      );
    },
    [endSession, router],
  );

  useEffect(() => {
    if (
      query.error instanceof ConsoleApiError &&
      (query.error.httpStatus === 401 || query.error.httpStatus === 403)
    ) {
      handleAuthorizationError(query.error);
    }
  }, [handleAuthorizationError, query.error]);

  const data = query.data;
  const visibleError =
    query.error instanceof ConsoleApiError &&
    (query.error.httpStatus === 401 || query.error.httpStatus === 403)
      ? null
      : query.error;

  return (
    <section className={styles.page} aria-labelledby="guardrails-title">
      <div className={styles.pageHeader}>
        <div className={styles.headingBlock}>
          <p className={styles.eyebrow}>정책 통제 영역</p>
          <h1 id="guardrails-title">가드레일</h1>
          <p>
            입력부터 툴 오염, 에이전트 액션, 출력까지 하나의 그래프로
            설계하세요. 게이트웨이가 전체 초안을 검증한 뒤에만 발행합니다.
          </p>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => setIsCreating(true)}
        >
          <span aria-hidden="true">＋</span>
          새 가드레일
        </button>
      </div>

      <div className={styles.checkpointGuide}>
        <div className={styles.checkpointRail} aria-label="검사 순서">
          <Checkpoint number="①" label="입력" detail="사용자 메시지" />
          <span aria-hidden="true" />
          <Checkpoint number="②" label="툴 결과" detail="신뢰하지 않는 데이터" action />
          <span aria-hidden="true" />
          <Checkpoint number="④" label="툴 호출" detail="에이전트 액션" action />
          <span aria-hidden="true" />
          <Checkpoint number="③" label="출력" detail="모델 응답" />
        </div>
        <p>번호는 검사 지점 ID이며, 레인은 실제 요청 실행 순서입니다.</p>
      </div>

      <div className={styles.statusBar}>
        <div className={styles.routeStatus}>
          <span className={styles.liveDot} aria-hidden="true" />
          <span>
            가드레일 <strong>{data?.total ?? 0}</strong>개
          </span>
        </div>
        <p>
          로그인 사용자 <strong>{operatorName}</strong>
        </p>
      </div>

      <div className={styles.content} aria-busy={query.isPending}>
        {query.isPending ? <GuardrailSkeleton /> : null}
        {!query.isPending && visibleError ? (
          <ErrorState error={visibleError} onRetry={() => void query.refetch()} />
        ) : null}
        {!query.isPending && !visibleError && data?.items.length === 0 ? (
          <EmptyState onCreate={() => setIsCreating(true)} />
        ) : null}
        {!query.isPending && !visibleError && data && data.items.length > 0 ? (
          <div className={styles.guardrailGrid}>
            {data.items.map((guardrail, index) => (
              <GuardrailCard
                key={guardrail.name}
                guardrail={guardrail}
                order={index + 1}
              />
            ))}
          </div>
        ) : null}
      </div>

      {isCreating ? (
        <CreateGuardrailDialog
          accessToken={accessToken}
          onClose={() => setIsCreating(false)}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}
    </section>
  );
}

function Checkpoint({
  number,
  label,
  detail,
  action = false,
}: {
  number: string;
  label: string;
  detail: string;
  action?: boolean;
}) {
  return (
    <div className={action ? styles.actionStep : undefined}>
      <b>{number}</b>
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
    </div>
  );
}

function GuardrailCard({
  guardrail,
  order,
}: {
  guardrail: GuardrailSummary;
  order: number;
}) {
  return (
    <article className={styles.guardrailCard}>
      <span className={styles.cardIndex} aria-hidden="true">
        {String(order).padStart(2, "0")}
      </span>
      <div className={styles.cardHeader}>
        <div>
          <p>정책 그래프</p>
          <h2>{guardrail.name}</h2>
        </div>
        <div className={styles.badges} aria-label="가드레일 상태">
          {guardrail.hasDraft ? <span className={styles.draftBadge}>초안</span> : null}
          {guardrail.latestVersionNumber !== null ? (
            <span className={styles.publishedBadge}>
              발행 v{guardrail.latestVersionNumber}
            </span>
          ) : (
            <span className={styles.unpublishedBadge}>미발행</span>
          )}
        </div>
      </div>

      <div className={styles.policyProjection}>
        <p className={styles.policyDescription}>
          {describeGuardrailSummary(guardrail)}
        </p>

        <div className={styles.projectionRow}>
          <span>검사 지점</span>
          <CheckpointPath checkpoints={guardrail.checkpoints} />
        </div>
        <div className={styles.projectionRow}>
          <span>결과</span>
          <div className={styles.actionChips}>
            {guardrail.actions.length > 0 ? (
              guardrail.actions.map((action) => (
                <span
                  key={action}
                  className={`${styles.actionChip} ${actionClassName(action)}`}
                >
                  {actionLabel(action)}
                </span>
              ))
            ) : (
              <span className={styles.emptyProjection}>결정 없음</span>
            )}
          </div>
        </div>
        <div className={styles.policyScale}>
          검사 {guardrail.checkCount}개 · 판정 {guardrail.verdictCount}개
        </div>
      </div>

      <footer className={styles.cardFooter}>
        <p>
          수정 <time dateTime={guardrail.updatedAt}>{formatDate(guardrail.updatedAt)}</time>
        </p>
        <div className={styles.cardActions}>
          {guardrail.latestVersionNumber !== null ? (
            <Link
              className={styles.secondaryLink}
              href={`/guardrails/${encodeURIComponent(guardrail.name)}/versions/${
                guardrail.latestVersionNumber
              }`}
            >
              v{guardrail.latestVersionNumber} 보기
            </Link>
          ) : null}
          <Link
            className={styles.primaryLink}
            href={`/guardrails/${encodeURIComponent(guardrail.name)}`}
          >
            초안 열기
          </Link>
        </div>
      </footer>
    </article>
  );
}

const checkpointCardCopy: Record<
  Checkpoint,
  { index: "①" | "②" | "④" | "③"; label: string }
> = {
  input: { index: "①", label: "입력" },
  tool_result: { index: "②", label: "툴 결과" },
  tool_call: { index: "④", label: "툴 호출" },
  output: { index: "③", label: "출력" },
};

function CheckpointPath({ checkpoints }: { checkpoints: Checkpoint[] }) {
  if (checkpoints.length === 0) {
    return <span className={styles.emptyProjection}>검사 지점 없음</span>;
  }

  return (
    <div className={styles.checkpointPath}>
      {checkpoints.map((checkpoint, index) => (
        <span key={checkpoint} className={styles.checkpointPathItem}>
          {index > 0 ? <i aria-hidden="true">→</i> : null}
          <b>{checkpointCardCopy[checkpoint].index}</b>
          <span>{checkpointCardCopy[checkpoint].label}</span>
        </span>
      ))}
    </div>
  );
}

function actionClassName(action: GuardrailAction): string {
  switch (action) {
    case "block":
      return styles.blockAction;
    case "mask":
      return styles.maskAction;
    case "allow":
      return styles.allowAction;
  }
}

function actionLabel(action: GuardrailAction): string {
  switch (action) {
    case "block":
      return "차단";
    case "mask":
      return "마스킹";
    case "allow":
      return "허용";
  }
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className={styles.emptyState}>
      <div className={styles.emptyFlow} aria-hidden="true">
        <span>①</span><i /><span>②</span><i /><span>④</span><i /><span>③</span>
      </div>
      <p className={styles.eyebrow}>아직 정책 그래프가 없습니다</p>
      <h2>에이전트가 읽고 실행할 범위를 통제하세요</h2>
      <p>
        초안을 만들고 네 검사 지점에 검사를 연결한 뒤 변경할 수 없는
        발행본을 만드세요.
      </p>
      <button className={styles.primaryButton} type="button" onClick={onCreate}>
        첫 가드레일 만들기
      </button>
    </div>
  );
}

function ErrorState({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => void;
}) {
  return (
    <div className={styles.errorState} role="alert">
      <span aria-hidden="true">!</span>
      <div>
        <p className={styles.dangerEyebrow}>가드레일 목록을 사용할 수 없음</p>
        <h2>가드레일을 불러오지 못했습니다</h2>
        <p>
          {error instanceof ConsoleApiError && error.httpStatus === 0
            ? "게이트웨이가 실행 중이고 이 콘솔에서 연결할 수 있는지 확인하세요."
            : error instanceof ConsoleApiError
              ? consoleErrorMessage(error)
              : "가드레일 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요."}
        </p>
        {error instanceof ConsoleApiError ? (
          <code>{consoleErrorReference(error)}</code>
        ) : null}
      </div>
      <button className={styles.secondaryButton} type="button" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  );
}

function GuardrailSkeleton() {
  return (
    <div className={styles.guardrailGrid} aria-label="가드레일 불러오는 중">
      {[0, 1].map((index) => (
        <div className={`${styles.guardrailCard} ${styles.skeleton}`} key={index}>
          <span /><span /><span />
        </div>
      ))}
    </div>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "최근";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" }).format(date);
}
