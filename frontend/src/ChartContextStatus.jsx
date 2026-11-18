export default function ChartContextStatus({context,loading,error,includeAfter,onRefresh}) {
  return <div className="mc-context-status">
    <div><p className="mc-help">{context ? `${context.preceding.length} preceding candles${includeAfter ? ` · ${context.following.length} / 160 later candles` : ''} · Extra chart context only. Saved analysis and scores stay fixed.` : loading ? 'Loading up to 160 preceding candles with indicators…' : 'Additional chart context is not loaded.'}</p>
      {includeAfter && context && <p className="mc-help">Later candles are retrospective context, outside the shaded review period. They were not available to the saved analysis.{context.following.length < 160 ? ' Refresh later for more available candles.' : ''}</p>}
      {context?.forming_at && !context.forming_candle && <p className="mc-help">No current forming candle is available for this window. Reload a live setup preview after its H4 candle closes to advance the evidence.</p>}
      {error && <p className="jv-error" role="alert">{error} Showing {context ? 'the last loaded context' : 'available saved history'}; the original review remains intact.</p>}</div>
    <button type="button" disabled={loading} onClick={onRefresh}>{loading ? 'Loading context…' : 'Refresh chart context'}</button>
  </div>
}
