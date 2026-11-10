export default function MetricCard({
  title,
  value,
  description,
  icon: Icon,
}) {
  return (
    <article className="metric">
      {Icon && (
        <div className="metric-icon">
          <Icon size={23} />
        </div>
      )}

      <div>
        <p>{title}</p>

        <strong>{value}</strong>

        {description && (
          <small>{description}</small>
        )}
      </div>
    </article>
  );
}