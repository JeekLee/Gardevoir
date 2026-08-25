/** Generate a unique id for a graph node or edge. */
export function randomId(): string {
  // crypto.randomUUID 는 보안 컨텍스트(HTTPS·localhost)에서만 정의된다. 콘솔은
  // LAN 의 평문 HTTP 로 접속되어 이 값이 undefined 이고, 호출하면 예외가 나 노드·
  // 엣지 추가가 조용히 실패한다. getRandomValues 는 이 제약이 없어 폴백으로 쓴다.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
