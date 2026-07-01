import type { Direction } from './types';

const FALLBACK = '#0d9488';

export function directionColor(input: Direction | string | null | undefined): string {
  if (!input) return FALLBACK;
  if (typeof input === 'object') {
    if (input.color && /^#[0-9a-fA-F]{6}$/.test(input.color)) return input.color;
    return hueFromName(input.name || '');
  }
  if (/^#[0-9a-fA-F]{6}$/.test(input)) return input;
  return hueFromName(input);
}

function hueFromName(name: string): string {
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return `hsl(${hue}, 55%, 42%)`;
}
