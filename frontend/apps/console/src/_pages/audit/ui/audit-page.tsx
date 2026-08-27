"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  auditActions,
  auditDetailOptions,
  auditListOptions,
  auditSummaryOptions,
  type AuditAction,
  type AuditCheckpoint,
  type AuditEventDetail,
  type AuditEventSummary,
  type AuditFilters,
  type AuditMode,
  type AuditSummary,
  type JsonValue,
} from "@/src/entities/audit";
import { useSession } from "@/src/entities/session";
import {
  ConsoleApiError,
  consoleErrorMessage,
  consoleErrorReference,
} from "@/src/shared/api";

import styles from "./audit-page.module.css";

const actionCopy: Record<AuditAction, string> = {
  allow: "허용",
  mask: "마스킹",
  blocked: "차단",
  approval_required: "승인 필요",
};

const checkpointCopy: Record<AuditCheckpoint, string> = {
  "": "검사 없음",
  input: "입력",
  tool_result: "툴 결과",
  output: "출력",
  tool_call: "툴 호출",
};

const modeCopy: Record<AuditMode, string> = {
  enforce: "적용",
  "dry-run": "관찰",
};

export function AuditPage() {
  const { session } = useSession();
  if (!session) return null;
  return <AuditWorkspace accessToken={session.tokens.accessToken} />;
}

function AuditWorkspace({ accessToken }: { accessToken: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { endSession } = useSession();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const filterSignature = searchParams.toString();
  const filters = useMemo(
    () => readFilters(new URLSearchParams(filterSignature)),
    [filterSignature],
  );
  const listQuery = useInfiniteQuery(auditListOptions(accessToken, filters));
  const summaryQuery = useQuery(auditSummaryOptions(accessToken, filters));

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

  useEffect(() => {
    for (const error of [listQuery.error, summaryQuery.error]) {
      if (
        error instanceof ConsoleApiError &&
        (error.httpStatus === 401 || error.httpStatus === 403)
      ) {
        handleAuthorizationError(error);
        return;
      }
    }
  }, [handleAuthorizationError, listQuery.error, summaryQuery.error]);

  const events = listQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const listError = authorizationSafeError(listQuery.error);
  const summaryError = authorizationSafeError(summaryQuery.error);

  function applyFilters(nextFilters: AuditFilters) {
    setSelectedId(null);
    const search = writeFilters(nextFilters);
    router.replace(search ? `${pathname}?${search}` : pathname);
  }

  return (
    <section
      className={styles.page}
      aria-labelledby="audit-title"
      lang="ko"
    >
      <header className={styles.pageHeader}>
        <h1 id="audit-title">감사</h1>
      </header>

      <SummaryStrip
        data={summaryQuery.data}
        error={summaryError}
        isLoading={summaryQuery.isPending}
        onRetry={() => void summaryQuery.refetch()}
      />

      <AuditFilterBar
        key={filterSignature}
        filters={filters}
        onApply={applyFilters}
        onReset={() => applyFilters({})}
      />

      <section className={styles.events} aria-labelledby="events-title">
        <div className={styles.sectionHeader}>
          <div>
            <h2 id="events-title">감사 기록</h2>
          </div>
          <p className={styles.resultStatus} aria-live="polite">
            {listQuery.isPending
              ? "기록을 불러오는 중…"
              : `${numberFormat(events.length)}건 표시`}
          </p>
        </div>

        <div className={styles.tableRegion} aria-busy={listQuery.isPending}>
          {listQuery.isPending ? <TableLoading /> : null}
          {!listQuery.isPending && listError ? (
            <ErrorState
              error={listError}
              onRetry={() => void listQuery.refetch()}
            />
          ) : null}
          {!listQuery.isPending && !listError && events.length === 0 ? (
            <EmptyState />
          ) : null}
          {!listQuery.isPending && !listError && events.length > 0 ? (
            <>
              <AuditTable events={events} onSelect={setSelectedId} />
              {listQuery.hasNextPage ? (
                <div className={styles.loadMore}>
                  <button
                    type="button"
                    onClick={() => void listQuery.fetchNextPage()}
                    disabled={listQuery.isFetchingNextPage}
                  >
                    {listQuery.isFetchingNextPage
                      ? "더 불러오는 중…"
                      : "더 보기"}
                  </button>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      </section>

      {selectedId ? (
        <AuditDetailDialog
          accessToken={accessToken}
          eventId={selectedId}
          onClose={() => setSelectedId(null)}
          onAuthorizationError={handleAuthorizationError}
        />
      ) : null}
    </section>
  );
}

function SummaryStrip({
  data,
  error,
  isLoading,
  onRetry,
}: {
  data: AuditSummary | undefined;
  error: Error | null;
  isLoading: boolean;
  onRetry: () => void;
}) {
  if (isLoading) {
    return (
      <div className={styles.summaryStrip} aria-label="요약 불러오는 중">
        {Array.from({ length: 7 }, (_, index) => (
          <span className={styles.summarySkeleton} key={index} />
        ))}
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className={styles.summaryError} role="alert">
        <span>요약을 불러오지 못했습니다.</span>
        <button type="button" onClick={onRetry}>
          다시 시도
        </button>
      </div>
    );
  }

  const known = new Set<string>(auditActions);
  const actionEntries = [
    ...auditActions.map(
      (action) => [action, data.countsByAction[action] ?? 0] as const,
    ),
    ...Object.entries(data.countsByAction).filter(
      ([action]) => !known.has(action),
    ),
  ];

  return (
    <div className={styles.summaryStrip} aria-label="필터 범위 요약">
      <SummaryMetric label="전체" value={numberFormat(data.total)} />
      {actionEntries.map(([action, count]) => (
        <SummaryMetric
          key={action}
          label={actionLabel(action)}
          value={numberFormat(count)}
          tone={action}
        />
      ))}
      <SummaryMetric label="지연 p50" value={latencyFormat(data.latencyP50)} />
      <SummaryMetric label="지연 p95" value={latencyFormat(data.latencyP95)} />
    </div>
  );
}

function SummaryMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className={`${styles.summaryMetric} ${toneClassName(tone)}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

type FilterDraft = {
  appName: string;
  guardrail: string;
  action: string;
  checkpoint: string;
  mode: string;
  tainted: string;
  from: string;
  to: string;
};

function AuditFilterBar({
  filters,
  onApply,
  onReset,
}: {
  filters: AuditFilters;
  onApply: (filters: AuditFilters) => void;
  onReset: () => void;
}) {
  const [draft, setDraft] = useState<FilterDraft>(() => filterDraft(filters));
  const [timeError, setTimeError] = useState<string | null>(null);

  function update(name: keyof FilterDraft, value: string) {
    setDraft((current) => ({ ...current, [name]: value }));
    if (name === "from" || name === "to") setTimeError(null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draft.from && draft.to && draft.from > draft.to) {
      setTimeError("시작 시각은 종료 시각보다 늦을 수 없습니다.");
      return;
    }
    onApply({
      appName: draft.appName.trim() || undefined,
      guardrail: draft.guardrail.trim() || undefined,
      action: isAuditAction(draft.action) ? draft.action : undefined,
      checkpoint: isFilterCheckpoint(draft.checkpoint)
        ? draft.checkpoint
        : undefined,
      mode: isAuditMode(draft.mode) ? draft.mode : undefined,
      tainted:
        draft.tainted === "true"
          ? true
          : draft.tainted === "false"
            ? false
            : undefined,
      from: draft.from ? new Date(draft.from).toISOString() : undefined,
      to: draft.to ? new Date(draft.to).toISOString() : undefined,
    });
  }

  return (
    <form className={styles.filters} onSubmit={submit} aria-label="감사 필터">
      <div className={styles.filterHeading}>
        <h2>필터</h2>
        <div className={styles.filterActions}>
          <button className={styles.resetButton} type="button" onClick={onReset}>
            초기화
          </button>
          <button className={styles.applyButton} type="submit">
            적용
          </button>
        </div>
      </div>

      <div className={styles.filterGrid}>
        <label>
          <span>앱</span>
          <input
            value={draft.appName}
            onChange={(event) => update("appName", event.target.value)}
            placeholder="예: customer-api"
            maxLength={255}
          />
        </label>
        <label>
          <span>가드레일</span>
          <input
            value={draft.guardrail}
            onChange={(event) => update("guardrail", event.target.value)}
            placeholder="예: pii-mask"
            maxLength={255}
          />
        </label>
        <label>
          <span>액션</span>
          <select
            value={draft.action}
            onChange={(event) => update("action", event.target.value)}
          >
            <option value="">전체</option>
            {auditActions.map((action) => (
              <option key={action} value={action}>
                {actionCopy[action]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>검사 지점</span>
          <select
            value={draft.checkpoint}
            onChange={(event) => update("checkpoint", event.target.value)}
          >
            <option value="">전체</option>
            <option value="input">입력</option>
            <option value="tool_result">툴 결과</option>
            <option value="output">출력</option>
            <option value="tool_call">툴 호출</option>
          </select>
        </label>
        <label>
          <span>모드</span>
          <select
            value={draft.mode}
            onChange={(event) => update("mode", event.target.value)}
          >
            <option value="">전체</option>
            <option value="enforce">적용</option>
            <option value="dry-run">관찰</option>
          </select>
        </label>
        <label>
          <span>오염</span>
          <select
            value={draft.tainted}
            onChange={(event) => update("tainted", event.target.value)}
          >
            <option value="">전체</option>
            <option value="true">오염됨</option>
            <option value="false">깨끗함</option>
          </select>
        </label>
        <label>
          <span>시작 시각</span>
          <input
            type="datetime-local"
            value={draft.from}
            max={draft.to || undefined}
            onChange={(event) => update("from", event.target.value)}
            aria-describedby={timeError ? "audit-time-error" : undefined}
          />
        </label>
        <label>
          <span>종료 시각</span>
          <input
            type="datetime-local"
            value={draft.to}
            min={draft.from || undefined}
            onChange={(event) => update("to", event.target.value)}
            aria-describedby={timeError ? "audit-time-error" : undefined}
          />
        </label>
      </div>
      {timeError ? (
        <p id="audit-time-error" className={styles.filterError} role="alert">
          {timeError}
        </p>
      ) : null}
    </form>
  );
}

function AuditTable({
  events,
  onSelect,
}: {
  events: AuditEventSummary[];
  onSelect: (eventId: string) => void;
}) {
  return (
    <div
      className={styles.tableScroll}
      tabIndex={0}
      aria-label="감사 이벤트 표. 좌우로 스크롤할 수 있습니다."
    >
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">시각</th>
            <th scope="col">앱</th>
            <th scope="col">가드레일</th>
            <th scope="col">액션</th>
            <th scope="col">검사 지점</th>
            <th scope="col">걸린 검사</th>
            <th scope="col">지연</th>
            <th scope="col">모드</th>
            <th scope="col">오염</th>
            <th scope="col">모델</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id} onClick={() => onSelect(event.id)}>
              <td>
                <button
                  className={styles.rowLink}
                  type="button"
                  onClick={(clickEvent) => {
                    clickEvent.stopPropagation();
                    onSelect(event.id);
                  }}
                  aria-label={`${dateTimeFormat(event.createdAt)} 감사 이벤트 상세 열기`}
                >
                  <time dateTime={event.createdAt} title={event.createdAt}>
                    {dateTimeFormat(event.createdAt)}
                  </time>
                </button>
              </td>
              <td><strong>{event.appName || "—"}</strong></td>
              <td>
                <span>{event.guardrail || "—"}</span>
                <small>v{event.guardrailVersion}</small>
              </td>
              <td><ActionBadge action={event.action} /></td>
              <td>{checkpointCopy[event.checkpoint]}</td>
              <td><Checks checks={event.checksFired} /></td>
              <td><code>{latencyFormat(event.latencyMs)}</code></td>
              <td>{modeCopy[event.mode]}</td>
              <td>
                <span className={event.tainted ? styles.tainted : styles.clean}>
                  {event.tainted ? "오염" : "깨끗"}
                </span>
              </td>
              <td><code>{event.model || "—"}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Checks({ checks }: { checks: string[] }) {
  if (checks.length === 0) return <span className={styles.muted}>없음</span>;
  const visible = checks.slice(0, 3);
  return (
    <span className={styles.checks}>
      {visible.map((check) => <code key={check}>{check}</code>)}
      {checks.length > visible.length ? <small>+{checks.length - visible.length}</small> : null}
    </span>
  );
}

function ActionBadge({ action }: { action: AuditAction }) {
  return (
    <span className={`${styles.actionBadge} ${toneClassName(action)}`}>
      {actionCopy[action]}
    </span>
  );
}

function AuditDetailDialog({
  accessToken,
  eventId,
  onClose,
  onAuthorizationError,
}: {
  accessToken: string;
  eventId: string;
  onClose: () => void;
  onAuthorizationError: (error: ConsoleApiError) => void;
}) {
  const query = useQuery(auditDetailOptions(accessToken, eventId));
  const setDialog = useCallback((element: HTMLDialogElement | null) => {
    if (element && !element.open) element.showModal();
  }, []);

  useEffect(() => {
    if (
      query.error instanceof ConsoleApiError &&
      (query.error.httpStatus === 401 || query.error.httpStatus === 403)
    ) {
      onAuthorizationError(query.error);
    }
  }, [onAuthorizationError, query.error]);

  const error = authorizationSafeError(query.error);
  return (
    <dialog
      ref={setDialog}
      className={styles.detailDialog}
      aria-labelledby="audit-detail-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className={styles.detailHeader}>
        <div>
          <h2 id="audit-detail-title">감사 이벤트</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="감사 상세 닫기" autoFocus>
          ×
        </button>
      </header>

      <div className={styles.detailBody} aria-busy={query.isPending}>
        {query.isPending ? <DetailLoading /> : null}
        {!query.isPending && error ? (
          <ErrorState error={error} onRetry={() => void query.refetch()} compact />
        ) : null}
        {!query.isPending && !error && query.data ? (
          <AuditDetailContent detail={query.data} />
        ) : null}
      </div>
    </dialog>
  );
}

function AuditDetailContent({ detail }: { detail: AuditEventDetail }) {
  return (
    <>
      <section className={styles.detailSection}>
        <div className={styles.detailSectionHeading}>
          <h3>요청과 결과</h3>
          <ActionBadge action={detail.action} />
        </div>
        <dl className={styles.detailGrid}>
          <DetailField label="감사 ID" value={<code>{detail.id}</code>} />
          <DetailField label="시각" value={dateTimeFormat(detail.createdAt)} />
          <DetailField label="앱" value={detail.appName || "—"} />
          <DetailField
            label="가드레일"
            value={`${detail.guardrail || "—"} · v${detail.guardrailVersion}`}
          />
          <DetailField label="검사 지점" value={checkpointCopy[detail.checkpoint]} />
          <DetailField label="티어" value={tierLabel(detail.tierReached)} />
          <DetailField label="모드" value={modeCopy[detail.mode]} />
          <DetailField label="오염" value={detail.tainted ? "오염됨" : "깨끗함"} />
          <DetailField label="지연" value={latencyFormat(detail.latencyMs)} />
          <DetailField label="모델" value={<code>{detail.model || "—"}</code>} />
          <DetailField label="요청 ID" value={<code>{detail.requestId || "—"}</code>} />
          <DetailField label="API 키 ID" value={<code>{detail.apiKeyId}</code>} />
          <DetailField label="프롬프트 토큰" value={numberFormat(detail.promptTokens)} />
          <DetailField label="완성 토큰" value={numberFormat(detail.completionTokens)} />
        </dl>
      </section>

      <section className={styles.detailSection}>
        <h3>걸린 검사</h3>
        <div className={styles.detailChecks}>
          {detail.checksFired.length > 0
            ? detail.checksFired.map((check) => <code key={check}>{check}</code>)
            : <span>걸린 검사가 없습니다.</span>}
        </div>
      </section>

      <section className={styles.detailSection}>
        <h3>판정 근거</h3>
        <JsonValueView value={detail.verdicts} />
      </section>
    </>
  );
}

function DetailField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function JsonValueView({ value }: { value: JsonValue }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className={styles.jsonEmpty}>없음</span>;
    return (
      <ol className={styles.jsonList}>
        {value.map((item, index) => (
          <li key={index}><JsonValueView value={item} /></li>
        ))}
      </ol>
    );
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span className={styles.jsonEmpty}>없음</span>;
    return (
      <dl className={styles.jsonObject}>
        {entries.map(([key, item]) => (
          <div key={key}>
            <dt>{verdictKeyLabel(key)}</dt>
            <dd><JsonValueView value={item} /></dd>
          </div>
        ))}
      </dl>
    );
  }
  return <code className={styles.jsonScalar}>{jsonScalar(value)}</code>;
}

function EmptyState() {
  return (
    <div className={styles.emptyState}>
      <h3>감사 이벤트 없음</h3>
    </div>
  );
}

function ErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: Error;
  onRetry: () => void;
  compact?: boolean;
}) {
  return (
    <div className={`${styles.errorState} ${compact ? styles.compactError : ""}`} role="alert">
      <span aria-hidden="true">!</span>
      <div>
        <h3>감사 기록을 불러오지 못했습니다</h3>
        <p>
          {error instanceof ConsoleApiError && error.httpStatus === 0
            ? "게이트웨이가 실행 중이고 콘솔 오리진이 허용됐는지 확인하세요."
            : error instanceof ConsoleApiError
              ? consoleErrorMessage(error)
              : "감사 기록을 불러오지 못했습니다."}
        </p>
        {error instanceof ConsoleApiError ? (
          <code>{consoleErrorReference(error)}</code>
        ) : null}
      </div>
      <button type="button" onClick={onRetry}>다시 시도</button>
    </div>
  );
}

function TableLoading() {
  return (
    <div className={styles.tableLoading} role="status">
      <span /><span /><span /><span />
      <p>감사 기록을 불러오는 중…</p>
    </div>
  );
}

function DetailLoading() {
  return (
    <div className={styles.detailLoading} role="status">
      <span /><span /><span />
      <p>판정 근거를 불러오는 중…</p>
    </div>
  );
}

function readFilters(search: URLSearchParams): AuditFilters {
  const action = search.get("action") ?? "";
  const checkpoint = search.get("checkpoint") ?? "";
  const mode = search.get("mode") ?? "";
  const tainted = search.get("tainted");
  return {
    appName: search.get("appName") || undefined,
    guardrail: search.get("guardrail") || undefined,
    action: isAuditAction(action) ? action : undefined,
    checkpoint: isFilterCheckpoint(checkpoint) ? checkpoint : undefined,
    mode: isAuditMode(mode) ? mode : undefined,
    tainted: tainted === "true" ? true : tainted === "false" ? false : undefined,
    from: validIso(search.get("from")),
    to: validIso(search.get("to")),
  };
}

function writeFilters(filters: AuditFilters): string {
  const search = new URLSearchParams();
  const strings: [string, string | undefined][] = [
    ["appName", filters.appName],
    ["guardrail", filters.guardrail],
    ["action", filters.action],
    ["checkpoint", filters.checkpoint],
    ["mode", filters.mode],
    ["from", filters.from],
    ["to", filters.to],
  ];
  for (const [key, value] of strings) {
    if (value) search.set(key, value);
  }
  if (filters.tainted !== undefined) search.set("tainted", String(filters.tainted));
  return search.toString();
}

function filterDraft(filters: AuditFilters): FilterDraft {
  return {
    appName: filters.appName ?? "",
    guardrail: filters.guardrail ?? "",
    action: filters.action ?? "",
    checkpoint: filters.checkpoint ?? "",
    mode: filters.mode ?? "",
    tainted: filters.tainted === undefined ? "" : String(filters.tainted),
    from: localDateTime(filters.from),
    to: localDateTime(filters.to),
  };
}

function localDateTime(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function validIso(value: string | null): string | undefined {
  if (!value || Number.isNaN(new Date(value).getTime())) return undefined;
  return value;
}

function isAuditAction(value: string): value is AuditAction {
  return auditActions.some((action) => action === value);
}

function isFilterCheckpoint(
  value: string,
): value is Exclude<AuditCheckpoint, ""> {
  return ["input", "tool_result", "output", "tool_call"].includes(value);
}

function isAuditMode(value: string): value is AuditMode {
  return value === "enforce" || value === "dry-run";
}

function authorizationSafeError(error: unknown): Error | null {
  if (
    error instanceof ConsoleApiError &&
    (error.httpStatus === 401 || error.httpStatus === 403)
  ) {
    return null;
  }
  return error instanceof Error ? error : null;
}

function toneClassName(tone: string | undefined): string {
  switch (tone) {
    case "blocked": return styles.blockedTone;
    case "mask": return styles.maskTone;
    case "allow": return styles.allowTone;
    case "approval_required": return styles.approvalTone;
    default: return "";
  }
}

function actionLabel(action: string): string {
  return isAuditAction(action) ? actionCopy[action] : action;
}

function dateTimeFormat(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function latencyFormat(value: number): string {
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} ms`;
}

function numberFormat(value: number): string {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function tierLabel(value: string): string {
  if (value === "rule" || value === "rules") return "규칙";
  if (value === "model") return "모델";
  return value ? "기타" : "없음";
}

const verdictKeyCopy: Record<string, string> = {
  would_have: "관찰 모드 예상 결과",
  masked: "마스킹 적용",
  pending_model: "모델 판정 대기",
  inspected: "검사 완료 지점",
  evidence: "액션 근거",
  tool: "툴",
  arguments: "검사한 인수",
  sources: "출처",
  check: "검사",
  action: "판정",
  count: "건수",
  checkpoint: "검사 지점",
};

function verdictKeyLabel(key: string): string {
  return verdictKeyCopy[key] ?? key.replaceAll("_", " ");
}

function jsonScalar(value: null | boolean | number | string): string {
  if (value === null) return "없음";
  if (typeof value === "boolean") return value ? "예" : "아니요";
  return String(value);
}
