import {
  isExtraAxisQuantity,
  isQuantityId,
  QUANTITY_IDS,
  type ExtraAxisQuantity,
  type QuantityId,
} from '../domain/quantities';

/**
 * A valid selection of shown quantities from arbitrary ids: known ids only, each once, in the
 * canonical order of {@link QUANTITY_IDS}, and at most one quantity with an extra axis (the first
 * one given wins).
 */
export function normalizeQuantities(ids: readonly unknown[]): readonly QuantityId[] {
  const known = ids.filter(isQuantityId);
  const extra = known.find(isExtraAxisQuantity);
  const wanted = new Set(known.filter((id) => !isExtraAxisQuantity(id) || id === extra));
  return Object.freeze(QUANTITY_IDS.filter((id) => wanted.has(id)));
}

/** True if both selections contain the same quantities (order ignored). */
export function sameQuantities(a: readonly QuantityId[], b: readonly QuantityId[]): boolean {
  return a.length === b.length && a.every((id) => b.includes(id));
}

/**
 * Selection after toggling `id`: removes it if shown, otherwise adds it. Adding a quantity with
 * an extra axis replaces the one shown before.
 */
export function toggleQuantity(current: readonly QuantityId[], id: QuantityId): readonly QuantityId[] {
  if (current.includes(id)) {
    return normalizeQuantities(current.filter((shown) => shown !== id));
  }
  const kept = isExtraAxisQuantity(id) ? current.filter((shown) => !isExtraAxisQuantity(shown)) : current;
  return normalizeQuantities([...kept, id]);
}

/** Selection with `extra` as the only extra-axis quantity, or none for `null`. */
export function withExtraAxis(current: readonly QuantityId[], extra: ExtraAxisQuantity | null): readonly QuantityId[] {
  const base = current.filter((id) => !isExtraAxisQuantity(id));
  return normalizeQuantities(extra === null ? base : [...base, extra]);
}

/** The extra-axis quantity of a selection, if any. */
export function extraAxisOf(current: readonly QuantityId[]): ExtraAxisQuantity | null {
  return current.find(isExtraAxisQuantity) ?? null;
}
