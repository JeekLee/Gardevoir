"use client";

import { useEffect, useRef, type KeyboardEvent } from "react";

import { checkpointMeta } from "../model/catalog";
import {
  editorTabAfterKey,
  editorTabs,
  type EditorTab,
} from "../model/checkpoint-view";
import styles from "./guardrail-editor.module.css";

export function EditorTabs({
  activeTab,
  focusRequest,
  onChange,
}: {
  activeTab: EditorTab;
  focusRequest: number;
  onChange: (tab: EditorTab) => void;
}) {
  const tabs = useRef(new Map<EditorTab, HTMLButtonElement>());
  const previousFocusRequest = useRef(focusRequest);

  useEffect(() => {
    if (previousFocusRequest.current === focusRequest) return;
    previousFocusRequest.current = focusRequest;
    tabs.current.get(activeTab)?.focus();
  }, [activeTab, focusRequest]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const nextTab = editorTabAfterKey(activeTab, event.key);
    if (!nextTab) return;

    event.preventDefault();
    onChange(nextTab);
    tabs.current.get(nextTab)?.focus();
  }

  return (
    <div className={styles.editorTabGroup}>
      <div
        className={styles.editorTabs}
        role="tablist"
        aria-label="가드레일 편집기 보기"
      >
        {editorTabs.map((tab) => (
          <button
            key={tab}
            ref={(element) => {
              if (element) tabs.current.set(tab, element);
              else tabs.current.delete(tab);
            }}
            id={`guardrail-tab-${tab}`}
            role="tab"
            type="button"
            tabIndex={activeTab === tab ? 0 : -1}
            aria-selected={activeTab === tab}
            aria-controls="guardrail-tab-panel"
            onClick={() => onChange(tab)}
            onKeyDown={onKeyDown}
          >
            {tab === "overview" ? (
              "개요"
            ) : (
              <>
                <span>{checkpointMeta[tab].index}</span>
                {checkpointMeta[tab].label}
              </>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
