// Target Setup screen.
//
// "Publish to Power BI"-style flow:
//   1. Pick a Power BI workspace the Fabric service principal can publish to
//   2. Type the model name (existing or new)
//   3. Optionally toggle XMLA merge (preserve user-authored objects)
//
// PBIP delivery also works — toggle the delivery format at the top and the
// picker switches to a local output path. (The .pbit template format is not
// offered in the UI: hand-authored .pbit packages don't reliably open in
// Power BI Desktop. The CLI/back end can still emit one.)

import { PageHeader } from './SourcesPicker'
import { ApiClientError } from '../api'
import { useFabricWorkspaces } from '../lib/queryClient'
import { useUrlParam } from '../lib/url-state'
import type { DeliveryKind } from '../types'
import { PowerBiMark } from '../components/BrandMarks'


const DELIVERY_OPTIONS: Array<{
  key: DeliveryKind
  label: string
  hint: string
}> = [
  { key: 'xmla', label: 'Publish to Power BI', hint: 'Push directly to a Fabric workspace via XMLA' },
  { key: 'pbip', label: 'PBIP folder', hint: 'TMDL files you open in Power BI Desktop' },
]


export function TargetSetup(): JSX.Element {
  const workspaces = useFabricWorkspaces()
  const [kind, setKind] = useUrlParam<DeliveryKind>('kind', 'xmla')
  const [workspace, setWorkspace] = useUrlParam<string>('workspace', '')
  const [modelName, setModelName] = useUrlParam<string>('model_name', '')
  const [xmlaMerge, setXmlaMerge] = useUrlParam<string>('xmla_merge', 'false')

  // For XMLA, target_id is the Power BI workspace the Fabric SP publishes to;
  // auth comes from the SP creds wired through app.yaml secrets. For PBIP the
  // server rewrites the output path into the App container's /tmp, so there's
  // nothing for the user to enter — we just carry the model name through.
  const effectiveTargetId = kind === 'xmla' ? workspace : modelName

  const canProceed = !!effectiveTargetId && !!modelName

  const nextHref = (() => {
    const p = new URLSearchParams(window.location.search)
    // useUrlParam doesn't auto-write the default; force `kind` into the
    // URL so downstream screens see the same value the user actually picked.
    // Without this, a user who lands on /target with no params, sees XMLA
    // already highlighted (the default), and clicks Next would arrive at
    // /preview which defaults to PBIP → the engine silently writes a local
    // PBIP folder instead of publishing.
    p.set('kind', kind)
    // Carry a target_id downstream: the workspace for XMLA, the model name for
    // PBIP (the server rewrites the PBIP path anyway, but the apply request
    // still expects a non-empty target).
    p.set('target_id', kind === 'xmla' ? workspace : modelName)
    return `/preview?${p.toString()}`
  })()

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Step 2 of 3"
        title="Target"
        subtitle="Choose where your Power BI semantic model lands."
        action={
          <div className="flex items-center gap-2">
            <a
              href={`/${window.location.search}`}
              className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
            >
              ← Back
            </a>
            <a
              href={nextHref}
              className={[
                'inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition',
                canProceed
                  ? 'bg-databricks-red text-white shadow-sm hover:bg-databricks-red/90'
                  : 'pointer-events-none bg-slate-200 text-slate-500',
              ].join(' ')}
            >
              Next: preview →
            </a>
          </div>
        }
      />

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-card">
        <SectionHeader title="Delivery format" />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {DELIVERY_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              onClick={() => setKind(opt.key)}
              className={[
                'rounded-lg border p-4 text-left transition',
                kind === opt.key
                  ? 'border-databricks-red bg-databricks-red/5 ring-2 ring-databricks-red/30'
                  : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-card',
              ].join(' ')}
            >
              <div className="flex items-start gap-3">
                {opt.key === 'xmla' && <PowerBiMark className="h-6 w-6 shrink-0" />}
                {opt.key !== 'xmla' && (
                  <div className="grid h-6 w-6 shrink-0 place-items-center rounded bg-slate-100 text-[10px] font-bold text-slate-600">
                    {opt.key === 'pbip' ? 'P' : 'T'}
                  </div>
                )}
                <div>
                  <div className="text-sm font-medium text-databricks-ink">{opt.label}</div>
                  <div className="mt-0.5 text-xs text-slate-500">{opt.hint}</div>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {kind === 'xmla' ? (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-card">
          <SectionHeader
            title="Power BI workspace"
            subtitle="Published via the Fabric service principal"
          />

          <div className="space-y-3">
            <Field
              label="Power BI workspace"
              hint="Workspaces the App's Fabric service principal can publish to (Premium/Fabric capacity). If the list is empty, the service principal isn't configured yet or doesn't have Contributor access — see the deployment runbook."
            >
              {workspaces.isLoading && (
                <div className="text-sm text-slate-500">Loading workspaces…</div>
              )}
              {workspaces.error && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  {(() => {
                    // Prefer the backend's structured envelope so the actual
                    // cause (e.g. an expired SP secret — AADSTS7000222) reaches
                    // the user, not a one-size-fits-all banner. Fall back to the
                    // generic guidance for non-envelope errors (network, etc.).
                    const envelope =
                      workspaces.error instanceof ApiClientError
                        ? workspaces.error.envelope
                        : null
                    return (
                      <>
                        <p className="font-medium">
                          {envelope?.message ??
                            "Couldn't list Fabric workspaces. Confirm the App has Fabric SP credentials configured and the SP has at least Contributor on your target workspaces (tenant XMLA write must also be enabled)."}
                        </p>
                        {envelope?.suggestion && (
                          <p className="mt-1 text-amber-700">{envelope.suggestion}</p>
                        )}
                      </>
                    )
                  })()}
                </div>
              )}
              {!workspaces.isLoading && !workspaces.error && (
                <select
                  value={workspace}
                  onChange={(e) => setWorkspace(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-databricks-red focus:outline-none focus:ring-2 focus:ring-databricks-red/20"
                >
                  <option value="">— pick a workspace —</option>
                  {(workspaces.data ?? []).map((w) => (
                    // value is the workspace GUID — that's what the PBI
                    // REST import endpoint takes; the label still shows
                    // the human-readable workspace name.
                    <option key={w.id} value={w.id}>
                      {w.name}
                      {w.is_dedicated_capacity ? ' · Premium/Fabric' : ' · Pro (no XMLA write)'}
                    </option>
                  ))}
                </select>
              )}
            </Field>

            <Field
              label="Model name"
              hint="Name of the semantic model to publish — type a new one, or an existing model's name to update it."
            >
              <input
                type="text"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="New model name"
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-databricks-red focus:outline-none focus:ring-2 focus:ring-databricks-red/20"
              />
            </Field>

            <label className="flex cursor-pointer items-start gap-3 rounded-md bg-slate-50 px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={xmlaMerge === 'true'}
                onChange={(e) => setXmlaMerge(String(e.target.checked))}
                className="mt-0.5 h-4 w-4 accent-databricks-red"
              />
              <div>
                <div className="font-medium text-databricks-ink">Merge into existing model</div>
                <div className="text-xs text-slate-500">
                  Preserve any DAX measures the user authored directly in PBI.
                </div>
              </div>
            </label>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-card">
          <SectionHeader title="PBIP output folder" />
          <div className="space-y-3">
            <Field label="Model name">
              <input
                type="text"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-databricks-red focus:outline-none focus:ring-2 focus:ring-databricks-red/20"
              />
              <div className="mt-1 text-xs text-slate-500">
                The PBIP is built inside the App container — you'll get a ZIP
                download after Apply.
              </div>
            </Field>
          </div>
        </div>
      )}
    </div>
  )
}


export function SectionHeader(props: { title: string; subtitle?: string }): JSX.Element {
  return (
    <div className="mb-4">
      <div className="text-sm font-semibold text-databricks-ink">{props.title}</div>
      {props.subtitle && (
        <div className="text-xs text-slate-500">{props.subtitle}</div>
      )}
    </div>
  )
}


export function Field(props: {
  label: string
  hint?: string
  children: React.ReactNode
}): JSX.Element {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-600">
        {props.label}
      </label>
      {props.children}
      {props.hint && <div className="mt-1 text-xs text-slate-500">{props.hint}</div>}
    </div>
  )
}
