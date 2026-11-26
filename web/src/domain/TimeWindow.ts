/** Chart resolution: raw samples, hourly means, or daily values from `daily.json`. */
export const RESOLUTIONS = ['raw', 'hourly', 'daily'] as const;
export type Resolution = (typeof RESOLUTIONS)[number];

/**
 * Immutable time window `[startT, endT)` in Unix seconds UTC with the resolution to show it in.
 */
export class TimeWindow {
  /** @throws RangeError if `endT <= startT`. */
  constructor(
    readonly startT: number,
    readonly endT: number,
    readonly resolution: Resolution,
  ) {
    if (!(endT > startT)) {
      throw new RangeError(`TimeWindow end ${endT} must be after start ${startT}`);
    }
    Object.freeze(this);
  }

  get durationS(): number {
    return this.endT - this.startT;
  }

  contains(t: number): boolean {
    return t >= this.startT && t < this.endT;
  }

  /** True if both windows have the same bounds and resolution. */
  equals(other: TimeWindow): boolean {
    return this.startT === other.startT && this.endT === other.endT && this.resolution === other.resolution;
  }

  withResolution(resolution: Resolution): TimeWindow {
    return new TimeWindow(this.startT, this.endT, resolution);
  }
}
