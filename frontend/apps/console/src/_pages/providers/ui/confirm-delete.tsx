"use client";

import { useState } from "react";

import { deleteProvider, type ProviderSummary } from "@/src/entities/provider";
import { ConsoleApiError } from "@/src/shared/api";
import { ConfirmDialog } from "@/src/shared/ui/confirm-dialog";

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
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

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
    <ConfirmDialog
      id="delete-provider"
      eyebrow="Remove route"
      title={`Delete ${provider.name}?`}
      description={
        <p>
          Requests using {provider.models.length === 1 ? "its model" : "its models"} will no
          longer have an upstream route. This action cannot be undone.
        </p>
      }
      cancelLabel="Keep provider"
      confirmLabel={isSubmitting ? "Deleting…" : "Delete provider"}
      isSubmitting={isSubmitting}
      error={error}
      onClose={onClose}
      onConfirm={() => void remove()}
    />
  );
}
