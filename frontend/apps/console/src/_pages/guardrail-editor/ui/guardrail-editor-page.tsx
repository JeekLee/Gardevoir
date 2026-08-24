"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";

import {
  guardrailDraftOptions,
  guardrailVersionOptions,
  type GuardrailDetail,
} from "@/src/entities/guardrail";
import { useSession } from "@/src/entities/session";
import { GuardrailEditor } from "@/src/features/guardrail-editor";
import { ConsoleApiError } from "@/src/shared/api";

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
  return (
    <EditorQueryBoundary
      accessToken={accessToken}
      name={name}
      query={query}
      readOnly={false}
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
    />
  );
}

function EditorQueryBoundary({
  accessToken,
  name,
  query,
  readOnly,
}: {
  accessToken: string;
  name: string;
  query: UseQueryResult<GuardrailDetail, Error>;
  readOnly: boolean;
}) {
  const router = useRouter();
  const { endSession } = useSession();

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

  if (query.isPending) {
    return (
      <div className={styles.loading} aria-live="polite">
        <span aria-hidden="true" />
        <div>
          <p>Loading policy graph</p>
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
          <p>{readOnly ? "Version unavailable" : "Draft unavailable"}</p>
          <h1>{name}</h1>
          <span>{errorMessage(query.error, readOnly)}</span>
          {query.error instanceof ConsoleApiError && query.error.requestId ? (
            <code>Reference {query.error.requestId}</code>
          ) : null}
        </div>
        <div className={styles.errorActions}>
          <Link href="/guardrails">Back to guardrails</Link>
          <button type="button" onClick={() => void query.refetch()}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <GuardrailEditor
      detail={query.data}
      accessToken={accessToken}
      readOnly={readOnly}
      onAuthorizationError={handleAuthorizationError}
    />
  );
}

function errorMessage(error: Error, readOnly: boolean): string {
  if (error instanceof ConsoleApiError && error.httpStatus === 404) {
    return readOnly
      ? "This immutable version does not exist."
      : "This guardrail no longer has an editable draft.";
  }
  if (error instanceof ConsoleApiError && error.httpStatus === 0) {
    return "The console could not reach the gateway.";
  }
  return error.message || "The policy graph could not be loaded.";
}
