"use client";

import { type ReactNode, useRef } from "react";

import styles from "./confirm-dialog.module.css";

export function ConfirmDialog({
  id,
  eyebrow,
  title,
  description,
  confirmLabel,
  cancelLabel,
  isSubmitting = false,
  error,
  onConfirm,
  onClose,
}: {
  id: string;
  eyebrow: string;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  isSubmitting?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  function setDialog(element: HTMLDialogElement | null) {
    dialogRef.current = element;
    if (element && !element.open) {
      element.showModal();
    }
  }

  return (
    <dialog
      ref={setDialog}
      className={styles.dialog}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      onCancel={(event) => {
        event.preventDefault();
        if (!isSubmitting) onClose();
      }}
    >
      <div className={styles.icon} aria-hidden="true">
        !
      </div>
      <div className={styles.copy}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h2 id={`${id}-title`}>{title}</h2>
        <div id={`${id}-description`} className={styles.description}>
          {description}
        </div>
      </div>
      {error ? (
        <div className={styles.error} role="alert">
          {error}
        </div>
      ) : null}
      <div className={styles.actions}>
        <button
          className={styles.cancel}
          type="button"
          onClick={onClose}
          disabled={isSubmitting}
          autoFocus
        >
          {cancelLabel}
        </button>
        <button
          className={styles.confirm}
          type="button"
          onClick={onConfirm}
          disabled={isSubmitting}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
