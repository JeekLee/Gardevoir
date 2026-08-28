"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  auditActions,
  type AuditAction,
  type AuditInsights,
} from "@/src/entities/audit";

import { actionCopy, checkpointCopy } from "../lib/audit-copy";
import styles from "./audit-page.module.css";

const actionColors: Record<AuditAction, string> = {
  allow: "var(--muted-strong)",
  mask: "var(--warn)",
  blocked: "var(--danger)",
  approval_required: "var(--brand)",
};

type SortKey = "check" | "count";
type SortDirection = "ascending" | "descending";

export function AuditInsightsPanel({
  data,
  selectedCheck,
  onSelectCheck,
}: {
  data: AuditInsights;
  selectedCheck?: string;
  onSelectCheck: (check: string) => void;
}) {
  const reducedMotion = useReducedMotion();
  const trend = useMemo(() => trendData(data), [data]);
  const checkpoints = useMemo(
    () =>
      data.checkpoints.map((item) => ({
        ...item,
        label: checkpointCopy[item.checkpoint],
      })),
    [data.checkpoints],
  );

  return (
    <section className={styles.insights} aria-label="감사 관측">
      <article className={`${styles.insightCard} ${styles.trendCard}`}>
        <h2>판정 추이</h2>
        {trend.length > 0 ? (
          <div className={styles.trendChart}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <AreaChart data={trend} accessibilityLayer>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="bucket"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  scale="time"
                  minTickGap={28}
                  stroke="var(--border-strong)"
                  tick={{ fill: "var(--muted)", fontSize: 11 }}
                  tickFormatter={(value) =>
                    formatBucket(Number(value), data.bucketSeconds)
                  }
                />
                <YAxis
                  allowDecimals={false}
                  width={34}
                  stroke="var(--border-strong)"
                  tick={{ fill: "var(--muted)", fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={(value) =>
                    formatBucket(Number(value), data.bucketSeconds, true)
                  }
                  formatter={(value, name) => [
                    numberFormat(Number(value)),
                    actionLabel(String(name)),
                  ]}
                />
                <Legend
                  formatter={(value) => actionLabel(String(value))}
                  wrapperStyle={{ color: "var(--muted-strong)", fontSize: 12 }}
                />
                {auditActions.map((action) => (
                  <Area
                    key={action}
                    dataKey={action}
                    name={action}
                    stackId="actions"
                    stroke={actionColors[action]}
                    fill={actionColors[action]}
                    fillOpacity={0.14}
                    strokeWidth={2}
                    isAnimationActive={!reducedMotion}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <InsightEmpty />
        )}
      </article>

      <CheckRanking
        checks={data.checks}
        selectedCheck={selectedCheck}
        onSelectCheck={onSelectCheck}
      />

      <article className={styles.insightCard}>
        <h2>체크포인트</h2>
        {checkpoints.length > 0 ? (
          <div className={styles.checkpointChart}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <BarChart data={checkpoints} layout="vertical" accessibilityLayer>
                <CartesianGrid stroke="var(--border)" horizontal={false} />
                <XAxis
                  type="number"
                  allowDecimals={false}
                  stroke="var(--border-strong)"
                  tick={{ fill: "var(--muted)", fontSize: 11 }}
                />
                <YAxis
                  dataKey="label"
                  type="category"
                  width={58}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "var(--muted-strong)", fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value) => [numberFormat(Number(value)), "건수"]}
                />
                <Bar
                  dataKey="count"
                  name="건수"
                  fill="var(--brand)"
                  radius={[0, 3, 3, 0]}
                  isAnimationActive={!reducedMotion}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <InsightEmpty />
        )}
      </article>
    </section>
  );
}

function CheckRanking({
  checks,
  selectedCheck,
  onSelectCheck,
}: {
  checks: AuditInsights["checks"];
  selectedCheck?: string;
  onSelectCheck: (check: string) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDirection, setSortDirection] =
    useState<SortDirection>("descending");
  const sorted = useMemo(
    () =>
      [...checks].sort((left, right) => {
        const comparison =
          sortKey === "count"
            ? left.count - right.count
            : left.check.localeCompare(right.check);
        return sortDirection === "ascending" ? comparison : -comparison;
      }),
    [checks, sortDirection, sortKey],
  );

  function sort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortDirection((current) =>
        current === "ascending" ? "descending" : "ascending",
      );
      return;
    }
    setSortKey(nextKey);
    setSortDirection(nextKey === "count" ? "descending" : "ascending");
  }

  function select(check: string) {
    onSelectCheck(check);
  }

  return (
    <article className={styles.insightCard}>
      <h2>노드 발화</h2>
      {sorted.length > 0 ? (
        <div className={styles.rankingScroll}>
          <table className={styles.rankingTable}>
            <thead>
              <tr>
                <th
                  scope="col"
                  aria-sort={sortKey === "check" ? sortDirection : "none"}
                >
                  <button type="button" onClick={() => sort("check")}>
                    노드 ID
                  </button>
                </th>
                <th
                  scope="col"
                  aria-sort={sortKey === "count" ? sortDirection : "none"}
                >
                  <button type="button" onClick={() => sort("count")}>
                    발화
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((item) => (
                <tr
                  key={item.check}
                  tabIndex={0}
                  aria-selected={item.check === selectedCheck}
                  onClick={() => select(item.check)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      select(item.check);
                    }
                  }}
                >
                  <td><code title={item.check}>{item.check}</code></td>
                  <td>{numberFormat(item.count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <InsightEmpty />
      )}
    </article>
  );
}

function InsightEmpty() {
  return <div className={styles.insightEmpty}>데이터 없음</div>;
}

function trendData(data: AuditInsights) {
  if (data.actionTrend.length === 0) return [];
  const bucketMs = data.bucketSeconds * 1_000;
  const start = Math.floor(new Date(data.fromAt).getTime() / bucketMs) * bucketMs;
  const end = Math.floor(new Date(data.toAt).getTime() / bucketMs) * bucketMs;
  const buckets = new Map<number, Record<AuditAction, number>>();
  for (let bucket = start; bucket <= end; bucket += bucketMs) {
    buckets.set(bucket, emptyActions());
  }
  for (const point of data.actionTrend) {
    const bucket = new Date(point.bucket).getTime();
    const counts = buckets.get(bucket) ?? emptyActions();
    counts[point.action] += point.count;
    buckets.set(bucket, counts);
  }
  return [...buckets].map(([bucket, counts]) => ({ bucket, ...counts }));
}

function emptyActions(): Record<AuditAction, number> {
  return {
    allow: 0,
    mask: 0,
    blocked: 0,
    approval_required: 0,
  };
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

function actionLabel(value: string): string {
  return auditActions.includes(value as AuditAction)
    ? actionCopy[value as AuditAction]
    : value;
}

function formatBucket(
  timestamp: number,
  bucketSeconds: number,
  detailed = false,
): string {
  const options: Intl.DateTimeFormatOptions =
    bucketSeconds >= 86_400 && !detailed
      ? { month: "2-digit", day: "2-digit" }
      : {
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        };
  return new Intl.DateTimeFormat("ko-KR", options).format(timestamp);
}

function numberFormat(value: number): string {
  return new Intl.NumberFormat("ko-KR").format(value);
}

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "0.45rem",
  color: "var(--text)",
  fontSize: "0.72rem",
};
