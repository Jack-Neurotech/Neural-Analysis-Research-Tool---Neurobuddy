import { PIPELINE_STEPS } from '../data/demoFixtures'
import { useInViewStep } from '../hooks/useInViewStep'
import styles from './ScrollStory.module.css'
import { cx } from '../lib/cx'

export function ScrollStory() {
  const { active, setActive, setRef } = useInViewStep(PIPELINE_STEPS.length)
  const mediaLeft = active >= 2

  return (
    <section id="pipeline" className={`scene ${styles.scene}`} aria-labelledby="pipeline-title">
      <div className="scene-inner">
        <p className="kicker">How an EEG becomes a report</p>
        <h2 id="pipeline-title" className="display" style={{ fontSize: 'clamp(32px, 5vw, 56px)' }}>
          Five steps. One local workspace.
        </h2>
        <p className="lede">
          This is a demonstration of the Coach workflow, not an uploader. Nothing is transmitted, stored, or analyzed.
        </p>

        <div className={cx(styles.layout, mediaLeft && styles.flip)}>
          <div className={styles.narrative}>
            {PIPELINE_STEPS.map((step, i) => (
              <article
                key={step.id}
                id={`pipe-${step.id}`}
                ref={setRef(i)}
                className={cx(styles.step, i === active && styles.stepOn)}
                aria-current={i === active}
              >
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </article>
            ))}
          </div>

          <aside className={`sticky-media ${styles.pin}`} aria-live="polite">
            <div className={styles.stage}>
              <img
                className={styles.photo}
                src="/media/pipeline-eeg-woman.jpg"
                alt="Smiling adult wearing a research EEG electrode cap with a visible scalp montage"
                width={1152}
                height={864}
              />
              <div className={styles.brand}>
                <img
                  src="/media/api-wordmark.png"
                  alt="Athletic Performance Intelligence"
                  width={890}
                  height={124}
                />
              </div>
              <div className={styles.overlay}>
                <p className="kicker">Pinned visual</p>
                <strong>{PIPELINE_STEPS[active].title}</strong>
                <p>{PIPELINE_STEPS[active].body}</p>
              </div>
            </div>
            <p className="caption">
              Demonstration photograph with Athletic Performance Intelligence branding. Illustrative only; this demo
              does not record or analyze visitor EEG.
            </p>
            <div className={styles.rail} role="group" aria-label="Pipeline progress">
              {PIPELINE_STEPS.map((step, i) => (
                <button
                  key={step.id}
                  type="button"
                  className={cx(styles.tick, i === active && styles.tickOn)}
                  aria-current={i === active}
                  aria-label={step.title}
                  onClick={() => {
                    setActive(i)
                    document.getElementById(`step-${step.id}`)?.scrollIntoView({ block: 'center' })
                  }}
                />
              ))}
            </div>
            <div className={styles.controls}>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={active === 0}
                onClick={() => {
                  const next = Math.max(0, active - 1)
                  setActive(next)
                  document.getElementById(`pipe-${PIPELINE_STEPS[next].id}`)?.scrollIntoView({ block: 'center' })
                }}
              >
                Back
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={active === PIPELINE_STEPS.length - 1}
                onClick={() => {
                  const next = Math.min(PIPELINE_STEPS.length - 1, active + 1)
                  setActive(next)
                  document.getElementById(`pipe-${PIPELINE_STEPS[next].id}`)?.scrollIntoView({ block: 'center' })
                }}
              >
                Next
              </button>
            </div>
          </aside>
        </div>
        {PIPELINE_STEPS.map((step) => (
          <span key={step.id} id={`step-${step.id}`} className="visually-hidden">
            {step.title}
          </span>
        ))}
        <p className="demo-note">Demo only · no backend connection · revolving layout settles rather than spinning.</p>
      </div>
    </section>
  )
}
