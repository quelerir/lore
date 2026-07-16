import type { IStep } from "@chainlit/react-client";
import styles from "./ExecutionSteps.module.css";

interface Props {
  steps: IStep[];
  running: boolean;
}

export default function ExecutionSteps({ steps, running }: Props) {
  if (!steps.length) return null;

  return (
    <details className={styles.box} open={running}>
      <summary className={styles.summary}>
        Ход выполнения
        <span className={styles.count}>{steps.length}</span>
      </summary>
      <ol className={styles.list}>
        {steps.map((step) => (
          <li
            key={step.id}
            className={step.isError ? styles.itemError : styles.item}
          >
            <div className={styles.name}>{step.name}</div>
            {step.input ? <pre className={styles.io}>{step.input}</pre> : null}
            <pre className={styles.io}>
              {step.output || (step.streaming ? "…" : "")}
            </pre>
          </li>
        ))}
      </ol>
    </details>
  );
}
