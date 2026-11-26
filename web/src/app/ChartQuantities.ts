import type { VariableSpec } from '../contract';
import { combineSeries, leafWetnessIndicator } from '../domain/derivedSeries';
import { absoluteHumidityGM3, dewPointC, LEAF_WET_RH_THRESHOLD_PCT, vapourPressureDeficitKpa } from '../domain/psychrometry';
import type { QuantityId } from '../domain/quantities';
import type { Resolution } from '../domain/TimeWindow';
import type { TimeSeries } from '../domain/TimeSeries';
import type { MessageKey } from '../i18n/cs';
import type { SensorChartData } from './ChartDataLoader';

/**
 * Where a quantity is drawn: on the temperature axis (left, °C), the humidity axis (right, %),
 * a third axis of its own, or as a band without an axis.
 */
export type QuantityAxis = 'temp' | 'rh' | 'extra' | 'band';

/** How a quantity's line is drawn (the colour is the sensor's). */
export type QuantityStyle = 'solid' | 'dashed' | 'dotted' | 'dashDot' | 'bars' | 'band';

/** Translation keys of a quantity's label; a resolution may have its own (e.g. daily sums). */
export interface QuantityLabels {
  readonly default: MessageKey;
  readonly daily?: MessageKey;
  readonly hourly?: MessageKey;
}

/** Display properties shared by every quantity. */
export interface QuantityDisplay {
  readonly unit: string;
  readonly axis: QuantityAxis;
  readonly style: QuantityStyle;
  /** Decimals in the chart legend and the axis. */
  readonly decimals: number;
  /** Decimals in the CSV export (the published precision of measured values is 0.01). */
  readonly csvDecimals: number;
  readonly labels: QuantityLabels;
}

/**
 * A quantity the chart can show for every selected sensor: measured, derived from the measured
 * temperature and humidity, or an indicator drawn as a band. New quantities are new subclasses
 * registered in {@link createQuantityRegistry}.
 */
export abstract class ChartQuantity {
  constructor(
    readonly id: QuantityId,
    readonly display: QuantityDisplay,
  ) {}

  /** Label key at `resolution`. */
  labelKey(resolution: Resolution): MessageKey {
    const labels = this.display.labels;
    return (resolution === 'daily' ? labels.daily : resolution === 'hourly' ? labels.hourly : undefined) ?? labels.default;
  }

  /** Placeholder values of the label, e.g. a threshold. */
  labelParams(): Readonly<Record<string, number>> {
    return {};
  }

  /** The quantity's values for one sensor at the loaded resolution. */
  abstract series(sensor: SensorChartData): TimeSeries;
}

/** A measured column of the chart data. */
export class MeasuredQuantity extends ChartQuantity {
  /**
   * @param column - Column of {@link SensorChartData}.
   * @param manifestLabelled - True if the label comes from the manifest's `variables`.
   */
  constructor(
    id: QuantityId & keyof SensorChartData,
    display: QuantityDisplay,
    private readonly column: 'temp_c' | 'rh_pct' | 'precip_mm' | 'battery_v',
    readonly manifestLabelled: boolean,
  ) {
    super(id, display);
  }

  series(sensor: SensorChartData): TimeSeries {
    return sensor[this.column];
  }
}

/**
 * A quantity computed pointwise from the shown temperature and humidity (at hourly and daily
 * resolution from the means, see `docs/web.md`).
 */
export class PsychrometricQuantity extends ChartQuantity {
  constructor(
    id: QuantityId,
    display: QuantityDisplay,
    private readonly formula: (tempC: number, rhPct: number) => number | null,
  ) {
    super(id, display);
  }

  series(sensor: SensorChartData): TimeSeries {
    return combineSeries(sensor.temp_c, sensor.rh_pct, this.formula);
  }
}

/** The leaf wetness proxy `RH >= threshold` as a 1/0 indicator, drawn as bands. */
export class LeafWetnessQuantity extends ChartQuantity {
  constructor(
    id: QuantityId,
    display: QuantityDisplay,
    readonly thresholdPct: number,
  ) {
    super(id, display);
  }

  override labelParams(): Readonly<Record<string, number>> {
    return { threshold: this.thresholdPct };
  }

  series(sensor: SensorChartData): TimeSeries {
    return leafWetnessIndicator(sensor.rh_pct, this.thresholdPct);
  }
}

/** The chart quantities by id, in registration order. */
export class QuantityRegistry {
  private readonly byId = new Map<QuantityId, ChartQuantity>();

  /** @throws Error if a quantity with the same id is registered already. */
  register(quantity: ChartQuantity): this {
    if (this.byId.has(quantity.id)) {
      throw new Error(`Chart quantity ${quantity.id} is registered twice`);
    }
    this.byId.set(quantity.id, quantity);
    return this;
  }

  /** @throws Error for an unregistered id. */
  get(id: QuantityId): ChartQuantity {
    const quantity = this.byId.get(id);
    if (quantity === undefined) {
      throw new Error(`Unknown chart quantity ${id}`);
    }
    return quantity;
  }

  /** The registered quantities among `ids`, in registration order. */
  select(ids: readonly QuantityId[]): ChartQuantity[] {
    return this.all().filter((quantity) => ids.includes(quantity.id));
  }

  all(): ChartQuantity[] {
    return [...this.byId.values()];
  }
}

/** Decimals of values shown in the chart. */
const CHART_DECIMALS = 1;
/** VPD (kPa) and battery voltage (V) change in the second decimal. */
const FINE_CHART_DECIMALS = 2;
/** Decimals of measured values in the CSV export: the precision the site publishes (0.01). */
const MEASURED_CSV_DECIMALS = 2;
/** Decimals of derived values in the CSV export: 0.01 °C, 0.01 g/m³ … */
const DERIVED_CSV_DECIMALS = 2;
/** … and 0.001 kPa for the VPD (one more than the chart). */
const VPD_CSV_DECIMALS = 3;
/** The leaf wetness indicator is 0 or 1. */
const INDICATOR_DECIMALS = 0;

/**
 * Every quantity of the chart. Units of temperature and humidity come from the manifest (with
 * the contract's units as fallback); the others are fixed by their formula or the contract.
 *
 * @param variables - Variable specs of the manifest.
 */
export function createQuantityRegistry(variables: readonly VariableSpec[]): QuantityRegistry {
  const unit = (id: string, fallback: string) => variables.find((v) => v.id === id)?.unit ?? fallback;
  const line = (unitText: string, axis: QuantityAxis, style: QuantityStyle, labels: QuantityLabels): QuantityDisplay => ({
    unit: unitText,
    axis,
    style,
    decimals: CHART_DECIMALS,
    csvDecimals: MEASURED_CSV_DECIMALS,
    labels,
  });
  return new QuantityRegistry()
    .register(new MeasuredQuantity('temp_c', line(unit('temp_c', '°C'), 'temp', 'solid', { default: 'quantityTemp' }), 'temp_c', true))
    .register(new MeasuredQuantity('rh_pct', line(unit('rh_pct', '%'), 'rh', 'dashed', { default: 'quantityRh' }), 'rh_pct', true))
    .register(
      new PsychrometricQuantity(
        'dew_point_c',
        { ...line('°C', 'temp', 'dotted', { default: 'quantityDewPoint' }), csvDecimals: DERIVED_CSV_DECIMALS },
        dewPointC,
      ),
    )
    .register(
      new LeafWetnessQuantity(
        'leaf_wetness',
        { ...line('0/1', 'band', 'band', { default: 'quantityLeafWetness' }), decimals: INDICATOR_DECIMALS, csvDecimals: INDICATOR_DECIMALS },
        LEAF_WET_RH_THRESHOLD_PCT,
      ),
    )
    .register(
      new PsychrometricQuantity(
        'vpd_kpa',
        { ...line('kPa', 'extra', 'dashDot', { default: 'quantityVpd' }), decimals: FINE_CHART_DECIMALS, csvDecimals: VPD_CSV_DECIMALS },
        vapourPressureDeficitKpa,
      ),
    )
    .register(
      new PsychrometricQuantity(
        'abs_humidity_g_m3',
        { ...line('g/m³', 'extra', 'dashDot', { default: 'quantityAbsHumidity' }), csvDecimals: DERIVED_CSV_DECIMALS },
        absoluteHumidityGM3,
      ),
    )
    .register(
      new MeasuredQuantity(
        'precip_mm',
        line('mm', 'extra', 'bars', { default: 'quantityPrecip', hourly: 'quantityPrecipHourly', daily: 'quantityPrecipDaily' }),
        'precip_mm',
        false,
      ),
    )
    .register(
      new MeasuredQuantity(
        'battery_v',
        { ...line('V', 'extra', 'dashDot', { default: 'quantityBattery', daily: 'quantityBatteryDaily' }), decimals: FINE_CHART_DECIMALS },
        'battery_v',
        false,
      ),
    );
}
