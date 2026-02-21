import { DevPanel } from '@/components/DevPanel'

export default function DevPage() {
  return (
    <div>
      <div className="border-b border-border px-8 py-4 flex items-center gap-3">
        <h1 className="text-lg font-semibold">Developer Panel</h1>
        <span className="text-xs bg-yellow-500/20 text-yellow-400 px-2 py-1 rounded border border-yellow-500/30">
          ⚠ Dev Mode Only
        </span>
      </div>
      <DevPanel />
    </div>
  )
}
