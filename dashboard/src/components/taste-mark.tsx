export default function TasteMark({ small = false }: { small?: boolean }) {
  return <span className={small ? "taste-mark small" : "taste-mark"} aria-hidden="true">
    <svg viewBox="0 0 80 80" fill="none"><g stroke="currentColor" strokeWidth="1.2">
      {[0, 45, 90, 135].map(angle => <ellipse key={angle} cx="40" cy="40" rx="13" ry="31" transform={`rotate(${angle} 40 40)`} />)}
      <circle cx="40" cy="40" r="5" fill="currentColor" stroke="none" />
    </g></svg>
  </span>;
}
