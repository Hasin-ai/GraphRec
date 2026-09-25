import { describe, expect, it } from 'vitest';
import { quotaState } from './quota';

describe('quota boundaries', () => {
  it.each([
    [0, null, 'informational', null], [90, null, 'informational', null],
    [0, 0, 'exhausted', 0], [5, 0, 'exhausted', 0],
    [79, 100, 'healthy', 21], [80, 100, 'approaching', 20],
    [100, 100, 'exhausted', 0], [120, 100, 'exhausted', 0],
  ] as const)('%s used against %s => %s', (used, limit, status, remaining) => {
    expect(quotaState(used, limit)).toMatchObject({ status, remaining });
  });
});
