import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

type DemoContextValue = {
  resetKey: number
  videoOpen: boolean
  openVideo: () => void
  closeVideo: () => void
  resetDemo: () => void
  replayDemo: () => void
}

const DemoContext = createContext<DemoContextValue | null>(null)

export function DemoProvider({ children }: { children: ReactNode }) {
  const [resetKey, setResetKey] = useState(0)
  const [videoOpen, setVideoOpen] = useState(false)

  const openVideo = useCallback(() => setVideoOpen(true), [])
  const closeVideo = useCallback(() => setVideoOpen(false), [])

  const resetDemo = useCallback(() => {
    setResetKey((n) => n + 1)
    setVideoOpen(false)
  }, [])

  const replayDemo = useCallback(() => {
    resetDemo()
    window.scrollTo({ top: 0, behavior: document.documentElement.dataset.motion === 'reduced' ? 'auto' : 'smooth' })
  }, [resetDemo])

  const value = useMemo(
    () => ({ resetKey, videoOpen, openVideo, closeVideo, resetDemo, replayDemo }),
    [resetKey, videoOpen, openVideo, closeVideo, resetDemo, replayDemo],
  )

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>
}

export function useDemo() {
  const ctx = useContext(DemoContext)
  if (!ctx) throw new Error('useDemo must be used within DemoProvider')
  return ctx
}
