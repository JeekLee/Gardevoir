"use client";

import { useRef, useState } from "react";

import { deleteProvider, type ProviderSummary } from "@/src/entities/provider";
import { ConsoleApiError } from "@/src/shared/api";

import styles from "./providers-page.module.css";

export function ConfirmDelete({
  accessToken,
  provider,
  onClose,
  onDeleted,
  onAuthorizationError,
}: {
  accessToken: string;
  provider: ProviderSummary;
  onClose: () => void;
  onDeleted: () => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function setDialog(element: HTMLDialogElement | null) {
    dialogRef.current = element;
    if (element && !element.open) {
      element.showModal();
    }
  }

  async function remove() {
    setError(null);
    setIsSubmitting(true);
    try {
      await deleteProvider(accessToken, provider.id);
      onDeleted();
    } catch (caught) {
      if (
        caught instanceof ConsoleApiError &&
        (caught.httpStatus === 401 || caught.httpStatus === 403)
      ) {
        onAuthorizationError(caught);
        return;
      }
      if (caught instanceof ConsoleApiError) {
        const reference = caught.requestId ? ` Reference ${caught.requestId}.` : "";
        setError(`${caught.message}${reference}`);
      } else {
        setError("This provider could not be deleted. Try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <dialog
      ref={setDialog}
      className={`${styles.dialog} ${styles.confirmDialog}`}
      aria-labelledby="delete-provider-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!isSubmitting) onClose();
      }}
    >
      <div className={styles.confirmIcon} aria-hidden="true">
        !
      </div>
      <div className={styles.confirmCopy}>
        <p className={styles.dangerEyebrow}>Remove route</p>
        <h2 id="delete-provider-title">Delete {provider.name}?</h2>
        <p>
          Requests using {provider.models.length === 1 ? "its model" : "its models"} will no
          longer have an upstream route. This action cannot be undone.
        </p>
      </div>
      {error ? (
        <div className={styles.formError} role="alert">
          {error}
        </div>
      ) : null}
      <div className={styles.dialogActions}>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onClose}
          disabled={isSubmitting}
          autoFocus
        >
          Keep provider
        </button>
        <button
          className={styles.dangerButton}
          type="button"
          onClick={() => void remove()}
          disabled={isSubmitting}
        >
          {isSubmitting ? "Deleting…" : "Delete provider"}
        </button>
      </div>
    </dialog>
  );
}
