import { useEffect, useRef } from 'react'
import { useDemo } from '../context/DemoContext'
import styles from './VideoModal.module.css'

export function VideoModal() {
  const { videoOpen, closeVideo } = useDemo()
  const dialog = useRef<HTMLDialogElement>(null)
  const video = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const el = dialog.current
    if (!el) return
    if (videoOpen) {
      if (!el.open) el.showModal()
    } else if (el.open) {
      el.close()
      video.current?.pause()
    }
  }, [videoOpen])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && videoOpen) closeVideo()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closeVideo, videoOpen])

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby="walkthrough-title"
      onClose={closeVideo}
      onClick={(e) => {
        if (e.target === dialog.current) closeVideo()
      }}
    >
      <div className={styles.bar}>
        <div>
          <p className="kicker" id="walkthrough-title">
            Product walkthrough
          </p>
          <p className={styles.meta}>Oddball, motor imagery, then sleep · user-initiated playback</p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={closeVideo} aria-label="Close walkthrough">
          Close
        </button>
      </div>
      {videoOpen ? (
        <video
          ref={video}
          className={styles.video}
          controls
          playsInline
          preload="metadata"
          src="/media/all-tests.mp4"
        >
          Your browser cannot play this walkthrough video.
        </video>
      ) : null}
    </dialog>
  )
}
