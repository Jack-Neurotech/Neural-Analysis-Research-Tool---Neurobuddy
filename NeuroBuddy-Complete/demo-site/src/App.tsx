import { AdvancedDemo } from './components/AdvancedDemo'
import { ClosingCta } from './components/ClosingCta'
import { Hero } from './components/Hero'
import { ReportDemo } from './components/ReportDemo'
import { ScrollStory } from './components/ScrollStory'
import { SiteChrome } from './components/SiteChrome'
import { TaskCarousel } from './components/TaskCarousel'
import { VideoModal } from './components/VideoModal'
import { WorkspaceDemo } from './components/WorkspaceDemo'
import { DemoProvider, useDemo } from './context/DemoContext'

function Scenes() {
  const { resetKey } = useDemo()
  return (
    <main id="main" key={resetKey}>
      <Hero />
      <ScrollStory />
      <WorkspaceDemo />
      <TaskCarousel />
      <ReportDemo />
      <AdvancedDemo />
      <ClosingCta />
    </main>
  )
}

export default function App() {
  return (
    <DemoProvider>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <SiteChrome />
      <Scenes />
      <VideoModal />
    </DemoProvider>
  )
}
