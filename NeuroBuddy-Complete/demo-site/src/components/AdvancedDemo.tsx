import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { cx } from '../lib/cx'
import styles from './AdvancedDemo.module.css'

const ITEMS = [
  {
    id: 'analysis',
    label: 'Analysis',
    short: 'HTML reports listed',
    heading: 'The Analysis tab lists completed HTML reports.',
    body: 'Each finished job stays in Reports & Jobs. Open HTML report opens the pipeline page for that run. ZIP and JSON sit beside it when the job produced them. Coach screenshot; this demo does not generate a report from visitor EEG.',
  },
  {
    id: 'packages',
    label: 'Packages',
    short: 'Drag into processing',
    heading: 'Drag a result package into the processing area.',
    body: 'An athlete or team chip gathers that person\'s reports. Drop it on the processing target to prepare the package. Silent walkthrough of the existing mock; playback is user-initiated.',
  },
] as const

function wrappedOffset(i: number, index: number, n: number) {
  let offset = i - index
  const half = n / 2
  if (offset > half) offset -= n
  if (offset < -half) offset += n
  return offset
}

export function AdvancedDemo() {
  const [index, setIndex] = useState(0)
  const [nudge, setNudge] = useState(0)
  const [dragging, setDragging] = useState(false)
  const drag = useRef({ active: false, startX: 0, moved: false })
  const nudgeRef = useRef(0)
  const videoRef = useRef<HTMLVideoElement>(null)

  const go = useCallback((dir: number) => {
    setIndex((i) => (i + dir + ITEMS.length) % ITEMS.length)
  }, [])

  useEffect(() => {
    if (ITEMS[index].id !== 'packages') {
      videoRef.current?.pause()
    }
  }, [index])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const root = document.getElementById('advanced')
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

  const current = ITEMS[index]

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
    <section id="advanced" className={`scene ${styles.scene}`} aria-labelledby="advanced-title" tabIndex={0}>
      <div className="scene-inner">
        <p className="kicker">Reports and packages</p>
        <h2 id="advanced-title" className="display" style={{ fontSize: 'clamp(28px, 4.2vw, 52px)' }}>
          Reports, then packages.
        </h2>
        <p className="lede">
          Arrow keys, drag, or swipe to rotate. One still of the Analysis tab. One walkthrough of placing a package on
          the processing target.
        </p>
        <p className="chip">Illustrative sample data. No live EEG is processed here.</p>

        <div className={styles.gallery}>
          <div
            className={styles.pips}
            role="listbox"
            aria-label="Package views"
            aria-orientation="horizontal"
            aria-activedescendant={`pkg-${current.id}`}
          >
            {ITEMS.map((item, i) => (
              <button
                key={item.id}
                id={`pkg-${item.id}`}
                type="button"
                role="option"
                aria-label={item.label}
                aria-selected={i === index}
                className={cx(styles.pip, i === index && styles.pipOn)}
                onClick={() => setIndex(i)}
              >
                {item.label}
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
              aria-label="Previous package view"
            >
              ←
            </button>
            <div className={cx(styles.track, dragging && styles.dragging)}>
              {ITEMS.map((item, i) => {
                const offset = wrappedOffset(i, index, ITEMS.length) - nudge
                const on = i === index
                return (
                  <article
                    key={item.id}
                    className={cx(styles.item, on && styles.itemOn)}
                    style={
                      {
                        '--o': String(offset),
                        '--abs': String(Math.abs(offset)),
                        zIndex: on ? 12 : 8 - Math.round(Math.abs(offset) * 4),
                        opacity: Math.abs(offset) > 1.15 ? 0 : undefined,
                        pointerEvents: Math.abs(offset) > 1.15 ? 'none' : undefined,
                      } as CSSProperties
                    }
                    onClick={() => {
                      if (drag.current.moved) return
                      setIndex(i)
                    }}
                  >
                    {item.id === 'analysis' ? (
                      <img
                        src="/media/Screenshot_Analysis.png"
                        alt="Coach Analysis tab listing a completed job with Open HTML report"
                        width={1536}
                        height={1000}
                        draggable={false}
                      />
                    ) : (
                      <video
                        ref={videoRef}
                        className={styles.video}
                        controls
                        playsInline
                        preload="metadata"
                        poster="/media/package-drag-poster.png"
                        src="/media/package-drag.mp4"
                        onPointerDown={(e) => e.stopPropagation()}
                      >
                        Your browser cannot play this package walkthrough.
                      </video>
                    )}
                    <span className={styles.itemMeta}>
                      <span className={styles.itemName}>{item.label}</span>
                    </span>
                  </article>
                )
              })}
            </div>
            <button
              type="button"
              className={cx(styles.nav, styles.navNext)}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => go(1)}
              aria-label="Next package view"
            >
              →
            </button>
          </div>
        </div>

        <div className={styles.detail}>
          <p className="kicker">{current.short}</p>
          <h3>{current.heading}</h3>
          <p>{current.body}</p>
        </div>
      </div>
    </section>
  )
}
