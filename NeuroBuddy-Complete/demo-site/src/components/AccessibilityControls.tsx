import { useEffect, useState } from 'react'
import { usePrefersReducedMotion } from '../hooks/usePrefersReducedMotion'

export function AccessibilityControls() {
  const osReduced = usePrefersReducedMotion()
  const [forced, setForced] = useState<boolean | null>(null)
  const reduced = forced ?? osReduced

  useEffect(() => {
    document.documentElement.dataset.motion = reduced ? 'reduced' : 'full'
  }, [reduced])

  return (
    <div className="a11y-dock">
      <button
        type="button"
        aria-pressed={reduced}
        onClick={() => setForced(!reduced)}
      >
        {reduced ? 'Motion: reduced' : 'Reduce motion'}
      </button>
    </div>
  )
}
