// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { cs } from '../../src/i18n/cs';
import { de } from '../../src/i18n/de';
import { en } from '../../src/i18n/en';
import { I18n } from '../../src/i18n/I18n';
import { ClusterIcon, inkFor, meanOfPresent, relativeLuminance } from '../../src/ui/ClusterIcon';
import { STALE_COLOR, TemperatureScale } from '../../src/ui/palette';

const icon = new ClusterIcon(new I18n({ cs, de, en }, 'cs'), new TemperatureScale());

describe('ClusterIcon', () => {
  it('colours a cluster by the mean temperature of the members that have a value', () => {
    // (12 + 18) / 2 = 15 °C → class [15, 20) → #fe9929; the stale member is ignored.
    const look = icon.appearance([12, null, 18], 0);
    expect(look).toEqual({ className: 'sensor-cluster', background: '#fe9929', ink: '#0b0b0b' });
    // (−6 + −10) / 2 = −8 °C → class below −5 → #08519c, white text.
    expect(icon.appearance([-6, -10], 1)).toEqual({
      className: 'sensor-cluster sensor-cluster--selected',
      background: '#08519c',
      ink: '#ffffff',
    });
    // −4 °C → #3182bd: dark text has the higher contrast (4.7 : 1 against 4.2 : 1).
    expect(icon.appearance([-4], 0).ink).toBe('#0b0b0b');
  });

  it('is grey with the no-value class only when no member has a value', () => {
    expect(icon.appearance([null, null], 0)).toEqual({
      className: 'sensor-cluster sensor-cluster--no-value',
      background: STALE_COLOR,
      ink: '#0b0b0b',
    });
  });

  it('shows the count, an accessible name and the colours', () => {
    const content = icon.content(5, icon.appearance([22], 0));
    expect(content.querySelector('[aria-hidden]')?.textContent).toBe('5');
    expect(content.querySelector('.visually-hidden')?.textContent).toBe('Skupina čidel: 5 – přiblížit');
    expect(content.style.background).toBe('rgb(236, 112, 20)');
    expect(content.style.color).toBe('rgb(11, 11, 11)');
  });
});

describe('colour helpers', () => {
  it('computes WCAG luminance and picks the better ink', () => {
    expect(relativeLuminance('#ffffff')).toBeCloseTo(1, 6);
    expect(relativeLuminance('#000000')).toBe(0);
    expect(inkFor('#fec44f')).toBe('#0b0b0b');
    expect(inkFor('#08519c')).toBe('#ffffff');
    expect(() => relativeLuminance('red')).toThrow('Not a #rrggbb colour: red');
  });

  it('averages present values only', () => {
    expect(meanOfPresent([1, null, 2])).toBe(1.5);
    expect(meanOfPresent([null])).toBeNull();
    expect(meanOfPresent([])).toBeNull();
  });
});
