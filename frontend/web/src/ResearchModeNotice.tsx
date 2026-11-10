export function ResearchModeNotice({ mode }: { mode?: string }) {
  const label =
    mode === "synthetic"
      ? "Synthetic research — invented data, not real financial evidence."
      : mode === "live"
        ? "Live-source research — not a guarantee of accuracy or investment advice."
        : "Unknown research mode — provenance was not recorded; do not assume live or verified data.";
  return (
    <p role="note" aria-label="Research mode">
      {label}
    </p>
  );
}
