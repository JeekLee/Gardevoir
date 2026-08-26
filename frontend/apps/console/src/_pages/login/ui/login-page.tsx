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
            <small>control room</small>
          </span>
        </div>

        <div className={styles.copy}>
          <p className={styles.eyebrow}>
            <span aria-hidden="true" />
            Sentinel online
          </p>
          <h1 id="login-title">Guard the path to every model.</h1>
          <p>
            Configure trusted upstreams and keep every request on a deliberate
            route.
          </p>
        </div>

        <div className={styles.signal} aria-label="Gateway status: awaiting authorization">
          <span className={styles.signalLine} aria-hidden="true" />
          <span className={styles.signalCore} aria-hidden="true" />
          <div>
            <strong>Gateway ready</strong>
            <small>Awaiting authorization</small>
          </div>
        </div>
      </section>

      <section className={styles.access} aria-label="Sign in">
        <div className={styles.card}>
          <LoginForm reason={reason} returnTo={returnTo} />
          <p className={styles.footnote}>
            Console credentials are separate from application <code>gdv_</code>
            keys.
          </p>
        </div>
      </section>
    </main>
  );
}
