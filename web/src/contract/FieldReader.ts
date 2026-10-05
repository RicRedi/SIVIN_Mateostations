import { ContractError } from './ContractError';

type JsonObject = Readonly<Record<string, unknown>>;

const MAX_SHOWN_CHARS = 40;

function describe(value: unknown): string {
  if (value === undefined) {
    return 'nothing (field is missing)';
  }
  const text = JSON.stringify(value);
  return text.length > MAX_SHOWN_CHARS ? `${text.slice(0, MAX_SHOWN_CHARS)}…` : text;
}

/**
 * Reads typed values out of parsed JSON and throws a {@link ContractError} naming the file and
 * JSON path of the first value that has the wrong type.
 */
export class FieldReader {
  constructor(private readonly file: string) {}

  fail(path: string, problem: string): never {
    throw new ContractError(this.file, path, problem);
  }

  object(value: unknown, path: string): JsonObject {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      this.fail(path, `must be an object, got ${describe(value)}`);
    }
    return value as JsonObject;
  }

  array(value: unknown, path: string): readonly unknown[] {
    if (!Array.isArray(value)) {
      this.fail(path, `must be an array, got ${describe(value)}`);
    }
    return value as readonly unknown[];
  }

  string(value: unknown, path: string): string {
    if (typeof value !== 'string') {
      this.fail(path, `must be a string, got ${describe(value)}`);
    }
    return value;
  }

  nullableString(value: unknown, path: string): string | null {
    return value === null ? null : this.string(value, path);
  }

  number(value: unknown, path: string): number {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      this.fail(path, `must be a finite number, got ${describe(value)}`);
    }
    return value;
  }

  integer(value: unknown, path: string): number {
    const number = this.number(value, path);
    if (!Number.isInteger(number)) {
      this.fail(path, `must be an integer, got ${describe(value)}`);
    }
    return number;
  }

  nullableNumber(value: unknown, path: string): number | null {
    return value === null ? null : this.number(value, path);
  }

  boolean(value: unknown, path: string): boolean {
    if (typeof value !== 'boolean') {
      this.fail(path, `must be true or false, got ${describe(value)}`);
    }
    return value;
  }

  literal<T extends string | number>(value: unknown, allowed: readonly T[], path: string): T {
    if (!allowed.includes(value as T)) {
      this.fail(path, `must be one of ${describe(allowed)}, got ${describe(value)}`);
    }
    return value as T;
  }

  /** A record whose values are all read by `readItem`. */
  record<T>(
    value: unknown,
    path: string,
    readItem: (item: unknown, itemPath: string) => T,
  ): Readonly<Record<string, T>> {
    const object = this.object(value, path);
    const result: Record<string, T> = {};
    for (const [key, item] of Object.entries(object)) {
      result[key] = readItem(item, `${path}.${key}`);
    }
    return result;
  }

  /** An array whose items are all read by `readItem`; `expectedLength` checks column length. */
  list<T>(
    value: unknown,
    path: string,
    readItem: (item: unknown, itemPath: string) => T,
    expectedLength?: number,
  ): readonly T[] {
    const items = this.array(value, path);
    if (expectedLength !== undefined && items.length !== expectedLength) {
      this.fail(path, `must have ${expectedLength} items like "t", got ${items.length}`);
    }
    return items.map((item, index) => readItem(item, `${path}[${index}]`));
  }

  /** Bound readers usable as `readItem` callbacks of {@link list} and {@link record}. */
  readonly numberItem = (item: unknown, path: string): number => this.number(item, path);
  readonly integerItem = (item: unknown, path: string): number => this.integer(item, path);
  readonly nullableNumberItem = (item: unknown, path: string): number | null =>
    this.nullableNumber(item, path);
  readonly stringItem = (item: unknown, path: string): string => this.string(item, path);
}
