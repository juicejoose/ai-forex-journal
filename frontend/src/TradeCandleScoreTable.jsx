import { chartStamp, chartTime } from './marketChartData.js'
import { scoreDirection, scoreNumber, signedScore } from './tradeScores.js'

function PointCells({ score }) {
  const available = score.direction !== 'insufficient_data'
  return <>
    <td>{scoreNumber(available ? score.bullish_points : null)}</td>
    <td>{scoreNumber(available ? score.bearish_points : null)}</td>
    <td>{signedScore(available ? score.net_score : null)}</td>
    <td>{scoreDirection(score.direction)}</td>
  </>
}

export default function TradeCandleScoreTable({ label, caption, candles, average }) {
  return <div className="trade-score-table" tabIndex={0} role="region" aria-label={label}>
    <table>
      <caption>{caption}</caption>
      <thead><tr><th scope="col">H4 close · New York</th><th scope="col">Bull</th><th scope="col">Bear</th><th scope="col">Net</th><th scope="col">Direction</th></tr></thead>
      <tbody>{candles.map(row => <tr key={row.open_time}>
        <th scope="row">{chartStamp(chartTime(row.close_time))}</th>
        <PointCells score={row} />
      </tr>)}</tbody>
      {average && <tfoot><tr><th scope="row">Session average</th><PointCells score={average} /></tr></tfoot>}
    </table>
  </div>
}
