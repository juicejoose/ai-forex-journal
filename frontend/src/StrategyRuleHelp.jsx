import { useEffect, useId, useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

export default function StrategyRuleHelp({ factor, open, onOpen, onClose }) {
  const tooltipId = useId()
  const trigger = useRef(null)
  const tooltip = useRef(null)
  const closeTimer = useRef(null)
  const pinned = useRef(false)

  function cancelClose() {
    window.clearTimeout(closeTimer.current)
  }

  function show() {
    cancelClose()
    onOpen()
  }

  function hide() {
    cancelClose()
    pinned.current = false
    onClose()
  }

  function leave() {
    cancelClose()
    if (!pinned.current && document.activeElement !== trigger.current) {
      closeTimer.current = window.setTimeout(onClose, 160)
    }
  }

  useLayoutEffect(() => {
    if (!open) return
    const anchor = trigger.current.getBoundingClientRect()
    const panel = tooltip.current
    const bounds = panel.getBoundingClientRect()
    const gap = 8
    const margin = 12
    const left = Math.max(margin, Math.min(anchor.left + anchor.width / 2 - bounds.width / 2, window.innerWidth - bounds.width - margin))
    const below = anchor.bottom + gap
    const top = below + bounds.height <= window.innerHeight - margin ? below : Math.max(margin, anchor.top - bounds.height - gap)
    panel.style.left = `${left}px`
    panel.style.top = `${top}px`
    panel.style.visibility = 'visible'
  }, [open, factor])

  useEffect(() => {
    if (!open) {
      pinned.current = false
      return
    }
    function dismiss() {
      window.clearTimeout(closeTimer.current)
      pinned.current = false
      onClose()
    }
    function outside(event) {
      if (!trigger.current?.contains(event.target) && !tooltip.current?.contains(event.target)) dismiss()
    }
    function escape(event) {
      if (event.key === 'Escape') dismiss()
    }
    function scroll(event) {
      if (!tooltip.current?.contains(event.target)) dismiss()
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    window.addEventListener('scroll', scroll, true)
    window.addEventListener('resize', dismiss)
    return () => {
      window.clearTimeout(closeTimer.current)
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('scroll', scroll, true)
      window.removeEventListener('resize', dismiss)
    }
  }, [open, onClose])

  return <>
    <button ref={trigger} type="button" className="ss-info-button"
      aria-label={`About ${factor.name}`} aria-describedby={open ? tooltipId : undefined}
      aria-expanded={open} onPointerEnter={(event) => { if (event.pointerType !== 'touch') show() }}
      onPointerLeave={leave} onFocus={show} onBlur={hide}
      onClick={() => { if (pinned.current) hide(); else { pinned.current = true; show() } }}>
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7.5" /><path d="M10 9v5" /><circle cx="10" cy="6.3" r="0.7" className="ss-info-dot" /></svg>
    </button>
    {open && createPortal(<div ref={tooltip} id={tooltipId} role="tooltip" className="ss-rule-tooltip"
      onPointerEnter={cancelClose} onPointerLeave={leave}>
      <strong>{factor.name}</strong>
      <p className="ss-tooltip-weight">Up to {factor.points} {factor.points === 1 ? 'point' : 'points'} per candle</p>
      <p><b>Bullish:</b> {factor.bullish}</p>
      <p><b>Bearish:</b> {factor.bearish}</p>
      {factor.distance_weighting && <p className="ss-tooltip-note">One EUR/USD pip is 0.0001. Equal EMA/SMA values earn zero. The maximum stays 5 points per candle when this factor earns only 1.</p>}
      {factor.slowdown && <p className="ss-tooltip-note">Uses three consecutive completed candles. Touching or crossing zero resets the slowdown comparison. Missing history makes this factor unavailable.</p>}
      <p className="ss-tooltip-note">Unmet conditions earn no points. Missing inputs are unavailable.</p>
    </div>, document.body)}
  </>
}
