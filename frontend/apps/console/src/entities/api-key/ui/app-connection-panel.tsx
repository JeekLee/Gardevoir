"use client";

import { useId, useState } from "react";

import { proxyChatCompletionsUrl } from "@/src/shared/config";

import {
  buildAppConnectionSnippet,
  type GardevoirMode,
} from "../model/app-connection";
import styles from "./app-connection-panel.module.css";

const apiKeyPlaceholder = "gdv_live_...";

export function AppConnectionPanel({
  guardrailNames,
  initialGuardrailName,
  apiKey,
  isGuardrailReady,
  title = "앱 연결",
  description,
}: {
  guardrailNames?: string[];
  initialGuardrailName?: string;
  apiKey?: string;
  isGuardrailReady?: boolean;
  title?: string;
  description?: string;
}) {
  const id = useId();
  const [selectedGuardrail, setSelectedGuardrail] = useState("");
  const [mode, setMode] = useState<GardevoirMode>("dry-run");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">(
    "idle",
  );
  const guardrailName =
    initialGuardrailName ??
    (guardrailNames?.includes(selectedGuardrail)
      ? selectedGuardrail
      : guardrailNames?.[0]) ??
    "";
  const endpoint = proxyChatCompletionsUrl();
  const snippet = buildAppConnectionSnippet({
    endpoint,
    apiKey: apiKey ?? apiKeyPlaceholder,
    guardrailName: guardrailName || "<guardrail-name>",
    mode,
  });
  const guardrailReady = isGuardrailReady ?? Boolean(guardrailName);

  async function copySnippet() {
    setCopyState("idle");
    try {
      await navigator.clipboard.writeText(snippet);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <section className={styles.panel} aria-labelledby={`${id}-title`}>
      <div className={styles.heading}>
        <div>
          <h2 id={`${id}-title`}>{title}</h2>
          {description ? <span>{description}</span> : null}
        </div>
        <code>{endpoint}</code>
      </div>

      <div className={styles.controls}>
        {guardrailNames ? (
          <label>
            <span>가드레일</span>
            <select
              value={guardrailName}
              onChange={(event) => {
                setSelectedGuardrail(event.target.value);
                setCopyState("idle");
              }}
              disabled={guardrailNames.length === 0}
            >
              {guardrailNames.length === 0 ? (
                <option value="">발행된 가드레일 없음</option>
              ) : (
                guardrailNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))
              )}
            </select>
          </label>
        ) : (
          <div className={styles.fixedValue}>
            <span>가드레일</span>
            <code>{guardrailName}</code>
          </div>
        )}
        <label>
          <span>모드</span>
          <select
            value={mode}
            onChange={(event) => {
              setMode(event.target.value as GardevoirMode);
              setCopyState("idle");
            }}
          >
            <option value="dry-run">dry-run · 기록만</option>
            <option value="enforce">enforce · 정책 적용</option>
          </select>
        </label>
        <div className={styles.fixedValue}>
          <span>API 키</span>
          <code>{apiKey ? "방금 만든 키 적용됨" : apiKeyPlaceholder}</code>
        </div>
      </div>

      {!guardrailReady ? (
        <p className={styles.readiness} role="status">
          이 가드레일을 발행한 뒤 실제 요청을 보낼 수 있습니다.
        </p>
      ) : null}

      <div className={styles.snippet}>
        <pre tabIndex={0} aria-label="앱 연결 curl 스니펫">
          <code>{snippet}</code>
        </pre>
        <button
          type="button"
          onClick={() => void copySnippet()}
          aria-label="앱 연결 curl 스니펫 복사"
        >
          {copyState === "copied" ? "복사됨" : "스니펫 복사"}
        </button>
      </div>
      <p className={styles.copyStatus} aria-live="polite">
        {copyState === "copied"
          ? "복사됨"
          : copyState === "failed"
            ? "복사하지 못했습니다. 스니펫을 직접 선택해 복사하세요."
            : ""}
      </p>

      <dl className={styles.headerGuide}>
        <div>
          <dt>Authorization</dt>
          <dd>발급한 gdv 키로 앱을 인증합니다.</dd>
        </div>
        <div>
          <dt>X-Gardevoir-Guardrail</dt>
          <dd>이 요청에 적용할 발행 가드레일을 고릅니다.</dd>
        </div>
        <div>
          <dt>X-Gardevoir-Mode</dt>
          <dd>dry-run은 차단하지 않고 결과만 기록하며, 생략하면 enforce입니다.</dd>
        </div>
      </dl>
    </section>
  );
}
