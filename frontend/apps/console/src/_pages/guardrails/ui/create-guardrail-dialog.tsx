"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";

import {
  createGuardrail,
  guardrailKeys,
} from "@/src/entities/guardrail";
import { ConsoleApiError } from "@/src/shared/api";

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
    const nextName = name.trim();

    if (!namePattern.test(nextName)) {
      setFieldError(
        "Use 1–64 lowercase letters, numbers, and single hyphen-separated words.",
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
          ? "A guardrail with this name already exists."
          : "This name is not a valid guardrail slug.",
      );
      return;
    }

    setFormError(formatError(error));
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
            <p className={styles.eyebrow}>New policy graph</p>
            <h2 id="create-guardrail-title">Name the guardrail</h2>
            <p>
              The name becomes a URL and request-header slug. You can build the
              four-checkpoint graph next.
            </p>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            aria-label="Close guardrail creation"
            onClick={onClose}
            disabled={createMutation.isPending}
          >
            ×
          </button>
        </div>

        {formError ? (
          <div className={styles.formError} role="alert">
            {formError}
          </div>
        ) : null}

        <div className={styles.dialogBody}>
          <label className={styles.field}>
            <span>Guardrail slug</span>
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
                Lowercase letters, numbers, and hyphens. The gateway validates
                the final name.
              </small>
            )}
          </label>

          <div className={styles.checkpointPreview} aria-label="Guardrail checkpoints">
            <span>① Input</span>
            <i aria-hidden="true" />
            <span className={styles.actionCheckpoint}>② Tool result</span>
            <i aria-hidden="true" />
            <span className={styles.actionCheckpoint}>④ Tool call</span>
            <i aria-hidden="true" />
            <span>③ Output</span>
          </div>
        </div>

        <div className={styles.dialogActions}>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onClose}
            disabled={createMutation.isPending}
          >
            Cancel
          </button>
          <button
            className={styles.primaryButton}
            type="submit"
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? "Creating…" : "Create graph"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function formatError(error: unknown): string {
  if (!(error instanceof ConsoleApiError)) {
    return "This guardrail could not be created. Try again.";
  }
  const reference = error.requestId ? ` Reference ${error.requestId}.` : "";
  return `${error.message}${reference}`;
}
