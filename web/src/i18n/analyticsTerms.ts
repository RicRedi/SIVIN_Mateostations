import type { I18n } from './I18n';
import { DEFAULT_LANGUAGE, type Language } from './languages';

/**
 * Labels of the machine-readable class and daily level ids of the indices, keyed
 * `<index_id>.<id>` (class ids repeat across indices with different meanings, e.g. `cool`).
 * The ids are those of the Python indices (`src/sivin/analytics/`); an id without a label is
 * shown as is.
 */
type Terms = Readonly<Record<string, string>>;

const cs: Terms = {
  'gdd_winkler.region_i': 'oblast I',
  'gdd_winkler.region_ii': 'oblast II',
  'gdd_winkler.region_iii': 'oblast III',
  'gdd_winkler.region_iv': 'oblast IV',
  'gdd_winkler.region_v': 'oblast V',
  'huglin.very_cool': 'velmi chladné',
  'huglin.cool': 'chladné',
  'huglin.temperate': 'mírné',
  'huglin.temperate_warm': 'mírně teplé',
  'huglin.warm': 'teplé',
  'huglin.very_warm': 'velmi teplé',
  'gst.too_cool': 'příliš chladné',
  'gst.cool': 'chladné',
  'gst.intermediate': 'střední',
  'gst.warm': 'teplé',
  'gst.hot': 'horké',
  'gst.too_hot': 'příliš horké',
  'cool_night.very_cool_nights': 'velmi chladné noci',
  'cool_night.cool_nights': 'chladné noci',
  'cool_night.temperate_nights': 'mírné noci',
  'cool_night.warm_nights': 'teplé noci',
  'botrytis_broome.no_wetness': 'bez ovlhčení',
  'botrytis_broome.wetness': 'ovlhčení (odhad)',
  'powdery_mildew_gt.low': 'nízké',
  'powdery_mildew_gt.moderate': 'střední',
  'powdery_mildew_gt.high': 'vysoké',
  'frost.none': 'bez mrazu',
  'frost.frost': 'mráz',
  'frost.hard_frost': 'silný mráz',
};

const de: Terms = {
  'gdd_winkler.region_i': 'Region I',
  'gdd_winkler.region_ii': 'Region II',
  'gdd_winkler.region_iii': 'Region III',
  'gdd_winkler.region_iv': 'Region IV',
  'gdd_winkler.region_v': 'Region V',
  'huglin.very_cool': 'sehr kühl',
  'huglin.cool': 'kühl',
  'huglin.temperate': 'gemäßigt',
  'huglin.temperate_warm': 'gemäßigt warm',
  'huglin.warm': 'warm',
  'huglin.very_warm': 'sehr warm',
  'gst.too_cool': 'zu kühl',
  'gst.cool': 'kühl',
  'gst.intermediate': 'mittel',
  'gst.warm': 'warm',
  'gst.hot': 'heiß',
  'gst.too_hot': 'zu heiß',
  'cool_night.very_cool_nights': 'sehr kühle Nächte',
  'cool_night.cool_nights': 'kühle Nächte',
  'cool_night.temperate_nights': 'gemäßigte Nächte',
  'cool_night.warm_nights': 'warme Nächte',
  'botrytis_broome.no_wetness': 'keine Nässe',
  'botrytis_broome.wetness': 'Nässe (geschätzt)',
  'powdery_mildew_gt.low': 'niedrig',
  'powdery_mildew_gt.moderate': 'mittel',
  'powdery_mildew_gt.high': 'hoch',
  'frost.none': 'kein Frost',
  'frost.frost': 'Frost',
  'frost.hard_frost': 'starker Frost',
};

const en: Terms = {
  'gdd_winkler.region_i': 'region I',
  'gdd_winkler.region_ii': 'region II',
  'gdd_winkler.region_iii': 'region III',
  'gdd_winkler.region_iv': 'region IV',
  'gdd_winkler.region_v': 'region V',
  'huglin.very_cool': 'very cool',
  'huglin.cool': 'cool',
  'huglin.temperate': 'temperate',
  'huglin.temperate_warm': 'temperate warm',
  'huglin.warm': 'warm',
  'huglin.very_warm': 'very warm',
  'gst.too_cool': 'too cool',
  'gst.cool': 'cool',
  'gst.intermediate': 'intermediate',
  'gst.warm': 'warm',
  'gst.hot': 'hot',
  'gst.too_hot': 'too hot',
  'cool_night.very_cool_nights': 'very cool nights',
  'cool_night.cool_nights': 'cool nights',
  'cool_night.temperate_nights': 'temperate nights',
  'cool_night.warm_nights': 'warm nights',
  'botrytis_broome.no_wetness': 'no wetness',
  'botrytis_broome.wetness': 'wetness (estimated)',
  'powdery_mildew_gt.low': 'low',
  'powdery_mildew_gt.moderate': 'moderate',
  'powdery_mildew_gt.high': 'high',
  'frost.none': 'no frost',
  'frost.frost': 'frost',
  'frost.hard_frost': 'hard frost',
};

/** The class and level labels per language. */
export const ANALYTICS_TERMS: Readonly<Record<Language, Terms>> = { cs, de, en };

/** Looks up class and level labels in the current language of an {@link I18n}. */
export class AnalyticsTerms {
  constructor(
    private readonly i18n: I18n,
    private readonly terms: Readonly<Record<Language, Terms>> = ANALYTICS_TERMS,
  ) {}

  /** Label of class or level `id` of index `indexId`: current language, Czech, then `id`. */
  label(indexId: string, id: string): string {
    const key = `${indexId}.${id}`;
    return this.terms[this.i18n.language][key] ?? this.terms[DEFAULT_LANGUAGE][key] ?? id;
  }
}
