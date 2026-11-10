import { useState } from "react";

export function RawData({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{label}</summary>
      {open && <pre>{JSON.stringify(value, null, 2)}</pre>}
    </details>
  );
}
