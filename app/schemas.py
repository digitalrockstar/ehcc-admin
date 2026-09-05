from datetime import date
from typing import Optional, List
from pydantic import BaseModel


class TeamCreate(BaseModel):
    name: str
    starting_balance: float = 0


class PlayerCreate(BaseModel):
    name: str
    contact_number: Optional[str] = None


class MatchCreate(BaseModel):
    match_date: date
    ground_fees: float
    additional_amount: float = 0
    notes: Optional[str] = None
    player_ids: List[int]


class MatchFeePayment(BaseModel):
    amount_paid: Optional[float] = None
    payment_date: Optional[date] = None


class TeamExpenseCreate(BaseModel):
    date: date
    category: str
    amount: float
    payment_source: str  # "account" | "player"
    paid_by_player_id: Optional[int] = None


class AllocationCreate(BaseModel):
    player_ids_in_order: List[int]


class AdHocIncomeCreate(BaseModel):
    date: date
    income_type: str
    amount: float
    match_id: Optional[int] = None
    notes: Optional[str] = None
