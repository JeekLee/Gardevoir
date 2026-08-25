"use client";

import { useRef } from "react";

import { checkpointMeta } from "../model/catalog";
import {
  guardrailTemplates,
  type GuardrailTemplate,
} from "../model/templates";
import styles from "./guardrail-editor.module.css";

export function TemplatePicker({
  onApply,
  onClose,
}: {
  onApply: (template: GuardrailTemplate) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  function setDialog(element: HTMLDialogElement | null) {
    dialogRef.current = element;
    if (element && !element.open) element.showModal();
  }

  return (
    <dialog
      ref={setDialog}
      className={styles.templateDialog}
      aria-labelledby="template-picker-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className={styles.templateHeader}>
        <div>
          <p>Scenario templates</p>
          <h2 id="template-picker-title">템플릿에서 시작</h2>
          <span>운영 시나리오를 고르면 검증된 그래프를 레인에 자동 배치합니다.</span>
        </div>
        <button type="button" onClick={onClose} aria-label="템플릿 선택 닫기">
          ×
        </button>
      </div>

      <div className={styles.templateGrid}>
        {guardrailTemplates.map((template, index) => (
          <article key={template.id} className={styles.templateCard}>
            <div className={styles.templateTitle}>
              <span>T{index + 1}</span>
              <div>
                <h3>{template.name}</h3>
                {index === 0 ? <b>대표</b> : null}
              </div>
            </div>
            <p>{template.description}</p>
            <div
              className={styles.templateCheckpoints}
              aria-label={`${template.name} 검사 지점`}
            >
              {template.checkpoints.map((checkpoint) => (
                <span key={checkpoint}>
                  {checkpointMeta[checkpoint].index} {checkpointMeta[checkpoint].label}
                </span>
              ))}
            </div>
            <button type="button" onClick={() => onApply(template)}>
              이 템플릿 사용
            </button>
          </article>
        ))}
      </div>
    </dialog>
  );
}
