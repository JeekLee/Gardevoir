"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  deleteGuardrail,
  guardrailKeys,
} from "@/src/entities/guardrail";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";
import { ConfirmDialog } from "@/src/shared/ui/confirm-dialog";

export function DeleteGuardrailDialog({
  accessToken,
  name,
  onClose,
  onDeleted,
  onAuthorizationError,
}: {
  accessToken: string;
  name: string;
  onClose: () => void;
  onDeleted: () => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [errorReference, setErrorReference] = useState<string | null>(null);
  const deleteMutation = useMutation({
    mutationFn: () => deleteGuardrail(accessToken, name),
  });

  async function remove() {
    setError(null);
    setErrorReference(null);
    try {
      await deleteMutation.mutateAsync();
      queryClient.removeQueries({ queryKey: guardrailKeys.item(name) });
      await queryClient.invalidateQueries({ queryKey: guardrailKeys.list() });
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
        setError("가드레일을 삭제하지 못했습니다.");
      }
    }
  }

  return (
    <ConfirmDialog
      id={`delete-guardrail-${name}`}
      eyebrow="가드레일 영구 삭제"
      title={`${name} 가드레일을 삭제할까요?`}
      description={
        <p>
          이 가드레일을 삭제하면 초안과 모든 발행 버전이 영구히 사라지고, 이
          이름으로 흐르던 요청은 더 이상 검사되지 않습니다. 되돌릴 수 없습니다.
        </p>
      }
      cancelLabel="가드레일 유지"
      confirmLabel={deleteMutation.isPending ? "삭제하는 중…" : "가드레일 삭제"}
      isSubmitting={deleteMutation.isPending}
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
