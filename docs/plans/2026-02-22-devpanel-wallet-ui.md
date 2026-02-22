# DevPanel Wallet UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dev worker wallet, auto-register both wallets on mount, show wallet cards with USDC balance + refresh, and replace the deadline datetime picker with a duration input.

**Architecture:** All changes are confined to the frontend. A new `fetchUsdcBalance` utility calls the Base Sepolia RPC directly. `DevPanel` uses `useEffect` + `localStorage` to auto-register the two preset wallets on first load, persisting their IDs. Deadline is stored as an offset (number + unit) and converted to ISO at submit time.

**Tech Stack:** Next.js, React, viem, Vitest, Tailwind / shadcn/ui

---

### Task 1: Generate worker wallet + update env vars

**Files:**
- Modify: `frontend/.env.local`

**Step 1: Generate a new worker wallet**

Run in project root:
```bash
cd frontend && node -e "
const { generatePrivateKey, privateKeyToAccount } = require('viem/accounts');
const key = generatePrivateKey();
const account = privateKeyToAccount(key);
console.log('PRIVATE_KEY=' + key);
console.log('ADDRESS=' + account.address);
"
```

**Step 2: Update `frontend/.env.local`**

Replace the existing content with:
```
NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY=0xf9ef800d689faa805c1f758891d0f3434e0bd6bc1394da1381563731e50ea997
NEXT_PUBLIC_DEV_WORKER_WALLET_KEY=<new key from step 1>
NEXT_PUBLIC_PLATFORM_WALLET=0x32dD7E61080e1c872e84EFcd2C144b9b7dA83f8F
```

(Keep existing publisher key, only rename it.)

**Step 3: Commit**
```bash
# .env.local is git-ignored — no commit needed for env file
# Commit only if any tracked file was changed in this task
```

---

### Task 2: Add `fetchUsdcBalance` utility + test

**Files:**
- Modify: `frontend/lib/utils.ts` (add the function)
- Modify: `frontend/lib/utils.test.ts` (add tests)

**Step 1: Write the failing test** in `frontend/lib/utils.test.ts`

Add at the end of the file:
```ts
describe('fetchUsdcBalance', () => {
  it('returns a numeric balance string', async () => {
    // This test calls the real RPC — skip in CI if needed
    const { fetchUsdcBalance } = await import('./utils')
    const balance = await fetchUsdcBalance('0x9F851CaeeaD0CDfEb12Cb498993D7559fFE11e20')
    // address has 20 USDC — just check it's a valid number string
    expect(parseFloat(balance)).toBeGreaterThanOrEqual(0)
  })
})
```

**Step 2: Run test to verify it fails**
```bash
cd frontend && npx vitest run lib/utils.test.ts
```
Expected: FAIL — `fetchUsdcBalance is not a function`

**Step 3: Implement `fetchUsdcBalance` in `frontend/lib/utils.ts`**

Add at the end of the existing file:
```ts
const BASE_SEPOLIA_RPC = 'https://sepolia.base.org'
const USDC_CONTRACT = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'

export async function fetchUsdcBalance(address: string): Promise<string> {
  // balanceOf(address) selector = 0x70a08231
  const data = '0x70a08231' + address.replace('0x', '').toLowerCase().padStart(64, '0')
  const resp = await fetch(BASE_SEPOLIA_RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', method: 'eth_call',
      params: [{ to: USDC_CONTRACT, data }, 'latest'],
      id: 1,
    }),
  })
  const json = await resp.json()
  const raw = BigInt(json.result ?? '0x0')
  return (Number(raw) / 1e6).toFixed(2)
}
```

**Step 4: Run test to verify it passes**
```bash
cd frontend && npx vitest run lib/utils.test.ts
```
Expected: all PASS

**Step 5: Commit**
```bash
git add frontend/lib/utils.ts frontend/lib/utils.test.ts
git commit -m "feat: add fetchUsdcBalance utility for Base Sepolia USDC"
```

---

### Task 3: Refactor DevPanel — wallet cards + auto-register

**Files:**
- Modify: `frontend/components/DevPanel.tsx`

This task replaces the entire component. Key behaviours:

1. **Env constants renamed:**
   - `DEV_WALLET_KEY` → `DEV_PUBLISHER_WALLET_KEY` (from `NEXT_PUBLIC_DEV_PUBLISHER_WALLET_KEY`)
   - New: `DEV_WORKER_WALLET_KEY` (from `NEXT_PUBLIC_DEV_WORKER_WALLET_KEY`)

2. **Auto-register on mount:**
   ```ts
   useEffect(() => {
     autoRegister()
   }, [])

   async function autoRegister() {
     // Publisher
     let pubId = localStorage.getItem('devPublisherId')
     if (!pubId && DEV_PUBLISHER_WALLET_KEY) {
       const user = await registerUser({
         nickname: 'dev-publisher',
         wallet: publisherAddress,
         role: 'publisher',
       })
       pubId = user.id
       localStorage.setItem('devPublisherId', pubId)
     }
     if (pubId) setPublisherId(pubId)

     // Worker
     let wrkId = localStorage.getItem('devWorkerId')
     if (!wrkId && DEV_WORKER_WALLET_KEY) {
       const user = await registerUser({
         nickname: 'dev-worker',
         wallet: workerAddress,
         role: 'worker',
       })
       wrkId = user.id
       localStorage.setItem('devWorkerId', wrkId)
     }
     if (wrkId) setWorkerId(wrkId)
   }
   ```

3. **WalletCard component** (defined inside the file, not exported):
   ```tsx
   function WalletCard({
     label, address, id, balance, onRefresh, refreshing, showFundLink,
   }: {
     label: string
     address: string | null
     id: string
     balance: string
     onRefresh: () => void
     refreshing: boolean
     showFundLink?: boolean
   }) {
     return (
       <div className="relative mb-4 p-3 bg-zinc-900 border border-zinc-700 rounded text-sm">
         <button
           onClick={onRefresh}
           disabled={refreshing}
           className="absolute top-2 right-2 text-muted-foreground hover:text-white disabled:opacity-40"
           title="Refresh balance"
         >
           ↻
         </button>
         <p className="text-muted-foreground mb-1">{label}</p>
         <p className="font-mono text-xs break-all">{address ?? '—'}</p>
         <p className="text-xs text-muted-foreground mt-1">
           Balance: <span className="text-white">{balance} USDC</span>
         </p>
         {id && (
           <p className="text-xs text-muted-foreground mt-0.5">
             ID: <span className="font-mono text-white break-all">{id}</span>
           </p>
         )}
         {showFundLink && (
           <a
             href="https://faucet.circle.com/"
             target="_blank"
             rel="noopener noreferrer"
             className="text-blue-400 text-xs hover:underline mt-1 inline-block"
           >
             Fund with testnet USDC
           </a>
         )}
       </div>
     )
   }
   ```

4. **Balance state + refresh:**
   ```ts
   const [pubBalance, setPubBalance] = useState('...')
   const [wrkBalance, setWrkBalance] = useState('...')
   const [pubRefreshing, setPubRefreshing] = useState(false)
   const [wrkRefreshing, setWrkRefreshing] = useState(false)

   async function refreshPubBalance() {
     if (!publisherAddress) return
     setPubRefreshing(true)
     setPubBalance(await fetchUsdcBalance(publisherAddress))
     setPubRefreshing(false)
   }

   async function refreshWrkBalance() {
     if (!workerAddress) return
     setWrkRefreshing(true)
     setWrkBalance(await fetchUsdcBalance(workerAddress))
     setWrkRefreshing(false)
   }

   // Fetch on mount
   useEffect(() => { refreshPubBalance() }, [publisherAddress])
   useEffect(() => { refreshWrkBalance() }, [workerAddress])
   ```

5. **Layout:** Keep 3-column grid. Publisher card goes above Publish Task form. Worker card goes above Submit Result form.

**Step 1: Rewrite `DevPanel.tsx`** incorporating all the above.

**Step 2: Verify the frontend compiles**
```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: no TypeScript errors

**Step 3: Commit**
```bash
git add frontend/components/DevPanel.tsx
git commit -m "feat: add dev wallet cards with auto-register and USDC balance"
```

---

### Task 4: Deadline duration input

**Files:**
- Modify: `frontend/components/DevPanel.tsx`

Replace the `datetime-local` input with a duration picker.

**Step 1: Replace deadline state and input**

Change state:
```ts
// Remove: const [deadline, setDeadline] = useState('')
const [deadlineDuration, setDeadlineDuration] = useState('1')
const [deadlineUnit, setDeadlineUnit] = useState<'hours' | 'days'>('days')
```

Quick-select presets helper:
```ts
const PRESETS = [
  { label: '1h', value: '1', unit: 'hours' },
  { label: '6h', value: '6', unit: 'hours' },
  { label: '12h', value: '12', unit: 'hours' },
  { label: '1d', value: '1', unit: 'days' },
  { label: '3d', value: '3', unit: 'days' },
  { label: '7d', value: '7', unit: 'days' },
] as const
```

Deadline ISO computation (used in `handlePublish`):
```ts
function computeDeadlineISO(): string {
  const ms = parseFloat(deadlineDuration) * (deadlineUnit === 'days' ? 86_400_000 : 3_600_000)
  return new Date(Date.now() + ms).toISOString()
}
// Replace: deadline: new Date(deadline).toISOString()
// With:    deadline: computeDeadlineISO()
```

Deadline JSX (replace the datetime-local field):
```tsx
<div className="flex flex-col gap-1.5">
  <Label>Deadline</Label>
  <div className="flex gap-2">
    <Input
      type="number"
      min="1"
      value={deadlineDuration}
      onChange={(e) => setDeadlineDuration(e.target.value)}
      className="w-20"
    />
    <Select
      value={deadlineUnit}
      onValueChange={(v) => setDeadlineUnit(v as typeof deadlineUnit)}
    >
      <SelectTrigger className="w-28">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="hours">Hours</SelectItem>
        <SelectItem value="days">Days</SelectItem>
      </SelectContent>
    </Select>
  </div>
  <div className="flex gap-1 flex-wrap">
    {PRESETS.map((p) => (
      <button
        key={p.label}
        type="button"
        onClick={() => { setDeadlineDuration(p.value); setDeadlineUnit(p.unit) }}
        className="text-xs px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-muted-foreground hover:text-white"
      >
        {p.label}
      </button>
    ))}
  </div>
</div>
```

Also remove the `required` from the deadline section (duration always has a value) and remove `deadline` from the form reset after successful publish.

**Step 2: Verify compiles**
```bash
cd frontend && npm run build 2>&1 | tail -20
```

**Step 3: Run all frontend tests**
```bash
cd frontend && npm test
```
Expected: 18 tests passing

**Step 4: Commit**
```bash
git add frontend/components/DevPanel.tsx
git commit -m "feat: replace deadline datetime picker with duration + unit selector"
```
