"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import {
  type ProviderSummary,
  useProviders,
} from "@/src/entities/provider";
import { useSession } from "@/src/entities/session";
import { ConsoleApiError } from "@/src/shared/api";

import { ConfirmDelete } from "./confirm-delete";
import { ProviderEditor } from "./provider-editor";
import styles from "./providers-page.module.css";

export function ProvidersPage() {
  const { session } = useSession();

  if (!session) {
    return null;
  }

  return (
    <ProviderWorkspace
      accessToken={session.tokens.accessToken}
      operatorName={session.user.name}
    />
  );
}

function ProviderWorkspace({
  accessToken,
  operatorName,
}: {
  accessToken: string;
  operatorName: string;
}) {
  const router = useRouter();
  const { endSession } = useSession();
  const [editor, setEditor] = useState<ProviderSummary | null | undefined>();
  const [deleting, setDeleting] = useState<ProviderSummary | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const handleAuthorizationError = useCallback(
    (error: ConsoleApiError) => {
      endSession();
      router.replace(
        error.httpStatus === 403
          ? "/login?reason=forbidden"
          : "/login?reason=expired",
      );
    },
    [endSession, router],
  );

  const { data, error, isLoading, reload } = useProviders(
    accessToken,
    handleAuthorizationError,
  );

  async function afterSaved(provider: ProviderSummary) {
    const wasEditing = editor !== null;
    setEditor(undefined);
    setNotice(
      wasEditing
        ? `${provider.name} was updated.`
        : `${provider.name} is ready to route requests.`,
    );
    await reload();
  }

  async function afterDeleted() {
    const name = deleting?.name ?? "Provider";
    setDeleting(null);
    setNotice(`${name} was deleted.`);
    await reload();
  }

  return (
    <section className={styles.page} aria-labelledby="providers-title">
      <div className={styles.pageHeader}>
        <div className={styles.headingBlock}>
          <p className={styles.eyebrow}>Upstream routing</p>
          <h1 id="providers-title">Model gateways</h1>
          <p>
            Register the OpenAI-compatible endpoints that protected requests may
            pass through.
          </p>
        </div>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => {
            setNotice(null);
            setEditor(null);
          }}
        >
          <span aria-hidden="true">＋</span>
          Add provider
        </button>
      </div>

      <div className={styles.statusBar}>
        <div className={styles.routeStatus}>
          <span className={styles.liveDot} aria-hidden="true" />
          <span>
            <strong>{data?.total ?? 0}</strong> provider{data?.total === 1 ? "" : "s"}
          </span>
        </div>
        <p>
          Signed in as <strong>{operatorName}</strong>
        </p>
      </div>

      {notice ? (
        <div className={styles.notice} role="status">
          <span aria-hidden="true">✓</span>
          {notice}
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss notification">
            ×
          </button>
        </div>
      ) : null}

      <div className={styles.content} aria-busy={isLoading}>
        {isLoading ? <ProviderSkeleton /> : null}
        {!isLoading && error ? (
          <ErrorState error={error} onRetry={() => void reload()} />
        ) : null}
        {!isLoading && !error && data?.items.length === 0 ? (
          <EmptyState onAdd={() => setEditor(null)} />
        ) : null}
        {!isLoading && !error && data && data.items.length > 0 ? (
          <div className={styles.providerGrid}>
            {data.items.map((provider, index) => (
              <ProviderCard
                key={provider.id}
                provider={provider}
                order={index + 1}
                onEdit={() => {
                  setNotice(null);
                  setEditor(provider);
                }}
                onDelete={() => {
                  setNotice(null);
                  setDeleting(provider);
                }}
              />
            ))}
          </div>
        ) : null}
      </div>

      {editor !== undefined ? (
        <ProviderEditor
          key={editor?.id ?? "new-provider"}
          accessToken={accessToken}
          provider={editor}
          onClose={() => setEditor(undefined)}
          onSaved={(provider) => void afterSaved(provider)}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}

      {deleting ? (
        <ConfirmDelete
          key={deleting.id}
          accessToken={accessToken}
          provider={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => void afterDeleted()}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}
    </section>
  );
}

function ProviderCard({
  provider,
  order,
  onEdit,
  onDelete,
}: {
  provider: ProviderSummary;
  order: number;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <article className={styles.gateCard}>
      <span className={styles.gateIndex} aria-hidden="true">
        {String(order).padStart(2, "0")}
      </span>
      <span className={styles.gateCore} aria-hidden="true" />

      <div className={styles.cardHeader}>
        <div>
          <p>Provider</p>
          <h2>{provider.name}</h2>
        </div>
        <span className={styles.activeBadge}>
          <span aria-hidden="true" />
          {provider.hasApiKey ? "Key connected" : "Keyless route"}
        </span>
      </div>

      <div className={styles.routePath}>
        <span>Gateway</span>
        <span className={styles.routeLine} aria-hidden="true">
          <i />
        </span>
        <code title={provider.baseUrl}>{provider.baseUrl}</code>
      </div>

      <div className={styles.models}>
        <p>{provider.models.length === 1 ? "Model" : "Models"}</p>
        <div>
          {provider.models.map((model) => (
            <code key={model}>{model}</code>
          ))}
        </div>
      </div>

      <footer className={styles.cardFooter}>
        <p>
          Updated <time dateTime={provider.updatedAt}>{formatDate(provider.updatedAt)}</time>
        </p>
        <div className={styles.cardActions}>
          <button type="button" onClick={onEdit}>
            Edit
          </button>
          <button className={styles.deleteAction} type="button" onClick={onDelete}>
            Delete
          </button>
        </div>
      </footer>
    </article>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className={styles.emptyState}>
      <div className={styles.emptyGate} aria-hidden="true">
        <span />
      </div>
      <p className={styles.eyebrow}>No routes yet</p>
      <h2>Add your first provider</h2>
      <p>
        Connect an OpenAI-compatible endpoint, then assign the models it should
        serve.
      </p>
      <button className={styles.primaryButton} type="button" onClick={onAdd}>
        Add provider
      </button>
    </div>
  );
}

function ErrorState({
  error,
  onRetry,
}: {
  error: ConsoleApiError;
  onRetry: () => void;
}) {
  return (
    <div className={styles.errorState} role="alert">
      <span aria-hidden="true">!</span>
      <div>
        <p className={styles.dangerEyebrow}>Route unavailable</p>
        <h2>Providers could not be loaded</h2>
        <p>
          {error.httpStatus === 0
            ? "Check that the gateway is running and this console origin is allowed."
            : error.message}
        </p>
        {error.requestId ? <code>Reference {error.requestId}</code> : null}
      </div>
      <button className={styles.secondaryButton} type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

function ProviderSkeleton() {
  return (
    <div className={styles.providerGrid} aria-label="Loading providers">
      {[0, 1].map((index) => (
        <div className={`${styles.gateCard} ${styles.skeleton}`} key={index}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "recently";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
  }).format(date);
}
