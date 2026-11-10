export default function Badge({
  children,
  tone = "",
}) {
  return (
    <span className={`badge ${tone}`}>
      {children}
    </span>
  );
}