import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { REPORT_PATHWAYS, type TaskType } from '../data/demoFixtures'
import { cx } from '../lib/cx'
import styles from './ReportDemo.module.css'

const ORDER: TaskType[] = ['oddball', 'sleep', 'motor', 'unspecified']

function wrappedOffset(i: number, index: number, n: number) {
  let offset = i - index
  const half = n / 2
  if (offset > half) offset -= n
  if (offset < -half) offset += n
  return offset
}

export function ReportDemo() {
  const [index, setIndex] = useState(0)
  const [nudge, setNudge] = useState(0)
  const [dragging, setDragging] = useState(false)
  const drag = useRef({ active: false, startX: 0, moved: false })
  const nudgeRef = useRef(0)

  const go = useCallback((dir: number) => {
    setIndex((i) => (i + dir + ORDER.length) % ORDER.length)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const root = document.getElementById('reports')
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

  const current = ORDER[index]

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
    <section id="reports" className={`scene ${styles.scene}`} aria-labelledby="reports-title" tabIndex={0}>
      <div className="scene-inner">
        <p className="kicker">HTML reports by pathway</p>
        <h2 id="reports-title" className="display" style={{ fontSize: 'clamp(28px, 4.2vw, 48px)' }}>
          What each HTML report actually contains.
        </h2>
        <p className="lede">
          Coach opens the pipeline's original HTML. Each card lists diagrams, unique statistics, and what those
          figures put out. Illustrative sample copy; this demo does not generate a report from visitor EEG.
        </p>
        <p className="chip">Illustrative sample data. No live EEG is processed here.</p>

        <div className={styles.gallery}>
          <div
            className={styles.pips}
            role="listbox"
            aria-label="HTML report type"
            aria-orientation="horizontal"
            aria-activedescendant={`report-${current}`}
          >
            {ORDER.map((id, i) => (
              <button
                key={id}
                id={`report-${id}`}
                type="button"
                role="option"
                aria-label={REPORT_PATHWAYS[id].label}
                aria-selected={i === index}
                className={cx(styles.pip, i === index && styles.pipOn)}
                onClick={() => setIndex(i)}
              >
                {REPORT_PATHWAYS[id].label}
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
              aria-label="Previous report type"
            >
              ←
            </button>
            <div className={cx(styles.track, dragging && styles.dragging)}>
              {ORDER.map((id, i) => {
                const offset = wrappedOffset(i, index, ORDER.length) - nudge
                const item = REPORT_PATHWAYS[id]
                const on = i === index
                return (
                  <button
                    key={id}
                    type="button"
                    tabIndex={-1}
                    aria-label={`Show ${item.label} report`}
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
                    onClick={(e) => {
                      if (drag.current.moved) {
                        e.preventDefault()
                        return
                      }
                      setIndex(i)
                    }}
                  >
                    {on ? (
                      <h3 className={styles.itemName}>{item.label}</h3>
                    ) : (
                      <span className={styles.itemName}>{item.label}</span>
                    )}
                    <span className={styles.itemShort}>{item.short}</span>
                    {on ? (
                      <div className={styles.itemBody}>
                        <div>
                          <p className={styles.colKicker}>Diagrams in this HTML</p>
                          <ul>
                            {item.diagrams.map((line) => (
                              <li key={line}>{line}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <p className={styles.colKicker}>Statistics unique to this pathway</p>
                          <ul>
                            {item.uniqueStats.map((line) => (
                              <li key={line}>{line}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <p className={styles.colKicker}>What those figures put out</p>
                          <p>{item.message}</p>
                          <p className={styles.note}>
                            Shared extras when generated: figure tables, brain activity player, comparison heatmap,
                            sleep replay. Sample description only.
                          </p>
                        </div>
                      </div>
                    ) : null}
                  </button>
                )
              })}
            </div>
            <button
              type="button"
              className={cx(styles.nav, styles.navNext)}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => go(1)}
              aria-label="Next report type"
            >
              →
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
