import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { COACHING_STRUGGLES } from '../data/demoFixtures'
import { cx } from '../lib/cx'
import { ImplementLink } from './ImplementLink'
import styles from './ClosingCta.module.css'

function wrappedOffset(i: number, index: number, n: number) {
  let offset = i - index
  const half = n / 2
  if (offset > half) offset -= n
  if (offset < -half) offset += n
  return offset
}

export function ClosingCta() {
  const [index, setIndex] = useState(0)
  const [nudge, setNudge] = useState(0)
  const [dragging, setDragging] = useState(false)
  const drag = useRef({ active: false, startX: 0, moved: false })
  const nudgeRef = useRef(0)
  const n = COACHING_STRUGGLES.length

  const go = useCallback((dir: number) => {
    setIndex((i) => (i + dir + n) % n)
  }, [n])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const root = document.getElementById('close')
      if (!root) return
      if (!root.contains(document.activeElement) && document.activeElement !== document.body) return
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        go(1)
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        go(-1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go])

  const current = COACHING_STRUGGLES[index]

  const endDrag = (clientX: number) => {
    if (!drag.current.active) return
    const dx = clientX - drag.current.startX
    const nudged = nudgeRef.current
    drag.current.active = false
    setDragging(false)
    if (drag.current.moved) {
      if (nudged > 0.22 || dx > 48) go(-1)
      else if (nudged < -0.22 || dx < -48) go(1)
    }
    nudgeRef.current = 0
    setNudge(0)
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    drag.current = { active: true, startX: e.clientX, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
    setDragging(true)
  }

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current.active) return
    const dx = e.clientX - drag.current.startX
    if (Math.abs(dx) > 6) drag.current.moved = true
    if (document.documentElement.dataset.motion === 'reduced') return
    const next = Math.max(-1, Math.min(1, dx / 220))
    nudgeRef.current = next
    setNudge(next)
  }

  return (
    <section id="close" className={`scene ${styles.scene}`} aria-labelledby="close-title" tabIndex={0}>
      <div className="scene-inner">
        <img
          className={styles.wordmark}
          src="/media/api-wordmark.png"
          alt="Athletic Performance Intelligence"
          width={890}
          height={124}
        />
        <h2 id="close-title" className="visually-hidden">
          Coaching struggles
        </h2>

        <div className={styles.gallery}>
          <div
            className={styles.pips}
            role="listbox"
            aria-label="Coaching struggles"
            aria-orientation="horizontal"
            aria-activedescendant={`struggle-${current.id}`}
          >
            {COACHING_STRUGGLES.map((item, i) => (
              <button
                key={item.id}
                id={`struggle-${item.id}`}
                type="button"
                role="option"
                aria-label={item.label}
                aria-selected={i === index}
                className={cx(styles.pip, i === index && styles.pipOn)}
                onClick={() => setIndex(i)}
              >
                {item.source === 'neurobuddy' ? 'Neurobuddy' : item.label}
              </button>
            ))}
          </div>
          <div
            className={styles.stage}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={(e) => endDrag(e.clientX)}
            onPointerCancel={(e) => endDrag(e.clientX)}
          >
            <button
              type="button"
              className={cx(styles.nav, styles.navPrev)}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => go(-1)}
              aria-label="Previous struggle"
            >
              ←
            </button>
            <div className={cx(styles.track, dragging && styles.dragging)}>
              {COACHING_STRUGGLES.map((item, i) => {
                const offset = wrappedOffset(i, index, n) - nudge
                const on = i === index
                return (
                  <button
                    key={item.id}
                    type="button"
                    tabIndex={-1}
                    aria-label={item.label}
                    className={cx(styles.item, on && styles.itemOn, item.source === 'neurobuddy' && styles.itemNb)}
                    style={
                      {
                        '--o': String(offset),
                        '--abs': String(Math.abs(offset)),
                        zIndex: on ? 12 : 8 - Math.round(Math.abs(offset) * 4),
                        opacity: Math.abs(offset) > 1.05 ? 0 : undefined,
                        pointerEvents: Math.abs(offset) > 1.05 ? 'none' : undefined,
                      } as CSSProperties
                    }
                    onClick={(e) => {
                      if (drag.current.moved) {
                        e.preventDefault()
                        return
                      }
                      setIndex(i)
                    }}
                  >
                    {on ? <h3 className={styles.itemName}>{item.label}</h3> : (
                      <span className={styles.itemName}>{item.source === 'neurobuddy' ? 'Neurobuddy' : item.label}</span>
                    )}
                  </button>
                )
              })}
            </div>
            <button
              type="button"
              className={cx(styles.nav, styles.navNext)}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => go(1)}
              aria-label="Next struggle"
            >
              →
            </button>
          </div>
        </div>

        <div className={styles.detail}>
          <p className="kicker" style={{ color: '#0f2532' }}>
            {current.source === 'api' ? 'From Athletic Performance Intelligence' : 'This Neurobuddy tour'}
          </p>
          <h3>{current.label}</h3>
          <p>{current.body}</p>
        </div>
        <div className={styles.cta}>
          <ImplementLink className={`btn btn-dark ${styles.ctaLink}`} />
        </div>
      </div>
    </section>
  )
}
