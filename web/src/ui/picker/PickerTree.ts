import type { SensorInfo } from '../../app/SensorCatalog';
import { RETIRED_STATUS, type MunicipalityGroup, type TrackGroup } from '../../app/SensorGroups';
import type { SensorQuery } from '../../app/SensorQuery';
import type { I18n } from '../../i18n/I18n';
import { checkState, type CheckState } from '../../state/GroupSelection';
import { el } from '../dom';
import type { SensorColors } from '../SensorColors';

/** What every node of the tree shows: the search, the selection and the line colours. */
export interface PickerViewState {
  readonly query: SensorQuery;
  readonly selectedIds: readonly string[];
}

/** Callbacks of the tree: a sensor checkbox or a group's "select all" checkbox changed. */
export interface PickerTreeHandlers {
  readonly onSensorToggle: (sensorId: string) => void;
  readonly onGroupToggle: (sensorIds: readonly string[]) => void;
}

/** A node of the picker tree: a group or a sensor row. */
interface PickerNode {
  readonly element: HTMLElement;
  /** Show the node for `state`; returns the ids of its visible sensors (none = node hidden). */
  update(state: PickerViewState): readonly string[];
  /** Number of sensors in the node, visible or not. */
  readonly size: number;
  expandAll(): void;
}

/** Show a check state on a native checkbox (`indeterminate` is exposed as "mixed"). */
export function applyCheckState(input: HTMLInputElement, state: CheckState): void {
  input.checked = state === 'all';
  input.indeterminate = state === 'some';
}

/** One sensor: checkbox, line-colour swatch, label and a muted line with variety / retired. */
class SensorRow implements PickerNode {
  readonly element: HTMLLIElement;
  readonly size = 1;
  private readonly checkbox: HTMLInputElement;
  private readonly swatch = el('span', { class: 'swatch', 'aria-hidden': 'true' });
  private readonly meta = el('span', { class: 'picker-sensor__meta' });

  constructor(
    private readonly sensor: SensorInfo,
    private readonly i18n: I18n,
    private readonly colors: SensorColors,
    onToggle: (sensorId: string) => void,
  ) {
    this.checkbox = el('input', { type: 'checkbox', value: sensor.id, id: `picker-sensor-${sensor.id}` });
    this.checkbox.addEventListener('change', () => {
      onToggle(sensor.id);
    });
    const retired = sensor.status === RETIRED_STATUS;
    this.element = el('li', { class: retired ? 'picker-sensor is-retired' : 'picker-sensor' }, [
      el('label', { for: this.checkbox.id }, [
        this.checkbox,
        this.swatch,
        el('span', { class: 'picker-sensor__text' }, [el('span', { class: 'picker-sensor__label' }, [sensor.label]), this.meta]),
      ]),
    ]);
  }

  update(state: PickerViewState): readonly string[] {
    const visible = state.query.matches(this.sensor);
    this.element.hidden = !visible;
    this.checkbox.checked = state.selectedIds.includes(this.sensor.id);
    const color = this.colors.colorFor(this.sensor.id);
    this.swatch.style.background = color ?? 'transparent';
    this.swatch.classList.toggle('swatch--empty', color === null);
    const parts = [this.sensor.variety, this.sensor.status === RETIRED_STATUS ? this.i18n.t('retired') : null];
    this.meta.textContent = parts.filter((part): part is string => part !== null).join(' · ');
    this.meta.hidden = this.meta.textContent === '';
    return visible ? [this.sensor.id] : [];
  }

  expandAll(): void {
    // A sensor row has nothing to expand.
  }
}

/**
 * A municipality or track: a "select all" checkbox (tri-state over the visible sensors), a
 * disclosure button with the name and the count of selected / visible sensors, and the children.
 *
 * During a search the checkbox acts on the matches only, so it says so: its name becomes
 * "Vybrat nalezená v <group>" and a hint "nalezeno m z n" shows how many of the group's sensors
 * match; its check state refers to the matches.
 */
class GroupNode implements PickerNode {
  readonly element: HTMLLIElement;
  private readonly checkbox = el('input', { type: 'checkbox', class: 'picker-group__all' });
  private readonly toggle: HTMLButtonElement;
  private readonly nameText = el('span', { class: 'picker-group__name' });
  private readonly count = el('span', { class: 'picker-group__count' });
  private readonly matches = el('span', { class: 'picker-group__matches' });
  readonly size: number;
  private readonly body: HTMLUListElement;
  private visibleIds: readonly string[] = [];
  private expanded = true;

  constructor(
    private readonly name: string | null,
    level: 'municipality' | 'track',
    bodyId: string,
    private readonly children: readonly PickerNode[],
    private readonly i18n: I18n,
    onGroupToggle: (sensorIds: readonly string[]) => void,
  ) {
    this.size = children.reduce((total, child) => total + child.size, 0);
    this.checkbox.addEventListener('change', () => {
      onGroupToggle(this.visibleIds);
    });
    this.toggle = el('button', { type: 'button', class: 'picker-group__toggle', 'aria-expanded': 'true', 'aria-controls': bodyId }, [
      el('span', { class: 'picker-group__chevron', 'aria-hidden': 'true' }),
      this.nameText,
      this.matches,
      this.count,
    ]);
    this.toggle.addEventListener('click', () => {
      this.setExpanded(!this.expanded);
    });
    this.body = el('ul', { class: 'picker-group__body', id: bodyId }, children.map((child) => child.element));
    this.element = el('li', { class: `picker-group picker-group--${level}` }, [
      el('div', { class: 'picker-group__head' }, [this.checkbox, this.toggle]),
      this.body,
    ]);
  }

  update(state: PickerViewState): readonly string[] {
    this.visibleIds = this.children.flatMap((child) => child.update(state));
    this.element.hidden = this.visibleIds.length === 0;
    const name = this.name ?? this.i18n.t('unassigned');
    this.nameText.textContent = name;
    this.element.classList.toggle('is-unassigned', this.name === null);
    const selected = this.visibleIds.filter((id) => state.selectedIds.includes(id)).length;
    this.count.textContent = `${selected}/${this.visibleIds.length}`;
    const searching = !state.query.isEmpty;
    this.matches.hidden = !searching;
    this.matches.textContent = searching ? this.i18n.t('groupMatches', { found: this.visibleIds.length, total: this.size }) : '';
    applyCheckState(this.checkbox, checkState(this.visibleIds, state.selectedIds));
    this.checkbox.setAttribute('aria-label', this.i18n.t(searching ? 'selectGroupMatches' : 'selectGroup', { group: name }));
    return this.visibleIds;
  }

  expandAll(): void {
    this.setExpanded(true);
    for (const child of this.children) {
      child.expandAll();
    }
  }

  private setExpanded(expanded: boolean): void {
    this.expanded = expanded;
    this.body.hidden = !expanded;
    this.toggle.setAttribute('aria-expanded', String(expanded));
  }
}

/**
 * The grouped checkbox list of the sensor picker: municipality → track → sensor. The DOM is
 * built once; `update` only shows, hides and checks, so focus stays where it is while the user
 * types or toggles.
 */
export class PickerTree {
  readonly element: HTMLUListElement;
  private readonly roots: readonly GroupNode[];

  constructor(
    groups: readonly MunicipalityGroup[],
    private readonly i18n: I18n,
    private readonly colors: SensorColors,
    private readonly handlers: PickerTreeHandlers,
  ) {
    let next = 0;
    const bodyId = (): string => `picker-group-${String(next++)}`;
    this.roots = groups.map(
      (group) =>
        new GroupNode(group.name, 'municipality', bodyId(), group.tracks.map((track) => this.trackNode(track, bodyId())), i18n, handlers.onGroupToggle),
    );
    this.element = el('ul', { class: 'picker-tree' }, this.roots.map((root) => root.element));
  }

  /** Update every node; returns the number of visible sensors. */
  update(state: PickerViewState): number {
    return this.roots.reduce((count, root) => count + root.update(state).length, 0);
  }

  expandAll(): void {
    for (const root of this.roots) {
      root.expandAll();
    }
  }

  private trackNode(track: TrackGroup, bodyId: string): GroupNode {
    const rows = track.sensors.map((sensor) => new SensorRow(sensor, this.i18n, this.colors, this.handlers.onSensorToggle));
    return new GroupNode(track.name, 'track', bodyId, rows, this.i18n, this.handlers.onGroupToggle);
  }
}
