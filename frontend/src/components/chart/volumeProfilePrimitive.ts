import type {
  IPrimitivePaneRenderer, IPrimitivePaneView,
  ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, Time,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { VolumeProfileSnapshotDTO } from '../../types/research';

export interface VolumeProfileVisualBin { low: number; high: number; volume: number; }
export interface VolumeProfileVisual {
  bins: VolumeProfileVisualBin[]; poc: number; vah: number; val: number; maxVolume: number;
}

const PROFILE_LABELS: Record<string, string> = {
  REAL_VOLUME: 'Real Volume Profile',
  TICK_VOLUME: 'Tick Volume Profile',
  BROKER_VOLUME: 'Broker Volume Profile',
  SIMULATED_VOLUME: 'Simulated Volume Profile',
};

export function volumeProfileLabel(volumeType: string): string {
  return PROFILE_LABELS[volumeType] ?? `Fixed Range Volume Profile unavailable (${volumeType})`;
}

export function isValidProfileRange(start: number, end: number, cursor: number): boolean {
  return Number.isInteger(start) && Number.isInteger(end) && start >= 0 && start <= end && end <= cursor;
}

export function adaptVolumeProfile(snapshot: VolumeProfileSnapshotDTO): VolumeProfileVisual {
  const bins = snapshot.bins.map(bin => ({ low: Number(bin.low), high: Number(bin.high), volume: Number(bin.volume) }));
  return { bins, poc: Number(snapshot.point_of_control), vah: Number(snapshot.value_area_high),
    val: Number(snapshot.value_area_low), maxVolume: Math.max(0, ...bins.map(bin => bin.volume)) };
}

class Renderer implements IPrimitivePaneRenderer {
  constructor(private series: ISeriesApi<'Candlestick'>, private visual: VolumeProfileVisual) {}
  draw(target: CanvasRenderingTarget2D) {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      if (this.visual.maxVolume <= 0) return;
      const maxWidth = Math.min(180, mediaSize.width * 0.28);
      context.save();
      for (const bin of this.visual.bins) {
        const top = this.series.priceToCoordinate(bin.high);
        const bottom = this.series.priceToCoordinate(bin.low);
        if (top === null || bottom === null) continue;
        const width = maxWidth * bin.volume / this.visual.maxVolume;
        context.fillStyle = 'rgba(0,188,212,0.24)';
        context.fillRect(mediaSize.width - width, top, width, Math.max(1, bottom - top));
      }
      for (const [price, color, width] of [[this.visual.poc, '#ffab00', 2], [this.visual.vah, '#00e676', 1], [this.visual.val, '#00e676', 1]] as const) {
        const y = this.series.priceToCoordinate(price);
        if (y === null) continue;
        context.strokeStyle = color; context.lineWidth = width;
        context.beginPath(); context.moveTo(mediaSize.width - maxWidth, y); context.lineTo(mediaSize.width, y); context.stroke();
      }
      context.restore();
    });
  }
}

export class VolumeProfilePrimitive implements ISeriesPrimitive<Time> {
  private series: ISeriesApi<'Candlestick'> | null = null;
  private requestUpdate: (() => void) | null = null;
  constructor(private visual: VolumeProfileVisual) {}
  attached(param: SeriesAttachedParameter<Time, 'Candlestick'>) { this.series = param.series; this.requestUpdate = param.requestUpdate; }
  detached() { this.series = null; this.requestUpdate = null; }
  paneViews(): readonly IPrimitivePaneView[] {
    if (!this.series) return [];
    const renderer = new Renderer(this.series, this.visual);
    return [{ zOrder: () => 'top', renderer: () => renderer }];
  }
  updateAllViews() { this.requestUpdate?.(); }
}
