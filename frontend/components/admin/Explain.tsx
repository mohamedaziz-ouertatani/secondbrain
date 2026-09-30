/** A plain-language reading beside a number, setting or action, with an optional longer "How it works". */
export function Explain({ line, more }: { line?: string | null; more?: string | null }) {
  if (!line && !more) return null;
  return (
    <div className="explain">
      {line && <p className="explain-line">{line}</p>}
      {more && (
        <details className="explain-more">
          <summary>How it works</summary>
          <p>{more}</p>
        </details>
      )}
    </div>
  );
}
