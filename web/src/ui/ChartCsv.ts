import type { SensorCatalog } from '../app/SensorCatalog';
import { csvFormat, CsvWriter } from '../app/CsvWriter';
import type { TimeZone } from '../domain/TimeZone';
import { MS_PER_SECOND } from '../domain/units';
import type { ViewRange } from '../domain/ViewRange';
import type { I18n } from '../i18n/I18n';
import type { Language } from '../i18n/languages';
import type { ChartModel } from './ChartModel';
import type { QuantityLabels } from './QuantityLabels';

/** Decimal mark of the export per UI language: comma where Excel's locale expects it. */
const DECIMAL_MARK: Readonly<Record<Language, string>> = { cs: ',', de: ',', en: '.' };

/** A file ready to be saved. */
export interface CsvFile {
  readonly fileName: string;
  readonly content: string;
}

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

/**
 * The CSV export of what the chart shows: the rows inside the visible (zoomed) range, the shown
 * quantities of the selected sensors at the loaded resolution, derived quantities included.
 *
 * Columns: local time of the display zone (`YYYY-MM-DD HH:MM:SS`), UTC (ISO 8601), then one
 * column per sensor and quantity with label and unit in the header. Rows without any shown
 * value (gap breaks of the chart) are left out; an empty field is a missing or masked value.
 * The file is UTF-8 with BOM, `;`-separated, CRLF; the decimal mark follows the UI language.
 */
export class ChartCsv {
  constructor(
    private readonly i18n: I18n,
    private readonly catalog: SensorCatalog,
    private readonly zone: TimeZone,
    private readonly labels: QuantityLabels,
  ) {}

  /** The file for `model` restricted to `view`. */
  file(model: ChartModel, view: ViewRange): CsvFile {
    return { fileName: this.fileName(model, view), content: this.content(model, view) };
  }

  /** `sivin_<sensor ids joined by ->_<from>_<to>.csv`, times local `YYYYMMDDTHHMM`, end exclusive. */
  fileName(model: ChartModel, view: ViewRange): string {
    const sensors = [...new Set(model.columns.map((column) => column.sensorId))];
    return `sivin_${sensors.join('-')}_${this.compactLocal(view.startT)}_${this.compactLocal(view.endT)}.csv`;
  }

  content(model: ChartModel, view: ViewRange): string {
    const writer = new CsvWriter(csvFormat(DECIMAL_MARK[this.i18n.language]));
    const resolution = model.window.resolution;
    const header = [
      this.i18n.t('csvLocalTime', { zone: this.zone.name }),
      this.i18n.t('csvUtcTime'),
      ...model.columns.map((column) => {
        const sensor = this.catalog.get(column.sensorId)?.label ?? column.sensorId;
        return `${sensor} – ${this.labels.labelWithUnit(column.quantity, resolution)}`;
      }),
    ];
    const rows = model.rowsWithin(view).map((i) => {
      const t = model.t[i] ?? 0;
      return [
        this.local(t),
        this.utc(t),
        ...model.columns.map((column) => writer.number(column.values[i], column.quantity.display.csvDecimals)),
      ];
    });
    return writer.write(header, rows);
  }

  private local(t: number): string {
    const local = this.zone.toLocal(t);
    return `${local.year}-${pad2(local.month)}-${pad2(local.day)} ${pad2(local.hour)}:${pad2(local.minute)}:${pad2(local.second)}`;
  }

  private utc(t: number): string {
    return new Date(t * MS_PER_SECOND).toISOString().replace(/\.\d{3}Z$/, 'Z');
  }

  private compactLocal(t: number): string {
    const local = this.zone.toLocal(t);
    return `${local.year}${pad2(local.month)}${pad2(local.day)}T${pad2(local.hour)}${pad2(local.minute)}`;
  }
}
