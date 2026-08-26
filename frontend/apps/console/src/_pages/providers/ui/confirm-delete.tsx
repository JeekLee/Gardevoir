"use client";

import { useState } from "react";

import { deleteProvider, type ProviderSummary } from "@/src/entities/provider";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";
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
  const [errorReference, setErrorReference] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function remove() {
    setError(null);
    setErrorReference(null);
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
        setError(consoleErrorMessage(caught));
        setErrorReference(consoleErrorReference(caught));
      } else {
        setError(
          "프로바이더를 삭제하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <ConfirmDialog
      id="delete-provider"
      eyebrow="업스트림 경로 삭제"
      title={`${provider.name} 프로바이더를 삭제할까요?`}
      description={
        <p>
          이 프로바이더의 모델 {provider.models.length}개를 사용하는 요청은 더 이상
          업스트림 경로를 찾을 수 없습니다. 이 작업은 되돌릴 수 없습니다.
        </p>
      }
      cancelLabel="프로바이더 유지"
      confirmLabel={isSubmitting ? "삭제하는 중…" : "프로바이더 삭제"}
      isSubmitting={isSubmitting}
      error={
        error ? (
          <>
            <span>{error}</span>
            {errorReference ? <code>{errorReference}</code> : null}
          </>
        ) : null
      }
      onClose={onClose}
      onConfirm={() => void remove()}
    />
  );
}
