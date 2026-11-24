import { PRODUCT } from '../data/demoFixtures'
import { NeuronFigure } from './NeuronFigure'
import { AccessibilityControls } from './AccessibilityControls'
import { useDemo } from '../context/DemoContext'

const LINKS = [
  { href: '#hero', label: 'Hero' },
  { href: '#pipeline', label: 'Pipeline' },
  { href: '#library', label: 'Library' },
  { href: '#tasks', label: 'Tasks' },
  { href: '#reports', label: 'Reports' },
  { href: '#advanced', label: 'Packages' },
  { href: '#close', label: 'Close' },
]

export function SiteChrome() {
  const { resetDemo } = useDemo()
  return (
    <>
      <div className="sample-banner">
        <p className="banner-label" role="status">
          {PRODUCT.sampleMark}
        </p>
        <AccessibilityControls />
      </div>
      <header className="site-header">
        <a className="brand" href="#hero">
          <NeuronFigure size="mark" alt="" />
          <span>
            <strong>{PRODUCT.name}</strong>
            <small>Interactive demo</small>
          </span>
        </a>
        <nav className="scene-nav" aria-label="Scene">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
        </nav>
        <button type="button" className="btn btn-ghost" onClick={resetDemo}>
          Reset demo
        </button>
      </header>
    </>
  )
}
