// Prices retain the paper ledger's four decimal places; cash uses paise.
export const formatPrice = (value: number) => new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2, maximumFractionDigits: 4, useGrouping: false,
}).format(value);

export function roundToTick(price: number, tickSize: number): number {
  if (tickSize <= 0) return price;
  return Number((Math.round(price / tickSize) * tickSize).toFixed(4));
}
export function adjustPrice(price: number, tickSize: number, dir: "up" | "down"): number {
  const ticks = Math.round(price / tickSize) + (dir === "up" ? 1 : -1);
  return Math.max(0, Number((ticks * tickSize).toFixed(4)));
}
