import { describe, expect, it } from "vitest";
import { safeExternalUrl } from "./security";

describe("evidence URL boundary", () => {
  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:image/svg+xml,<svg onload=alert(1)>",
    "//evil.test",
    "https://user:pass@example.com",
    "https://example.com\n",
    "https:\\evil.test",
  ])("rejects %s", (value) => {
    expect(safeExternalUrl(value)).toBeUndefined();
  });
  it("preserves exact source sections", () => {
    expect(safeExternalUrl("https://www.sec.gov/filing#section")).toBe(
      "https://www.sec.gov/filing#section",
    );
  });
});
