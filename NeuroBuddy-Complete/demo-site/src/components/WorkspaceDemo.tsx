import { DEFAULT_LIBRARY } from '../data/demoFixtures'
import styles from './WorkspaceDemo.module.css'

const EXAMPLE = DEFAULT_LIBRARY[0]
const ATHLETE = EXAMPLE.athletes[0]

export function WorkspaceDemo() {
  return (
    <section id="library" className={`scene ${styles.scene}`} aria-labelledby="library-title">
      <div className="scene-inner">
        <p className="kicker">The Dataset Library, explained</p>
        <h2 id="library-title" className="display" style={{ fontSize: 'clamp(32px, 5vw, 56px)' }}>
          Team, athlete, shelf.
        </h2>
        <p className="lede">
          A researcher nests recordings under a team folder, then an athlete folder, then baseline and testing shelves.
          Files must be from the same athlete with compatible task and channel configurations for a meaningful comparison.
        </p>
        <p className="chip">Illustrative sample data. No live EEG is processed here.</p>

        <div className={styles.layout}>
          <div>
            <ol className={styles.steps} aria-label="How a library is organized">
              <li>
                <h3>Make a team folder</h3>
                <p>One lab or roster. Example: {EXAMPLE.name}.</p>
              </li>
              <li>
                <h3>Make an athlete folder</h3>
                <p>Recordings stay nested under one person. Example: {ATHLETE.name}.</p>
              </li>
              <li>
                <h3>Place files on shelves</h3>
                <p>Empty shelves are placeholders until compatible EEG files occupy them.</p>
              </li>
              <li>
                <h3>Send a shelf to processing</h3>
                <p>Drag a populated shelf into the processing area. This demo does not run a pipeline.</p>
              </li>
            </ol>

            <div className={styles.diagram}>
              <article className={styles.tree} aria-label="Static example of team and athlete folders">
                <p className="kicker">Static example</p>
                <div className={styles.folder}>
                  <p className={styles.summary}>
                    Team folder
                    <span>{EXAMPLE.name}</span>
                  </p>
                  <div className={styles.inner}>
                    <div className={styles.folder}>
                      <p className={styles.summary}>
                        Athlete folder
                        <span>{ATHLETE.name}</span>
                      </p>
                      <div className={styles.inner}>
                        <p className={styles.group}>Baseline · placeholders</p>
                        <p className={styles.shelf}>Baseline · Oddball</p>
                        <p className={styles.shelf}>Baseline · Oddball</p>
                        <p className={styles.group}>Testing · placeholder</p>
                        <p className={styles.shelf}>Testing · Oddball</p>
                      </div>
                    </div>
                  </div>
                </div>
              </article>
              <aside className={styles.drop} aria-label="Processing area, illustrated">
                <p className="kicker">Processing</p>
                <strong>Drop a populated shelf here</strong>
                <p>In the product, drag a shelf into this target. Illustrative only.</p>
              </aside>
            </div>
          </div>

          <figure className={styles.player}>
            <figcaption>
              <p className="kicker">Product walkthrough</p>
              <h3>Create a team, add an athlete, file a shelf, send to processing</h3>
              <p className="caption">
                Coach Atlas recording of the Dataset Library. User-initiated playback with controls. Illustrative sample
                data; this website does not import or analyze EEG.
              </p>
            </figcaption>
            <video
              className={styles.video}
              controls
              playsInline
              preload="metadata"
              poster="/media/Screenshot_Dataset_Library.png"
              src="/media/all-tests.mp4"
            >
              Your browser cannot play this walkthrough video.
            </video>
          </figure>
        </div>
      </div>
    </section>
  )
}
