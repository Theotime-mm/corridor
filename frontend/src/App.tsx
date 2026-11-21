import { MapPanel } from './components/MapPanel'
import { SignIn } from './components/SignIn'
import { TimelinePanel } from './components/TimelinePanel'
import { TopBar } from './components/TopBar'
import { Sidebar } from './components/sidebar/Sidebar'
import { useStore } from './store'

export default function App() {
  const callsign = useStore((s) => s.callsign)
  if (!callsign) return <SignIn />

  return (
    <div className="layout">
      <TopBar />
      <div className="main">
        <MapPanel />
        <Sidebar />
      </div>
      <TimelinePanel />
    </div>
  )
}
