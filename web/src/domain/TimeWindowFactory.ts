import { ResolutionPolicy } from './ResolutionPolicy';
import { TimeWindow } from './TimeWindow';
import { TimeZone } from './TimeZone';
import type { RelativePreset, ResolutionChoice, WindowSpec } from './WindowSpec';
import { SECONDS_PER_DAY, SECONDS_PER_HOUR } from './units';

/**
 * Growing season used by the "season" preset: 1 April – 31 October (local calendar days),
 * the GDD/Winkler period of MIGRATION_PLAN.md §3.1.
 */
export const SEASON_START = { month: 4, day: 1 } as const;
export const SEASON_END_INCLUSIVE = { month: 10, day: 31 } as const;

const PRESET_LOCAL_DAYS: Readonly<Record<Exclude<RelativePreset, '24h'>, number>> = {
  '7d': 7,
  '30d': 30,
};

const MIDNIGHT = { hour: 0, minute: 0, second: 0 } as const;

/**
 * Turns a {@link WindowSpec} into a concrete {@link TimeWindow}.
 *
 * Relative presets end at `anchorEndT` (the end of the available data, rounded up to a full
 * hour). `24h` is exactly 86 400 s; `7d` and `30d` go back the given number of local calendar
 * days to the same wall-clock time, so a window over a DST change is one hour longer or shorter.
 */
export class TimeWindowFactory {
  constructor(
    private readonly zone: TimeZone,
    private readonly policy: ResolutionPolicy,
  ) {}

  /**
   * @param spec - Requested window.
   * @param anchorEndT - End of available data, Unix seconds UTC.
   * @param choice - Requested resolution or `auto` (subject to the policy's point caps).
   * @throws RangeError for a custom date that is not a valid `YYYY-MM-DD`.
   */
  create(spec: WindowSpec, anchorEndT: number, choice: ResolutionChoice): TimeWindow {
    const [startT, endT] = this.bounds(spec, anchorEndT);
    return new TimeWindow(startT, endT, this.policy.resolve(choice, endT - startT));
  }

  private bounds(spec: WindowSpec, anchorEndT: number): readonly [number, number] {
    const endT = Math.ceil(anchorEndT / SECONDS_PER_HOUR) * SECONDS_PER_HOUR;
    switch (spec.kind) {
      case '24h':
        return [endT - SECONDS_PER_DAY, endT];
      case '7d':
      case '30d':
        return [this.zone.addDays(endT, -PRESET_LOCAL_DAYS[spec.kind]), endT];
      case 'season':
        return this.seasonBounds(spec.year);
      case 'custom':
        return this.customBounds(spec.from, spec.to);
    }
  }

  private seasonBounds(year: number): readonly [number, number] {
    const startT = this.zone.toUtc({ year, ...SEASON_START, ...MIDNIGHT });
    const lastDayT = this.zone.toUtc({ year, ...SEASON_END_INCLUSIVE, ...MIDNIGHT });
    return [startT, this.zone.addDays(lastDayT, 1)];
  }

  private customBounds(from: string, to: string): readonly [number, number] {
    const [first, last] = from <= to ? [from, to] : [to, from];
    return [this.zone.startOfDate(first), this.zone.startOfDate(TimeZone.nextIsoDate(last))];
  }
}
