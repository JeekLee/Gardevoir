import Link from "next/link";

import { GardevoirMark } from "@/src/shared/ui/gardevoir-mark";

import styles from "./not-found.module.css";

export default function NotFound() {
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="not-found-title">
        <GardevoirMark />
        <p>찾을 수 없는 경로</p>
        <h1 id="not-found-title">페이지를 찾을 수 없습니다</h1>
        <span>주소를 확인하거나 가드레일 목록으로 돌아가세요.</span>
        <Link href="/guardrails">가드레일 목록으로</Link>
      </section>
    </main>
  );
}
