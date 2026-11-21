import { getTrend } from "../utils/data";

/* Colour-coded Rising / Stable / Dropping label. <b>, not <span>, so the zone-card span rules don't restyle it. */
export default function TrendTag({ rate }) {
  const trend = getTrend(rate);

  return trend && (
    <b className={`trend-tag ${trend.tone}`}>{trend.text}</b>
  );
}
