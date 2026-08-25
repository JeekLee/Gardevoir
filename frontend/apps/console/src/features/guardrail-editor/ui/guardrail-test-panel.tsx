"use client";

import { useMutation } from "@tanstack/react-query";
import { useMemo, useRef, useState, type FormEvent } from "react";

import { useProviders } from "@/src/entities/provider";
import { ConsoleApiError } from "@/src/shared/api";

import { streamGuardrailTest } from "../api/test-guardrail";
import {
  providerModelOptions,
  type GuardrailTestCheckpoint,
  type GuardrailTestResult,
} from "../model/guardrail-test";
import styles from "./guardrail-test-panel.module.css";

const checkpointCards: {
  key: keyof GuardrailTestResult["checkpoints"];
  index: string;
  label: string;
}[] = [
  { key: "input", index: "①", label: "Input" },
  { key: "toolResult", index: "②", label: "Tool result" },
  { key: "output", index: "③", label: "Output" },
  { key: "toolCall", index: "④", label: "Tool call" },
];

export function GuardrailTestPanel({
  accessToken,
  guardrailName,
  dirty,
  onSaveDraft,
  onAuthorizationError,
  onGatewayError,
  onResult,
  onClear,
  onClose,
}: {
  accessToken: string;
  guardrailName: string;
  dirty: boolean;
  onSaveDraft: () => Promise<boolean>;
  onAuthorizationError: (error: ConsoleApiError) => void;
  onGatewayError: (error: ConsoleApiError) => void;
  onResult: (result: GuardrailTestResult) => void;
  onClear: () => void;
  onClose: () => void;
}) {
  const providers = useProviders(accessToken, onAuthorizationError);
  const modelOptions = useMemo(
    () => providerModelOptions(providers.data?.items ?? []),
    [providers.data],
  );
  const [model, setModel] = useState("");
  const [message, setMessage] = useState("가드레일이 실제 호출에서 어떻게 동작하는지 알려줘.");
  const [result, setResult] = useState<GuardrailTestResult | null>(null);
  const [streamedContent, setStreamedContent] = useState("");
  const [hasStarted, setHasStarted] = useState(false);
  const [streamState, setStreamState] = useState<
    "idle" | "streaming" | "cancelled"
  >("idle");
  const [error, setError] = useState<ConsoleApiError | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const abortController = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: (input: {
      model: string;
      message: string;
      signal: AbortSignal;
      onDelta: (content: string) => void;
    }) => streamGuardrailTest(accessToken, guardrailName, input),
  });
  const selectedModel = modelOptions.some((option) => option.model === model)
    ? model
    : (modelOptions[0]?.model ?? "");

  async function runTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedModel || !message.trim()) return;

    setError(null);
    setResult(null);
    setStreamedContent("");
    setHasStarted(false);
    setStreamState("idle");
    onClear();
    setIsPreparing(true);
    if (dirty && !(await onSaveDraft())) {
      setIsPreparing(false);
      return;
    }

    const controller = new AbortController();
    abortController.current = controller;
    setHasStarted(true);
    setStreamState("streaming");
    setIsPreparing(false);
    try {
      const next = await mutation.mutateAsync({
        model: selectedModel,
        message: message.trim(),
        signal: controller.signal,
        onDelta: (content) =>
          setStreamedContent((current) => current + content),
      });
      setResult(next);
      setStreamState("idle");
      onResult(next);
    } catch (caught) {
      if (controller.signal.aborted) {
        setStreamState("cancelled");
        return;
      }
      setStreamState("idle");
      const normalized = normalizeError(caught);
      if (normalized.httpStatus === 401 || normalized.httpStatus === 403) {
        onAuthorizationError(normalized);
        return;
      }
      setError(normalized);
      onGatewayError(normalized);
    } finally {
      if (abortController.current === controller) {
        abortController.current = null;
      }
      setIsPreparing(false);
    }
  }

  function close() {
    abortController.current?.abort();
    onClear();
    onClose();
  }

  const isBusy =
    isPreparing || mutation.isPending || streamState === "streaming";

  return (
    <section className={styles.panel} aria-labelledby="guardrail-test-title">
      <header>
        <div>
          <p>Draft enforce</p>
          <h2 id="guardrail-test-title">실제 업스트림 호출 테스트</h2>
          <span>
            저장된 draft를 즉석 컴파일하고 마스킹된 응답을 실시간으로 확인합니다.
          </span>
        </div>
        <button type="button" onClick={close} aria-label="테스트 패널 닫기">
          ×
        </button>
      </header>

      <form className={styles.form} onSubmit={(event) => void runTest(event)}>
        <label>
          <span>샘플 user 메시지</span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            disabled={isBusy}
            rows={4}
            required
          />
        </label>
        <label>
          <span>업스트림 모델</span>
          <select
            value={selectedModel}
            onChange={(event) => setModel(event.target.value)}
            disabled={isBusy || providers.isLoading || modelOptions.length === 0}
            required
          >
            {modelOptions.length === 0 ? (
              <option value="">사용 가능한 모델 없음</option>
            ) : (
              modelOptions.map((option) => (
                <option key={option.model} value={option.model}>
                  {option.model} · {option.provider}
                </option>
              ))
            )}
          </select>
          <small>
            {providers.isLoading
              ? "프로바이더 모델을 불러오는 중입니다."
              : "GET /v1/providers에 등록된 모델만 표시합니다."}
          </small>
        </label>
        <div className={styles.formActions}>
          <button
            className={styles.runButton}
            type="submit"
            disabled={
              isBusy || providers.isLoading || !selectedModel || !message.trim()
            }
          >
            {isPreparing
              ? "Draft 저장 중…"
              : streamState === "streaming"
                ? "응답 스트리밍 중…"
                : dirty
                  ? "Draft 저장 후 실제 호출 테스트"
                  : "실제 호출 테스트"}
          </button>
          {streamState === "streaming" ? (
            <button
              className={styles.cancelButton}
              type="button"
              onClick={() => abortController.current?.abort()}
            >
              스트리밍 취소
            </button>
          ) : null}
        </div>
      </form>

      {providers.error ? (
        <div className={styles.error} role="alert">
          <span>{providers.error.message}</span>
          <button type="button" onClick={() => void providers.reload()}>
            모델 다시 불러오기
          </button>
        </div>
      ) : null}

      {error ? (
        <div className={styles.error} role="alert">
          <strong>{error.code}</strong>
          <span>{error.message}</span>
          {error.requestId ? <code>Reference {error.requestId}</code> : null}
        </div>
      ) : null}

      {hasStarted ? (
        <StreamedResponse
          content={result?.appliedContent ?? streamedContent}
          result={result}
          state={streamState}
        />
      ) : null}

      {result ? <TestResult result={result} /> : null}
    </section>
  );
}

function TestResult({ result }: { result: GuardrailTestResult }) {
  return (
    <div className={styles.result}>
      <div className={styles.resultSummary}>
        <div>
          <span>Overall action</span>
          <strong className={styles[result.overallAction]}>
            {result.overallAction}
          </strong>
        </div>
        <dl>
          <div>
            <dt>Model</dt>
            <dd>{result.model}</dd>
          </div>
          <div>
            <dt>Latency</dt>
            <dd>{result.latencyMs.toFixed(1)} ms</dd>
          </div>
          {result.auditId ? (
            <div>
              <dt>Audit</dt>
              <dd>{result.auditId}</dd>
            </div>
          ) : null}
        </dl>
      </div>

      <div className={styles.checkpoints} aria-label="체크포인트 테스트 결과">
        {checkpointCards.map((card) => (
          <CheckpointCard
            key={card.key}
            checkpoint={result.checkpoints[card.key]}
            index={card.index}
            label={card.label}
          />
        ))}
      </div>

      {result.toolCalls.length > 0 ? (
        <div className={styles.responseResults}>
          <div className={styles.toolCalls}>
            <span>Tool calls</span>
            <pre>{JSON.stringify(result.toolCalls, null, 2)}</pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StreamedResponse({
  content,
  result,
  state,
}: {
  content: string;
  result: GuardrailTestResult | null;
  state: "idle" | "streaming" | "cancelled";
}) {
  const blocked = result?.blocked ?? false;
  return (
    <div
      className={`${styles.streamedResult} ${blocked ? styles.blockedResult : ""}`}
      aria-live="polite"
      aria-busy={state === "streaming"}
    >
      <header>
        <span>실제 적용 결과 · 실시간</span>
        {state === "streaming" ? <small>스트리밍 중</small> : null}
        {(result?.unmaskable ?? 0) > 0 ? (
          <strong className={styles.unmaskableBadge}>
            {`일부 매치가 홀드백을 벗어나 마스킹되지 못함(${result?.unmaskable})`}
          </strong>
        ) : null}
      </header>
      <pre>
        {blocked
          ? `🚫 차단됨 — ${result?.blockedAt ?? "unknown"} (${result?.blockedReason ?? "사유 없음"})`
          : content ||
            (state === "streaming"
              ? "업스트림 응답을 기다리는 중…"
              : state === "cancelled"
                ? "(스트리밍이 취소되었습니다)"
                : "(텍스트 응답 없음)")}
      </pre>
    </div>
  );
}

function CheckpointCard({
  checkpoint,
  index,
  label,
}: {
  checkpoint: GuardrailTestCheckpoint;
  index: string;
  label: string;
}) {
  return (
    <article className={checkpoint.checksFired.length > 0 ? styles.firedCard : undefined}>
      <header>
        <span>{index}</span>
        <strong>{label}</strong>
        <b className={styles[checkpoint.action]}>
          {checkpoint.ran ? checkpoint.action : "not run"}
        </b>
      </header>
      <dl>
        <div>
          <dt>Ran</dt>
          <dd>{checkpoint.ran ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt>Tier</dt>
          <dd>{checkpoint.tier || "—"}</dd>
        </div>
        <div>
          <dt>Masked</dt>
          <dd>{checkpoint.masked ? "yes" : "no"}</dd>
        </div>
      </dl>
      <div className={styles.firedChecks}>
        <span>Checks fired</span>
        {checkpoint.checksFired.length > 0 ? (
          <div>
            {checkpoint.checksFired.map((code, index) => (
              <code key={`${code}-${index}`}>{code}</code>
            ))}
          </div>
        ) : (
          <small>없음</small>
        )}
      </div>
      {checkpoint.evidence.length > 0 ? (
        <div className={styles.evidence}>
          <span>Evidence</span>
          {checkpoint.evidence.map((item, index) => (
            <p key={`${item.tool}-${index}`}>
              <strong>{item.tool}</strong>
              <code>{item.arguments.join(", ") || "arguments 없음"}</code>
            </p>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function normalizeError(error: unknown): ConsoleApiError {
  return error instanceof ConsoleApiError
    ? error
    : new ConsoleApiError({
        httpStatus: 0,
        code: "CONSOLE-006",
        message: "가드레일 실제 호출 테스트를 완료하지 못했습니다.",
      });
}
