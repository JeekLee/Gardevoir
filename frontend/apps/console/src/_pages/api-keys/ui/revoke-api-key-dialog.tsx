"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  apiKeyKeys,
  type ApiKeySummary,
  revokeApiKey,
} from "@/src/entities/api-key";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";
import { ConfirmDialog } from "@/src/shared/ui/confirm-dialog";

export function RevokeApiKeyDialog({
  accessToken,
  apiKey,
  onClose,
  onRevoked,
  onAuthorizationError,
}: {
  accessToken: string;
  apiKey: ApiKeySummary;
  onClose: () => void;
  onRevoked: () => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [errorReference, setErrorReference] = useState<string | null>(null);
  const revokeMutation = useMutation({
    mutationFn: () => revokeApiKey(accessToken, apiKey.id),
  });

  async function revoke() {
    setError(null);
    setErrorReference(null);
    try {
      await revokeMutation.mutateAsync();
      void queryClient.invalidateQueries({ queryKey: apiKeyKeys.list() });
      onRevoked();
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
          "API 키를 폐기하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
        );
      }
    }
  }

  return (
    <ConfirmDialog
      id="revoke-api-key"
      eyebrow="앱 크레덴셜 폐기"
      title={`${apiKey.name} API 키를 폐기할까요?`}
      description={
        <p>
          이 키를 사용하는 앱 요청은 즉시 인증에 실패합니다. 폐기한 키는 다시
          활성화할 수 없습니다.
        </p>
      }
      cancelLabel="API 키 유지"
      confirmLabel={revokeMutation.isPending ? "폐기하는 중…" : "API 키 폐기"}
      isSubmitting={revokeMutation.isPending}
      error={
        error ? (
          <>
            <span>{error}</span>
            {errorReference ? <code>{errorReference}</code> : null}
          </>
        ) : null
      }
      onClose={onClose}
      onConfirm={() => void revoke()}
    />
  );
}
