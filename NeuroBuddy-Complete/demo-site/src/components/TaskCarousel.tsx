import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { TASKS, type SlotKind, type TaskType } from '../data/demoFixtures'
import { cx } from '../lib/cx'
import styles from './TaskCarousel.module.css'

const ORDER: TaskType[] = ['oddball', 'motor', 'sleep', 'unspecified']

function wrappedOffset(i: number, index: number, n: number) {
  let offset = i - index
  const half = n / 2
  if (offset > half) offset -= n
  if (offset < -half) offset += n
  return offset
}

export function TaskCarousel() {
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
      const root = document.getElementById('tasks')
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
  const task = TASKS[current]

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
    <section id="tasks" className={`scene ${styles.scene}`} aria-labelledby="tasks-title" tabIndex={0}>
      <div className="scene-inner">
        <p className="kicker">Test type revolving selector</p>
        <h2 id="tasks-title" className="display" style={{ fontSize: 'clamp(32px, 5vw, 56px)' }}>
          Four pathways. Different evidence.
        </h2>
        <p className="lede">
          Arrow keys, drag, or swipe to rotate. Essential text never spins. Photographs are atmospheric, not
          measurements.
        </p>

        <div className={styles.gallery}>
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
              aria-label="Previous experiment"
            >
              ←
            </button>
            <div className={cx(styles.track, dragging && styles.dragging)}>
              {ORDER.map((id, i) => {
                const offset = wrappedOffset(i, index, ORDER.length) - nudge
                const item = TASKS[id]
                return (
                  <button
                    key={id}
                    type="button"
                    tabIndex={-1}
                    aria-label={`Show ${item.label}`}
                    className={cx(styles.item, i === index && styles.itemOn)}
                    style={
                      {
                        '--o': String(offset),
                        '--abs': String(Math.abs(offset)),
                        zIndex: 10 - Math.round(Math.abs(offset) * 4),
                        opacity: Math.abs(offset) > 1.45 ? 0 : undefined,
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
                    <img src={item.photo.src} alt="" width={1152} height={864} draggable={false} />
                    <span className={styles.itemMeta}>
                      <span className={styles.itemName}>{item.label}</span>
                    </span>
                  </button>
                )
              })}
            </div>
            <button
              type="button"
              className={cx(styles.nav, styles.navNext)}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => go(1)}
              aria-label="Next experiment"
            >
              →
            </button>
          </div>

          <div className={styles.controls}>
            <div
              className={styles.pips}
              role="listbox"
              aria-label="Experiment selector"
              aria-orientation="horizontal"
              aria-activedescendant={`task-${current}`}
            >
              {ORDER.map((id, i) => (
                <button
                  key={id}
                  id={`task-${id}`}
                  type="button"
                  role="option"
                  aria-label={TASKS[id].label}
                  aria-selected={i === index}
                  className={cx(styles.pip, i === index && styles.pipOn)}
                  onClick={() => setIndex(i)}
                >
                  {TASKS[id].label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className={styles.card}>
          <div>
            <p className="kicker">{task.short}</p>
            <h3>{task.label}</h3>
            <p>{task.explanation}</p>
            <p className={styles.why}>
              <strong>Why it matters.</strong> {task.why}
            </p>
            <p className="demo-note">{task.caveat}</p>
            <p className="caption">{task.photo.caption}</p>
          </div>
          <div>
            <p className="kicker">Required / Companion / Optional</p>
            <ul className={styles.slots}>
              {task.slots.map((slot) => (
                <li key={slot.label} className={styles[slot.kind as SlotKind]}>
                  <strong>{slot.label}</strong>
                  <span>{slot.kind}</span>
                  <p>{slot.detail}</p>
                </li>
              ))}
            </ul>
            <p className="caption">
              .tsv / .json are annotations or metadata, not standalone raw EEG. Companion import in the product is a
              separate action, not a universal auto-complete.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
