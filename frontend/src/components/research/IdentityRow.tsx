interface IdentityRowProps { label: 'Dataset' | 'Run' | 'Result'; value: string | null; }

export function IdentityRow({ label, value }: IdentityRowProps) {
  const shortened = value ? `${value.slice(0, 14)}\u2026${value.slice(-8)}` : '\u2014';
  return (
    <div className="experiment-identity-row">
      <span>{label}</span>
      <code title={value ?? 'Identity unavailable'}>{shortened}</code>
      {value && (
        <button
          type="button"
          className="experiment-copy"
          aria-label={`Copy ${label.toLowerCase()} identity`}
          onClick={() => navigator.clipboard?.writeText(value)}
        >
          Copy
        </button>
      )}
    </div>
  );
}
