"use client";

import { useSyncExternalStore } from "react";

const noSubscribe = () => () => {};

/**
 * A browser-only value read once after hydration (e.g. window.location.origin): the server
 * render and the first client render use `serverValue`, so markup always matches.
 */
export function useClientValue<T>(read: () => T, serverValue: T): T {
  return useSyncExternalStore(noSubscribe, read, () => serverValue);
}
