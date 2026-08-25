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
import { ConsoleApiError } from "@/src/shared/api";

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
          <p className={styles.eyebrow}>Policy control plane</p>
          <h1 id="guardrails-title">Guardrails</h1>
          <p>
            Author one graph across input, tool contamination, agent actions, and
            output. Publish only when the gateway accepts the complete draft.
          </p>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => setIsCreating(true)}
        >
          <span aria-hidden="true">＋</span>
          New guardrail
        </button>
      </div>

      <div className={styles.checkpointRail} aria-label="Inspection sequence">
        <Checkpoint number="①" label="Input" detail="User message" />
        <span aria-hidden="true" />
        <Checkpoint number="②" label="Tool result" detail="Untrusted data" action />
        <span aria-hidden="true" />
        <Checkpoint number="④" label="Tool call" detail="Agent action" action />
        <span aria-hidden="true" />
        <Checkpoint number="③" label="Output" detail="Model response" />
      </div>

      <div className={styles.statusBar}>
        <div className={styles.routeStatus}>
          <span className={styles.liveDot} aria-hidden="true" />
          <span>
            <strong>{data?.total ?? 0}</strong> guardrail
            {data?.total === 1 ? "" : "s"}
          </span>
        </div>
        <p>
          Signed in as <strong>{operatorName}</strong>
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
          <p>Policy graph</p>
          <h2>{guardrail.name}</h2>
        </div>
        <div className={styles.badges} aria-label="Guardrail status">
          {guardrail.hasDraft ? <span className={styles.draftBadge}>Draft</span> : null}
          {guardrail.latestVersionNumber !== null ? (
            <span className={styles.publishedBadge}>
              Published v{guardrail.latestVersionNumber}
            </span>
          ) : (
            <span className={styles.unpublishedBadge}>Not published</span>
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
                  {action}
                </span>
              ))
            ) : (
              <span className={styles.emptyProjection}>결정 없음</span>
            )}
          </div>
        </div>
        <div className={styles.policyScale}>
          체크 {guardrail.checkCount} · verdict {guardrail.verdictCount}
        </div>
      </div>

      <footer className={styles.cardFooter}>
        <p>
          Updated <time dateTime={guardrail.updatedAt}>{formatDate(guardrail.updatedAt)}</time>
        </p>
        <div className={styles.cardActions}>
          {guardrail.latestVersionNumber !== null ? (
            <Link
              className={styles.secondaryLink}
              href={`/guardrails/${encodeURIComponent(guardrail.name)}/versions/${
                guardrail.latestVersionNumber
              }`}
            >
              View v{guardrail.latestVersionNumber}
            </Link>
          ) : null}
          <Link
            className={styles.primaryLink}
            href={`/guardrails/${encodeURIComponent(guardrail.name)}`}
          >
            Open draft
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
  input: { index: "①", label: "Input" },
  tool_result: { index: "②", label: "Tool result" },
  tool_call: { index: "④", label: "Tool call" },
  output: { index: "③", label: "Output" },
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

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className={styles.emptyState}>
      <div className={styles.emptyFlow} aria-hidden="true">
        <span>①</span><i /><span>②</span><i /><span>④</span><i /><span>③</span>
      </div>
      <p className={styles.eyebrow}>No policy graphs yet</p>
      <h2>Control what agents read and do</h2>
      <p>
        Start with a draft, connect checks across the four checkpoint lanes, then
        publish an immutable version.
      </p>
      <button className={styles.primaryButton} type="button" onClick={onCreate}>
        Create first guardrail
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
        <p className={styles.dangerEyebrow}>Policy index unavailable</p>
        <h2>Guardrails could not be loaded</h2>
        <p>
          {error instanceof ConsoleApiError && error.httpStatus === 0
            ? "Check that the gateway is running and reachable from this console."
            : error.message}
        </p>
        {error instanceof ConsoleApiError && error.requestId ? (
          <code>Reference {error.requestId}</code>
        ) : null}
      </div>
      <button className={styles.secondaryButton} type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

function GuardrailSkeleton() {
  return (
    <div className={styles.guardrailGrid} aria-label="Loading guardrails">
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
  if (Number.isNaN(date.getTime())) return "recently";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(date);
}
