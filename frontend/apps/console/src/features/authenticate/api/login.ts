import { parseSession } from "@/src/entities/session";
import { apiRequest } from "@/src/shared/api";

export function login(input: { email: string; password: string }) {
  return apiRequest({
    path: "/auth/login",
    method: "POST",
    body: input,
    parse: parseSession,
  });
}
