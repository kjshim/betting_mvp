# Contributing to Betting MVP

Thank you for your interest in contributing to the Betting MVP! This document provides guidelines and instructions for contributors.

## 🚀 Quick Start for Contributors

1. **Fork the repository**
2. **Clone your fork locally**
   ```bash
   git clone https://github.com/yourusername/betting_mvp.git
   cd betting_mvp
   ```

3. **Set up development environment**
   ```bash
   make install
   make up
   make migrate
   make seed
   ```

4. **Run tests to ensure everything works**
   ```bash
   make test-local
   make lint
   ```

## 🛠️ Development Workflow

### Branch Naming
- `feature/description` - New features
- `bugfix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

### Making Changes

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes following our code standards**
3. **Write or update tests**
4. **Run the full test suite**
   ```bash
   make test-local
   make lint
   make format
   ```

5. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: add your feature description

   More detailed explanation of what this change does and why.
   
   🤖 Generated with [Claude Code](https://claude.ai/code)
   
   Co-Authored-By: Claude <noreply@anthropic.com>"
   ```

6. **Push and create a Pull Request**

## 📋 Code Standards

### Python Code Style
- **Formatting**: Black (88 character line length)
- **Linting**: Ruff for Python best practices
- **Type Checking**: MyPy for static analysis
- **Import Sorting**: isort compatible ordering

### Commit Message Format
```
type(scope): short description

Longer explanation of the change, if needed.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

### Testing Requirements
- **Unit tests** for all business logic
- **Integration tests** for API endpoints
- **Property tests** for complex calculations (payouts, ledger)
- **Minimum 90% coverage** for domain/ and adapters/
- **All tests must pass** before merging

### Documentation
- **Docstrings** for all public functions and classes
- **Type hints** for all function parameters and return values
- **Update README.md** for user-facing changes
- **Update CLAUDE.md** for architectural changes

## 🧪 Testing Guidelines

### Writing Tests
```python
# Good test example
def test_ledger_entries_must_balance():
    """Test that all ledger entries sum to zero"""
    entries = [
        ("cash", user_id, 1000000, "deposit", ref_id),
        ("house", None, -1000000, "deposit", ref_id),
    ]
    ledger_entries = ledger_service.create_entries(entries)
    assert sum(entry.amount_u for entry in ledger_entries) == 0
```

### Test Categories
- **Unit tests**: `tests/test_*.py`
- **Integration tests**: End-to-end workflows
- **Property tests**: Use Hypothesis for edge cases
- **API tests**: FastAPI TestClient

### Running Tests
```bash
# All tests
make test-local

# Specific test file
pytest tests/test_ledger.py -v

# With coverage
pytest --cov=. tests/

# Property tests with more examples
pytest tests/test_payouts.py::test_payout_property_zero_sum --hypothesis-show-statistics
```

## 🔒 Security Guidelines

### Financial Code
- **Double-entry ledger**: All transactions must balance
- **Input validation**: Validate all monetary amounts
- **Integer arithmetic**: Use micro-USDC (no floats)
- **Audit trails**: Log all financial operations

### General Security
- **No secrets in code**: Use environment variables
- **SQL injection**: Use parameterized queries (SQLAlchemy ORM)
- **Input sanitization**: Validate all user inputs
- **Error handling**: Don't expose internal details

## 📊 Performance Guidelines

### Database
- **Use indexes** for frequent queries
- **Batch operations** when possible
- **Connection pooling** for production
- **Query optimization** with EXPLAIN

### API
- **Async/await** for I/O operations
- **Pagination** for large result sets
- **Caching** with Redis where appropriate
- **Rate limiting** for production

## 🐛 Bug Reports

When reporting bugs, please include:

1. **Environment details** (Python version, OS, Docker version)
2. **Steps to reproduce** the issue
3. **Expected vs actual behavior**
4. **Error logs** (sanitized of sensitive data)
5. **System state** (TVL, round status, etc.)

Use this template:
```markdown
## Bug Description
Brief description of the issue

## Environment
- Python version:
- OS:
- Docker version:

## Steps to Reproduce
1. Step one
2. Step two
3. Step three

## Expected Behavior
What should have happened

## Actual Behavior
What actually happened

## Logs
```
error logs here
```

## Additional Context
Any other relevant information
```

## 🎯 Feature Requests

For new features, please:

1. **Check existing issues** to avoid duplicates
2. **Describe the use case** and business value
3. **Propose the solution** with technical details
4. **Consider backwards compatibility**
5. **Include test cases** in the proposal

## 🔍 Code Review Process

### For Contributors
- **Self-review** your code before submitting
- **Write clear PR descriptions** explaining the change
- **Include test results** and screenshots if relevant
- **Respond promptly** to review feedback
- **Keep PRs small** and focused on single changes

### For Reviewers
- **Review within 2 business days**
- **Focus on correctness, security, and maintainability**
- **Be constructive** and educational in feedback
- **Test the changes** locally when possible
- **Check documentation** is updated

## 📚 Learning Resources

### Understanding the Codebase
1. **Read README.md** for project overview
2. **Study CLAUDE.md** for architectural decisions
3. **Review OPERATING_MANUAL.md** for business logic
4. **Run the demo** (`python demo.py`) to see the system in action

### Key Concepts
- **Double-entry bookkeeping**: Every transaction has equal debits and credits
- **Micro-USDC**: All amounts in 10^-6 USDC units
- **Round lifecycle**: OPEN → LOCKED → SETTLED
- **Payout calculation**: Pro-rata distribution with fees

### External Documentation
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/)
- [Pytest Documentation](https://docs.pytest.org/)
- [Docker Compose](https://docs.docker.com/compose/)

## 🤝 Community Guidelines

### Code of Conduct
- **Be respectful** to all contributors
- **Help others learn** and grow
- **Focus on the code**, not the person
- **Assume good intentions**

### Communication
- **Use clear, descriptive language**
- **Provide context** for your changes
- **Ask questions** if something is unclear
- **Share knowledge** with the community

## ✨ Recognition

Contributors who make significant contributions will be:
- **Listed in the README** contributors section
- **Mentioned in release notes**
- **Invited to join** the maintainer team (for regular contributors)

## 📞 Getting Help

- **GitHub Issues**: Technical questions and bugs
- **GitHub Discussions**: General questions and ideas
- **Code Review**: Tag maintainers for urgent reviews

Thank you for contributing to Betting MVP! 🎉