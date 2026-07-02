import {
  createRouter,
  createRoute,
  createRootRoute,
  Outlet,
  useRouterState,
} from '@tanstack/react-router'

import { SourcesPicker } from './screens/SourcesPicker'
import { TargetSetup } from './screens/TargetSetup'
import { PreviewDiff } from './screens/PreviewDiff'
import { ApplyProgress } from './screens/ApplyProgress'
import { History } from './screens/History'
import { HistoryDetail } from './screens/HistoryDetail'
import { Validate } from './screens/Validate'
import { WarehousePicker } from './components/WarehousePicker'
import { ArrowFlow, DatabricksMark, PowerBiMark } from './components/BrandMarks'
import { useUrlSearch } from './lib/url-state'
import { api } from './api'


function NavLink(props: { to: string; children: React.ReactNode }): JSX.Element {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const active = pathname === props.to
  const search = useUrlSearch()
  return (
    <a
      href={`${props.to}${search}`}
      className={[
        'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
        active
          ? 'bg-white text-databricks-ink shadow-sm'
          : 'text-slate-300 hover:bg-white/10 hover:text-white',
      ].join(' ')}
    >
      {props.children}
    </a>
  )
}


function Header(): JSX.Element {
  async function newSync(): Promise<void> {
    if (!window.confirm('Start a new sync? This clears your current selections and the translation cache.')) return
    try {
      await api.clearCache()
    } catch {
      // best-effort — still reset the wizard even if the cache clear failed
    }
    window.location.href = '/' // full reload to Sources; warehouse + catalog persist in localStorage
  }
  return (
    <header className="border-b border-databricks-ink/40 bg-gradient-to-r from-databricks-ink via-databricks-navy to-databricks-ink text-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-3">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <DatabricksMark className="h-6 w-6" />
            <ArrowFlow className="h-3 w-8 text-slate-500" />
            <PowerBiMark className="h-6 w-6" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">sync_semantics</div>
            <div className="text-[10px] uppercase tracking-wider text-slate-400">
              Databricks → Power BI
            </div>
          </div>
        </div>

        <nav className="flex items-center gap-1 rounded-lg bg-databricks-ink/40 p-1">
          <NavLink to="/">Sources</NavLink>
          <NavLink to="/target">Target</NavLink>
          <NavLink to="/preview">Preview</NavLink>
          <NavLink to="/validate">Validate</NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void newSync()}
            title="Start a new sync — clears your current selections and the translation cache, then returns to Sources"
            className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md bg-white/10 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-white/20"
          >
            <span aria-hidden="true" className="text-base leading-none">↻</span>
            New sync
          </button>
          <WarehousePicker />
        </div>
      </div>
    </header>
  )
}


const rootRoute = createRootRoute({
  component: () => (
    <div className="min-h-screen bg-gradient-to-b from-databricks-smoke/50 to-slate-50">
      <Header />
      <main className="mx-auto max-w-7xl px-6 py-6">
        <Outlet />
      </main>
    </div>
  ),
})

const sourcesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: SourcesPicker })
const targetRoute = createRoute({ getParentRoute: () => rootRoute, path: '/target', component: TargetSetup })
const previewRoute = createRoute({ getParentRoute: () => rootRoute, path: '/preview', component: PreviewDiff })
const applyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/apply', component: ApplyProgress })
const validateRoute = createRoute({ getParentRoute: () => rootRoute, path: '/validate', component: Validate })
const historyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/history', component: History })
const historyDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/history/$runId',
  component: HistoryDetail,
})

const routeTree = rootRoute.addChildren([
  sourcesRoute,
  targetRoute,
  previewRoute,
  applyRoute,
  validateRoute,
  historyRoute,
  historyDetailRoute,
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
