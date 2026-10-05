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

/** Decides whether a sample's QC flags exclude it. */
export class QcMask {
  /** @param excludeBits - OR-ed {@link QcFlag} values that exclude a sample. */
  constructor(readonly excludeBits: number = DEFAULT_EXCLUDE_MASK) {}

  excludes(qc: number): boolean {
    return (qc & this.excludeBits) !== 0;
  }
}
