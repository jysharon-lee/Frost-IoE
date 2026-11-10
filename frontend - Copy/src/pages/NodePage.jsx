import ReadingDetails from "../components/ReadingDetails";

export default function NodePage({
  node,
  ...props
}) {
  return (
    <ReadingDetails
      {...props}
      node={node}
    />
  );
}