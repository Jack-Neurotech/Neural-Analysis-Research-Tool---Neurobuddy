import { useEffect, useRef, useState } from 'react'

export function useInViewStep(count: number) {
  const refs = useRef<Array<HTMLElement | null>>([])
  const [active, setActive] = useState(0)

  useEffect(() => {
    const nodes = refs.current.filter((n): n is HTMLElement => Boolean(n))
    if (!nodes.length) return
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (!visible) return
        const idx = nodes.indexOf(visible.target as HTMLElement)
        if (idx >= 0) setActive(idx)
      },
      { rootMargin: '-35% 0px -45% 0px', threshold: [0.25, 0.5, 0.75] },
    )
    nodes.forEach((n) => io.observe(n))
    return () => io.disconnect()
  }, [count])

  const setRef = (index: number) => (el: HTMLElement | null) => {
    refs.current[index] = el
  }

  return { active, setActive, setRef }
}
