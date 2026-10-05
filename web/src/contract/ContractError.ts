/** Raised when a data file does not match the site data contract (MIGRATION_PLAN.md §2.6). */
export class ContractError extends Error {
  /**
   * @param file - Contract file name, e.g. `manifest.json`.
   * @param path - JSON path of the offending value, e.g. `$.sensors.77678271.last_t`.
   * @param problem - What is wrong, e.g. `must be a number, got "abc"`.
   */
  constructor(
    readonly file: string,
    readonly path: string,
    readonly problem: string,
  ) {
    super(`${file}: ${path} ${problem}`);
    this.name = 'ContractError';
  }
}
