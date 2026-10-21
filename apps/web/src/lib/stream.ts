/**
 * Streamed replies over server-sent events (POST, so not EventSource).
 *
 * The backend sends `delta` events with text as the model writes it, `restart` when the backup
 * provider takes over mid-reply (drop the partial text), then `done` with the final body (its
 * `reply` replaces the streamed text) or `error`. Errors before the first event arrive as a
 * normal HTTP error and throw ApiError like `api()`.
 */
import { ApiError, codeFrom } from "./api";

/** The reply had started when it failed: nothing was saved, the message can be sent again. */
export class StreamInterruptedError extends ApiError {
  constructor(code: string) {
    super(0, code);
    this.name = "StreamInterruptedError";
  }
}

export type StreamHandlers = {
  onDelta: (text: string) => void;
  onRestart: () => void;
};

type Options = { guestToken?: string };

export async function streamApi<T>(
  path: string,
  body: unknown,
  handlers: StreamHandlers,
  options: Options = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  // Not `Authorization`: that header carries HTTP basic auth of a gate in front of the app.
  if (options.guestToken) headers["X-Agentree-Guest"] = options.guestToken;
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (!res.ok || !res.body || !res.headers.get("content-type")?.startsWith("text/event-stream")) {
    throw new ApiError(res.ok ? 502 : res.status, codeFrom(await jsonOrNull(res)));
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value.replace(/\r\n/g, "\n");
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const event = parse(block);
        if (!event) continue;
        if (event.name === "delta") handlers.onDelta(String(event.data.text ?? ""));
        else if (event.name === "restart") handlers.onRestart();
        else if (event.name === "done") return event.data as T;
        else if (event.name === "error") throw new StreamInterruptedError(String(event.data.code ?? "unknown_error"));
      }
    }
  } catch (err) {
    if (err instanceof StreamInterruptedError) throw err;
    throw new StreamInterruptedError("network_error");
  } finally {
    reader.cancel().catch(() => {});
  }
  throw new StreamInterruptedError("network_error"); // ended without `done`
}

function parse(block: string): { name: string; data: Record<string, unknown> } | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try {
    return { name, data: JSON.parse(data.join("\n")) as Record<string, unknown> };
  } catch {
    return null;
  }
}

async function jsonOrNull(res: Response): Promise<unknown> {
  try {
    return JSON.parse(await res.text());
  } catch {
    return null;
  }
}
