"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import {
  type ProviderSummary,
  useProviders,
} from "@/src/entities/provider";
import { useSession } from "@/src/entities/session";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import { ConfirmDelete } from "./confirm-delete";
import { ProviderEditor } from "./provider-editor";
import styles from "./providers-page.module.css";

export function ProvidersPage() {
  const { session } = useSession();

  if (!session) {
    return null;
  }

  return <ProviderWorkspace accessToken={session.tokens.accessToken} />;
}

function ProviderWorkspace({
  accessToken,
}: {
  accessToken: string;
}) {
  const router = useRouter();
  const { endSession } = useSession();
  const [editor, setEditor] = useState<ProviderSummary | null | undefined>();
  const [deleting, setDeleting] = useState<ProviderSummary | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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

  const { data, error, isLoading, reload } = useProviders(
    accessToken,
    handleAuthorizationError,
  );

  async function afterSaved(provider: ProviderSummary) {
    const wasEditing = editor !== null;
    setEditor(undefined);
    setNotice(
      wasEditing
        ? `${provider.name} 프로바이더 수정됨`
        : `${provider.name} 프로바이더 추가됨`,
    );
    await reload();
  }

  async function afterDeleted() {
    const name = deleting?.name ?? "프로바이더";
    setDeleting(null);
    setNotice(`${name} 프로바이더 삭제됨`);
    await reload();
  }

  return (
    <section className={styles.page} aria-labelledby="providers-title">
      <div className={styles.pageHeader}>
        <div className={styles.headingBlock}>
          <h1 id="providers-title">프로바이더</h1>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => {
            setNotice(null);
            setEditor(null);
          }}
        >
          프로바이더 추가
        </button>
      </div>

      <div className={styles.statusBar}>
        <div className={styles.routeStatus}>
          <span>
            프로바이더 <strong>{data?.total ?? 0}</strong>개
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

      <div className={styles.content} aria-busy={isLoading}>
        {isLoading ? <ProviderSkeleton /> : null}
        {!isLoading && error ? (
          <ErrorState error={error} onRetry={() => void reload()} />
        ) : null}
        {!isLoading && !error && data?.items.length === 0 ? (
          <EmptyState onAdd={() => setEditor(null)} />
        ) : null}
        {!isLoading && !error && data && data.items.length > 0 ? (
          <div className={styles.providerGrid}>
            {data.items.map((provider) => (
              <ProviderCard
                key={provider.id}
                provider={provider}
                onEdit={() => {
                  setNotice(null);
                  setEditor(provider);
                }}
                onDelete={() => {
                  setNotice(null);
                  setDeleting(provider);
                }}
              />
            ))}
          </div>
        ) : null}
      </div>

      {editor !== undefined ? (
        <ProviderEditor
          key={editor?.id ?? "new-provider"}
          accessToken={accessToken}
          provider={editor}
          onClose={() => setEditor(undefined)}
          onSaved={(provider) => void afterSaved(provider)}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}

      {deleting ? (
        <ConfirmDelete
          key={deleting.id}
          accessToken={accessToken}
          provider={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => void afterDeleted()}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}
    </section>
  );
}

function ProviderCard({
  provider,
  onEdit,
  onDelete,
}: {
  provider: ProviderSummary;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <article className={styles.gateCard}>
      <div className={styles.cardHeader}>
        <div>
          <h2>{provider.name}</h2>
        </div>
        <span className={styles.activeBadge}>
          {provider.hasApiKey ? "API 키 연결됨" : "API 키 없음"}
        </span>
      </div>

      <div className={styles.routePath}>
        <span>Base URL</span>
        <code title={provider.baseUrl}>{provider.baseUrl}</code>
      </div>

      <div className={styles.models}>
        <p>모델 {provider.models.length}개</p>
        <div>
          {provider.models.map((model) => (
            <code key={model}>{model}</code>
          ))}
        </div>
      </div>

      <footer className={styles.cardFooter}>
        <p>
          수정 <time dateTime={provider.updatedAt}>{formatDate(provider.updatedAt)}</time>
        </p>
        <div className={styles.cardActions}>
          <button type="button" onClick={onEdit}>
            수정
          </button>
          <button className={styles.deleteAction} type="button" onClick={onDelete}>
            삭제
          </button>
        </div>
      </footer>
    </article>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className={styles.emptyState}>
      <h2>프로바이더 없음</h2>
      <button className={styles.primaryButton} type="button" onClick={onAdd}>
        프로바이더 추가
      </button>
    </div>
  );
}

function ErrorState({
  error,
  onRetry,
}: {
  error: ConsoleApiError;
  onRetry: () => void;
}) {
  return (
    <div className={styles.errorState} role="alert">
      <span aria-hidden="true">!</span>
      <div>
        <p className={styles.dangerEyebrow}>업스트림 경로를 사용할 수 없음</p>
        <h2>프로바이더를 불러오지 못했습니다</h2>
        <p>
          {error.httpStatus === 0
            ? "게이트웨이가 실행 중이고 이 콘솔 오리진이 허용됐는지 확인하세요."
            : consoleErrorMessage(error)}
        </p>
        <code>{consoleErrorReference(error)}</code>
      </div>
      <button className={styles.secondaryButton} type="button" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  );
}

function ProviderSkeleton() {
  return (
    <div className={styles.providerGrid} aria-label="프로바이더 불러오는 중">
      {[0, 1].map((index) => (
        <div className={`${styles.gateCard} ${styles.skeleton}`} key={index}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "최근";
  }
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
  }).format(date);
}
