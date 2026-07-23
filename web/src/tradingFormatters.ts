export function parseRiskReward(value: string | undefined): number {
  if (!value) return 0;
  const match = value.match(/(\d+(?:\.\d+)?)/);
  return match ? Number(match[1]) : 0;
}
