import { MS_PER_SECOND, SECONDS_PER_DAY } from './units';

/** A wall-clock date and time in some time zone (month 1–12). */
export interface LocalDateTime {
  readonly year: number;
  readonly month: number;
  readonly day: number;
  readonly hour: number;
  readonly minute: number;
  readonly second: number;
}

const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const MIDNIGHT = { hour: 0, minute: 0, second: 0 } as const;

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

/**
 * Conversions between Unix seconds (UTC) and wall-clock time of one IANA time zone, using the
 * platform's `Intl` time-zone database (handles daylight saving time).
 */
export class TimeZone {
  private readonly formatter: Intl.DateTimeFormat;

  /** @param name - IANA time-zone name, e.g. `Europe/Prague`. @throws RangeError if unknown. */
  constructor(readonly name: string) {
    this.formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: name,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
    });
  }

  /** Wall-clock time at Unix time `tS` (seconds). */
  toLocal(tS: number): LocalDateTime {
    const fields: Record<string, number> = {};
    for (const part of this.formatter.formatToParts(new Date(tS * MS_PER_SECOND))) {
      if (part.type !== 'literal') {
        fields[part.type] = Number(part.value);
      }
    }
    return {
      year: fields.year ?? 0,
      month: fields.month ?? 1,
      day: fields.day ?? 1,
      hour: fields.hour ?? 0,
      minute: fields.minute ?? 0,
      second: fields.second ?? 0,
    };
  }

  /** Offset of local time from UTC at `tS`, in seconds (Prague: 3600 in winter, 7200 in summer). */
  offsetS(tS: number): number {
    return TimeZone.naiveUtcS(this.toLocal(tS)) - tS;
  }

  /**
   * Unix seconds of a wall-clock time. For a time that occurs twice (DST end) the earlier
   * instant is returned; for a time skipped by DST start, the instant one offset step later.
   */
  toUtc(local: LocalDateTime): number {
    const naiveS = TimeZone.naiveUtcS(local);
    const offsetBeforeS = this.offsetS(naiveS - SECONDS_PER_DAY);
    const offsetAfterS = this.offsetS(naiveS + SECONDS_PER_DAY);
    const matching = [naiveS - offsetBeforeS, naiveS - offsetAfterS].filter(
      (candidateS) => TimeZone.naiveUtcS(this.toLocal(candidateS)) === naiveS,
    );
    return matching.length > 0 ? Math.min(...matching) : naiveS - offsetBeforeS;
  }

  /** Local midnight that starts the day `isoDate` (`YYYY-MM-DD`), in Unix seconds. */
  startOfDate(isoDate: string): number {
    const match = ISO_DATE_PATTERN.exec(isoDate);
    if (match === null) {
      throw new RangeError(`Expected a date YYYY-MM-DD, got "${isoDate}"`);
    }
    return this.toUtc({
      year: Number(match[1]),
      month: Number(match[2]),
      day: Number(match[3]),
      ...MIDNIGHT,
    });
  }

  /** Same wall-clock time `days` local calendar days later (negative = earlier). */
  addDays(tS: number, days: number): number {
    const local = this.toLocal(tS);
    const shifted = new Date(Date.UTC(local.year, local.month - 1, local.day + days));
    return this.toUtc({
      ...local,
      year: shifted.getUTCFullYear(),
      month: shifted.getUTCMonth() + 1,
      day: shifted.getUTCDate(),
    });
  }

  /** Local calendar day of `tS` as `YYYY-MM-DD`. */
  isoDate(tS: number): string {
    const { year, month, day } = this.toLocal(tS);
    return `${year}-${pad2(month)}-${pad2(day)}`;
  }

  /** The `YYYY-MM-DD` that follows `isoDate`. */
  static nextIsoDate(isoDate: string): string {
    const nextS = Date.parse(`${isoDate}T00:00:00Z`) / MS_PER_SECOND + SECONDS_PER_DAY;
    return new Date(nextS * MS_PER_SECOND).toISOString().slice(0, ISO_DATE_LENGTH);
  }

  private static naiveUtcS(local: LocalDateTime): number {
    const ms = Date.UTC(local.year, local.month - 1, local.day, local.hour, local.minute, local.second);
    return ms / MS_PER_SECOND;
  }
}

const ISO_DATE_LENGTH = 'YYYY-MM-DD'.length;
