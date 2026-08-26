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
import { ConsoleApiError } from "@/src/shared/api";
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

    const pendingModels = modelDraft
      .split(",")
      .map((model) => model.trim())
      .filter(Boolean);
    const nextModels = [...new Set([...models, ...pendingModels])];
    const nextName = name.trim();
    const nextBaseUrl = baseUrl.trim();
    const nextErrors: FieldErrors = {};

    if (!nextName) {
      nextErrors.name = "Enter a provider name.";
    }
    if (!isHttpUrl(nextBaseUrl)) {
      nextErrors.baseUrl = "Enter a complete http:// or https:// URL.";
    }
    if (nextModels.length === 0) {
      nextErrors.models = "Add at least one model.";
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
        applyGatewayError(caught, setFieldErrors, setFormError);
      } else {
        setFormError("This provider could not be saved. Try again.");
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
            <p className={styles.eyebrow}>{provider ? "Edit route" : "New route"}</p>
            <h2 id="provider-editor-title">
              {provider ? `Update ${provider.name}` : "Add a provider"}
            </h2>
            <p>
              Connect one OpenAI-compatible endpoint to the models it serves.
            </p>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            aria-label="Close provider editor"
          >
            ×
          </button>
        </div>

        {formError ? (
          <div className={styles.formError} role="alert">
            {formError}
          </div>
        ) : null}

        <div className={styles.formBody}>
          <label className={styles.field}>
            <span>Provider name</span>
            <input
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setFieldErrors((current) => ({ ...current, name: undefined }));
              }}
              aria-invalid={Boolean(fieldErrors.name)}
              aria-describedby={fieldErrors.name ? "provider-name-error" : undefined}
              placeholder="OpenAI production"
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
            <span>Base URL</span>
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
                Include the version path expected by the provider.
              </small>
            )}
          </label>

          <div className={styles.field}>
            <label htmlFor="provider-api-key">
              API key <em>Optional</em>
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
                  ? "Key will be removed"
                  : provider?.hasApiKey
                    ? "Current key is hidden"
                    : "sk-…"
              }
            />
            <small className={styles.fieldHelp}>
              {removeApiKey
                ? "The saved key will be removed when you save these changes."
                : provider?.hasApiKey
                  ? "The current key cannot be shown. Leave this empty to keep it, or enter a replacement."
                  : "Leave empty for a local or keyless model server."}
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
                {removeApiKey ? "Keep saved key" : "Remove saved key"}
              </button>
            ) : null}
          </div>

          <div className={styles.field}>
            <span>Models</span>
            <div
              className={`${styles.modelField} ${fieldErrors.models ? styles.invalid : ""}`}
            >
              {models.map((model) => (
                <span className={styles.modelToken} key={model}>
                  <code>{model}</code>
                  <button
                    type="button"
                    onClick={() => setModels((current) => current.filter((item) => item !== model))}
                    aria-label={`Remove ${model}`}
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
                placeholder={models.length ? "Add another model" : "gpt-5.2, text-embedding-3-large"}
              />
            </div>
            {fieldErrors.models ? (
              <small id="provider-models-error" className={styles.fieldError}>
                {fieldErrors.models}
              </small>
            ) : (
              <small id="provider-models-help" className={styles.fieldHelp}>
                Press Enter or comma after each model. A model can belong to only one provider.
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
            Cancel
          </button>
          <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving route…" : provider ? "Save changes" : "Add provider"}
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
          eyebrow="Remove credential"
          title={`Remove the saved key for ${provider?.name ?? "this provider"}?`}
          description={
            <p>
              Requests routed to this provider may fail unless its endpoint accepts
              keyless access. The key is removed only after you save the provider.
            </p>
          }
          cancelLabel="Keep key"
          confirmLabel="Remove key"
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
) {
  if (error.code === "PROVIDER-002") {
    setFieldErrors((current) => ({
      ...current,
      name: "Another provider already uses this name.",
    }));
    return;
  }
  if (error.code === "PROVIDER-003") {
    const model = typeof error.details?.model === "string" ? ` “${error.details.model}”` : "";
    setFieldErrors((current) => ({
      ...current,
      models: `Model${model} is already routed through another provider.`,
    }));
    return;
  }
  if (error.code === "PROVIDER-004") {
    setFieldErrors((current) => ({
      ...current,
      models: "Add at least one model.",
    }));
    return;
  }

  const reference = error.requestId ? ` Reference ${error.requestId}.` : "";
  setFormError(`${error.message}${reference}`);
}
