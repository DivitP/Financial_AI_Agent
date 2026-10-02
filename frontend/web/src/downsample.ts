import { ForecastCandle } from "./api";

/** Display-only OHLC buckets: preserve opening/closing prices and each bucket's extremes. */
export function downsampleCandles(candles: ForecastCandle[], maximum = 60): ForecastCandle[] {
  if (!Number.isInteger(maximum) || maximum < 1) throw Error("maximum must be positive");
  if (candles.length <= maximum) return candles;
  const result: ForecastCandle[] = [];
  for (let bucket = 0; bucket < maximum; bucket++) {
    const start = Math.floor(bucket * candles.length / maximum);
    const end = Math.floor((bucket + 1) * candles.length / maximum);
    const values = candles.slice(start, end);
    result.push({ session: `${values[0].session} – ${values.at(-1)!.session}`, open: values[0].open, close: values.at(-1)!.close,
      high: values.reduce((high, candle) => Math.max(high, Number(candle.high)), -Infinity),
      low: values.reduce((low, candle) => Math.min(low, Number(candle.low)), Infinity) });
  }
  return result;
}
