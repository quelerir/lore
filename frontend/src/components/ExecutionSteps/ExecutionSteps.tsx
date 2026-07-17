import type { IStep } from "@chainlit/react-client";
import {
  formatDuration,
  formatIo,
  MESSAGE_TYPES,
} from "../../chat/executionSteps";
import styles from "./ExecutionSteps.module.css";

interface Props {
  steps: IStep[];
  running: boolean;
}

function statusMark(step: IStep): string {
  if (step.isError) return "✗";
  if (step.streaming || !step.end) return "…";
  return "✓";
}

function StepItem({ step }: { step: IStep }) {
  const children = (step.steps ?? []).filter((s) => !MESSAGE_TYPES.has(s.type));
  const isRunning = Boolean(step.streaming) || !step.end;
  const duration = formatDuration(step.start, step.end);
  return (
    <li className={step.isError ? styles.itemError : styles.item}>
      <details open={isRunning}>
        <summary className={styles.stepSummary}>
          <span className={styles.mark}>{statusMark(step)}</span>
          <span className={styles.typeBadge}>{step.type}</span>
          <span className={styles.stepName}>{step.name}</span>
          {duration ? <span className={styles.duration}>{duration}</span> : null}
        </summary>
        {step.input ? <pre className={styles.io}>{formatIo(step.input)}</pre> : null}
        {step.output || step.streaming ? (
          <pre className={styles.io}>
            {formatIo(step.output) || (step.streaming ? "…" : "")}
          </pre>
        ) : null}
        {children.length ? (
          <ol className={styles.list}>
            {children.map((child) => (
              <StepItem key={child.id} step={child} />
            ))}
          </ol>
        ) : null}
      </details>
    </li>
  );
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
          <StepItem key={step.id} step={step} />
        ))}
      </ol>
    </details>
  );
}
