/**
 * Quality-control bit flags, mirroring `QcFlag` of MIGRATION_PLAN.md §2.7.
 */
export const QcFlag = {
  MISSING: 1,
  OUT_OF_RANGE: 2,
  SPIKE: 4,
  STEP: 8,
  STUCK: 16,
  PRE_DEPLOYMENT: 32,
  NEIGHBOR_OUTLIER: 64,
  TIMESTAMP_SUSPECT: 128,
  MANUAL_EXCLUDE: 256,
} as const;

/**
 * Flags that exclude a sample from display aggregates; mirrors the plan's DEFAULT_EXCLUDE
 * (§2.7 column "Vylučuje z indexů"). STEP, NEIGHBOR_OUTLIER and TIMESTAMP_SUSPECT are
 * informative only.
 */
export const DEFAULT_EXCLUDE_MASK =
  QcFlag.MISSING |
  QcFlag.OUT_OF_RANGE |
  QcFlag.SPIKE |
  QcFlag.STUCK |
  QcFlag.PRE_DEPLOYMENT |
  QcFlag.MANUAL_EXCLUDE;

/**
 * Mask used for display in the web portal: {@link DEFAULT_EXCLUDE_MASK} without MISSING.
 *
 * `qc` is one flag set per row (§2.5/§2.6), so MISSING on a row may mean that only one of the
 * variables is null. For display a `null` value already means "missing", so MISSING is handled
 * per value through `null`, and a valid temperature is not hidden because humidity is null.
 * All other excluding flags still hide the whole row.
 */
export const DISPLAY_EXCLUDE_MASK = DEFAULT_EXCLUDE_MASK & ~QcFlag.MISSING;

/** Decides whether a sample's QC flags exclude it. */
export class QcMask {
  /** @param excludeBits - OR-ed {@link QcFlag} values that exclude a sample. */
  constructor(readonly excludeBits: number = DEFAULT_EXCLUDE_MASK) {}

  excludes(qc: number): boolean {
    return (qc & this.excludeBits) !== 0;
  }
}
