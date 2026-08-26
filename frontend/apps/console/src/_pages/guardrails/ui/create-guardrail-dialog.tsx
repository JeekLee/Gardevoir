"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";

import {
  createGuardrail,
  guardrailKeys,
} from "@/src/entities/guardrail";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import styles from "./guardrails-page.module.css";

const namePattern = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;

export function CreateGuardrailDialog({
  accessToken,
  onClose,
  onAuthorizationError,
}: {
  accessToken: string;
  onClose: () => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formErrorReference, setFormErrorReference] = useState<string | null>(
    null,
  );

  const createMutation = useMutation({
    mutationFn: (nextName: string) =>
      createGuardrail(accessToken, {
        name: nextName,
        graph: { nodes: [], edges: [] },
      }),
  });

  function setDialog(element: HTMLDialogElement | null) {
    dialogRef.current = element;
    if (element && !element.open) element.showModal();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFieldError(null);
    setFormError(null);
    setFormErrorReference(null);
    const nextName = name.trim();

    if (!namePattern.test(nextName)) {
      setFieldError(
        "영문 소문자와 숫자를 사용하고 단어는 하이픈 하나로 구분해 1~64자로 입력하세요.",
      );
      return;
    }

    try {
      const detail = await createMutation.mutateAsync(nextName);
      queryClient.setQueryData(guardrailKeys.draft(nextName), detail);
      await queryClient.invalidateQueries({ queryKey: guardrailKeys.list() });
      router.push(`/guardrails/${encodeURIComponent(detail.name)}`);
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
    if (
      error instanceof ConsoleApiError &&
      (error.code === "GUARDRAIL-006" || error.code === "GUARDRAIL-010")
    ) {
      setFieldError(
        error.code === "GUARDRAIL-006"
          ? "같은 이름의 가드레일이 이미 있습니다."
          : "가드레일 이름 형식이 올바르지 않습니다.",
      );
      return;
    }

    if (error instanceof ConsoleApiError) {
      setFormError(consoleErrorMessage(error));
      setFormErrorReference(consoleErrorReference(error));
    } else {
      setFormError(
        "가드레일을 만들지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
      );
      setFormErrorReference(null);
    }
  }

  return (
    <dialog
      ref={setDialog}
      className={styles.dialog}
      aria-labelledby="create-guardrail-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!createMutation.isPending) onClose();
      }}
    >
      <form className={styles.dialogForm} onSubmit={handleSubmit}>
        <div className={styles.dialogHeader}>
          <div>
            <p className={styles.eyebrow}>새 정책 그래프</p>
            <h2 id="create-guardrail-title">가드레일 이름 지정</h2>
            <p>
              이름은 URL과 요청 헤더에서 식별자로 사용됩니다. 만든 뒤 네 검사
              지점의 그래프를 구성하세요.
            </p>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            aria-label="가드레일 만들기 닫기"
            onClick={onClose}
            disabled={createMutation.isPending}
          >
            ×
          </button>
        </div>

        {formError ? (
          <div className={styles.formError} role="alert">
            <span>{formError}</span>
            {formErrorReference ? <code>{formErrorReference}</code> : null}
          </div>
        ) : null}

        <div className={styles.dialogBody}>
          <label className={styles.field}>
            <span>가드레일 이름</span>
            <input
              className={styles.slugInput}
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setFieldError(null);
              }}
              aria-invalid={Boolean(fieldError)}
              aria-describedby={
                fieldError ? "guardrail-name-error" : "guardrail-name-help"
              }
              placeholder="agent-action-control"
              autoComplete="off"
              maxLength={64}
              autoFocus
            />
            {fieldError ? (
              <small id="guardrail-name-error" className={styles.fieldError}>
                {fieldError}
              </small>
            ) : (
              <small id="guardrail-name-help" className={styles.fieldHelp}>
                영문 소문자, 숫자, 하이픈만 사용할 수 있습니다. 최종 형식은
                게이트웨이가 검증합니다.
              </small>
            )}
          </label>

          <div className={styles.checkpointPreview} aria-label="가드레일 검사 지점">
            <span>① 입력</span>
            <i aria-hidden="true" />
            <span className={styles.actionCheckpoint}>② 툴 결과</span>
            <i aria-hidden="true" />
            <span className={styles.actionCheckpoint}>④ 툴 호출</span>
            <i aria-hidden="true" />
            <span>③ 출력</span>
          </div>
          <small className={styles.checkpointPreviewNote}>
            번호는 검사 지점 ID이며, 미리보기는 실제 요청 실행 순서입니다.
          </small>
        </div>

        <div className={styles.dialogActions}>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onClose}
            disabled={createMutation.isPending}
          >
            취소
          </button>
          <button
            className={styles.primaryButton}
            type="submit"
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? "만드는 중…" : "그래프 만들기"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
