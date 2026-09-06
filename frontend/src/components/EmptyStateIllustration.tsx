/** Decorative research folio: never represents actual market data. */
export function EmptyStateIllustration() {
  return <svg className="empty-state-illustration" viewBox="0 0 160 112" fill="none" aria-hidden="true">
    <path d="M28 84h104M44 88V26h66v62M50 20h66v62" stroke="currentColor" strokeWidth="1.5" />
    <path d="M57 41h37M57 48h25M57 70h40" stroke="currentColor" opacity=".35" />
    <circle cx="100" cy="76" r="15" fill="var(--surface)" stroke="currentColor" strokeWidth="1.5" />
    <path d="m111 87 13 13M93 76h14M100 69v14" stroke="currentColor" strokeWidth="1.5" />
    <path d="M24 38h10M29 33v10M128 48h6" stroke="currentColor" opacity=".5" />
  </svg>;
}
