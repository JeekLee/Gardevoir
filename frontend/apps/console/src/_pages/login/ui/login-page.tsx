import { LoginForm } from "@/src/features/authenticate";
import { GardevoirMark } from "@/src/shared/ui/gardevoir-mark";

import styles from "./login-page.module.css";

export function LoginPage({
  reason,
  returnTo,
}: {
  reason: "expired" | "forbidden" | null;
  returnTo: string | null;
}) {
  return (
    <main className={styles.page}>
      <section className={styles.intro} aria-labelledby="login-title">
        <div className={styles.brand}>
          <GardevoirMark />
          <span>
            <strong>gardevoir</strong>
            <small>통제실</small>
          </span>
        </div>

        <div className={styles.copy}>
          <p className={styles.eyebrow}>
            <span aria-hidden="true" />
            보호 체계 가동 중
          </p>
          <h1 id="login-title">모든 모델 경로를 안전하게 통제하세요.</h1>
          <p>
            신뢰할 수 있는 업스트림을 연결하고 모든 요청을 정해진 경로로
            전달하세요.
          </p>
        </div>

        <div className={styles.signal} aria-label="게이트웨이 상태: 인증 대기 중">
          <span className={styles.signalLine} aria-hidden="true" />
          <span className={styles.signalCore} aria-hidden="true" />
          <div>
            <strong>게이트웨이 준비 완료</strong>
            <small>인증 대기 중</small>
          </div>
        </div>
      </section>

      <section className={styles.access} aria-label="로그인">
        <div className={styles.card}>
          <LoginForm reason={reason} returnTo={returnTo} />
          <p className={styles.footnote}>
            콘솔 계정은 애플리케이션 <code>gdv_</code> 키와 별도로 관리됩니다.
          </p>
        </div>
      </section>
    </main>
  );
}
