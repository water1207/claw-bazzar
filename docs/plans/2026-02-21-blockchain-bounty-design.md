# Blockchain Bounty System Design

## Goal

Extend the Agent Market with user registration (nickname + wallet), bounty payments via x402 protocol (USDC on Base Sepolia), and automatic payout to winners (80% bounty, 20% platform fee) via web3.py.

## Architecture

```
Publisher                         Platform                          Worker
   │                                │                                 │
   ├─ POST /users ─────────────────►│ Register (nickname + wallet)    │
   │                                │                                 │
   ├─ POST /tasks (bounty=$5) ─────►│ HTTP 402 ──► x402 payment      │
   │  x402 USDC payment ──────────►│ Confirm ──► Task created (open) │
   │                                │                                 │
   │                                │◄──── POST /users ───────────────┤
   │                                │◄──── POST /submissions ─────────┤
   │                                │  Oracle scores ──► winner found │
   │                                │                                 │
   │                                │── web3.py USDC transfer ───────►│
   │                                │  (bounty × 80%)                 │
```

## Data Model Changes

### New: User Table

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| nickname | String | Unique |
| wallet | String | EVM address (0x...) |
| role | Enum | publisher / worker / both |
| created_at | DateTime | UTC |

### Modified: Task Table

New fields:

| Field | Type | Notes |
|-------|------|-------|
| publisher_id | String | FK → User.id |
| bounty | Float | USDC amount |
| payment_tx_hash | String (nullable) | x402 payment transaction hash |
| payout_status | Enum | pending / paid / failed |
| payout_tx_hash | String (nullable) | Payout transaction hash |
| payout_amount | Float (nullable) | Actual amount paid to winner |

### Modified: Submission Table

- `worker_id` changes from free text to FK → User.id

## API Changes

### New Endpoints

```
POST /users                              # Register user
GET  /users/{user_id}                    # Get user profile
POST /internal/tasks/{task_id}/payout    # Retry failed payout
```

### Modified Endpoints

```
POST /tasks                              # Now requires x402 payment (bounty field)
POST /tasks/{task_id}/submissions        # worker_id must be registered User.id
```

## x402 Integration (Bounty Collection)

- Library: `fastapi-x402`
- Network: `base-sepolia`
- Token: USDC
- Flow: `POST /tasks` returns 402 → client pays → facilitator settles → task created
- The `@pay()` decorator amount is dynamic based on the `bounty` field

## Payout Service (web3.py)

Triggered when a winner is determined (fastest_first threshold hit or quality_first deadline settlement).

Flow:
1. Calculate payout: `bounty × (1 - PLATFORM_FEE_RATE)`
2. Look up winner's wallet from User table
3. Sign and send USDC `transfer()` via web3.py
4. Wait for confirmation, record tx_hash
5. Update task `payout_status` to `paid`
6. On failure: set `payout_status` to `failed`, log error

### Environment Variables

```
PLATFORM_PRIVATE_KEY    # Platform wallet private key
PLATFORM_WALLET         # Platform wallet address
BASE_SEPOLIA_RPC_URL    # RPC endpoint (e.g. https://sepolia.base.org)
USDC_CONTRACT           # USDC contract address on Base Sepolia
PLATFORM_FEE_RATE       # Default 0.20 (20%)
```

## Settlement Logic Changes

### fastest_first

Existing: score >= threshold → close task, set winner.
New: after setting winner → call `payout_service.pay_winner(task_id)`.

### quality_first

Existing: scheduler finds expired tasks → pick highest score → close.
New: after closing → call `payout_service.pay_winner(task_id)`.

## Testing Strategy

- **User CRUD**: registration, uniqueness, validation
- **x402 flow**: mock fastapi-x402 middleware, verify task requires valid payment
- **Payout**: mock web3.py, verify amount = bounty × 0.80, tx_hash recorded, failure handling
- **Integration**: full lifecycle with mocked blockchain interactions
- No real blockchain calls in tests

## Dependencies

New:
- `fastapi-x402` — x402 protocol middleware
- `web3>=7.0` — Ethereum interaction
