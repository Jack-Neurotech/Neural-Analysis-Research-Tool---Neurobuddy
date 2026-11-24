import { PRODUCT } from '../data/demoFixtures'
import { useDemo } from '../context/DemoContext'
import { ImplementLink } from './ImplementLink'
import { NeuronFigure } from './NeuronFigure'
import styles from './Hero.module.css'

export function Hero() {
  const { openVideo } = useDemo()
  return (
    <section id="hero" className={`scene ${styles.hero}`} aria-labelledby="hero-title">
      <div className={`scene-inner ${styles.grid}`}>
        <div className={styles.copy}>
          <p className="kicker">The brain, made interpretable</p>
          <h1 id="hero-title" className={`display ${styles.title}`}>
            {PRODUCT.name}
          </h1>
          <p className={styles.claim}>{PRODUCT.tagline}</p>
          <p className="lede">{PRODUCT.subtext}</p>
          <p className="chip">{PRODUCT.disclaimer}</p>
          <div className="btn-row">
            <a className="btn btn-primary" href={import.meta.env.VITE_COACH_URL || "http://127.0.0.1:8765/#library"}>
              Try Neuro-Buddy
            </a>
            <a className="btn btn-primary" href="#pipeline">
              Explore the interactive demo
            </a>
            <button type="button" className="btn btn-ghost" onClick={openVideo}>
              Watch product walkthrough
            </button>
            <ImplementLink className="btn btn-ghost" />
          </div>
        </div>
        <div className={styles.media}>
          <div className={styles.frame}>
            <figure className={styles.subject}>
              <img
                src="/media/eeg-subject.jpg"
                alt="Adult wearing a research EEG electrode cap with a visible scalp montage"
                width={1152}
                height={864}
                decoding="sync"
                fetchPriority="high"
              />
            </figure>
            <div className={styles.motif} aria-hidden="true">
              <NeuronFigure alt="" />
            </div>
          </div>
          <p className={styles.mediaCaption}>
            Demonstration photograph of a research EEG electrode cap. Illustrative only; no live EEG is processed.
          </p>
        </div>
      </div>
    </section>
  )
}
