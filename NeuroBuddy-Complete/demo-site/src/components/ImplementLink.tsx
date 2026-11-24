import { PRODUCT } from '../data/demoFixtures'

export function ImplementLink({ className }: { className: string }) {
  return (
    <a
      className={className}
      href={PRODUCT.implementHref}
      target="_blank"
      rel="noopener noreferrer"
    >
      {PRODUCT.implementLabel}
      <span className="visually-hidden"> (opens in a new tab)</span>
    </a>
  )
}
