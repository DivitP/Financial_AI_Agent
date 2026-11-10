import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { PriceHistory } from "./PriceHistory";

it("renders a native historical chart and accessible values without encoded images", () => {
  const { container } = render(
    <PriceHistory
      snapshots={[
        {
          lane: "ohlcv",
          status: "completed",
          error_message: null,
          payload: {
            currency: "USD",
            adjustment_policy: "provider_adjusted_close",
            candles: [
              { timestamp: "2026-01-01", close: 100 },
              { timestamp: "2026-01-02", close: 102 },
            ],
          },
        },
      ]}
    />,
  );
  expect(screen.getByRole("img")).toHaveAccessibleName(/No future predictions/);
  expect(screen.getByText("102")).toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
});
