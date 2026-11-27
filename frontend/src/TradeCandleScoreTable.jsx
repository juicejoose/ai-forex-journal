import { chartStamp, chartTime } from './marketChartData.js'
import { scoreDirection, scoreNumber, signedScore } from './tradeScores.js'

export function BullBearCells({ score, available }) {
  const bull = available ? score.bullish_points : null
  const bear = available ? score.bearish_points : null
  return <>
    <td className={Number.isFinite(bull) && bull > 0 ? 'trade-positive' : undefined}>{scoreNumber(bull)}</td>
    <td className={Number.isFinite(bear) && bear > 0 ? 'trade-negative' : undefined}>{scoreNumber(bear)}</td>
  </>
}

function PointCells({ score }) {
  const available = score.direction !== 'insufficient_data'
  const net = available ? score.net_score : null
  const directionColor = { bullish: 'trade-positive', bearish: 'trade-negative' }[score.direction]
  return <>
    <BullBearCells score={score} available={available} />
    <td className={Number.isFinite(net) && net !== 0 ? directionColor : undefined}>{signedScore(net)}</td>
    <td className={directionColor}>{scoreDirection(score.direction)}</td>
  </>
}

export default function TradeCandleScoreTable({ label, caption, candles, average }) {
  return <div className="trade-score-table" tabIndex={0} role="region" aria-label={label}>
    <table>
      <caption>{caption}</caption>
      <thead><tr><th scope="col">H4 close · New York</th><th scope="col" className="trade-positive">Bull</th><th scope="col" className="trade-negative">Bear</th><th scope="col">Net</th><th scope="col">Direction</th></tr></thead>
      <tbody>{candles.map(row => <tr key={row.open_time}>
        <th scope="row">{chartStamp(chartTime(row.close_time))}</th>
        <PointCells score={row} />
      </tr>)}</tbody>
      {average && <tfoot><tr><th scope="row">Session average</th><PointCells score={average} /></tr></tfoot>}
    </table>
  </div>
}
