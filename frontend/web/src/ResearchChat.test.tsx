import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ResearchChat } from "./ResearchChat";

afterEach(() => vi.unstubAllGlobals());

it("streams validated excerpts and opens their exact citation", async () => {
  const claim = { text: "Revenue faces pressure.", citation: { url: "https://example.com/filing#risks", evidence_id: "e1", section: "Risks", excerpt: "Revenue faces pressure.", published_at: "2026-01-01" } };
  const turn = { id: 1, question: "Revenue?", answer: { status: "answered", message: "Source excerpts", claims: [claim] } };
  const bytes = new TextEncoder().encode(`event: claim\ndata: ${JSON.stringify(claim)}\n\nevent: complete\ndata: ${JSON.stringify(turn)}\n\n`);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] }).mockResolvedValueOnce({ ok: true, body: new ReadableStream({ start(c) { c.enqueue(bytes.slice(0, 30)); c.enqueue(bytes.slice(30)); c.close(); } }) }));
  render(<ResearchChat runId="run" />);
  fireEvent.change(screen.getByLabelText("Research question"), { target: { value: "Revenue?" } });
  fireEvent.click(screen.getByRole("button", { name: "Ask question" }));
  expect(await screen.findByText("Source excerpts")).toBeInTheDocument();
  expect(screen.getByText("Revenue faces pressure.")).toBeInTheDocument();
  fireEvent.mouseEnter(screen.getByRole("button", { name: "Source: Risks" }));
  expect(await screen.findByRole("link", { name: "Open exact source" })).toHaveAttribute("href", "https://example.com/filing#risks");
});

it("restores insufficient-evidence history", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [{ id: 1, question: "Unknown?", answer: { status: "insufficient_evidence", message: "Insufficient evidence", claims: [] } }] }));
  render(<ResearchChat runId="run" />);
  expect(await screen.findByText("Insufficient evidence")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Open exact source" })).not.toBeInTheDocument();
});
