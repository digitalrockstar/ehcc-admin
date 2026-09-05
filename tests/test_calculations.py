import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.calculations import (
    calculate_match_player_fee,
    calculate_total_fee_obligations,
    calculate_match_surplus,
    calculate_fees_settled,
    calculate_outstanding_fees,
    allocate_expense,
)


def test_section7_example1_exact_division():
    fee = calculate_match_player_fee(4500, 10)
    assert fee == 450
    assert calculate_total_fee_obligations(fee, 10) == 4500


def test_section7_example2_rounded():
    fee = calculate_match_player_fee(5000, 12)
    assert fee == 417
    assert calculate_total_fee_obligations(fee, 12) == 5004


def test_section10_over_collection():
    assert calculate_match_surplus(5004, 5000) == 4
    assert calculate_fees_settled(5004, 5000) == 5000
    assert calculate_outstanding_fees(5004, 5000) == 0


def test_section10_under_collection():
    assert calculate_match_surplus(4998, 5000) == 0
    assert calculate_fees_settled(4998, 5000) == 4998
    assert calculate_outstanding_fees(4998, 5000) == 2


def test_section10_exact_collection():
    assert calculate_match_surplus(5000, 5000) == 0
    assert calculate_outstanding_fees(5000, 5000) == 0


def test_section10_rounding_difference_table():
    # obligations = 5004 (417 x 12)
    cases = [(5000, 4, 0), (5004, 0, 0), (5005, 0, 1), (5010, 0, 6)]
    for collected, outstanding, surplus in cases:
        assert calculate_outstanding_fees(collected, 5004) == outstanding
        assert calculate_match_surplus(collected, 5004) == surplus


def test_section18_allocation_500_across_3():
    shares = allocate_expense(500, ["p1", "p2", "p3"])
    assert shares == {"p1": 167, "p2": 167, "p3": 166}
    assert sum(shares.values()) == 500


def test_section18_allocation_470_across_6():
    shares = allocate_expense(470, ["p1", "p2", "p3", "p4", "p5", "p6"])
    assert shares == {"p1": 79, "p2": 79, "p3": 78, "p4": 78, "p5": 78, "p6": 78}
    assert sum(shares.values()) == 470


def test_section45_core_end_to_end_numbers():
    fee = calculate_match_player_fee(4500, 10)
    assert fee == 450
    assert calculate_total_fee_obligations(fee, 10) == 4500
    shares = allocate_expense(470, [f"p{i}" for i in range(5)])
    assert sum(shares.values()) == 470
    assert shares == {"p0": 94, "p1": 94, "p2": 94, "p3": 94, "p4": 94}


def test_section46_scenario1_exact():
    assert calculate_fees_settled(5004, 5004) == 5004
    assert calculate_outstanding_fees(5004, 5004) == 0
    assert calculate_match_surplus(5004, 5004) == 0


def test_section46_scenario2_under():
    assert calculate_fees_settled(5000, 5004) == 5000
    assert calculate_outstanding_fees(5000, 5004) == 4
    assert calculate_match_surplus(5000, 5004) == 0


def test_section46_scenario3_over():
    assert calculate_fees_settled(5010, 5004) == 5004
    assert calculate_outstanding_fees(5010, 5004) == 0
    assert calculate_match_surplus(5010, 5004) == 6


def test_section46_scenario4_multiple_values():
    assert calculate_match_surplus(5002, 5000) == 2
    assert calculate_match_surplus(5005, 5000) == 5
    assert calculate_outstanding_fees(4998, 5000) == 2
    assert calculate_match_surplus(4998, 5000) == 0
