import styles from "./navigan-mark.module.css";

export function NaviganMark({
  compact = false,
  reverse = compact,
}: {
  compact?: boolean;
  reverse?: boolean;
}) {
  return (
    <span
      className={`${styles.mark} ${compact ? styles.compact : ""}`}
      aria-hidden="true"
    >
      <img
        src={`/graphics/navigan-mark-${reverse ? "reverse" : "graphite"}.webp`}
        width="160"
        height="116"
        alt=""
      />
    </span>
  );
}
