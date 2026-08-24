"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ConsoleApiError } from "@/src/shared/api";

import { listProviders } from "../api/provider-api";
import type { ProviderPage } from "./provider";

type ProviderState = {
  data: ProviderPage | null;
  error: ConsoleApiError | null;
  isLoading: boolean;
};

export function useProviders(
  accessToken: string,
  onAuthorizationError: (error: ConsoleApiError) => void,
) {
  const [state, setState] = useState<ProviderState>({
    data: null,
    error: null,
    isLoading: true,
  });
  const activeRequest = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setState((current) => ({ ...current, error: null, isLoading: true }));

    try {
      const data = await listProviders(accessToken, controller.signal);
      if (!controller.signal.aborted) {
        setState({ data, error: null, isLoading: false });
      }
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      if (
        error instanceof ConsoleApiError &&
        (error.httpStatus === 401 || error.httpStatus === 403)
      ) {
        onAuthorizationError(error);
        return;
      }
      setState({
        data: null,
        error:
          error instanceof ConsoleApiError
            ? error
            : new ConsoleApiError({
                httpStatus: 0,
                code: "CONSOLE-005",
                message: "The provider list could not be loaded.",
              }),
        isLoading: false,
      });
    }
  }, [accessToken, onAuthorizationError]);

  useEffect(() => {
    const controller = new AbortController();
    activeRequest.current = controller;

    void listProviders(accessToken, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ data, error: null, isLoading: false });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        if (
          error instanceof ConsoleApiError &&
          (error.httpStatus === 401 || error.httpStatus === 403)
        ) {
          onAuthorizationError(error);
          return;
        }
        setState({
          data: null,
          error: normalizeError(error),
          isLoading: false,
        });
      });

    return () => controller.abort();
  }, [accessToken, onAuthorizationError]);

  return { ...state, reload };
}

function normalizeError(error: unknown): ConsoleApiError {
  return error instanceof ConsoleApiError
    ? error
    : new ConsoleApiError({
        httpStatus: 0,
        code: "CONSOLE-005",
        message: "The provider list could not be loaded.",
      });
}
