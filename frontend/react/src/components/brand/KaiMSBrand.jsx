export function KaiMSBrand({ compact = false, inverse = false, onActivate = null }) {
  const content = (
    <>
      <span className="kaims-brand-mark" aria-hidden="true">
        <svg viewBox="0 0 48 48" role="img">
          <path className="kaims-mark-k" d="M14 11v26M15 25l16-14M15 25l17 13" />
          <path className="kaims-mark-signal" d="M7 31h7l4-7 5 11 4-7h14" />
        </svg>
      </span>
      <span className="kaims-brand-copy">
        <strong>Kai<span>MS</span></strong>
        <small>Intelligent managed service</small>
      </span>
    </>
  );

  return onActivate ? (
    <button
      type="button"
      className={`kaims-brand kaims-brand-home ${compact ? "is-compact" : ""} ${inverse ? "is-inverse" : ""}`}
      aria-label="Go to KaiMS home"
      onClick={onActivate}
    >
      {content}
    </button>
  ) : (
    <div
      className={`kaims-brand ${compact ? "is-compact" : ""} ${inverse ? "is-inverse" : ""}`}
      aria-label="KaiMS intelligent managed service"
    >
      {content}
    </div>
  );
}
