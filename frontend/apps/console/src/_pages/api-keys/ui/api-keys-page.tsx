"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  apiKeyListOptions,
  apiKeyStatus,
  AppConnectionPanel,
  type ApiKeyStatus,
  type ApiKeySummary,
} from "@/src/entities/api-key";
import { guardrailListOptions } from "@/src/entities/guardrail";
import { useSession } from "@/src/entities/session";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import { CreateApiKeyDialog } from "./create-api-key-dialog";
import { EditApiKeyDialog } from "./edit-api-key-dialog";
import { RevokeApiKeyDialog } from "./revoke-api-key-dialog";
import styles from "./api-keys-page.module.css";

export function ApiKeysPage() {
  const { session } = useSession();
  if (!session) return null;

  return (
    <ApiKeyWorkspace
      accessToken={session.tokens.accessToken}
      operatorName={session.user.name}
    />
  );
}

function ApiKeyWorkspace({
  accessToken,
  operatorName,
}: {
  accessToken: string;
  operatorName: string;
}) {
  const router = useRouter();
  const { endSession } = useSession();
  const [isCreating, setIsCreating] = useState(false);
  const [editing, setEditing] = useState<ApiKeySummary | null>(null);
  const [revoking, setRevoking] = useState<ApiKeySummary | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const apiKeysQuery = useQuery(apiKeyListOptions(accessToken));
  const guardrailsQuery = useQuery(guardrailListOptions(accessToken));

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
    const authorizationError = [apiKeysQuery.error, guardrailsQuery.error].find(
      (error) =>
        error instanceof ConsoleApiError &&
        (error.httpStatus === 401 || error.httpStatus === 403),
    );
    if (authorizationError instanceof ConsoleApiError) {
      handleAuthorizationError(authorizationError);
    }
  }, [
    apiKeysQuery.error,
    guardrailsQuery.error,
    handleAuthorizationError,
  ]);

  const publishedGuardrailNames = useMemo(
    () =>
      guardrailsQuery.data?.items
        .filter((guardrail) => guardrail.latestVersionNumber !== null)
        .map((guardrail) => guardrail.name) ?? [],
    [guardrailsQuery.data],
  );
  const visibleError =
    apiKeysQuery.error instanceof ConsoleApiError &&
    (apiKeysQuery.error.httpStatus === 401 ||
      apiKeysQuery.error.httpStatus === 403)
      ? null
      : apiKeysQuery.error;

  return (
    <section className={styles.page} aria-labelledby="api-keys-title">
      <div className={styles.pageHeader}>
        <div className={styles.headingBlock}>
          <p className={styles.eyebrow}>앱 크레덴셜</p>
          <h1 id="api-keys-title">API 키</h1>
          <p>
            앱이 gardevoir를 호출할 때 사용할 키를 발급하고, 연결할 가드레일을
            실제 요청 예시로 확인하세요.
          </p>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => {
            setNotice(null);
            setIsCreating(true);
          }}
        >
          <span aria-hidden="true">＋</span>
          새 API 키
        </button>
      </div>

      <AppConnectionPanel
        guardrailNames={publishedGuardrailNames}
        isGuardrailReady={
          !guardrailsQuery.isPending &&
          !guardrailsQuery.error &&
          publishedGuardrailNames.length > 0
        }
      />

      <div className={styles.statusBar}>
        <div className={styles.routeStatus}>
          <span className={styles.liveDot} aria-hidden="true" />
          <span>
            API 키 <strong>{apiKeysQuery.data?.total ?? 0}</strong>개
          </span>
        </div>
        <p>
          로그인 사용자 <strong>{operatorName}</strong>
        </p>
      </div>

      {notice ? (
        <div className={styles.notice} role="status">
          <span aria-hidden="true">✓</span>
          {notice}
          <button type="button" onClick={() => setNotice(null)} aria-label="알림 닫기">
            ×
          </button>
        </div>
      ) : null}

      <div className={styles.content} aria-busy={apiKeysQuery.isPending}>
        {apiKeysQuery.isPending ? <ApiKeySkeleton /> : null}
        {!apiKeysQuery.isPending && visibleError ? (
          <ErrorState
            error={visibleError}
            onRetry={() => void apiKeysQuery.refetch()}
          />
        ) : null}
        {!apiKeysQuery.isPending &&
        !visibleError &&
        apiKeysQuery.data?.items.length === 0 ? (
          <EmptyState onCreate={() => setIsCreating(true)} />
        ) : null}
        {!apiKeysQuery.isPending &&
        !visibleError &&
        apiKeysQuery.data &&
        apiKeysQuery.data.items.length > 0 ? (
          <ApiKeyTable
            apiKeys={apiKeysQuery.data.items}
            onEdit={(apiKey) => {
              setNotice(null);
              setEditing(apiKey);
            }}
            onRevoke={(apiKey) => {
              setNotice(null);
              setRevoking(apiKey);
            }}
          />
        ) : null}
      </div>

      {isCreating ? (
        <CreateApiKeyDialog
          accessToken={accessToken}
          guardrailNames={publishedGuardrailNames}
          onClose={() => setIsCreating(false)}
          onCreated={(name) => setNotice(`${name} API 키를 만들었습니다.`)}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}

      {editing ? (
        <EditApiKeyDialog
          key={editing.id}
          accessToken={accessToken}
          apiKey={editing}
          onClose={() => setEditing(null)}
          onSaved={(apiKey) => {
            setEditing(null);
            setNotice(`${apiKey.name} API 키를 수정했습니다.`);
          }}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}

      {revoking ? (
        <RevokeApiKeyDialog
          key={revoking.id}
          accessToken={accessToken}
          apiKey={revoking}
          onClose={() => setRevoking(null)}
          onRevoked={() => {
            setRevoking(null);
            setNotice(`${revoking.name} API 키를 폐기했습니다.`);
          }}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}
    </section>
  );
}

function ApiKeyTable({
  apiKeys,
  onEdit,
  onRevoke,
}: {
  apiKeys: ApiKeySummary[];
  onEdit: (apiKey: ApiKeySummary) => void;
  onRevoke: (apiKey: ApiKeySummary) => void;
}) {
  return (
    <div className={styles.tableFrame}>
      <table className={styles.table}>
        <caption className={styles.visuallyHidden}>발급된 API 키 목록</caption>
        <thead>
          <tr>
            <th scope="col">이름</th>
            <th scope="col">키</th>
            <th scope="col">생성</th>
            <th scope="col">만료</th>
            <th scope="col">상태</th>
            <th scope="col">작업</th>
          </tr>
        </thead>
        <tbody>
          {apiKeys.map((apiKey) => {
            const status = apiKeyStatus(apiKey);
            return (
              <tr key={apiKey.id}>
                <td>
                  <strong>{apiKey.name}</strong>
                </td>
                <td>
                  <code>{apiKey.keyPreview}</code>
                </td>
                <td>
                  <time dateTime={apiKey.createdAt}>
                    {formatDateTime(apiKey.createdAt)}
                  </time>
                </td>
                <td>
                  {apiKey.expiresAt ? (
                    <time dateTime={apiKey.expiresAt}>
                      {formatDateTime(apiKey.expiresAt)}
                    </time>
                  ) : (
                    <span className={styles.noExpiry}>없음</span>
                  )}
                </td>
                <td>
                  <StatusBadge status={status} />
                </td>
                <td>
                  <div className={styles.rowActions}>
                    <button
                      type="button"
                      onClick={() => onEdit(apiKey)}
                      disabled={status !== "active"}
                      title={
                        status === "active"
                          ? `${apiKey.name} 수정`
                          : "활성 API 키만 수정할 수 있습니다."
                      }
                    >
                      수정
                    </button>
                    <button
                      className={styles.revokeAction}
                      type="button"
                      onClick={() => onRevoke(apiKey)}
                      disabled={status === "revoked"}
                    >
                      {status === "revoked" ? "폐기됨" : "폐기"}
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }: { status: ApiKeyStatus }) {
  const label =
    status === "active" ? "활성" : status === "revoked" ? "폐기됨" : "만료됨";
  return <span className={`${styles.statusBadge} ${styles[status]}`}>{label}</span>;
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className={styles.emptyState}>
      <span className={styles.emptyKey} aria-hidden="true">
        gdv_
      </span>
      <p className={styles.eyebrow}>첫 연결 준비</p>
      <h2>아직 API 키가 없습니다 — 앱을 연결하려면 키를 만드세요</h2>
      <p>
        평문 키는 생성 직후 한 번만 보입니다. 안전한 비밀 저장소에 보관할
        준비를 마친 뒤 발급하세요.
      </p>
      <button className={styles.primaryButton} type="button" onClick={onCreate}>
        첫 API 키 만들기
      </button>
    </div>
  );
}

function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className={styles.errorState} role="alert">
      <span aria-hidden="true">!</span>
      <div>
        <p className={styles.dangerEyebrow}>앱 크레덴셜을 사용할 수 없음</p>
        <h2>API 키를 불러오지 못했습니다</h2>
        <p>
          {error instanceof ConsoleApiError
            ? consoleErrorMessage(error)
            : "API 키 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요."}
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

function ApiKeySkeleton() {
  return (
    <div className={`${styles.tableFrame} ${styles.skeleton}`} aria-label="API 키 불러오는 중">
      <span />
      <span />
      <span />
    </div>
  );
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "알 수 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
