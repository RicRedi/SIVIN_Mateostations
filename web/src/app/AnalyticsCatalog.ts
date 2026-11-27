import type { IndexSpec, Manifest } from '../contract';

/**
 * How an index is shown in the "Ukazatele" section: `heat` and `ripening` cards show the value
 * and class, `phenology` cards an estimated date (day of year → date, always marked
 * orientational), `risk` indices a daily risk strip.
 */
export type IndicatorKind = 'heat' | 'ripening' | 'phenology' | 'risk';

/** An index of the manifest with the way it is shown. */
export interface Indicator {
  readonly spec: IndexSpec;
  readonly kind: IndicatorKind;
}

/**
 * Indices of the season cards, in display order (owner-approved scope of WP-3.4):
 * heat sums, the ripening-night index and the three phenology models.
 */
export const SEASON_CARD_INDICES: readonly (readonly [string, IndicatorKind])[] = [
  ['gdd_winkler', 'heat'],
  ['huglin', 'heat'],
  ['bedd', 'heat'],
  ['gst', 'heat'],
  ['cool_night', 'ripening'],
  ['budburst', 'phenology'],
  ['gfv', 'phenology'],
  ['gsr', 'phenology'],
];

/** Indices with a daily risk strip, in display order: grey mould, powdery mildew, frost. */
export const RISK_STRIP_INDICES: readonly string[] = ['botrytis_broome', 'powdery_mildew_gt', 'frost'];

/**
 * The indicators the manifest offers: the configured lists above, restricted to indices the
 * manifest lists (an index the pipeline does not compute is simply not shown).
 */
export class AnalyticsCatalog {
  private constructor(
    readonly cards: readonly Indicator[],
    readonly risks: readonly Indicator[],
  ) {}

  static fromManifest(manifest: Manifest): AnalyticsCatalog {
    const byId = new Map(manifest.indices.map((spec) => [spec.id, spec]));
    const pick = (id: string, kind: IndicatorKind): Indicator[] => {
      const spec = byId.get(id);
      return spec === undefined ? [] : [{ spec, kind }];
    };
    return new AnalyticsCatalog(
      SEASON_CARD_INDICES.flatMap(([id, kind]) => pick(id, kind)),
      RISK_STRIP_INDICES.flatMap((id) => pick(id, 'risk')),
    );
  }
}
