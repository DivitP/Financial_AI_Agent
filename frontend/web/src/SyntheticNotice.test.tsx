import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SyntheticNotice } from "./SyntheticNotice";

it("labels invented data and does not label live data synthetic", () => {
  const { rerender } = render(<SyntheticNotice snapshots={[]} />);
  expect(screen.queryByRole("note")).toBeNull();
  rerender(<SyntheticNotice snapshots={[{lane: "quote", status: "completed", error_message: null, payload: {synthetic: true}}]} />);
  expect(screen.getByRole("note")).toHaveTextContent("not SEC filings");
  rerender(<SyntheticNotice snapshots={[{lane: "quote", status: "completed", error_message: null, payload: {provider: "yahoo"}}]} />);
  expect(screen.queryByRole("note")).toBeNull();
});
