import math
from decimal import Decimal


def per_party_share(amount: Decimal, num_parties: int) -> Decimal:
    """Section 9: each share = CEILING((amount / n) / 5) * 5."""
    if num_parties <= 0:
        raise ValueError("num_parties must be positive")
    raw = Decimal(amount) / num_parties
    return Decimal(math.ceil(raw / 5)) * 5


def allocation_surplus(per_share: Decimal, num_parties: int, amount: Decimal) -> Decimal:
    return (per_share * num_parties) - Decimal(amount)
