import { describe, expect, it } from 'vitest';
import { openingTrendText } from './openingTrendText';

describe('current trend qualification reasons', () => {
  it('explains missing data and withdrawal in both languages', () => {
    for (const code of ['CURRENT_TREND_MINUTES_MISSING', 'CURRENT_TREND_UNIT_SOURCE_CHANGED_OR_EXPIRED',
      'CURRENT_TREND_READ_UNAVAILABLE', 'CURRENT_DAILY_TREND_CONFLICT', 'REFERENCE_TIME_CONFLICT', 'CLOCK_DISCONTINUITY']) {
      expect(openingTrendText(code, 'zh')).not.toBe(code);
      expect(openingTrendText(code, 'en')).not.toBe(code);
    }
    expect(openingTrendText('CURRENT_DAILY_TREND_CONFLICT', 'zh')).toContain('撤回');
  });

  it('keeps unknown technical codes available for diagnostics', () => {
    expect(openingTrendText('NEW_PROVIDER_DETAIL', 'en')).toBe('NEW_PROVIDER_DETAIL');
  });

  it('distinguishes the three independent option source proofs', () => {
    for (const role of ['DEPTH_UNITS', 'DELIVERABLE', 'QUOTE_MULTIPLIER']) {
      for (const state of ['MISSING', 'CHANGED', 'UNAVAILABLE']) {
        const code = `CONTRACT_${role}_SOURCE_${state}`;
        expect(openingTrendText(code, 'zh')).not.toBe(code);
        expect(openingTrendText(code, 'en')).not.toBe(code);
      }
    }
    expect(openingTrendText('CONTRACT_QUOTE_MULTIPLIER_IDENTITY_UNVERIFIED', 'zh')).toContain('报价乘数');
  });
});
