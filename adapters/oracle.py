import datetime
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Optional


class PriceOracle(ABC):
    @abstractmethod
    async def get_official_close(self, date: datetime.date) -> Optional[Decimal]:
        """Get the official market close price for a given date"""
        pass


class MockOracle(PriceOracle):
    def __init__(self, fixture_data: Optional[Dict[datetime.date, Decimal]] = None):
        self.fixture_data = fixture_data or {}
        # Add some default test data
        if not self.fixture_data:
            base_date = datetime.date(2025, 9, 1)
            base_price = Decimal("100.00")
            
            # Generate 30 days of mock data with small variations
            for i in range(30):
                date = base_date + datetime.timedelta(days=i)
                # Simulate price movement: slight upward trend with some volatility
                variation = Decimal(str((i % 7 - 3) * 0.5))  # -1.5 to +1.5
                price = base_price + Decimal(str(i * 0.1)) + variation
                self.fixture_data[date] = price

    async def get_official_close(self, date: datetime.date) -> Optional[Decimal]:
        """Mock oracle - returns fixture data for the given date"""
        return self.fixture_data.get(date)

    def set_price(self, date: datetime.date, price: Decimal):
        """Helper method to set price for testing"""
        self.fixture_data[date] = price

    def simulate_failure(self, date: datetime.date):
        """Helper method to simulate oracle failure for testing"""
        if date in self.fixture_data:
            del self.fixture_data[date]