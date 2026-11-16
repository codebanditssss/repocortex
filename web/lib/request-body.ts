export class BodyTooLargeError extends Error {}
export class BodyReadTimeoutError extends Error {}

/** Bound bytes while streaming, including requests without Content-Length. */
export async function readLimitedBody(request: Request, limit: number, timeoutMs = 15000): Promise<string> {
  const declared = request.headers.get("content-length");
  if (declared && Number(declared) > limit) throw new BodyTooLargeError();
  if (!request.body) return "";
  const reader = request.body.getReader();
  if (request.signal.aborted) {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
    throw new DOMException("Upload cancelled", "AbortError");
  }
  const chunks: Uint8Array[] = [];
  let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: () => void;
  // One deadline for the entire upload; receiving bytes does not reset it.
  const deadline = new Promise<never>((_resolve, reject) => {
    onAbort = () => {
      reject(new DOMException("Upload cancelled", "AbortError"));
      void reader.cancel().catch(() => {});
    };
    request.signal.addEventListener("abort", onAbort, { once: true });
    timer = setTimeout(() => {
      reject(new BodyReadTimeoutError());
      // Cancellation itself may never settle for a hostile stream.
      void reader.cancel().catch(() => {});
    }, timeoutMs);
  });
  try {
    while (true) {
      const { done, value } = await Promise.race([reader.read(), deadline]);
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        void reader.cancel().catch(() => {});
        throw new BodyTooLargeError();
      }
      chunks.push(value);
    }
  } finally {
    clearTimeout(timer);
    request.signal.removeEventListener("abort", onAbort!);
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}
