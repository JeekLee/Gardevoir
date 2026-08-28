"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  guardrailListOptions,
  guardrailVersionOptions,
  guardrailVersionsOptions,
  testGuardrail,
  type GuardrailGraph,
  type GuardrailTestInput,
  type GuardrailTestMessage,
  type GuardrailTestMode,
} from "@/src/entities/guardrail";
import { useProviders } from "@/src/entities/provider";
import { useSession } from "@/src/entities/session";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";
import { randomId } from "@/src/shared/lib";

import {
  addToolDefinitionPreset,
  injectionScenario,
  parseToolDefinitionsJson,
  providerModelOptions,
  toolDefinitionPresets,
  type ToolDefinitionPreset,
  type PlaygroundRun,
} from "../model/playground";
import { PlaygroundResult } from "./playground-result";
import styles from "./playground.module.css";

type ImageAttachment = {
  id: string;
  name: string;
  size: number;
  dataUrl: string;
};

type RunVariables = {
  name: string;
  graph: GuardrailGraph;
  mode: GuardrailTestMode;
  input: GuardrailTestInput;
};

type ToolResultDraft = {
  id: string;
  toolCallId: string;
  content: string;
};

export function PlaygroundPage() {
  const { session } = useSession();
  if (!session) return null;
  return <PlaygroundWorkspace accessToken={session.tokens.accessToken} />;
}

function PlaygroundWorkspace({ accessToken }: { accessToken: string }) {
  const router = useRouter();
  const { endSession } = useSession();
  const [guardrailName, setGuardrailName] = useState("");
  const [versionNumber, setVersionNumber] = useState<number | null>(null);
  const [model, setModel] = useState("");
  const [mode, setMode] = useState<GuardrailTestMode>("enforce");
  const [message, setMessage] = useState("");
  const [images, setImages] = useState<ImageAttachment[]>([]);
  const [toolsJson, setToolsJson] = useState("");
  const [toolChoice, setToolChoice] = useState("auto");
  const [toolResults, setToolResults] = useState<ToolResultDraft[]>([]);
  const [imageError, setImageError] = useState<string | null>(null);
  const [runError, setRunError] = useState<ConsoleApiError | null>(null);
  const [run, setRun] = useState<PlaygroundRun | null>(null);

  const authorize = useCallback(
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

  const guardrailsQuery = useQuery(guardrailListOptions(accessToken));
  const publishedGuardrails = useMemo(
    () =>
      (guardrailsQuery.data?.items ?? []).filter(
        (guardrail) => guardrail.latestVersionNumber !== null,
      ),
    [guardrailsQuery.data],
  );
  const selectedGuardrail = publishedGuardrails.some(
    (guardrail) => guardrail.name === guardrailName,
  )
    ? guardrailName
    : (publishedGuardrails[0]?.name ?? "");

  const versionsQuery = useQuery({
    ...guardrailVersionsOptions(accessToken, selectedGuardrail),
    enabled: selectedGuardrail.length > 0,
  });
  const versions = versionsQuery.data?.items ?? [];
  const selectedVersion = versions.some(
    (version) => version.versionNumber === versionNumber,
  )
    ? versionNumber
    : (versions[0]?.versionNumber ?? null);

  const detailQuery = useQuery({
    ...guardrailVersionOptions(
      accessToken,
      selectedGuardrail,
      selectedVersion ?? 0,
    ),
    enabled: selectedGuardrail.length > 0 && selectedVersion !== null,
  });

  const providers = useProviders(accessToken, authorize);
  const modelOptions = useMemo(
    () => providerModelOptions(providers.data?.items ?? []),
    [providers.data],
  );
  const selectedModel = modelOptions.some((option) => option.model === model)
    ? model
    : (modelOptions[0]?.model ?? "");
  const parsedTools = useMemo(
    () => parseToolDefinitionsJson(toolsJson),
    [toolsJson],
  );
  const selectedToolChoice = parsedTools.names.includes(toolChoice)
    ? toolChoice
    : "auto";

  const mutation = useMutation({
    mutationFn: async ({ name, input, graph, mode: runMode }: RunVariables) => ({
      result: await testGuardrail(accessToken, name, input),
      graph,
      mode: runMode,
    }),
  });

  useEffect(() => {
    for (const error of [
      guardrailsQuery.error,
      versionsQuery.error,
      detailQuery.error,
    ]) {
      if (
        error instanceof ConsoleApiError &&
        (error.httpStatus === 401 || error.httpStatus === 403)
      ) {
        authorize(error);
        return;
      }
    }
  }, [
    authorize,
    detailQuery.error,
    guardrailsQuery.error,
    versionsQuery.error,
  ]);

  async function runTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !selectedGuardrail ||
      selectedVersion === null ||
      !selectedModel ||
      !detailQuery.data ||
      (!message.trim() && images.length === 0 && toolResults.length === 0) ||
      parsedTools.error ||
      toolResults.some(
        (result) => !result.toolCallId.trim() || !result.content.trim(),
      )
    ) {
      return;
    }

    setRunError(null);
    const messages: GuardrailTestMessage[] = [];
    if (message.trim() || images.length > 0) {
      messages.push({ role: "user", content: requestContent(message, images) });
    }
    messages.push(
      ...toolResults.map((result) => ({
        role: "tool" as const,
        content: result.content,
        tool_call_id: result.toolCallId.trim(),
      })),
    );
    try {
      const next = await mutation.mutateAsync({
        name: selectedGuardrail,
        graph: detailQuery.data.graph,
        mode,
        input: {
          model: selectedModel,
          messages,
          version: String(selectedVersion),
          mode,
          tools: parsedTools.tools.length > 0 ? parsedTools.tools : undefined,
          toolChoice:
            parsedTools.tools.length === 0
              ? undefined
              : selectedToolChoice === "auto"
                ? "auto"
                : {
                    type: "function",
                    function: { name: selectedToolChoice },
                  },
        },
      });
      setRun(next);
    } catch (error) {
      const normalized = normalizeRunError(error);
      if (normalized.httpStatus === 401 || normalized.httpStatus === 403) {
        authorize(normalized);
        return;
      }
      setRunError(normalized);
    }
  }

  async function addImages(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []).filter((file) =>
      file.type.startsWith("image/"),
    );
    event.currentTarget.value = "";
    if (files.length === 0) return;

    setImageError(null);
    try {
      const next = await Promise.all(files.map(readImage));
      setImages((current) => [...current, ...next]);
    } catch {
      setImageError("이미지 파일을 읽지 못했습니다.");
    }
  }

  function addToolPreset(presetId: ToolDefinitionPreset["id"]) {
    setToolsJson((current) => addToolDefinitionPreset(current, presetId));
    setRun(null);
  }

  function addToolResult() {
    setToolResults((current) => [
      ...current,
      { id: randomId(), toolCallId: "", content: "" },
    ]);
  }

  function updateToolResult(
    id: string,
    field: "toolCallId" | "content",
    value: string,
  ) {
    setToolResults((current) =>
      current.map((result) =>
        result.id === id ? { ...result, [field]: value } : result,
      ),
    );
  }

  function applyInjectionScenario() {
    setMessage(injectionScenario.message);
    setImages([]);
    setToolsJson(addToolDefinitionPreset("", "send_email"));
    setToolChoice(injectionScenario.toolChoice);
    setToolResults([
      {
        id: randomId(),
        toolCallId: injectionScenario.toolCallId,
        content: injectionScenario.toolResult,
      },
    ]);
    setRun(null);
    setRunError(null);
  }

  const listError = visibleError(guardrailsQuery.error);
  const versionsError = visibleError(versionsQuery.error);
  const detailError = visibleError(detailQuery.error);
  const hasInput =
    message.trim().length > 0 || images.length > 0 || toolResults.length > 0;
  const isBusy = mutation.isPending;

  return (
    <section className={styles.page} aria-labelledby="playground-title" lang="ko">
      <header className={styles.pageHeader}>
        <h1 id="playground-title">Playground</h1>
      </header>

      <div className={styles.workspace}>
        <form className={styles.controls} onSubmit={(event) => void runTest(event)}>
          <div className={styles.controlGrid}>
            <label>
              <span>가드레일</span>
              <select
                value={selectedGuardrail}
                onChange={(event) => {
                  setGuardrailName(event.target.value);
                  setVersionNumber(null);
                  setRun(null);
                }}
                disabled={isBusy || guardrailsQuery.isPending}
              >
                {publishedGuardrails.length === 0 ? (
                  <option value="">발행본 없음</option>
                ) : (
                  publishedGuardrails.map((guardrail) => (
                    <option key={guardrail.name} value={guardrail.name}>
                      {guardrail.name}
                    </option>
                  ))
                )}
              </select>
            </label>

            <label>
              <span>버전</span>
              <select
                value={selectedVersion ?? ""}
                onChange={(event) => {
                  setVersionNumber(Number(event.target.value));
                  setRun(null);
                }}
                disabled={isBusy || versionsQuery.isPending || versions.length === 0}
              >
                {versions.length === 0 ? (
                  <option value="">발행본 없음</option>
                ) : (
                  versions.map((version) => (
                    <option key={version.versionNumber} value={version.versionNumber}>
                      발행 v{version.versionNumber} · {formatDate(version.publishedAt)} · 노드{" "}
                      {version.nodeCount} · 판정 {version.verdictCount}
                    </option>
                  ))
                )}
              </select>
            </label>

            <label>
              <span>프로바이더 · 모델</span>
              <select
                value={selectedModel}
                onChange={(event) => {
                  setModel(event.target.value);
                  setRun(null);
                }}
                disabled={isBusy || providers.isLoading || modelOptions.length === 0}
              >
                {modelOptions.length === 0 ? (
                  <option value="">사용 가능한 모델 없음</option>
                ) : (
                  modelOptions.map((option) => (
                    <option key={option.model} value={option.model}>
                      {option.provider} · {option.model}
                    </option>
                  ))
                )}
              </select>
            </label>

            <label>
              <span>모드</span>
              <select
                value={mode}
                onChange={(event) => {
                  setMode(event.target.value as GuardrailTestMode);
                  setRun(null);
                }}
                disabled={isBusy}
              >
                <option value="enforce">enforce</option>
                <option value="dry-run">dry-run</option>
              </select>
            </label>
          </div>

          {guardrailsQuery.isPending ? <InlineStatus>가드레일 불러오는 중…</InlineStatus> : null}
          {listError ? (
            <InlineError error={listError} onRetry={() => void guardrailsQuery.refetch()} />
          ) : null}
          {!guardrailsQuery.isPending && !listError && publishedGuardrails.length === 0 ? (
            <InlineEmpty href="/guardrails" label="발행된 가드레일이 없습니다." />
          ) : null}
          {versionsError ? (
            <InlineError error={versionsError} onRetry={() => void versionsQuery.refetch()} />
          ) : null}
          {detailError ? (
            <InlineError error={detailError} onRetry={() => void detailQuery.refetch()} />
          ) : null}
          {providers.error ? (
            <InlineError error={providers.error} onRetry={() => void providers.reload()} />
          ) : null}
          {!providers.isLoading && !providers.error && modelOptions.length === 0 ? (
            <InlineEmpty href="/providers" label="사용 가능한 모델이 없습니다." />
          ) : null}

          <label className={styles.queryField}>
            <span>쿼리</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              disabled={isBusy}
              rows={8}
              placeholder="메시지를 입력하세요"
            />
          </label>

          <div className={styles.imageField}>
            <div className={styles.imageFieldHeader}>
              <span>이미지</span>
              <label className={styles.imageButton}>
                <span>이미지 추가</span>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  disabled={isBusy}
                  onChange={(event) => void addImages(event)}
                />
              </label>
            </div>
            {images.length > 0 ? (
              <ul className={styles.imageList} aria-label="첨부 이미지">
                {images.map((image) => (
                  <li key={image.id}>
                    <Image
                      src={image.dataUrl}
                      alt=""
                      width={43}
                      height={43}
                      unoptimized
                    />
                    <span title={image.name}>
                      <strong>{image.name}</strong>
                      <small>{formatBytes(image.size)}</small>
                    </span>
                    <button
                      type="button"
                      aria-label={`${image.name} 이미지 제거`}
                      onClick={() =>
                        setImages((current) =>
                          current.filter((item) => item.id !== image.id),
                        )
                      }
                      disabled={isBusy}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.emptyImages}>첨부 없음</p>
            )}
            {imageError ? (
              <p className={styles.imageError} role="alert">
                {imageError}
              </p>
            ) : null}
          </div>

          <section className={styles.toolScenario} aria-labelledby="tool-scenario-title">
            <div className={styles.toolScenarioHeader}>
              <h2 id="tool-scenario-title">툴 시나리오</h2>
              <button
                type="button"
                onClick={applyInjectionScenario}
                disabled={isBusy}
              >
                인젝션 시연
              </button>
            </div>

            <div className={styles.toolDefinitions}>
              <span id="tool-definitions-label">툴 정의</span>
              <div className={styles.toolPresets} aria-label="툴 정의 프리셋">
                {toolDefinitionPresets.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => addToolPreset(preset.id)}
                    disabled={isBusy}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
              <textarea
                value={toolsJson}
                onChange={(event) => {
                  setToolsJson(event.target.value);
                  setRun(null);
                }}
                rows={12}
                spellCheck={false}
                disabled={isBusy}
                aria-invalid={Boolean(parsedTools.error)}
                aria-labelledby="tool-definitions-label"
                placeholder="[]"
              />
              {parsedTools.error ? (
                <small className={styles.scenarioError} role="alert">
                  {parsedTools.error}
                </small>
              ) : null}
            </div>

            <label className={styles.toolChoice}>
              <span>tool_choice</span>
              <select
                value={selectedToolChoice}
                onChange={(event) => {
                  setToolChoice(event.target.value);
                  setRun(null);
                }}
                disabled={isBusy || parsedTools.names.length === 0}
              >
                <option value="auto">auto</option>
                {parsedTools.names.map((name) => (
                  <option key={name} value={name}>
                    {name} 강제
                  </option>
                ))}
              </select>
            </label>

            <div className={styles.toolResults}>
              <div className={styles.toolResultsHeader}>
                <span>이전 툴 결과</span>
                <button type="button" onClick={addToolResult} disabled={isBusy}>
                  결과 추가
                </button>
              </div>
              {toolResults.length === 0 ? (
                <p>없음</p>
              ) : (
                <ul>
                  {toolResults.map((result, index) => (
                    <li key={result.id}>
                      <div>
                        <strong>role: tool · {index + 1}</strong>
                        <button
                          type="button"
                          onClick={() =>
                            setToolResults((current) =>
                              current.filter((item) => item.id !== result.id),
                            )
                          }
                          disabled={isBusy}
                          aria-label={`이전 툴 결과 ${index + 1} 삭제`}
                        >
                          ×
                        </button>
                      </div>
                      <label>
                        <span>tool_call_id</span>
                        <input
                          value={result.toolCallId}
                          onChange={(event) =>
                            updateToolResult(
                              result.id,
                              "toolCallId",
                              event.target.value,
                            )
                          }
                          required
                          disabled={isBusy}
                          placeholder="call_..."
                        />
                      </label>
                      <label>
                        <span>내용</span>
                        <textarea
                          value={result.content}
                          onChange={(event) =>
                            updateToolResult(
                              result.id,
                              "content",
                              event.target.value,
                            )
                          }
                          rows={4}
                          required
                          disabled={isBusy}
                        />
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          {runError ? (
            <div className={styles.runError} role="alert">
              <span>{runError.message}</span>
              <code>{consoleErrorReference(runError)}</code>
            </div>
          ) : null}

          <button
            className={styles.runButton}
            type="submit"
            disabled={
              isBusy ||
              !hasInput ||
              !selectedGuardrail ||
              selectedVersion === null ||
              !selectedModel ||
              !detailQuery.data ||
              Boolean(parsedTools.error) ||
              toolResults.some(
                (result) => !result.toolCallId.trim() || !result.content.trim(),
              )
            }
          >
            {isBusy ? "판정 중…" : "실행"}
          </button>
        </form>

        <div className={styles.resultRegion} aria-live="polite" aria-busy={isBusy}>
          {run ? (
            <PlaygroundResult run={run} />
          ) : (
            <div className={styles.emptyResult}>
              <strong>{isBusy ? "판정 중…" : "판정 결과 없음"}</strong>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function InlineStatus({ children }: { children: string }) {
  return (
    <p className={styles.inlineStatus} role="status">
      {children}
    </p>
  );
}

function InlineError({
  error,
  onRetry,
}: {
  error: ConsoleApiError;
  onRetry: () => void;
}) {
  return (
    <div className={styles.inlineError} role="alert">
      <span>{consoleErrorMessage(error)}</span>
      <button type="button" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  );
}

function InlineEmpty({ href, label }: { href: string; label: string }) {
  return (
    <div className={styles.inlineEmpty}>
      <span>{label}</span>
      <Link href={href}>설정으로 이동 →</Link>
    </div>
  );
}

function requestContent(message: string, images: ImageAttachment[]) {
  const text = message.trim();
  if (images.length === 0) return text;
  return [
    ...(text ? [{ type: "text" as const, text }] : []),
    ...images.map((image) => ({
      type: "image_url" as const,
      image_url: { url: image.dataUrl },
    })),
  ];
}

function readImage(file: File): Promise<ImageAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("error", () => reject(reader.error));
    reader.addEventListener("load", () => {
      if (typeof reader.result !== "string") {
        reject(new Error("Invalid image data"));
        return;
      }
      resolve({
        id: randomId(),
        name: file.name,
        size: file.size,
        dataUrl: reader.result,
      });
    });
    reader.readAsDataURL(file);
  });
}

function normalizeRunError(error: unknown): ConsoleApiError {
  return error instanceof ConsoleApiError
    ? error
    : new ConsoleApiError({
        httpStatus: 0,
        code: "CONSOLE-006",
        message: "가드레일 판정을 완료하지 못했습니다.",
      });
}

function visibleError(error: Error | null): ConsoleApiError | null {
  if (!(error instanceof ConsoleApiError)) return null;
  return error.httpStatus === 401 || error.httpStatus === 403 ? null : error;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
