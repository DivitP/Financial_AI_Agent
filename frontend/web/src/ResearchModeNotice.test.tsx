import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ResearchModeNotice } from "./ResearchModeNotice";

it("shows synthetic, live and old-record unknown provenance explicitly", () => {
  const { rerender } = render(<ResearchModeNotice mode="synthetic" />);
  expect(screen.getByRole("note")).toHaveTextContent("invented data");
  rerender(<ResearchModeNotice mode="live" />);
  expect(screen.getByRole("note")).toHaveTextContent("Live-source");
  rerender(<ResearchModeNotice />);
  expect(screen.getByRole("note")).toHaveTextContent("Unknown research mode");
});
