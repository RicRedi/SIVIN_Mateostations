import type { SensorInfo } from './SensorCatalog';

/** Locale of the collation of municipality, track and sensor names (they are Czech). */
const NAME_COLLATION_LOCALE = 'cs';

/** Registry status of a sensor that is permanently out of use (listed last, greyed). */
export const RETIRED_STATUS = 'retired';

/** Second grouping level: the sensors of one vineyard track (`name: null` = unassigned). */
export interface TrackGroup {
  /** Stable key, unique among all groups. */
  readonly key: string;
  readonly name: string | null;
  /** Sensors in display order: by label, retired sensors last. */
  readonly sensors: readonly SensorInfo[];
}

/** First grouping level: the tracks of one municipality (`name: null` = unassigned). */
export interface MunicipalityGroup {
  readonly key: string;
  readonly name: string | null;
  readonly tracks: readonly TrackGroup[];
}

/**
 * Groups sensors by municipality (obec) and vineyard track (viniční trať), the two levels of the
 * sensor picker (owner decision 2026-10-05).
 *
 * Groups are sorted by name (Czech collation, numbers in natural order) with the unassigned
 * group (`null`, a sensor without municipality or track) last. Within a track, sensors are
 * sorted by label and retired sensors come last.
 */
export class SensorGrouping {
  private readonly collator: Intl.Collator;

  constructor(locale: string = NAME_COLLATION_LOCALE) {
    this.collator = new Intl.Collator(locale, { numeric: true, sensitivity: 'base' });
  }

  /** The sensors as municipality groups, each with its track groups. */
  group(sensors: readonly SensorInfo[]): readonly MunicipalityGroup[] {
    return this.split(sensors, (sensor) => sensor.municipality).map(([municipality, members]) => ({
      key: JSON.stringify([municipality]),
      name: municipality,
      tracks: this.split(members, (sensor) => sensor.track).map(([track, trackMembers]) => ({
        key: JSON.stringify([municipality, track]),
        name: track,
        sensors: [...trackMembers].sort(this.compareSensors),
      })),
    }));
  }

  /** Split by a nullable name, sorted by name with `null` last; member order is kept. */
  private split(
    sensors: readonly SensorInfo[],
    nameOf: (sensor: SensorInfo) => string | null,
  ): [string | null, SensorInfo[]][] {
    const groups = new Map<string | null, SensorInfo[]>();
    for (const sensor of sensors) {
      const name = nameOf(sensor);
      const members = groups.get(name);
      if (members === undefined) {
        groups.set(name, [sensor]);
      } else {
        members.push(sensor);
      }
    }
    return [...groups].sort(([a], [b]) => this.compareNames(a, b));
  }

  private compareNames(a: string | null, b: string | null): number {
    if (a === null || b === null) {
      return Number(a === null) - Number(b === null);
    }
    return this.collator.compare(a, b);
  }

  private readonly compareSensors = (a: SensorInfo, b: SensorInfo): number => {
    const retired = Number(a.status === RETIRED_STATUS) - Number(b.status === RETIRED_STATUS);
    return retired !== 0 ? retired : this.collator.compare(a.label, b.label) || this.collator.compare(a.id, b.id);
  };
}
