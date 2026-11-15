// A series primitive keeps draft zones aligned during pan, zoom and resize.
export class ZoneBands {
  constructor() {
    this.bands = []
    this.renderer = { draw: target => this.draw(target) }
    this.views = [{ zOrder: () => 'bottom', renderer: () => this.renderer }]
  }
  attached({ chart, series, requestUpdate }) {
    this.chart = chart
    this.series = series
    this.requestUpdate = requestUpdate
  }
  detached() { this.chart = null; this.series = null; this.requestUpdate = null }
  paneViews() { return this.views }
  setBands(bands) { this.bands = bands; this.requestUpdate?.() }
  draw(target) {
    if (!this.chart || !this.series) return
    const scale = this.chart.timeScale()
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      for (const band of this.bands) {
        const first = scale.logicalToCoordinate(band.start)
        const last = scale.logicalToCoordinate(band.end)
        if (first === null || last === null) continue
        const halfBar = Math.abs((scale.logicalToCoordinate(1) ?? 0) - (scale.logicalToCoordinate(0) ?? 0)) / 2
        const a = first - halfBar
        const b = last + halfBar
        const top = this.series.priceToCoordinate(band.upper)
        const bottom = this.series.priceToCoordinate(band.lower)
        if ([a,b,top,bottom].some(value => value === null || !Number.isFinite(value))) continue
        const left = Math.max(0, a), right = Math.min(mediaSize.width, b)
        if (right <= left || bottom < 0 || top > mediaSize.height) continue
        const color = band.kind === 'support' ? '#249c79' : '#d65e70'
        ctx.save()
        ctx.fillStyle = color + '24'
        ctx.fillRect(left, top, right-left, Math.max(1,bottom-top))
        ctx.strokeStyle = color
        ctx.lineWidth = 1
        ctx.strokeRect(left, top, right-left, Math.max(1,bottom-top))
        ctx.fillStyle = color
        ctx.font = '11px sans-serif'
        ctx.fillText(band.label, left+5, Math.max(13,top-5), Math.max(1,right-left-10))
        ctx.restore()
      }
    })
  }
}
