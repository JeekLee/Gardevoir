import styles from "./gardevoir-mark.module.css";

export function GardevoirMark({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={`${styles.mark} ${compact ? styles.compact : ""}`}
      aria-hidden="true"
    >
      <svg viewBox="0 0 48 48" role="presentation">
        <path
          className={styles.crown}
          d="M8 8.5 24 3l16 5.5v13.2c0 10.2-6.3 18.5-16 23.3C14.3 40.2 8 31.9 8 21.7V8.5Z"
        />
        <path
          className={styles.face}
          d="M14.4 13.2 24 9.9l9.6 3.3v8.2c0 7-3.7 12.8-9.6 16.5-5.9-3.7-9.6-9.5-9.6-16.5v-8.2Z"
        />
        <path className={styles.gate} d="M19 18v11m10-11v11M19 21h10" />
      </svg>
    </span>
  );
}
