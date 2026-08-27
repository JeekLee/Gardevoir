import type {
  Checkpoint,
  GuardrailGraph,
} from "@/src/entities/guardrail";

export type GuardrailTemplate = {
  id: string;
  name: string;
  description: string;
  checkpoints: Checkpoint[];
  graph: GuardrailGraph;
};

export const guardrailTemplates: GuardrailTemplate[] = [
  {
    id: "tainted-side-effect",
    name: "오염 데이터에서 행동 차단",
    description: "외부(툴 결과) 데이터가 섞인 대화에서 부작용 툴 호출을 차단합니다.",
    checkpoints: ["tool_result", "tool_call"],
    graph: {
      nodes: [
        {
          id: "tainted",
          type: "taint",
          config: { checkpoint: "tool_call" },
        },
        {
          id: "side-effect",
          type: "side_effect",
          config: { checkpoint: "tool_call", read_only: [] },
        },
        { id: "tainted-and-side-effect", type: "all", config: {} },
        {
          id: "block",
          type: "verdict",
          config: { action: "block" },
        },
      ],
      edges: [
        { src: "tainted", dst: "tainted-and-side-effect" },
        { src: "side-effect", dst: "tainted-and-side-effect" },
        { src: "tainted-and-side-effect", dst: "block" },
      ],
    },
  },
  {
    id: "output-pii-mask",
    name: "출력 PII 마스킹",
    description: "모델 응답에서 주민/카드번호 형태를 찾으면 마스킹합니다.",
    checkpoints: ["output"],
    graph: {
      nodes: [
        {
          id: "output-text",
          type: "extract",
          config: { checkpoint: "output" },
        },
        {
          id: "ssn",
          type: "regex",
          config: { pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b" },
        },
        {
          id: "mask",
          type: "verdict",
          config: { action: "mask" },
        },
      ],
      edges: [
        { src: "output-text", dst: "ssn" },
        { src: "ssn", dst: "mask" },
      ],
    },
  },
  {
    id: "input-length-limit",
    name: "입력 길이 제한",
    description: "사용자 입력이 너무 길면 차단합니다.",
    checkpoints: ["input"],
    graph: {
      nodes: [
        {
          id: "input-text",
          type: "extract",
          config: { checkpoint: "input" },
        },
        { id: "too-long", type: "length", config: { max_chars: 4000 } },
        {
          id: "block",
          type: "verdict",
          config: { action: "block" },
        },
      ],
      edges: [
        { src: "input-text", dst: "too-long" },
        { src: "too-long", dst: "block" },
      ],
    },
  },
  {
    id: "external-argument",
    name: "외부 인수 출처 차단",
    description: "툴 호출 인수가 외부 툴 결과에서 온 것이면 차단합니다.",
    checkpoints: ["tool_result", "tool_call"],
    graph: {
      nodes: [
        {
          id: "external-arg",
          type: "provenance",
          config: { checkpoint: "tool_call", min_length: 8 },
        },
        {
          id: "block",
          type: "verdict",
          config: { action: "block" },
        },
      ],
      edges: [{ src: "external-arg", dst: "block" }],
    },
  },
];
