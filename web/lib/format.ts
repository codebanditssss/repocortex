export function formatPercent(value: number): string {
  return `${Number((value * 100).toFixed(2))}%`;
}
