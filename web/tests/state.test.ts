import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_APP_STATE, MAX_COMPARED_SENSORS, selectOnly, toggleInSelection, type AppState } from '../src/state/AppState';
import { HashStateCodec } from '../src/state/HashStateCodec';
import { Store } from '../src/state/Store';

const codec = new HashStateCodec();

describe('HashStateCodec', () => {
  it('encodes the documented example', () => {
    const state: AppState = { selectedSensorIds: ['77678271', '77680921'], window: { kind: '7d' }, resolution: 'hourly', language: 'cs' };
    expect(codec.encode(state)).toBe('#s=77678271,77680921&w=7d&r=hourly&lang=cs');
  });

  it.each<AppState>([
    { selectedSensorIds: ['77678271'], window: { kind: '24h' }, resolution: 'raw', language: 'de' },
    { selectedSensorIds: ['77678271', '77799986'], window: { kind: 'season', year: 2026 }, resolution: 'auto', language: 'en' },
    { selectedSensorIds: [], window: { kind: 'custom', from: '2026-06-01', to: '2026-06-15' }, resolution: 'daily', language: 'cs' },
    { selectedSensorIds: [], window: { kind: '30d' }, resolution: 'auto', language: 'cs' },
  ])('round-trips %j', (state) => {
    expect({ ...DEFAULT_APP_STATE, ...codec.decode(codec.encode(state)) }).toEqual(state);
  });

  it('omits r for automatic resolution and s for an empty selection', () => {
    expect(codec.encode(DEFAULT_APP_STATE)).toBe('#w=7d&lang=cs');
  });

  it('ignores invalid parts and keeps valid ones', () => {
    expect(codec.decode('#s=7767<8271,77680921&w=year&r=fast&lang=fr')).toEqual({ selectedSensorIds: ['77680921'] });
    expect(codec.decode('#w=season&y=26')).toEqual({});
    expect(codec.decode('#w=custom&from=2026-06-01')).toEqual({});
    expect(codec.decode('')).toEqual({});
    expect(codec.decode('#s=77678271%2C77680921')).toEqual({ selectedSensorIds: ['77678271', '77680921'] });
  });
});

describe('Store', () => {
  it('notifies listeners with new and previous state only on change', () => {
    const store = new Store({ a: 1, b: 'x' });
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.update({ a: 1 });
    expect(listener).not.toHaveBeenCalled();
    store.update({ a: 2 });
    expect(listener).toHaveBeenCalledWith({ a: 2, b: 'x' }, { a: 1, b: 'x' });
    expect(Object.isFrozen(store.state)).toBe(true);
    unsubscribe();
    store.update({ a: 3 });
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe('selection', () => {
  it('selects one sensor or toggles it in the comparison', () => {
    expect(selectOnly('a')).toEqual(['a']);
    expect(toggleInSelection(['a'], 'b')).toEqual(['a', 'b']);
    expect(toggleInSelection(['a', 'b'], 'a')).toEqual(['b']);
  });

  it('does not exceed the comparison limit', () => {
    const full = ['a', 'b'];
    expect(toggleInSelection(full, 'c', 2)).toBe(full);
    expect(MAX_COMPARED_SENSORS).toBe(8);
  });
});
