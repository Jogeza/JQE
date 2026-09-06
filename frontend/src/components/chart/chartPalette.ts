export interface JQEChartPalette {
  background: string;
  grid: string;
  axis: string;
  text: string;
  bull: string;
  bullSoft: string;
  bear: string;
  bearSoft: string;
  accent: string;
  accentSoft: string;
  accentSecondary: string;
  neutral: string;
  crosshair: string;
  profile: string;
}

export const chartPaletteFallback: JQEChartPalette = {
  background: '#080a0d',
  grid: 'rgba(207, 216, 227, 0.045)',
  axis: '#303741',
  text: '#929ba8',
  bull: '#3f9b67',
  bullSoft: 'rgba(63, 155, 103, 0.28)',
  bear: '#c7545d',
  bearSoft: 'rgba(199, 84, 93, 0.28)',
  accent: '#4f83df',
  accentSoft: 'rgba(79, 131, 223, 0.24)',
  accentSecondary: '#8ba7cf',
  neutral: '#a5adb8',
  crosshair: '#6684ad',
  profile: 'rgba(133, 145, 160, 0.22)',
};

const cssTokens: Record<keyof JQEChartPalette, string> = {
  background: '--chart-bg', grid: '--chart-grid', axis: '--chart-axis', text: '--chart-text',
  bull: '--chart-bull', bullSoft: '--chart-bull-soft', bear: '--chart-bear', bearSoft: '--chart-bear-soft',
  accent: '--chart-accent', accentSoft: '--chart-accent-soft', accentSecondary: '--chart-accent-secondary',
  neutral: '--chart-neutral', crosshair: '--chart-crosshair', profile: '--chart-profile',
};

export function getChartPalette(element?: Element): JQEChartPalette {
  if (typeof window === 'undefined') return chartPaletteFallback;
  const styles = window.getComputedStyle(element ?? document.documentElement);
  return Object.fromEntries(Object.entries(cssTokens).map(([key, token]) => [
    key, styles.getPropertyValue(token).trim() || chartPaletteFallback[key as keyof JQEChartPalette],
  ])) as unknown as JQEChartPalette;
}
