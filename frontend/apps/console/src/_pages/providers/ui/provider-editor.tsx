"use client";

import {
  type FormEvent,
  type KeyboardEvent,
  useRef,
  useState,
} from "react";

import {
  createProvider,
  type CreateProviderInput,
  type ProviderSummary,
  type UpdateProviderInput,
  updateProvider,
} from "@/src/entities/provider";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";
import { ConfirmDialog } from "@/src/shared/ui/confirm-dialog";

import { providerApiKeyChange } from "../model/api-key-change";
import styles from "./providers-page.module.css";

type FieldErrors = Partial<Record<"name" | "baseUrl" | "models", string>>;

export function ProviderEditor({
  accessToken,
  provider,
  onClose,
  onSaved,
  onAuthorizationError,
}: {
  accessToken: string;
  provider: ProviderSummary | null;
  onClose: () => void;
  onSaved: (provider: ProviderSummary) => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(provider?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(provider?.baseUrl ?? "");
  const [apiKey, setApiKey] = useState("");
  const [removeApiKey, setRemoveApiKey] = useState(false);
  const [isConfirmingKeyRemoval, setIsConfirmingKeyRemoval] = useState(false);
  const [models, setModels] = useState<string[]>(provider?.models ?? []);
  const [modelDraft, setModelDraft] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [formErrorReference, setFormErrorReference] = useState<string | null>(
    null,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  function setDialog(element: HTMLDialogElement | null) {
    dialogRef.current = element;
    if (element && !element.open) {
      element.showModal();
    }
  }

  function commitModelDraft() {
    const additions = modelDraft
      .split(",")
      .map((model) => model.trim())
      .filter(Boolean);

    if (additions.length > 0) {
      setModels((current) => [...new Set([...current, ...additions])]);
      setFieldErrors((current) => ({ ...current, models: undefined }));
    }
    setModelDraft("");
    return additions;
  }

  function handleModelKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commitModelDraft();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setFormErrorReference(null);

    const pendingModels = modelDraft
      .split(",")
      .map((model) => model.trim())
      .filter(Boolean);
    const nextModels = [...new Set([...models, ...pendingModels])];
    const nextName = name.trim();
    const nextBaseUrl = baseUrl.trim();
    const nextErrors: FieldErrors = {};

    if (!nextName) {
      nextErrors.name = "프로바이더 이름을 입력하세요.";
    }
    if (!isHttpUrl(nextBaseUrl)) {
      nextErrors.baseUrl = "http:// 또는 https://로 시작하는 전체 URL을 입력하세요.";
    }
    if (nextModels.length === 0) {
      nextErrors.models = "모델을 하나 이상 추가하세요.";
    }

    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    const commonInput = {
      name: nextName,
      baseUrl: nextBaseUrl,
      models: nextModels,
    };
    const apiKeyChange = providerApiKeyChange({
      isEditing: provider !== null,
      draft: apiKey,
      removeConfirmed: removeApiKey,
    });

    setIsSubmitting(true);
    try {
      let saved: ProviderSummary;
      if (provider) {
        const input: UpdateProviderInput = {
          ...commonInput,
          apiKey: apiKeyChange,
        };
        saved = await updateProvider(accessToken, provider.id, input);
      } else {
        const input: CreateProviderInput = {
          ...commonInput,
          apiKey: apiKeyChange ?? "",
        };
        saved = await createProvider(accessToken, input);
      }
      onSaved(saved);
    } catch (caught) {
      if (
        caught instanceof ConsoleApiError &&
        (caught.httpStatus === 401 || caught.httpStatus === 403)
      ) {
        onAuthorizationError(caught);
        return;
      }
      if (caught instanceof ConsoleApiError) {
        applyGatewayError(
          caught,
          setFieldErrors,
          setFormError,
          setFormErrorReference,
        );
      } else {
        setFormError("프로바이더를 저장하지 못했습니다.");
        setFormErrorReference(null);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const editorDialog = (
    <dialog
      ref={setDialog}
      className={styles.dialog}
      aria-labelledby="provider-editor-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!isSubmitting) onClose();
      }}
    >
      <form className={styles.editor} onSubmit={handleSubmit}>
        <div className={styles.dialogHeader}>
          <div>
            <p className={styles.eyebrow}>{provider ? "경로 수정" : "새 경로"}</p>
            <h2 id="provider-editor-title">
              {provider ? `${provider.name} 수정` : "프로바이더 추가"}
            </h2>
            <p>
              OpenAI 호환 엔드포인트 하나와 해당 엔드포인트가 제공할 모델을
              연결하세요.
            </p>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            aria-label="프로바이더 편집기 닫기"
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

        <div className={styles.formBody}>
          <label className={styles.field}>
            <span>프로바이더 이름</span>
            <input
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setFieldErrors((current) => ({ ...current, name: undefined }));
              }}
              aria-invalid={Boolean(fieldErrors.name)}
              aria-describedby={fieldErrors.name ? "provider-name-error" : undefined}
              placeholder="OpenAI 운영"
              maxLength={255}
              autoFocus
            />
            {fieldErrors.name ? (
              <small id="provider-name-error" className={styles.fieldError}>
                {fieldErrors.name}
              </small>
            ) : null}
          </label>

          <label className={styles.field}>
            <span>기본 URL</span>
            <input
              className={styles.monoInput}
              type="url"
              value={baseUrl}
              onChange={(event) => {
                setBaseUrl(event.target.value);
                setFieldErrors((current) => ({ ...current, baseUrl: undefined }));
              }}
              aria-invalid={Boolean(fieldErrors.baseUrl)}
              aria-describedby={fieldErrors.baseUrl ? "provider-url-error" : "provider-url-help"}
              placeholder="https://api.openai.com/v1"
            />
            {fieldErrors.baseUrl ? (
              <small id="provider-url-error" className={styles.fieldError}>
                {fieldErrors.baseUrl}
              </small>
            ) : (
              <small id="provider-url-help" className={styles.fieldHelp}>
                프로바이더가 요구하는 버전 경로까지 포함하세요.
              </small>
            )}
          </label>

          <div className={styles.field}>
            <label htmlFor="provider-api-key">
              API 키 <em>선택</em>
            </label>
            <input
              id="provider-api-key"
              className={styles.monoInput}
              type="password"
              value={apiKey}
              onChange={(event) => {
                setApiKey(event.target.value);
                setRemoveApiKey(false);
              }}
              autoComplete="new-password"
              disabled={removeApiKey}
              placeholder={
                removeApiKey
                  ? "저장하면 키가 삭제됩니다"
                  : provider?.hasApiKey
                    ? "현재 키는 표시되지 않습니다"
                    : "sk-…"
              }
            />
            <small className={styles.fieldHelp}>
              {removeApiKey
                ? "변경 내용을 저장하면 기존 키를 삭제합니다."
                : provider?.hasApiKey
                  ? "현재 키는 다시 표시할 수 없습니다. 유지하려면 비워 두고, 교체하려면 새 키를 입력하세요."
                  : "로컬 서버나 키가 필요 없는 모델 서버라면 비워 두세요."}
            </small>
            {provider?.hasApiKey ? (
              <button
                className={removeApiKey ? styles.undoKeyButton : styles.removeKeyButton}
                type="button"
                onClick={() => {
                  if (removeApiKey) {
                    setRemoveApiKey(false);
                  } else {
                    setIsConfirmingKeyRemoval(true);
                  }
                }}
              >
                {removeApiKey ? "저장된 키 유지" : "저장된 키 삭제"}
              </button>
            ) : null}
          </div>

          <div className={styles.field}>
            <span>모델</span>
            <div
              className={`${styles.modelField} ${fieldErrors.models ? styles.invalid : ""}`}
            >
              {models.map((model) => (
                <span className={styles.modelToken} key={model}>
                  <code>{model}</code>
                  <button
                    type="button"
                    onClick={() => setModels((current) => current.filter((item) => item !== model))}
                    aria-label={`${model} 모델 삭제`}
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                value={modelDraft}
                onChange={(event) => setModelDraft(event.target.value)}
                onKeyDown={handleModelKeyDown}
                onBlur={commitModelDraft}
                aria-invalid={Boolean(fieldErrors.models)}
                aria-describedby={fieldErrors.models ? "provider-models-error" : "provider-models-help"}
                placeholder={models.length ? "다른 모델 추가" : "gpt-5.2, text-embedding-3-large"}
              />
            </div>
            {fieldErrors.models ? (
              <small id="provider-models-error" className={styles.fieldError}>
                {fieldErrors.models}
              </small>
            ) : (
              <small id="provider-models-help" className={styles.fieldHelp}>
                모델마다 Enter 또는 쉼표를 입력하세요. 한 모델은 하나의
                프로바이더에만 연결할 수 있습니다.
              </small>
            )}
          </div>
        </div>

        <div className={styles.dialogActions}>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
          >
            취소
          </button>
          <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>
            {isSubmitting ? "경로 저장 중…" : provider ? "변경 저장" : "프로바이더 추가"}
          </button>
        </div>
      </form>
    </dialog>
  );

  return (
    <>
      {editorDialog}
      {isConfirmingKeyRemoval ? (
        <ConfirmDialog
          id="remove-provider-key"
          eyebrow="인증 정보 삭제"
          title={`${provider?.name ?? "이 프로바이더"}의 저장된 키를 삭제할까요?`}
          description={
            <p>
              엔드포인트가 키 없는 접근을 허용하지 않으면 이 프로바이더로 전달한
              요청이 실패할 수 있습니다. 프로바이더를 저장할 때 키를 삭제합니다.
            </p>
          }
          cancelLabel="키 유지"
          confirmLabel="키 삭제"
          onClose={() => setIsConfirmingKeyRemoval(false)}
          onConfirm={() => {
            setApiKey("");
            setRemoveApiKey(true);
            setIsConfirmingKeyRemoval(false);
          }}
        />
      ) : null}
    </>
  );
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function applyGatewayError(
  error: ConsoleApiError,
  setFieldErrors: (updater: (current: FieldErrors) => FieldErrors) => void,
  setFormError: (message: string) => void,
  setFormErrorReference: (reference: string | null) => void,
) {
  if (error.code === "PROVIDER-002") {
    setFieldErrors((current) => ({
      ...current,
      name: "같은 이름의 프로바이더가 이미 있습니다.",
    }));
    return;
  }
  if (error.code === "PROVIDER-003") {
    const model =
      typeof error.details?.model === "string"
        ? `“${error.details.model}” 모델`
        : "이 모델";
    setFieldErrors((current) => ({
      ...current,
      models: `${model}은(는) 다른 프로바이더에 이미 연결되어 있습니다.`,
    }));
    return;
  }
  if (error.code === "PROVIDER-004") {
    setFieldErrors((current) => ({
      ...current,
      models: "모델을 하나 이상 추가하세요.",
    }));
    return;
  }

  setFormError(consoleErrorMessage(error));
  setFormErrorReference(consoleErrorReference(error));
}
