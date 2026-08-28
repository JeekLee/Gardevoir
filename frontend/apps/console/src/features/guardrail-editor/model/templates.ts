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
    name: "외부 데이터 유입 후 부작용 툴",
    description: "툴 결과가 들어온 뒤 부작용 툴 호출을 차단합니다.",
    checkpoints: ["tool_result", "tool_call"],
    graph: {
      nodes: [
        {
          id: "tool-result-history",
          type: "extract",
          config: { from: "tool_result", at: "tool_call" },
        },
        {
          id: "has-tool-result",
          type: "regex",
          config: { pattern: "." },
        },
        {
          id: "side-effect-tool",
          type: "tool_extract",
          config: {
            tools: { exclude: ["read_file", "web_search"] },
            field: "name",
          },
        },
        {
          id: "has-side-effect-tool",
          type: "regex",
          config: { pattern: "." },
        },
        {
          id: "block",
          type: "verdict",
          config: { action: "block", combine: "all" },
        },
      ],
      edges: [
        { src: "tool-result-history", dst: "has-tool-result" },
        { src: "has-tool-result", dst: "block" },
        { src: "side-effect-tool", dst: "has-side-effect-tool" },
        { src: "has-side-effect-tool", dst: "block" },
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
          config: { from: "output_text", at: "output" },
        },
        {
          id: "ssn",
          type: "regex",
          config: { pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b" },
        },
        {
          id: "mask",
          type: "verdict",
          config: { action: "mask", combine: "any" },
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
          config: { from: "user_text", at: "input" },
        },
        {
          id: "too-long",
          type: "regex",
          config: { pattern: "(?s).{4001,}" },
        },
        {
          id: "block",
          type: "verdict",
          config: { action: "block", combine: "any" },
        },
      ],
      edges: [
        { src: "input-text", dst: "too-long" },
        { src: "too-long", dst: "block" },
      ],
    },
  },
  {
    id: "external-email-domain",
    name: "허용 도메인 외 발신 차단",
    description: "사내 도메인 밖의 수신 주소를 차단합니다.",
    checkpoints: ["tool_call"],
    graph: {
      nodes: [
        {
          id: "email-to",
          type: "tool_extract",
          config: {
            tools: { exclude: ["read_file", "web_search"] },
            field: "to",
          },
        },
        {
          id: "company-domain",
          type: "regex",
          config: { pattern: "@company\\.com$" },
        },
        {
          id: "outside-company",
          type: "not",
          config: {},
        },
        {
          id: "block",
          type: "verdict",
          config: { action: "block", combine: "any" },
        },
      ],
      edges: [
        { src: "email-to", dst: "company-domain" },
        { src: "company-domain", dst: "outside-company" },
        { src: "outside-company", dst: "block" },
      ],
    },
  },
];
