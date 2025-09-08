import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import app
from domain.models import RoundStatus, User, Round, BetSide
from infra.db import AsyncSessionLocal
from domain.services import LedgerService, RoundScheduler
from adapters.oracle import MockOracle


@pytest.fixture
def client():
    """Create a test client"""
    return TestClient(app)


class TestAPIIntegration:
    def test_user_creation(self, client):
        """Test user creation endpoint"""
        response = client.post("/users", json={"email": "test@example.com"})
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert data["email"] == "test@example.com"
        
        # Test duplicate email
        response = client.post("/users", json={"email": "test@example.com"})
        assert response.status_code == 409
    
    def test_wallet_creation(self, client):
        """Test wallet creation endpoint"""
        # First create a user
        user_response = client.post("/users", json={"email": "test@example.com"})
        user_id = user_response.json()["id"]
        
        # Create wallet
        response = client.post("/wallets", json={"user_id": user_id})
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert data["user_id"] == user_id
        assert data["address"].startswith("0x")
        assert len(data["address"]) == 42
    
    def test_deposit_webhook(self, client):
        """Test deposit webhook endpoint"""
        # Create user
        user_response = client.post("/users", json={"email": "test@example.com"})
        user_id = user_response.json()["id"]
        
        # Simulate deposit
        response = client.post(
            "/simulate/deposit_webhook",
            json={"user_id": user_id, "amount_u": 1000000}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["user_id"] == user_id
        assert data["amount_u"] == 1000000
        assert data["type"] == "DEPOSIT"
        assert data["status"] == "CONFIRMED"
    
    def test_betting_flow(self, client):
        """Test complete betting flow"""
        # Create user
        user_response = client.post("/users", json={"email": "test@example.com"})
        user_id = user_response.json()["id"]
        
        # Deposit funds
        deposit_response = client.post(
            "/simulate/deposit_webhook",
            json={"user_id": user_id, "amount_u": 10000000}
        )
        assert deposit_response.status_code == 200
        
        # Check TVL
        tvl_response = client.get("/tvl")
        assert tvl_response.status_code == 200
        tvl_data = tvl_response.json()
        assert tvl_data["total_cash_u"] >= 10000000
        
        # Try to get current round (should be None initially)
        round_response = client.get("/rounds/current")
        assert round_response.status_code == 200
        # Should return None if no round exists
        
        # Note: In a real test, you'd need to create a round first
        # This would typically be done through the CLI or scheduler
    
    def test_tvl_endpoint(self, client):
        """Test TVL endpoint with no data"""
        response = client.get("/tvl")
        assert response.status_code == 200
        
        data = response.json()
        assert "locked_u" in data
        assert "total_cash_u" in data
        assert "pending_withdrawals_u" in data
        
        # Initially should be zero
        assert data["locked_u"] == 0
        assert data["total_cash_u"] == 0
        assert data["pending_withdrawals_u"] == 0
    
    def test_withdrawal_insufficient_funds(self, client):
        """Test withdrawal with insufficient funds"""
        # Create user
        user_response = client.post("/users", json={"email": "test@example.com"})
        user_id = user_response.json()["id"]
        
        # Try to withdraw without funds
        response = client.post(
            "/withdrawals",
            json={"user_id": user_id, "amount_u": 1000000}
        )
        assert response.status_code == 400
        assert "Insufficient balance" in response.json()["detail"]
    
    def test_bet_no_open_round(self, client):
        """Test betting when no round is open"""
        # Create user and deposit
        user_response = client.post("/users", json={"email": "test@example.com"})
        user_id = user_response.json()["id"]
        
        client.post(
            "/simulate/deposit_webhook",
            json={"user_id": user_id, "amount_u": 10000000}
        )
        
        # Try to place bet
        response = client.post(
            "/bets",
            json={"user_id": user_id, "side": "UP", "stake_u": 1000000}
        )
        assert response.status_code == 400
        assert "No open round available" in response.json()["detail"]
    
    def test_health_and_metrics(self, client):
        """Test health and metrics endpoints"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        
        response = client.get("/metrics")
        assert response.status_code == 200
        # Prometheus metrics should be in text format
        assert response.headers["content-type"].startswith("text/plain")
    
    def test_root_endpoint(self, client):
        """Test root endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["message"] == "Betting MVP API"
        assert "version" in data