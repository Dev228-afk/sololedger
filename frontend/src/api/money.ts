/**
 * Exact decimal-string money helpers backed by BigInt minor units (USD cents).
 * Never uses IEEE-754 floating-point number arithmetic for money totals.
 */
export function parseDecimalToCents(raw: string): bigint {
  const trimmed = raw.trim();
  const negative = trimmed.startsWith('-');
  const unsigned = negative ? trimmed.slice(1) : trimmed.startsWith('+') ? trimmed.slice(1) : trimmed;
  const parts = unsigned.split('.');
  const wholePart = parts[0] && parts[0].length > 0 ? parts[0] : '0';
  const fracRaw = parts[1] ?? '';
  const fracPadded = (fracRaw + '00').slice(0, 2);
  const cents = BigInt(wholePart) * 100n + BigInt(fracPadded);
  return negative ? -cents : cents;
}

export function formatCentsToDecimalString(cents: bigint): string {
  const neg = cents < 0n;
  const abs = neg ? -cents : cents;
  const whole = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, '0');
  return `${neg ? '-' : ''}${whole.toString()}.${frac}`;
}

export function formatDisplayUsd(decimalStr: string, withPlus = false): string {
  const neg = decimalStr.startsWith('-');
  const unsigned = neg ? decimalStr.slice(1) : decimalStr;
  if (neg) return `-$${unsigned}`;
  return withPlus ? `+$${unsigned}` : `$${unsigned}`;
}

export function sumDecimalStrings(values: readonly string[]): string {
  let total = 0n;
  for (const val of values) {
    total += parseDecimalToCents(val);
  }
  return formatCentsToDecimalString(total);
}

