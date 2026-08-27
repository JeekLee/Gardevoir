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
import { DeleteGuardrailDialog } from "@/src/features/delete-guardrail";
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
    <GuardrailWorkspace accessToken={session.tokens.accessToken} />
  );
}

function GuardrailWorkspace({
  accessToken,
}: {
  accessToken: string;
}) {
  const router = useRouter();
  const { endSession } = useSession();
  const [isCreating, setIsCreating] = useState(false);
  const [deleting, setDeleting] = useState<GuardrailSummary | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
          <h1 id="guardrails-title">가드레일</h1>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => setIsCreating(true)}
        >
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
          <span>
            가드레일 <strong>{data?.total ?? 0}</strong>개
          </span>
        </div>
      </div>

      {notice ? (
        <div className={styles.notice} role="status">
          {notice}
          <button type="button" onClick={() => setNotice(null)} aria-label="알림 닫기">
            ×
          </button>
        </div>
      ) : null}

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
            {data.items.map((guardrail) => (
              <GuardrailCard
                key={guardrail.name}
                guardrail={guardrail}
                onDelete={() => {
                  setNotice(null);
                  setDeleting(guardrail);
                }}
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

      {deleting ? (
        <DeleteGuardrailDialog
          key={deleting.name}
          accessToken={accessToken}
          name={deleting.name}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            setNotice(`${deleting.name} 가드레일 삭제됨`);
          }}
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
  onDelete,
}: {
  guardrail: GuardrailSummary;
  onDelete: () => void;
}) {
  const description = guardrail.description.trim();

  return (
    <article className={styles.guardrailCard}>
      <div className={styles.cardHeader}>
        <div>
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
          {description || describeGuardrailSummary(guardrail)}
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
          <button
            className={styles.deleteAction}
            type="button"
            onClick={onDelete}
            aria-label={`${guardrail.name} 가드레일 삭제`}
          >
            삭제
          </button>
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
      <h2>가드레일 없음</h2>
      <button className={styles.primaryButton} type="button" onClick={onCreate}>
        새 가드레일
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
              : "가드레일 목록을 불러오지 못했습니다."}
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
