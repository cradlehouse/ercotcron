'use client'

// Editable price levels. A plain GET form: the levels belong in the URL, so
// submitting navigates and every server component re-reads them. Client-side
// only to show the value moving as the slider drags.

import { useState } from 'react'

import { DEFAULT_THRESHOLDS, FIELDS, isDefault, type Thresholds } from '@/lib/thresholds'

export function ThresholdBar({
  thresholds,
  hidden,
}: {
  thresholds: Thresholds
  /** Other query state to preserve across the form submit. */
  hidden: Record<string, string>
}) {
  const [draft, setDraft] = useState(thresholds)
  const dirty = FIELDS.some((f) => draft[f.key] !== thresholds[f.key])

  return (
    <form method="get" action="/" className="border-b border-line bg-panel-2/40 px-4 py-3">
      {Object.entries(hidden).map(([k, v]) => (
        <input key={k} type="hidden" name={k} value={v} />
      ))}
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        {FIELDS.map((field) => {
          const value = draft[field.key]
          const trade = field.key === 'chargeBelow' || field.key === 'dischargeAbove'
          return (
            <label key={field.key} className="flex flex-col gap-1">
              <span className="flex items-baseline gap-1.5 text-[11px]">
                <span className={trade ? 'text-zinc-300' : 'text-zinc-500'}>{field.label}</span>
                <span className="tnum font-semibold text-zinc-200">${value}</span>
              </span>
              <span className="flex items-center gap-2">
                <input
                  type="range"
                  min={0}
                  max={field.max}
                  step={1}
                  value={value}
                  onChange={(e) =>
                    setDraft({ ...draft, [field.key]: Number(e.target.value) })
                  }
                  className="h-1 w-28 accent-emerald-400"
                  aria-label={field.label}
                />
                <input
                  type="number"
                  name={field.urlKey}
                  value={value}
                  onChange={(e) =>
                    setDraft({ ...draft, [field.key]: Number(e.target.value) })
                  }
                  className="tnum w-20 rounded border border-line bg-panel px-1.5 py-0.5 text-[11px] text-zinc-300"
                />
              </span>
              <span className="text-[10px] text-zinc-600">{field.hint}</span>
            </label>
          )
        })}

        <div className="flex items-center gap-2">
          <button
            type="submit"
            className={`rounded border px-3 py-1 text-[11px] transition-colors ${
              dirty
                ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
                : 'border-line text-zinc-500'
            }`}
          >
            {dirty ? 'apply levels' : 'levels applied'}
          </button>
          {!isDefault(thresholds) && (
            <button
              type="submit"
              name="reset"
              value="1"
              onClick={() => setDraft(DEFAULT_THRESHOLDS)}
              className="text-[11px] text-zinc-600 underline-offset-2 hover:text-zinc-300 hover:underline"
            >
              reset
            </button>
          )}
        </div>
      </div>
    </form>
  )
}
