"""Pure, side-effect-free financial calculations.

These functions contain zero DB/ORM code on purpose: they are the part of
the app most likely to be wrong if written casually, so they are isolated
and unit-tested directly against the PRD's worked examples and acceptance
tests (Sections 7, 10, 18, 45, 46).
"""
import math


def calculate_match_player_fee(total_match_expense: int, num_players: int) -> int:
    """Section 7: Player Fee = CEILING(Total Match Expense / Number of Players)."""
    if num_players <= 0:
        raise ValueError("num_players must be greater than zero")
    return math.ceil(total_match_expense / num_players)


def calculate_total_fee_obligations(player_fee: int, num_players: int) -> int:
    return player_fee * num_players


def calculate_match_surplus(total_actual_collections: int, total_fee_obligations: int) -> int:
    """Section 10: Match Surplus = MAX(0, Actual Collections - Fee Obligations)."""
    return max(0, total_actual_collections - total_fee_obligations)


def calculate_fees_settled(total_actual_collections: int, total_fee_obligations: int) -> int:
    """Amount of the obligation actually covered by collections (capped at the obligation)."""
    return min(total_actual_collections, total_fee_obligations)


def calculate_outstanding_fees(total_actual_collections: int, total_fee_obligations: int) -> int:
    return max(0, total_fee_obligations - total_actual_collections)


def allocate_expense(expense_amount: int, player_ids_in_order: list) -> dict:
    """Section 18: exact whole-rupee allocation.

    Base Share = FLOOR(E / N); remainder distributed ₹1 at a time, in the
    exact order players were selected, until the remainder is exhausted.
    Returns {player_id: share_amount}. SUM(shares) always equals expense_amount.
    """
    n = len(player_ids_in_order)
    if n <= 0:
        raise ValueError("must allocate to at least one player")
    base_share = expense_amount // n
    remainder = expense_amount - (base_share * n)

    shares = {}
    for i, player_id in enumerate(player_ids_in_order):
        shares[player_id] = base_share + (1 if i < remainder else 0)

    assert sum(shares.values()) == expense_amount, "allocation must sum exactly to expense amount"
    return shares
