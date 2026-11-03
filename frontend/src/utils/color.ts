import type { Palette } from "../types";
import { PALETTE_KEYS } from "../types";

const HEX = /^#[0-9a-fA-F]{6}$/;

export function normalizeHex(value: string): string | null {
  const text = value.trim();
  return HEX.test(text) ? text.toLowerCase() : null;
}

function channel(value: number): number {
  const scaled = value / 255;
  return scaled <= 0.04045 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
}

export function contrastRatio(foreground: string, background: string): number {
  const left = luminance(foreground);
  const right = luminance(background);
  const lighter = Math.max(left, right);
  const darker = Math.min(left, right);
  return (lighter + 0.05) / (darker + 0.05);
}

function luminance(color: string): number {
  const hex = normalizeHex(color);
  if (!hex) return 0;
  const red = parseInt(hex.slice(1, 3), 16);
  const green = parseInt(hex.slice(3, 5), 16);
  const blue = parseInt(hex.slice(5, 7), 16);
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue);
}

export function paletteProblems(colors: Partial<Palette>): string[] {
  const problems: string[] = [];
  for (const key of PALETTE_KEYS) {
    if (!colors[key] || !normalizeHex(colors[key] as string)) {
      problems.push(`${key} must be a #RRGGBB color`);
    }
  }
  if (problems.length) return problems;
  const palette = colors as Palette;
  const checks: [keyof Palette, keyof Palette, number][] = [
    ["text", "bg", 4.5],
    ["text", "surface", 4.5],
    ["muted", "bg", 3],
    ["muted", "surface", 3],
    ["accent", "bg", 3],
    ["danger", "surface", 3],
    ["warning", "surface", 3],
    ["ok", "surface", 3],
    ["info", "surface", 3],
  ];
  for (const [foreground, background, minimum] of checks) {
    const ratio = contrastRatio(palette[foreground], palette[background]);
    if (ratio < minimum) {
      problems.push(`${foreground} on ${background} is ${ratio.toFixed(2)}:1; need ${minimum.toFixed(1)}:1`);
    }
  }
  return problems;
}

const CSS_VARS: Record<keyof Palette, string> = {
  bg: "--bg",
  surface: "--surface",
  text: "--text",
  muted: "--muted",
  border: "--border",
  accent: "--accent",
  accent_2: "--accent-2",
  danger: "--danger",
  warning: "--warning",
  ok: "--ok",
  info: "--info",
};

export function applyPalette(palette: Palette, density?: string): void {
  const root = document.documentElement;
  for (const key of PALETTE_KEYS) {
    const hex = normalizeHex(palette[key]);
    if (hex) root.style.setProperty(CSS_VARS[key], hex);
  }
  root.style.colorScheme = luminance(palette.bg) > 0.4 ? "light" : "dark";
  if (density) root.dataset.density = density;
}

export const THEME_OVERRIDE_KEY = "cyberdeck.themeOverride";
