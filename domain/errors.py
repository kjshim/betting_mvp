"""
Comprehensive error handling for chain operations.

This module defines custom exceptions and error handling patterns
for blockchain-related operations that require careful error management.
"""

import logging
from enum import Enum
from typing import Any, Dict, Optional, Type, Union
from dataclasses import dataclass
import asyncio
import functools
import time


logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels for different types of blockchain errors"""
    LOW = "low"          # Temporary network issues, retryable
    MEDIUM = "medium"    # Configuration issues, might need intervention
    HIGH = "high"        # Balance issues, transaction failures
    CRITICAL = "critical"  # Security issues, data corruption


class ErrorCategory(Enum):
    """Categories of blockchain-related errors"""
    NETWORK = "network"           # RPC connection, timeout issues
    VALIDATION = "validation"     # Invalid addresses, amounts
    INSUFFICIENT_FUNDS = "insufficient_funds"  # Not enough balance
    TRANSACTION = "transaction"   # Transaction execution issues
    CONFIRMATION = "confirmation"  # Block confirmation problems
    SECURITY = "security"         # Private key, signature issues
    RATE_LIMIT = "rate_limit"    # API rate limiting
    CONFIGURATION = "configuration"  # Wrong network, contract address
    DATA_INTEGRITY = "data_integrity"  # Database/chain state mismatch


@dataclass
class ErrorContext:
    """Additional context for error handling and debugging"""
    user_id: Optional[str] = None
    tx_hash: Optional[str] = None
    amount: Optional[int] = None
    address: Optional[str] = None
    network: Optional[str] = None
    block_number: Optional[int] = None
    gas_price: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class ChainError(Exception):
    """Base exception for all blockchain-related errors"""
    
    def __init__(
        self, 
        message: str, 
        category: ErrorCategory, 
        severity: ErrorSeverity,
        retryable: bool = False,
        context: Optional[ErrorContext] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.retryable = retryable
        self.context = context or ErrorContext()
        self.original_error = original_error
        self.timestamp = time.time()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for logging/monitoring"""
        return {
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "retryable": self.retryable,
            "timestamp": self.timestamp,
            "context": {
                "user_id": self.context.user_id,
                "tx_hash": self.context.tx_hash,
                "amount": self.context.amount,
                "address": self.context.address,
                "network": self.context.network,
                "block_number": self.context.block_number,
                "gas_price": self.context.gas_price,
                "metadata": self.context.metadata,
            },
            "original_error": str(self.original_error) if self.original_error else None
        }


class NetworkError(ChainError):
    """Network connectivity issues"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.LOW,
            retryable=True,
            context=context,
            original_error=original_error
        )


class ValidationError(ChainError):
    """Input validation errors"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            context=context,
            original_error=original_error
        )


class InsufficientFundsError(ChainError):
    """Insufficient balance errors"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.INSUFFICIENT_FUNDS,
            severity=ErrorSeverity.HIGH,
            retryable=False,
            context=context,
            original_error=original_error
        )


class TransactionError(ChainError):
    """Transaction execution errors"""
    
    def __init__(self, message: str, retryable: bool = False, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.TRANSACTION,
            severity=ErrorSeverity.HIGH,
            retryable=retryable,
            context=context,
            original_error=original_error
        )


class ConfirmationError(ChainError):
    """Block confirmation issues"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIRMATION,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
            context=context,
            original_error=original_error
        )


class SecurityError(ChainError):
    """Security-related errors (private keys, signatures, etc.)"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
            retryable=False,
            context=context,
            original_error=original_error
        )


class RateLimitError(ChainError):
    """API rate limiting errors"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.LOW,
            retryable=True,
            context=context,
            original_error=original_error
        )


class ConfigurationError(ChainError):
    """Configuration errors (wrong network, invalid contract, etc.)"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.HIGH,
            retryable=False,
            context=context,
            original_error=original_error
        )


class DataIntegrityError(ChainError):
    """Data integrity issues between database and blockchain"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            category=ErrorCategory.DATA_INTEGRITY,
            severity=ErrorSeverity.CRITICAL,
            retryable=False,
            context=context,
            original_error=original_error
        )


class ErrorHandler:
    """Centralized error handling and classification"""
    
    @staticmethod
    def classify_web3_error(error: Exception, context: Optional[ErrorContext] = None) -> ChainError:
        """
        Classify a Web3 exception into our custom error types.
        
        This function maps common Web3.py exceptions to our domain-specific errors.
        """
        error_msg = str(error).lower()
        
        # Network/connectivity errors
        if any(keyword in error_msg for keyword in [
            "connection", "timeout", "network", "unreachable", 
            "connection refused", "connection reset", "dns"
        ]):
            return NetworkError(
                f"Network connectivity issue: {error}",
                context=context,
                original_error=error
            )
            
        # Rate limiting
        if any(keyword in error_msg for keyword in [
            "rate limit", "too many requests", "429"
        ]):
            return RateLimitError(
                f"API rate limit exceeded: {error}",
                context=context,
                original_error=error
            )
            
        # Insufficient funds
        if any(keyword in error_msg for keyword in [
            "insufficient", "balance", "funds", "allowance"
        ]):
            return InsufficientFundsError(
                f"Insufficient funds for transaction: {error}",
                context=context,
                original_error=error
            )
            
        # Gas-related issues
        if any(keyword in error_msg for keyword in [
            "gas", "out of gas", "gas limit", "gas price"
        ]):
            return TransactionError(
                f"Gas-related transaction error: {error}",
                retryable=True,
                context=context,
                original_error=error
            )
            
        # Nonce issues
        if any(keyword in error_msg for keyword in [
            "nonce", "already known", "replacement underpriced"
        ]):
            return TransactionError(
                f"Transaction nonce issue: {error}",
                retryable=True,
                context=context,
                original_error=error
            )
            
        # Invalid address/data
        if any(keyword in error_msg for keyword in [
            "invalid address", "invalid hex", "checksum", "ens name not found"
        ]):
            return ValidationError(
                f"Invalid input data: {error}",
                context=context,
                original_error=error
            )
            
        # Contract errors
        if any(keyword in error_msg for keyword in [
            "execution reverted", "contract call", "function call"
        ]):
            return TransactionError(
                f"Smart contract execution failed: {error}",
                retryable=False,
                context=context,
                original_error=error
            )
            
        # Configuration errors
        if any(keyword in error_msg for keyword in [
            "method not found", "invalid method", "unsupported"
        ]):
            return ConfigurationError(
                f"Configuration or method error: {error}",
                context=context,
                original_error=error
            )
            
        # Default to generic transaction error
        return TransactionError(
            f"Unknown blockchain error: {error}",
            retryable=False,
            context=context,
            original_error=error
        )
        
    @staticmethod
    def should_retry(error: ChainError, attempt: int, max_attempts: int = 3) -> bool:
        """Determine if an error should be retried"""
        if attempt >= max_attempts:
            return False
            
        if not error.retryable:
            return False
            
        # Don't retry critical errors
        if error.severity == ErrorSeverity.CRITICAL:
            return False
            
        # Don't retry validation errors
        if error.category == ErrorCategory.VALIDATION:
            return False
            
        # Don't retry insufficient funds
        if error.category == ErrorCategory.INSUFFICIENT_FUNDS:
            return False
            
        return True
        
    @staticmethod
    def get_retry_delay(attempt: int, base_delay: float = 1.0) -> float:
        """Calculate exponential backoff delay for retry"""
        return min(base_delay * (2 ** attempt), 60.0)  # Cap at 60 seconds


def with_error_handling(
    max_retries: int = 3,
    base_delay: float = 1.0,
    context_factory = None
):
    """
    Decorator for automatic error handling and retry logic.
    
    Usage:
    @with_error_handling(max_retries=3)
    async def my_blockchain_operation(self, ...):
        # Your code here
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except ChainError:
                    # Already a classified error, just re-raise
                    raise
                    
                except Exception as e:
                    # Create context if factory provided
                    context = context_factory(*args, **kwargs) if context_factory else None
                    
                    # Classify the error
                    chain_error = ErrorHandler.classify_web3_error(e, context)
                    
                    # Log the error
                    logger.warning(f"Blockchain operation failed (attempt {attempt + 1}): {chain_error.to_dict()}")
                    
                    # Check if we should retry
                    if ErrorHandler.should_retry(chain_error, attempt, max_retries):
                        delay = ErrorHandler.get_retry_delay(attempt, base_delay)
                        logger.info(f"Retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                        last_error = chain_error
                        continue
                    else:
                        # No more retries, raise the classified error
                        raise chain_error
                        
            # Should never reach here, but just in case
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected error in retry logic")
            
        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern for protecting against cascading failures.
    
    Automatically opens the circuit when too many errors occur,
    preventing further calls until the service recovers.
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
    def call(self, func):
        """Execute a function with circuit breaker protection"""
        async def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                # Check if enough time has passed to try again
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "HALF_OPEN"
                else:
                    raise ChainError(
                        "Circuit breaker is OPEN - service unavailable",
                        category=ErrorCategory.NETWORK,
                        severity=ErrorSeverity.HIGH,
                        retryable=False
                    )
                    
            try:
                result = await func(*args, **kwargs)
                
                # Success - reset failure count and close circuit
                self.failure_count = 0
                self.state = "CLOSED"
                return result
                
            except ChainError as e:
                self.failure_count += 1
                self.last_failure_time = time.time()
                
                # Open circuit if we've reached the threshold
                if self.failure_count >= self.failure_threshold:
                    self.state = "OPEN"
                    logger.error(f"Circuit breaker OPENED after {self.failure_count} failures")
                    
                raise e
                
        return wrapper
        
    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status"""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout
        }


class ErrorReporter:
    """
    Centralized error reporting and metrics collection.
    
    In production, this would integrate with monitoring systems
    like Sentry, DataDog, or Prometheus.
    """
    
    def __init__(self):
        self.error_counts = {}
        self.recent_errors = []
        
    def report_error(self, error: ChainError):
        """Report an error for monitoring and metrics"""
        # Count errors by category and severity
        key = f"{error.category.value}_{error.severity.value}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        
        # Store recent errors (keep last 100)
        self.recent_errors.append(error)
        self.recent_errors = self.recent_errors[-100:]
        
        # Log based on severity
        error_dict = error.to_dict()
        if error.severity == ErrorSeverity.CRITICAL:
            logger.critical(f"CRITICAL ERROR: {error_dict}")
        elif error.severity == ErrorSeverity.HIGH:
            logger.error(f"HIGH SEVERITY ERROR: {error_dict}")
        elif error.severity == ErrorSeverity.MEDIUM:
            logger.warning(f"MEDIUM SEVERITY ERROR: {error_dict}")
        else:
            logger.info(f"LOW SEVERITY ERROR: {error_dict}")
            
        # In production, you would also:
        # - Send to Sentry for error tracking
        # - Update Prometheus metrics
        # - Trigger alerts for critical errors
        # - Store in monitoring database
        
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of error statistics"""
        return {
            "total_errors": len(self.recent_errors),
            "error_counts_by_type": self.error_counts.copy(),
            "recent_error_categories": [
                error.category.value for error in self.recent_errors[-10:]
            ]
        }


# Global error reporter instance
error_reporter = ErrorReporter()