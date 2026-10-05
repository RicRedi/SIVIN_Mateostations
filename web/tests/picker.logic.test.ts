import { describe, expect, it } from 'vitest';
import type { SensorInfo } from '../src/app/SensorCatalog';
import { SensorGrouping } from '../src/app/SensorGroups';
import { SensorQuery, foldText } from '../src/app/SensorQuery';
import { checkState, toggleGroupInSelection } from '../src/state/GroupSelection';

// Picker logic (WP-3.5). All sensors, names and varieties are synthetic.

function sensor(id: string, municipality: string | null, track: string | null, extra: Partial<SensorInfo> = {}): SensorInfo {
  return {
    id,
    label: `${id} (demo)`,
    lat: 48.8,
    lon: 16.6,
    elevation_m: null,
    placedSince: null,
    municipality,
    track,
    variety: null,
    status: 'active',
    latest: null,
    hasData: true,
    ...extra,
  };
}

const SENSORS = [
  sensor('90000005', 'Obec B', 'Trať 10'),
  sensor('90000004', null, null),
  sensor('90000003', 'Obec A', 'Trať 2', { status: 'retired', label: 'A retired' }),
  sensor('90000002', 'Obec A', 'Trať 2', { label: 'Z active' }),
  sensor('90000001', 'Obec A', null),
  sensor('90000006', 'Obec B', 'Trať 9'),
  sensor('90000007', 'Čejkovice', 'Trať 1'),
  sensor('90000008', 'Obec A', 'Trať 2', { label: 'M active', status: 'inactive' }),
];

describe('SensorGrouping', () => {
  const groups = new SensorGrouping().group(SENSORS);

  it('sorts municipalities by Czech collation with the unassigned group last', () => {
    // Czech collation: "Č" sorts after "C" and before "D", so before "O".
    expect(groups.map((g) => g.name)).toEqual(['Čejkovice', 'Obec A', 'Obec B', null]);
  });

  it('sorts tracks naturally with the unassigned track last', () => {
    const obecA = groups[1];
    const obecB = groups[2];
    expect(obecA?.tracks.map((t) => t.name)).toEqual(['Trať 2', null]);
    expect(obecB?.tracks.map((t) => t.name)).toEqual(['Trať 9', 'Trať 10']);
    expect(groups[3]?.tracks.map((t) => t.name)).toEqual([null]);
  });

  it('sorts sensors by label with retired sensors last', () => {
    const track = groups[1]?.tracks[0];
    expect(track?.sensors.map((s) => s.id)).toEqual(['90000008', '90000002', '90000003']);
  });

  it('gives every group a unique key', () => {
    const keys = groups.flatMap((g) => [g.key, ...g.tracks.map((t) => t.key)]);
    expect(new Set(keys).size).toBe(keys.length);
    expect(groups[3]?.key).toBe('[null]');
    expect(groups[1]?.tracks[1]?.key).toBe('["Obec A",null]');
  });

  it('keeps every sensor exactly once', () => {
    const ids = groups.flatMap((g) => g.tracks.flatMap((t) => t.sensors.map((s) => s.id)));
    expect([...ids].sort()).toEqual(SENSORS.map((s) => s.id).sort());
  });

  it('breaks label ties by id', () => {
    const twins = new SensorGrouping().group([sensor('2', 'X', 'Y', { label: 'same' }), sensor('1', 'X', 'Y', { label: 'same' })]);
    expect(twins[0]?.tracks[0]?.sensors.map((s) => s.id)).toEqual(['1', '2']);
  });
});

describe('SensorQuery', () => {
  const vineyard = sensor('77678271', 'Šakvice', 'Trkmanská', { label: '77678271 (VUT)', variety: 'Ryzlink rýnský' });

  it('folds case and diacritics', () => {
    expect(foldText('Šlechtitelská Ž ČÍ')).toBe('slechtitelska z ci');
  });

  it('matches id, label, municipality, track and variety without diacritics', () => {
    for (const text of ['7767', 'vut', 'sakvice', 'TRKMAN', 'rynsky', 'Ryzlink  Šak']) {
      expect(SensorQuery.parse(text).matches(vineyard)).toBe(true);
    }
  });

  it('needs every word to match', () => {
    expect(SensorQuery.parse('ryzlink pálava').matches(vineyard)).toBe(false);
    expect(SensorQuery.parse('obec').matches(vineyard)).toBe(false);
  });

  it('matches everything when empty and ignores null fields', () => {
    expect(SensorQuery.EMPTY.isEmpty).toBe(true);
    expect(SensorQuery.parse('   ').isEmpty).toBe(true);
    expect(SensorQuery.parse('  ').matches(sensor('1', null, null))).toBe(true);
    expect(SensorQuery.parse('null').matches(sensor('1', null, null))).toBe(false);
    expect(SensorQuery.parse('Mik').text).toBe('Mik');
  });
});

describe('group selection', () => {
  it('computes the tri-state of a group', () => {
    expect(checkState(['a', 'b'], [])).toBe('none');
    expect(checkState(['a', 'b'], ['b'])).toBe('some');
    expect(checkState(['a', 'b'], ['b', 'x', 'a'])).toBe('all');
    expect(checkState([], ['a'])).toBe('none');
  });

  it('adds the unselected sensors of a group in group order', () => {
    expect(toggleGroupInSelection(['x', 'b'], ['a', 'b', 'c'])).toEqual({ selection: ['x', 'b', 'a', 'c'], added: 2, truncated: false });
  });

  it('removes a fully selected group and keeps the rest', () => {
    expect(toggleGroupInSelection(['a', 'x', 'b'], ['a', 'b'])).toEqual({ selection: ['x'], added: 0, truncated: false });
  });

  it('stops at the comparison limit and reports truncation', () => {
    const selected = ['s1', 's2', 's3', 's4', 's5', 's6'];
    expect(toggleGroupInSelection(selected, ['g1', 'g2', 'g3', 'g4'])).toEqual({
      selection: [...selected, 'g1', 'g2'],
      added: 2,
      truncated: true,
    });
    const full = [...selected, 'g1', 'g2'];
    const none = toggleGroupInSelection(full, ['g3', 'g4']);
    expect(none).toEqual({ selection: full, added: 0, truncated: true });
    expect(none.selection).toBe(full);
    expect(toggleGroupInSelection(['a'], ['b', 'c', 'd'], 2)).toEqual({ selection: ['a', 'b'], added: 1, truncated: true });
  });

  it('leaves the selection unchanged for an empty group', () => {
    const selected = ['a'];
    expect(toggleGroupInSelection(selected, []).selection).toBe(selected);
  });
});
