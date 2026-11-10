"""ERC-6909 minimal multi-token standard simulator (pure Python).

ERC-6909 is the minimalist alternative to ERC-1155: one contract holds many
token ids, each with its own supply and balances, plus per-id allowances and
per-id operator approvals. There is no URI/metadata hook and no safe-transfer
receiver check -- that is the whole point: less surface, less gas.

Modelled here as an in-memory ledger:

* ``mint(to, id, amount)`` / ``burn(from, id, amount)`` -- supply changes.
* ``transfer(to, id, amount)`` -- move the caller's own tokens.
* ``transfer_from(from, to, id, amount)`` -- move someone else's tokens,
  allowed when the caller is an operator for ``from`` OR holds a sufficient
  per-id allowance from ``from``. Operators bypass allowances; allowances are
  spent (decreased) on use.
* ``approve(spender, id, amount)`` / ``allowance(owner, spender, id)`` --
  per-id allowances, ERC-20 style.
* ``set_operator(spender, approved)`` / ``is_operator(owner, spender)`` --
  per-owner operator approvals covering every id.
* ``balance_of(owner, id)`` / ``total_supply(id)`` -- read-only views.

Every state change appends a dict to ``events`` (a Transfer / Approval /
OperatorSet audit log, mirroring the ERC-6909 events).

Run the doctests with ``python3 -m doctest erc6909.py -v`` or
``python3 erc6909.py --test``. Run the demo with ``python3 erc6909.py --demo``.

>>> t = ERC6909Token()
>>> t.mint("alice", 1, 100)
>>> t.balance_of("alice", 1)
100
>>> t.total_supply(1)
100
>>> t.transfer("bob", 1, 40)  # caller is the deployer by default
Traceback (most recent call last):
...
ValueError: insufficient balance: deployer holds 0 of id 1
>>> t.mint("deployer", 1, 50)
>>> t.transfer("bob", 1, 40)
>>> t.balance_of("bob", 1)
40
>>> t.balance_of("deployer", 1)
10
"""

from __future__ import annotations

import argparse
import sys

__all__ = ["ERC6909Token"]


class ERC6909Token:
    """Minimal in-memory ERC-6909 multi-token ledger.

    ``caller`` is the address acting in the next call; use ``as_caller``
    (context manager) or pass ``caller=`` explicitly to switch actors.
    """

    def __init__(self, deployer: str = "deployer") -> None:
        self._balances: dict[tuple[str, int], int] = {}
        self._supply: dict[int, int] = {}
        self._allowances: dict[tuple[str, str, int], int] = {}
        self._operators: dict[tuple[str, str], bool] = {}
        self.events: list[dict] = []
        self.caller = deployer

    # -- context helper -------------------------------------------------
    class _AsCaller:
        def __init__(self, token: "ERC6909Token", caller: str) -> None:
            self._token = token
            self._caller = caller
            self._prev = token.caller

        def __enter__(self) -> "ERC6909Token":
            self._token.caller = self._caller
            return self._token

        def __exit__(self, *exc: object) -> bool:
            self._token.caller = self._prev
            return False

    def as_caller(self, caller: str) -> "_AsCaller":
        """Use as ``with token.as_caller("alice"): ...`` to act as ``caller``."""
        return self._AsCaller(self, caller)

    # -- read-only views ------------------------------------------------
    def balance_of(self, owner: str, token_id: int) -> int:
        """Balance of ``owner`` for ``token_id`` (0 when never held).

        >>> t = ERC6909Token()
        >>> t.balance_of("nobody", 7)
        0
        """
        return self._balances.get((owner, token_id), 0)

    def total_supply(self, token_id: int) -> int:
        """Total minted-minus-burned supply of ``token_id``.

        >>> t = ERC6909Token()
        >>> t.mint("alice", 2, 5)
        >>> t.total_supply(2)
        5
        """
        return self._supply.get(token_id, 0)

    def allowance(self, owner: str, spender: str, token_id: int) -> int:
        """Per-id allowance ``owner`` granted to ``spender``.

        >>> t = ERC6909Token()
        >>> t.allowance("alice", "bob", 1)
        0
        """
        return self._allowances.get((owner, spender, token_id), 0)

    def is_operator(self, owner: str, spender: str) -> bool:
        """Whether ``spender`` is an operator for ``owner`` (all ids).

        >>> t = ERC6909Token()
        >>> t.is_operator("alice", "bob")
        False
        """
        return self._operators.get((owner, spender), False)

    # -- approvals ------------------------------------------------------
    def approve(self, spender: str, token_id: int, amount: int) -> None:
        """Set ``spender``'s allowance for ``token_id`` to ``amount``.

        >>> t = ERC6909Token()
        >>> t.mint("alice", 1, 100)
        >>> with t.as_caller("alice"):
        ...     t.approve("bob", 1, 30)
        >>> t.allowance("alice", "bob", 1)
        30
        """
        if amount < 0:
            raise ValueError("allowance cannot be negative")
        self._allowances[(self.caller, spender, token_id)] = amount
        self.events.append(
            {"event": "Approval", "owner": self.caller,
             "spender": spender, "id": token_id, "amount": amount}
        )

    def set_operator(self, spender: str, approved: bool) -> None:
        """Approve (or revoke) ``spender`` as operator for the caller.

        >>> t = ERC6909Token()
        >>> with t.as_caller("alice"):
        ...     t.set_operator("bob", True)
        >>> t.is_operator("alice", "bob")
        True
        >>> with t.as_caller("alice"):
        ...     t.set_operator("bob", False)
        >>> t.is_operator("alice", "bob")
        False
        """
        self._operators[(self.caller, spender)] = approved
        self.events.append(
            {"event": "OperatorSet", "owner": self.caller,
             "spender": spender, "approved": approved}
        )

    # -- supply ---------------------------------------------------------
    def mint(self, to: str, token_id: int, amount: int) -> None:
        """Create ``amount`` of ``token_id`` for ``to`` (no access control here).

        >>> t = ERC6909Token()
        >>> t.mint("alice", 1, 10)
        >>> t.mint("alice", 1, 5)
        >>> t.balance_of("alice", 1)
        15
        >>> t.mint("alice", 1, 0)
        Traceback (most recent call last):
        ...
        ValueError: amount must be positive
        """
        if amount <= 0:
            raise ValueError("amount must be positive")
        self._balances[(to, token_id)] = self.balance_of(to, token_id) + amount
        self._supply[token_id] = self.total_supply(token_id) + amount
        self.events.append(
            {"event": "Transfer", "caller": self.caller, "from": None,
             "to": to, "id": token_id, "amount": amount}
        )

    def burn(self, from_: str, token_id: int, amount: int) -> None:
        """Destroy ``amount`` of ``token_id`` held by ``from_``.

        The caller must be ``from_`` or an operator / allowance holder for it.

        >>> t = ERC6909Token()
        >>> t.mint("alice", 1, 10)
        >>> with t.as_caller("alice"):
        ...     t.burn("alice", 1, 4)
        >>> t.balance_of("alice", 1)
        6
        >>> t.total_supply(1)
        6
        """
        self._spend_if_needed(from_, token_id, amount)
        if self.balance_of(from_, token_id) < amount:
            raise ValueError(
                f"insufficient balance: {from_} holds "
                f"{self.balance_of(from_, token_id)} of id {token_id}"
            )
        self._balances[(from_, token_id)] = self.balance_of(from_, token_id) - amount
        self._supply[token_id] = self.total_supply(token_id) - amount
        self.events.append(
            {"event": "Transfer", "caller": self.caller, "from": from_,
             "to": None, "id": token_id, "amount": amount}
        )

    # -- transfers ------------------------------------------------------
    def transfer(self, to: str, token_id: int, amount: int) -> None:
        """Move ``amount`` of ``token_id`` from the caller to ``to``.

        >>> t = ERC6909Token()
        >>> t.mint("alice", 1, 50)
        >>> with t.as_caller("alice"):
        ...     t.transfer("bob", 1, 20)
        >>> t.balance_of("bob", 1)
        20
        >>> t.balance_of("alice", 1)
        30
        """
        self.transfer_from(self.caller, to, token_id, amount)

    def transfer_from(self, from_: str, to: str, token_id: int, amount: int) -> None:
        """Move ``amount`` of ``token_id`` from ``from_`` to ``to``.

        The caller must be ``from_`` itself, an operator for ``from_``, or
        hold a sufficient per-id allowance (which is then spent).

        >>> t = ERC6909Token()
        >>> t.mint("alice", 1, 100)
        >>> with t.as_caller("alice"):
        ...     t.approve("bob", 1, 25)
        >>> with t.as_caller("bob"):
        ...     t.transfer_from("alice", "carol", 1, 25)
        >>> t.balance_of("carol", 1)
        25
        >>> t.allowance("alice", "bob", 1)
        0
        >>> with t.as_caller("bob"):
        ...     t.transfer_from("alice", "carol", 1, 1)
        Traceback (most recent call last):
        ...
        ValueError: insufficient allowance: bob may spend 0 of alice's id 1
        """
        if amount <= 0:
            raise ValueError("amount must be positive")
        self._spend_if_needed(from_, token_id, amount)
        if self.balance_of(from_, token_id) < amount:
            raise ValueError(
                f"insufficient balance: {from_} holds "
                f"{self.balance_of(from_, token_id)} of id {token_id}"
            )
        self._balances[(from_, token_id)] = self.balance_of(from_, token_id) - amount
        self._balances[(to, token_id)] = self.balance_of(to, token_id) + amount
        self.events.append(
            {"event": "Transfer", "caller": self.caller, "from": from_,
             "to": to, "id": token_id, "amount": amount}
        )

    def _spend_if_needed(self, from_: str, token_id: int, amount: int) -> None:
        """Enforce authorization for third-party moves; spend allowance."""
        if self.caller == from_:
            return
        if self.is_operator(from_, self.caller):
            return
        allowed = self.allowance(from_, self.caller, token_id)
        if allowed < amount:
            raise ValueError(
                f"insufficient allowance: {self.caller} may spend {allowed} "
                f"of {from_}'s id {token_id}"
            )
        self._allowances[(from_, self.caller, token_id)] = allowed - amount

    # -- convenience ----------------------------------------------------
    def holders_of(self, token_id: int) -> list[str]:
        """Addresses holding a nonzero balance of ``token_id``.

        >>> t = ERC6909Token()
        >>> t.mint("alice", 1, 10)
        >>> t.mint("bob", 1, 5)
        >>> t.mint("carol", 2, 7)
        >>> t.holders_of(1)
        ['alice', 'bob']
        >>> t.holders_of(2)
        ['carol']
        """
        return sorted(
            owner for (owner, tid), bal in self._balances.items()
            if tid == token_id and bal > 0
        )


def demo() -> None:
    """Two ids, one operator, one allowance: the whole standard in 20 lines."""
    t = ERC6909Token()
    t.mint("alice", 1, 100)          # id 1: fungible points
    t.mint("alice", 2, 1)            # id 2: a unique badge
    with t.as_caller("alice"):
        t.set_operator("marketplace", True)
        t.approve("bob", 1, 25)
    with t.as_caller("marketplace"):
        t.transfer_from("alice", "carol", 2, 1)   # operator moves the badge
    with t.as_caller("bob"):
        t.transfer_from("alice", "dave", 1, 25)   # allowance moves points
    print(f"id 1 supply: {t.total_supply(1)}, holders: {t.holders_of(1)}")
    print(f"id 2 owner:  {t.holders_of(2)}")
    print(f"bob's remaining allowance: {t.allowance('alice', 'bob', 1)}")
    print(f"events logged: {len(t.events)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="run the demo")
    parser.add_argument("--test", action="store_true", help="run the doctests")
    args = parser.parse_args(argv)
    if args.test:
        import doctest

        result = doctest.testmod(verbose=False)
        print(f"doctests: {result.attempted} attempted, "
              f"{result.failed} failed")
        return 1 if result.failed else 0
    demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
