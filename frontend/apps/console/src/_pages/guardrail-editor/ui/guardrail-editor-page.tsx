"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  guardrailDraftOptions,
  guardrailListOptions,
  guardrailVersionOptions,
  type GuardrailDetail,
} from "@/src/entities/guardrail";
import { useSession } from "@/src/entities/session";
import { DeleteGuardrailDialog } from "@/src/features/delete-guardrail";
import { GuardrailEditor } from "@/src/features/guardrail-editor";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import styles from "./guardrail-editor-page.module.css";

export function GuardrailEditorPage({
  name,
  versionNumber,
}: {
  name: string;
  versionNumber?: number;
}) {
  const { session } = useSession();
  if (!session) return null;

  return versionNumber === undefined ? (
    <DraftWorkspace accessToken={session.tokens.accessToken} name={name} />
  ) : (
    <VersionWorkspace
      accessToken={session.tokens.accessToken}
      name={name}
      versionNumber={versionNumber}
    />
  );
}

function DraftWorkspace({
  accessToken,
  name,
}: {
  accessToken: string;
  name: string;
}) {
  const query = useQuery(guardrailDraftOptions(accessToken, name));
  const listQuery = useQuery(guardrailListOptions(accessToken));
  const latestPublishedVersion =
    listQuery.data?.items.find((guardrail) => guardrail.name === name)
      ?.latestVersionNumber ?? null;
  return (
    <EditorQueryBoundary
      accessToken={accessToken}
      name={name}
      query={query}
      readOnly={false}
      latestPublishedVersion={latestPublishedVersion}
    />
  );
}

function VersionWorkspace({
  accessToken,
  name,
  versionNumber,
}: {
  accessToken: string;
  name: string;
  versionNumber: number;
}) {
  const query = useQuery(
    guardrailVersionOptions(accessToken, name, versionNumber),
  );
  return (
    <EditorQueryBoundary
      accessToken={accessToken}
      name={name}
      query={query}
      readOnly
      latestPublishedVersion={versionNumber}
    />
  );
}

function EditorQueryBoundary({
  accessToken,
  name,
  query,
  readOnly,
  latestPublishedVersion,
}: {
  accessToken: string;
  name: string;
  query: UseQueryResult<GuardrailDetail, Error>;
  readOnly: boolean;
  latestPublishedVersion: number | null;
}) {
  const router = useRouter();
  const { endSession } = useSession();
  const [isDeleting, setIsDeleting] = useState(false);

  const handleAuthorizationError = useCallback(
    (error: ConsoleApiError) => {
      const editorPath = readOnly
        ? `/guardrails/${encodeURIComponent(name)}/versions/${latestPublishedVersion}`
        : `/guardrails/${encodeURIComponent(name)}`;
      endSession();
      router.replace(
        error.httpStatus === 403
          ? "/login?reason=forbidden"
          : `/login?reason=expired&returnTo=${encodeURIComponent(editorPath)}`,
      );
    },
    [endSession, latestPublishedVersion, name, readOnly, router],
  );

  useEffect(() => {
    if (
      query.error instanceof ConsoleApiError &&
      (query.error.httpStatus === 401 || query.error.httpStatus === 403)
    ) {
      handleAuthorizationError(query.error);
    }
  }, [handleAuthorizationError, query.error]);

  if (query.isPending) {
    return (
      <div className={styles.loading} aria-live="polite">
        <span aria-hidden="true" />
        <div>
          <p>정책 그래프를 불러오는 중…</p>
          <h1>{name}</h1>
        </div>
      </div>
    );
  }

  if (query.error) {
    if (
      query.error instanceof ConsoleApiError &&
      (query.error.httpStatus === 401 || query.error.httpStatus === 403)
    ) {
      return null;
    }
    return (
      <div className={styles.errorState} role="alert">
        <span aria-hidden="true">!</span>
        <div>
          <p>{readOnly ? "발행본을 사용할 수 없음" : "초안을 사용할 수 없음"}</p>
          <h1>{name}</h1>
          <span>{errorMessage(query.error, readOnly)}</span>
          {query.error instanceof ConsoleApiError ? (
            <code>{consoleErrorReference(query.error)}</code>
          ) : null}
        </div>
        <div className={styles.errorActions}>
          <Link href="/guardrails">가드레일 목록으로</Link>
          <button type="button" onClick={() => void query.refetch()}>
            다시 시도
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <GuardrailEditor
        detail={query.data}
        accessToken={accessToken}
        readOnly={readOnly}
        latestPublishedVersion={latestPublishedVersion}
        onDelete={() => setIsDeleting(true)}
        onAuthorizationError={handleAuthorizationError}
      />
      {isDeleting ? (
        <DeleteGuardrailDialog
          accessToken={accessToken}
          name={name}
          onClose={() => setIsDeleting(false)}
          onDeleted={() => router.replace("/guardrails")}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}
    </>
  );
}

function errorMessage(error: Error, readOnly: boolean): string {
  if (error instanceof ConsoleApiError && error.httpStatus === 404) {
    return readOnly
      ? "요청한 발행 버전이 없습니다. 가드레일 목록에서 현재 발행본을 확인하세요."
      : "편집할 초안이 없습니다. 가드레일 목록을 새로고침하세요.";
  }
  if (error instanceof ConsoleApiError && error.httpStatus === 0) {
    return "게이트웨이에 연결할 수 없습니다. 게이트웨이 상태와 네트워크 설정을 확인하세요.";
  }
  if (error instanceof ConsoleApiError) return consoleErrorMessage(error);
  return "정책 그래프를 불러오지 못했습니다.";
}
