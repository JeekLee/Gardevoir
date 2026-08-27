"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef, useState } from "react";

import {
  apiKeyKeys,
  type ApiKeySummary,
  updateApiKey,
} from "@/src/entities/api-key";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import {
  isFutureDateTime,
  toAwareIso,
  toDateTimeInputValue,
} from "../model/date-input";
import styles from "./api-keys-page.module.css";

export function EditApiKeyDialog({
  accessToken,
  apiKey,
  onClose,
  onSaved,
  onAuthorizationError,
}: {
  accessToken: string;
  apiKey: ApiKeySummary;
  onClose: () => void;
  onSaved: (apiKey: ApiKeySummary) => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(apiKey.name);
  const [expiresAt, setExpiresAt] = useState(
    toDateTimeInputValue(apiKey.expiresAt),
  );
  const [nameError, setNameError] = useState<string | null>(null);
  const [expiryError, setExpiryError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [errorReference, setErrorReference] = useState<string | null>(null);
  const updateMutation = useMutation({
    mutationFn: (input: { name: string; expiresAt: string | null }) =>
      updateApiKey(accessToken, apiKey.id, input),
  });

  function setDialog(element: HTMLDialogElement | null) {
    dialogRef.current = element;
    if (element && !element.open) element.showModal();
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

    try {
      const saved = await updateMutation.mutateAsync({
        name: nextName,
        expiresAt: toAwareIso(expiresAt),
      });
      void queryClient.invalidateQueries({ queryKey: apiKeyKeys.list() });
      onSaved(saved);
    } catch (error) {
      handleUpdateError(error);
    }
  }

  function handleUpdateError(error: unknown) {
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
    setFormError("API 키를 수정하지 못했습니다.");
  }

  return (
    <dialog
      ref={setDialog}
      className={styles.dialog}
      aria-labelledby="edit-api-key-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!updateMutation.isPending) onClose();
      }}
    >
      <form className={styles.dialogForm} onSubmit={handleSubmit}>
        <div className={styles.dialogHeader}>
          <div>
            <p className={styles.eyebrow}>크레덴셜 설정</p>
            <h2 id="edit-api-key-title">{apiKey.name} 수정</h2>
            <p>키 값은 바뀌지 않습니다. 이름과 만료 시각만 수정합니다.</p>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            onClick={onClose}
            disabled={updateMutation.isPending}
            aria-label="API 키 수정 닫기"
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
              aria-describedby={nameError ? "edit-api-key-name-error" : undefined}
              maxLength={255}
              autoFocus
            />
            {nameError ? (
              <small id="edit-api-key-name-error" className={styles.fieldError}>
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
                expiryError
                  ? "edit-api-key-expiry-error"
                  : "edit-api-key-expiry-help"
              }
            />
            {expiryError ? (
              <small id="edit-api-key-expiry-error" className={styles.fieldError}>
                {expiryError}
              </small>
            ) : (
              <small id="edit-api-key-expiry-help" className={styles.fieldHelp}>
                비워 두고 저장하면 만료 시각을 제거합니다.
              </small>
            )}
          </label>
        </div>

        <div className={styles.dialogActions}>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onClose}
            disabled={updateMutation.isPending}
          >
            취소
          </button>
          <button
            className={styles.primaryButton}
            type="submit"
            disabled={updateMutation.isPending}
          >
            {updateMutation.isPending ? "저장하는 중…" : "변경 저장"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
