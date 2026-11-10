# erc6909-token-sim

ERC-6909 minimal multi-token standard simulator in pure Python (zero
dependencies). One contract, many token ids, each with its own supply and
balances — the minimalist alternative to ERC-1155: no metadata URI, no
safe-transfer receiver hook, just per-id balances, per-id allowances, and
per-owner operator approvals.

## What it models

| Feature | Function |
|---|---|
| Mint / burn | `mint(to, id, amount)`, `burn(from, id, amount)` |
| Own transfer | `transfer(to, id, amount)` |
| Third-party transfer | `transfer_from(from, to, id, amount)` |
| Per-id allowance | `approve(spender, id, amount)`, `allowance(owner, spender, id)` |
| Operator (all ids) | `set_operator(spender, approved)`, `is_operator(owner, spender)` |
| Views | `balance_of(owner, id)`, `total_supply(id)`, `holders_of(id)` |

Authorization for `transfer_from` / `burn` by someone other than the owner:
the caller must be the owner, an operator for the owner, or hold a
sufficient per-id allowance — allowances are spent (decreased) on use,
operators bypass them. Every state change is appended to `token.events`
(`Transfer` / `Approval` / `OperatorSet` audit log).

## Usage

```python
from erc6909 import ERC6909Token

t = ERC6909Token()
t.mint("alice", 1, 100)          # id 1: fungible points
t.mint("alice", 2, 1)            # id 2: a unique badge

with t.as_caller("alice"):
    t.set_operator("marketplace", True)   # operator: any id, any amount
    t.approve("bob", 1, 25)              # allowance: only id 1, up to 25

with t.as_caller("marketplace"):
    t.transfer_from("alice", "carol", 2, 1)  # operator moves the badge

with t.as_caller("bob"):
    t.transfer_from("alice", "dave", 1, 25)  # allowance spent, now 0

t.balance_of("dave", 1)   # 25
t.holders_of(1)           # ['alice', 'dave']
```

## Run

```bash
python3 erc6909.py --demo   # short demo
python3 erc6909.py --test   # doctests
```

All doctests pass.
