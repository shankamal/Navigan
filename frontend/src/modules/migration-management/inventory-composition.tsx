import styles from "./migration-experience.module.css";
const colors = ["#267245", "#168b98", "#7858b5", "#d18b28", "#687680"];
export function InventoryComposition({ kinds }: { kinds: [string, number][] }) {
  const sorted = [...kinds].sort((a, b) => b[1] - a[1]);
  const groups: [string, number][] = sorted.slice(0, 4);
  const rest = sorted.slice(4).reduce((sum, [, count]) => sum + count, 0);
  if (rest) groups.push(["Other kinds", rest]);
  const total = groups.reduce((sum, [, count]) => sum + count, 0);
  if (!total) return null;
  let end = 0;
  const segments = groups.map(([, count], i) => {
    const start = end;
    end += (count / total) * 100;
    return `${colors[i]} ${start}% ${end}%`;
  });
  return (
    <figure
      className={styles.composition}
      aria-label={`Resource composition: ${total} collected records`}
    >
      <div
        className={styles.donut}
        style={{ background: `conic-gradient(${segments.join(",")})` }}
        aria-hidden="true"
      />
      <figcaption>
        <strong>Resource mix</strong>
        <div className={styles.legend}>
          {groups.map(([name, count], i) => (
            <span key={name}>
              <i
                className={styles.dot}
                style={{ background: colors[i] }}
                aria-hidden="true"
              />
              {name} <strong>{count}</strong>
            </span>
          ))}
        </div>
      </figcaption>
    </figure>
  );
}
