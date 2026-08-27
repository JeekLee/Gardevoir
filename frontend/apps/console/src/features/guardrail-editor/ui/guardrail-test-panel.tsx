"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { useProviders } from "@/src/entities/provider";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import { streamGuardrailTest } from "../api/test-guardrail";
import {
  providerModelOptions,
  type GuardrailTestCheckpoint,
  type GuardrailTestPre,
  type GuardrailTestResult,
} from "../model/guardrail-test";
import styles from "./guardrail-test-panel.module.css";

type StreamState = "idle" | "streaming" | "cancelled";

const checkpointSections: {
  key: keyof GuardrailTestResult["checkpoints"];
  index: string;
  label: string;
  timing: "immediate" | "streaming";
}[] = [
  { key: "input", index: "①", label: "입력 적용 결과", timing: "immediate" },
  {
    key: "toolResult",
    index: "②",
    label: "툴 결과 적용 결과",
    timing: "immediate",
  },
  {
    key: "output",
    index: "③",
    label: "출력 적용 결과",
    timing: "streaming",
  },
  {
    key: "toolCall",
    index: "④",
    label: "툴 호출 적용 결과",
    timing: "streaming",
  },
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
  const [pre, setPre] = useState<GuardrailTestPre | null>(null);
  const [result, setResult] = useState<GuardrailTestResult | null>(null);
  const [streamedContent, setStreamedContent] = useState("");
  const [hasStarted, setHasStarted] = useState(false);
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [error, setError] = useState<ConsoleApiError | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const abortController = useRef<AbortController | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const mutation = useMutation({
    mutationFn: (input: {
      model: string;
      message: string;
      signal: AbortSignal;
      onPre: (pre: GuardrailTestPre) => void;
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
    setPre(null);
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
        onPre: setPre,
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

  const close = useCallback(() => {
    abortController.current?.abort();
    onClear();
    onClose();
  }, [onClear, onClose]);

  useEffect(() => {
    closeButton.current?.focus();
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    window.addEventListener("keydown", closeOnEscape, true);
    return () => window.removeEventListener("keydown", closeOnEscape, true);
  }, [close]);

  const isBusy =
    isPreparing || mutation.isPending || streamState === "streaming";

  return (
    <section
      className={styles.panel}
      role="dialog"
      aria-modal="false"
      aria-labelledby="guardrail-test-title"
    >
      <header className={styles.panelHeader}>
        <div className={styles.headerCopy}>
          <h2 id="guardrail-test-title">업스트림 테스트</h2>
        </div>
        <button
          ref={closeButton}
          className={styles.closeButton}
          type="button"
          onClick={close}
          aria-label="테스트 패널 닫기"
        >
          ×
        </button>
      </header>

      <div className={styles.testContext}>
        <div className={styles.testMode}>
          <strong>저장된 초안 · enforce · 발행본 영향 없음</strong>
        </div>
        <label className={styles.modelPicker}>
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
          {providers.isLoading ? <small>모델을 불러오는 중…</small> : null}
        </label>
      </div>

      <form className={styles.form} onSubmit={(event) => void runTest(event)}>
        <label>
          <span>테스트 메시지</span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            disabled={isBusy}
            rows={4}
            required
          />
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
              ? "초안 저장 중…"
              : streamState === "streaming"
                ? "응답 스트리밍 중…"
                : dirty
                  ? "저장 후 테스트"
                  : "테스트"}
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
          <span>{consoleErrorMessage(providers.error)}</span>
          <button type="button" onClick={() => void providers.reload()}>
            모델 다시 불러오기
          </button>
        </div>
      ) : null}

      {!providers.isLoading && !providers.error && modelOptions.length === 0 ? (
        <div className={styles.emptyModels} role="status">
          <div>
            <strong>사용 가능한 모델이 없습니다.</strong>
            <span>
              테스트에는 모델이 연결된 프로바이더가 하나 이상 필요합니다.
            </span>
          </div>
          <Link href="/providers">프로바이더 설정으로 이동 →</Link>
        </div>
      ) : null}

      {error ? (
        <div className={styles.error} role="alert">
          <span>{consoleErrorMessage(error)}</span>
          <code>{consoleErrorReference(error)}</code>
        </div>
      ) : null}

      {hasStarted ? (
        <TestFlow
          pre={pre}
          result={result}
          streamedContent={streamedContent}
          state={streamState}
        />
      ) : null}
    </section>
  );
}

function TestFlow({
  pre,
  result,
  streamedContent,
  state,
}: {
  pre: GuardrailTestPre | null;
  result: GuardrailTestResult | null;
  streamedContent: string;
  state: StreamState;
}) {
  const appliedContent = result?.appliedContent ?? streamedContent;

  return (
    <div className={styles.result}>
      {result ? (
        <ResultSummary result={result} />
      ) : (
        <div className={styles.streamingSummary} role="status">
          <span>업스트림 응답</span>
          <strong>
            {state === "streaming" ? "스트리밍 중" : "스트리밍 취소됨"}
          </strong>
        </div>
      )}

      <div className={styles.checkpoints} aria-label="검사 지점별 테스트 결과">
        {checkpointSections.map((section) => {
          const checkpoint =
            result?.checkpoints[section.key] ??
            (section.key === "input"
              ? pre?.input
              : section.key === "toolResult"
                ? pre?.toolResult
                : null) ??
            null;
          const inactiveReason = knownInactiveReason(
            section.key,
            checkpoint,
            result,
          );
          return (
            <CheckpointSection
              key={section.key}
              checkpoint={checkpoint}
              checkpointKey={section.key}
              index={section.index}
              label={section.label}
              timing={section.timing}
              state={state}
              inactiveReason={inactiveReason}
              blocked={result?.blockedAt === section.key}
              blockedReason={
                result?.blockedAt === section.key ? result.blockedReason : null
              }
              appliedContent={
                section.key === "output" ? appliedContent : undefined
              }
              rawContent={
                section.key === "output" ? result?.rawContent : undefined
              }
              toolCalls={
                section.key === "toolCall" ? (result?.toolCalls ?? []) : undefined
              }
              unmaskable={
                section.key === "output" ? result?.unmaskable : undefined
              }
            />
          );
        })}
      </div>
    </div>
  );
}

function ResultSummary({ result }: { result: GuardrailTestResult }) {
  return (
    <div className={styles.resultSummary}>
      <div>
        <span>최종 판정</span>
        <strong className={styles[result.overallAction]}>
          {actionLabel(result.overallAction)}
        </strong>
      </div>
      <dl>
        <div>
          <dt>모델</dt>
          <dd>{result.model}</dd>
        </div>
        <div>
          <dt>지연</dt>
          <dd>{result.latencyMs.toFixed(1)} ms</dd>
        </div>
        {result.auditId ? (
          <div>
            <dt>감사</dt>
            <dd>{result.auditId}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

function CheckpointSection({
  checkpoint,
  checkpointKey,
  index,
  label,
  timing,
  state,
  inactiveReason,
  blocked,
  blockedReason,
  appliedContent,
  rawContent,
  toolCalls,
  unmaskable,
}: {
  checkpoint: GuardrailTestCheckpoint | null;
  checkpointKey: keyof GuardrailTestResult["checkpoints"];
  index: string;
  label: string;
  timing: "immediate" | "streaming";
  state: StreamState;
  inactiveReason: string | null;
  blocked: boolean;
  blockedReason: string | null;
  appliedContent?: string;
  rawContent?: string;
  toolCalls?: Record<string, unknown>[];
  unmaskable?: number;
}) {
  const inactive = inactiveReason !== null || (checkpoint !== null && !checkpoint.ran);

  return (
    <article
      className={`${styles.checkpointSection} ${
        checkpoint && checkpoint.checksFired.length > 0 ? styles.firedCard : ""
      } ${inactive ? styles.inactiveSection : ""}`}
    >
      <header>
        <span className={styles.checkpointIndex}>{index}</span>
        <div>
          <h3>{label}</h3>
          <small>{timing === "immediate" ? "즉시 확정" : "스트리밍 중 확정"}</small>
        </div>
        {checkpoint ? (
          <b
            className={
              !inactive
                ? `${styles.actionBadge} ${styles[checkpoint.action]}`
                : styles.inactiveBadge
            }
            aria-label={
              !inactive
                ? `적용 판정 ${actionLabel(checkpoint.action)}`
                : "적용 판정 미발동"
            }
          >
            {!inactive ? actionLabel(checkpoint.action) : "미발동"}
          </b>
        ) : (
          <b className={inactive ? styles.inactiveBadge : styles.pendingBadge}>
            {inactive ? "미발동" : "확인 중"}
          </b>
        )}
      </header>

      {blocked ? (
        <p className={styles.blockedNotice}>
          🚫 차단됨 — {blockedReason || "사유 없음"}
        </p>
      ) : null}

      {checkpoint ? (
        <CheckpointDetails
          checkpoint={checkpoint}
          checkpointKey={checkpointKey}
          inactiveReason={inactiveReason}
        />
      ) : (
        <PendingCheckpoint inactiveReason={inactiveReason} state={state} />
      )}

      {(checkpointKey === "input" || checkpointKey === "toolResult") && checkpoint ? (
        <RequestText checkpoint={checkpoint} />
      ) : null}

      {checkpointKey === "output" ? (
        <OutputContent
          content={appliedContent ?? ""}
          rawContent={rawContent ?? ""}
          state={state}
          unmaskable={unmaskable ?? 0}
        />
      ) : null}

      {checkpointKey === "toolCall" && (toolCalls?.length ?? 0) > 0 ? (
        <div className={styles.toolCalls}>
          <span>툴 호출</span>
          <pre>{JSON.stringify(toolCalls, null, 2)}</pre>
        </div>
      ) : null}
    </article>
  );
}

function CheckpointDetails({
  checkpoint,
  checkpointKey,
  inactiveReason,
}: {
  checkpoint: GuardrailTestCheckpoint;
  checkpointKey: keyof GuardrailTestResult["checkpoints"];
  inactiveReason: string | null;
}) {
  const inactive = inactiveReason !== null || !checkpoint.ran;
  return (
    <div className={styles.checkpointDetails}>
      {inactive ? (
        <p className={styles.inactiveState}>
          {inactiveReason ?? inactiveMessage(checkpointKey)}
        </p>
      ) : null}
      <dl>
        <div>
          <dt>검사 실행</dt>
          <dd>{inactive ? "아니요" : "예"}</dd>
        </div>
        <div>
          <dt>도달 티어</dt>
          <dd>{inactive ? "—" : tierLabel(checkpoint.tier)}</dd>
        </div>
        <div>
          <dt>마스킹</dt>
          <dd>{!inactive && checkpoint.masked ? "예" : "아니요"}</dd>
        </div>
      </dl>
      <div className={styles.firedChecks}>
        <span>발동한 검사</span>
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
      <div className={styles.evidence}>
        <span>근거</span>
        {checkpoint.evidence.length > 0 ? (
          checkpoint.evidence.map((item, index) => (
            <p key={`${item.tool}-${index}`}>
              <strong>{item.tool}</strong>
              <code>{item.arguments.join(", ") || "인수 없음"}</code>
            </p>
          ))
        ) : (
          <small>없음</small>
        )}
      </div>
    </div>
  );
}

function PendingCheckpoint({
  inactiveReason,
  state,
}: {
  inactiveReason: string | null;
  state: StreamState;
}) {
  if (inactiveReason !== null) {
    return <p className={styles.inactiveState}>{inactiveReason}</p>;
  }
  return (
    <p className={styles.pendingState}>
      {state === "cancelled" ? "결과 없음 (스트리밍 취소)" : "판정 결과 확인 중…"}
    </p>
  );
}

function OutputContent({
  content,
  rawContent,
  state,
  unmaskable,
}: {
  content: string;
  rawContent: string;
  state: StreamState;
  unmaskable: number;
}) {
  return (
    <div
      className={styles.outputContent}
      aria-live="polite"
      aria-busy={state === "streaming"}
    >
      <header>
        <span>실제 적용 텍스트</span>
        {state === "streaming" ? <small>스트리밍 중</small> : null}
        {unmaskable > 0 ? (
          <strong className={styles.unmaskableBadge}>
            일부 매치가 마스킹되지 못함 ({unmaskable})
          </strong>
        ) : null}
      </header>
      <pre>
        {content ||
          (state === "streaming"
            ? "업스트림 응답을 기다리는 중…"
            : state === "cancelled"
              ? "(스트리밍이 취소되었습니다)"
              : "(텍스트 응답 없음)")}
      </pre>
      {rawContent && rawContent !== content ? (
        <details>
          <summary>원본 모델 응답</summary>
          <pre>{rawContent}</pre>
        </details>
      ) : null}
    </div>
  );
}

function RequestText({ checkpoint }: { checkpoint: GuardrailTestCheckpoint }) {
  const { rawText, appliedText } = checkpoint;
  if (!rawText) return null;

  const changedText = appliedText !== null && appliedText !== rawText ? appliedText : null;
  return (
    <div className={styles.requestText}>
      <header>
        <span>검사 요청 텍스트</span>
        <small className={changedText ? styles.maskedStatus : styles.unmaskedStatus}>
          {changedText ? "마스킹 적용" : "마스킹 없음"}
        </small>
      </header>
      <div className={changedText ? styles.textComparison : styles.singleText}>
        <section className={styles.textBlock}>
          <span>원본</span>
          <pre>{rawText}</pre>
        </section>
        {changedText ? (
          <>
            <span className={styles.applyArrow} aria-hidden="true">
              →
            </span>
            <section className={`${styles.textBlock} ${styles.appliedText}`}>
              <span>적용 (마스킹)</span>
              <pre>
                <MaskedAppliedText content={changedText} />
              </pre>
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}

const maskPlaceholder = "[개인정보 삭제됨]";

function MaskedAppliedText({ content }: { content: string }) {
  const parts = content.split(maskPlaceholder);
  return parts.map((part, index) => (
    <span key={`${index}-${part}`}>
      {part}
      {index < parts.length - 1 ? (
        <mark className={styles.maskHighlight}>{maskPlaceholder}</mark>
      ) : null}
    </span>
  ));
}

function inactiveMessage(
  checkpointKey: keyof GuardrailTestResult["checkpoints"],
): string {
  if (checkpointKey === "toolResult") return "미발동 (입력 없음)";
  if (checkpointKey === "toolCall") return "미발동 (도구 없음)";
  return "미발동 (이전 단계에서 종료)";
}

function knownInactiveReason(
  checkpointKey: keyof GuardrailTestResult["checkpoints"],
  checkpoint: GuardrailTestCheckpoint | null,
  result: GuardrailTestResult | null,
): string | null {
  if (
    checkpointKey === "toolResult" &&
    checkpoint !== null &&
    !checkpoint.rawText
  ) {
    return "미발동 (입력 없음)";
  }
  if (
    checkpointKey === "toolCall" &&
    result !== null &&
    result.toolCalls.length === 0
  ) {
    return "미발동 (도구 없음)";
  }
  return null;
}

function normalizeError(error: unknown): ConsoleApiError {
  return error instanceof ConsoleApiError
    ? error
    : new ConsoleApiError({
        httpStatus: 0,
        code: "CONSOLE-006",
        message: "가드레일 테스트를 완료하지 못했습니다.",
      });
}

function actionLabel(action: GuardrailTestCheckpoint["action"]): string {
  if (action === "block") return "차단";
  if (action === "mask") return "마스킹";
  return "허용";
}

function tierLabel(tier: string): string {
  if (tier === "rule" || tier === "rules") return "규칙";
  if (tier === "model") return "모델";
  return tier ? "기타" : "—";
}
