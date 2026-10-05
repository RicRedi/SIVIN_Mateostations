import { SENSOR_COLORS } from './palette';

/**
 * Assigns line colours to the compared sensors.
 *
 * A sensor keeps its colour while it stays selected; a newly selected sensor gets the first
 * colour no selected sensor uses. With at most as many compared sensors as colours (the
 * comparison cap), two compared sensors never share a colour.
 */
export class SensorColors {
  private slots = new Map<string, number>();

  constructor(private readonly palette: readonly string[] = SENSOR_COLORS) {}

  /** Recompute the assignment for the current selection. */
  update(selectedIds: readonly string[]): void {
    const next = new Map<string, number>();
    for (const id of selectedIds) {
      const slot = this.slots.get(id);
      if (slot !== undefined) {
        next.set(id, slot);
      }
    }
    for (const id of selectedIds) {
      if (!next.has(id)) {
        const used = new Set(next.values());
        let slot = 0;
        while (used.has(slot) && slot < this.palette.length) {
          slot += 1;
        }
        next.set(id, slot % this.palette.length);
      }
    }
    this.slots = next;
  }

  /** Colour of a selected sensor, or `null` when it is not selected. */
  colorFor(sensorId: string): string | null {
    const slot = this.slots.get(sensorId);
    return slot === undefined ? null : (this.palette[slot] ?? null);
  }
}
