/** Exact catalogue quantities. Never use binary floating point for commands. */
export type Quantity = string | number;
export const quantityText = (value: Quantity) => String(value);
const micros = (value: Quantity) => {
 const match = /^(\d+)(?:\.(\d{1,6}))?$/.exec(String(value));
 if (!match) throw new Error('Use a nonnegative quantity with at most six decimal places.');
 return BigInt(match[1]) * 1000000n + BigInt((match[2] || '').padEnd(6, '0'));
};
export function subtractQuantity(a: Quantity, b: Quantity): string {
 const result = micros(a) - micros(b);
 if (result < 0n) throw new Error('Stored quantities are inconsistent. Refresh the workspace.');
 const fraction = String(result % 1000000n).padStart(6, '0').replace(/0+$/, '');
 return `${result / 1000000n}${fraction ? '.' + fraction : ''}`;
}
export const positiveQuantity = (value: Quantity) => micros(value) > 0n;
export const discreteUnit = (unit: string) => ['pcs', 'bag', 'sheet', 'roll', 'length'].includes(unit);

export const compareQuantity = (a: Quantity, b: Quantity) => micros(a) < micros(b) ? -1 : micros(a) > micros(b) ? 1 : 0;
export function formatQuantity(value: Quantity): string {
 const [whole, fraction] = String(value).split('.');
 return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction ? '.' + fraction : '');
}
