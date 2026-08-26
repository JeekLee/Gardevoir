"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef, useState } from "react";

import {
  apiKeyKeys,
  AppConnectionPanel,
  createApiKey,
  type ApiKeyCreated,
} from "@/src/entities/api-key";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import { isFutureDateTime, toAwareIso } from "../model/date-input";
import styles from "./api-keys-page.module.css";

export function CreateApiKeyDialog({
  accessToken,
  guardrailNames,
  onClose,
  onCreated,
  onAuthorizationError,
}: {
  accessToken: string;
  guardrailNames: string[];
  onClose: () => void;
  onCreated: (name: string) => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [expiryError, setExpiryError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [errorReference, setErrorReference] = useState<string | null>(null);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  const createMutation = useMutation({
    mutationFn: (input: { name: string; expiresAt?: string }) =>
      createApiKey(accessToken, input),
  });

  function setDialog(element: HTMLDialogElement | null) {
    dialogRef.current = element;
    if (element && !element.open) element.showModal();
  }

  function close() {
    setCreated(null);
    createMutation.reset();
    onClose();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNameError(null);
    setExpiryError(null);
    setFormError(null);
    setErrorReference(null);

    const nextName = name.trim();
    if (!nextName) {
      setNameError("API 키 이름을 입력하세요.");
      return;
    }
    if (expiresAt && !isFutureDateTime(expiresAt)) {
      setExpiryError("현재보다 이후인 만료 시각을 선택하세요.");
      return;
    }

    const expiryIso = toAwareIso(expiresAt);
    try {
      const result = await createMutation.mutateAsync({
        name: nextName,
        ...(expiryIso ? { expiresAt: expiryIso } : {}),
      });
      createMutation.reset();
      setCreated(result);
      onCreated(result.name);
      void queryClient.invalidateQueries({ queryKey: apiKeyKeys.list() });
    } catch (error) {
      handleCreateError(error);
    }
  }

  function handleCreateError(error: unknown) {
    if (
      error instanceof ConsoleApiError &&
      (error.httpStatus === 401 || error.httpStatus === 403)
    ) {
      onAuthorizationError(error);
      return;
    }
    if (error instanceof ConsoleApiError && error.code === "APIKEY-004") {
      setNameError("같은 이름의 API 키가 이미 있습니다.");
      return;
    }
    if (error instanceof ConsoleApiError && error.code === "APIKEY-010") {
      setExpiryError("현재보다 이후인 만료 시각을 선택하세요.");
      return;
    }
    if (error instanceof ConsoleApiError) {
      setFormError(consoleErrorMessage(error));
      setErrorReference(consoleErrorReference(error));
      return;
    }
    setFormError(
      "API 키를 만들지 못했습니다. 입력 내용과 연결 상태를 확인한 뒤 다시 시도하세요.",
    );
  }

  async function copyKey() {
    if (!created) return;
    setCopyState("idle");
    try {
      await navigator.clipboard.writeText(created.key);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <dialog
      ref={setDialog}
      className={`${styles.dialog} ${created ? styles.revealDialog : ""}`}
      aria-labelledby="create-api-key-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!createMutation.isPending) close();
      }}
    >
      {created ? (
        <div className={styles.reveal}>
          <div className={styles.dialogHeader}>
            <div>
              <p className={styles.eyebrow}>발급 완료 · 1회 공개</p>
              <h2 id="create-api-key-title">{created.name} API 키</h2>
              <p>평문 키를 안전한 비밀 저장소에 복사한 뒤 앱을 연결하세요.</p>
            </div>
            <button
              className={styles.closeButton}
              type="button"
              onClick={close}
              aria-label="발급된 API 키 닫기"
            >
              ×
            </button>
          </div>

          <div className={styles.secretWarning} role="alert">
            <span aria-hidden="true">!</span>
            <strong>지금 저장하세요 — 이 키는 다시 볼 수 없습니다.</strong>
          </div>

          <div className={styles.secretBox}>
            <code>{created.key}</code>
            <button
              type="button"
              onClick={() => void copyKey()}
              aria-label={`${created.name} 평문 API 키 복사`}
            >
              {copyState === "copied" ? "복사됨" : "키 복사"}
            </button>
          </div>
          <p className={styles.copyFeedback} aria-live="polite">
            {copyState === "copied"
              ? "평문 API 키를 클립보드에 복사했습니다."
              : copyState === "failed"
                ? "복사하지 못했습니다. 키를 직접 선택해 복사하세요."
                : ""}
          </p>

          <AppConnectionPanel
            guardrailNames={guardrailNames}
            apiKey={created.key}
            title="이 키로 앱 연결"
            description="아래 스니펫은 방금 만든 키를 사용합니다. 다이얼로그를 닫으면 다시 만들 수 없습니다."
          />

          <div className={styles.dialogActions}>
            <button className={styles.primaryButton} type="button" onClick={close}>
              키를 저장했습니다
            </button>
          </div>
        </div>
      ) : (
        <form className={styles.dialogForm} onSubmit={handleSubmit}>
          <div className={styles.dialogHeader}>
            <div>
              <p className={styles.eyebrow}>새 앱 크레덴셜</p>
              <h2 id="create-api-key-title">새 API 키</h2>
              <p>용도를 알아볼 수 있는 이름과 선택 만료 시각을 지정하세요.</p>
            </div>
            <button
              className={styles.closeButton}
              type="button"
              onClick={close}
              disabled={createMutation.isPending}
              aria-label="API 키 만들기 닫기"
            >
              ×
            </button>
          </div>

          {formError ? (
            <div className={styles.formError} role="alert">
              <span>{formError}</span>
              {errorReference ? <code>{errorReference}</code> : null}
            </div>
          ) : null}

          <div className={styles.dialogBody}>
            <label className={styles.field}>
              <span>이름</span>
              <input
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setNameError(null);
                }}
                aria-invalid={Boolean(nameError)}
                aria-describedby={nameError ? "api-key-name-error" : undefined}
                placeholder="production-chat"
                maxLength={255}
                autoComplete="off"
                autoFocus
              />
              {nameError ? (
                <small id="api-key-name-error" className={styles.fieldError}>
                  {nameError}
                </small>
              ) : null}
            </label>

            <label className={styles.field}>
              <span>
                만료 <em>선택</em>
              </span>
              <input
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => {
                  setExpiresAt(event.target.value);
                  setExpiryError(null);
                }}
                aria-invalid={Boolean(expiryError)}
                aria-describedby={
                  expiryError ? "api-key-expiry-error" : "api-key-expiry-help"
                }
              />
              {expiryError ? (
                <small id="api-key-expiry-error" className={styles.fieldError}>
                  {expiryError}
                </small>
              ) : (
                <small id="api-key-expiry-help" className={styles.fieldHelp}>
                  비워 두면 만료되지 않습니다. 입력한 로컬 시각을 시간대가 포함된
                  값으로 변환해 저장합니다.
                </small>
              )}
            </label>
          </div>

          <div className={styles.dialogActions}>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={close}
              disabled={createMutation.isPending}
            >
              취소
            </button>
            <button
              className={styles.primaryButton}
              type="submit"
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? "만드는 중…" : "API 키 만들기"}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
