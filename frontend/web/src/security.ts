/** Provider-controlled links must be absolute HTTP(S), without credentials or controls. */
export function safeExternalUrl(value: unknown): string | undefined {
  if (typeof value !== "string" || /[\u0000-\u0020\u007f\\]/.test(value) || !/^https?:\/\//i.test(value)) return undefined;
  try {
    const url = new URL(value);
    return url.hostname && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}
