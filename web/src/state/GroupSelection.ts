import { MAX_COMPARED_SENSORS } from './AppState';

/** How many sensors of a group are selected: none, some (tri-state "mixed") or all. */
export type CheckState = 'none' | 'some' | 'all';

/** Check state of a group with the sensors `groupIds`; an empty group counts as `none`. */
export function checkState(groupIds: readonly string[], selected: readonly string[]): CheckState {
  const chosen = groupIds.filter((id) => selected.includes(id)).length;
  if (chosen === 0) {
    return 'none';
  }
  return chosen === groupIds.length ? 'all' : 'some';
}

/** Outcome of toggling a whole group in the comparison. */
export interface GroupToggle {
  /** The new selection (the same array when nothing changed). */
  readonly selection: readonly string[];
  /** Number of sensors of the group added to the selection. */
  readonly added: number;
  /** True when some sensors of the group were not added because of the comparison limit. */
  readonly truncated: boolean;
}

/**
 * Toggle a group ("select all" checkbox of a municipality or a track).
 *
 * A fully selected group is removed from the selection. Otherwise its unselected sensors are
 * appended in group order until `max` sensors are selected; the rest is left out and reported
 * as `truncated`, so the caller can tell the user about the limit.
 */
export function toggleGroupInSelection(
  selected: readonly string[],
  groupIds: readonly string[],
  max: number = MAX_COMPARED_SENSORS,
): GroupToggle {
  if (groupIds.length === 0) {
    return { selection: selected, added: 0, truncated: false };
  }
  if (checkState(groupIds, selected) === 'all') {
    return { selection: selected.filter((id) => !groupIds.includes(id)), added: 0, truncated: false };
  }
  const missing = groupIds.filter((id) => !selected.includes(id));
  const room = Math.max(0, max - selected.length);
  const added = missing.slice(0, room);
  return {
    selection: added.length === 0 ? selected : [...selected, ...added],
    added: added.length,
    truncated: added.length < missing.length,
  };
}

/** Why the last selection change hit the comparison limit; shown to the user once. */
export type LimitNotice =
  | { readonly kind: 'sensor' }
  | { readonly kind: 'group'; readonly added: number };
