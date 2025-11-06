# Test Suite Documentation

## Overview

The test suite (`test_vote.py`) provides comprehensive coverage of all documented functionality in the voting tool. It includes **62 test cases** organized into 10 test classes covering all major features.

## Running Tests

### Basic Usage

```bash
# Run all tests
python3 -m pytest test_vote.py -v

# Run with coverage report
python3 -m pytest test_vote.py --cov=vote --cov-report=term-missing

# Run specific test class
python3 -m pytest test_vote.py::TestAdaptiveTiming -v

# Run specific test
python3 -m pytest test_vote.py::TestAdaptiveTiming::test_standard_timing_when_ahead -v
```

### Test Output

When all tests pass, you'll see:
```
============================== 62 passed in 1.10s ==============================
```

## Test Coverage

### Test Classes

1. **TestResultExtraction** (13 tests)
   - HTML parsing and result extraction
   - Lead percentage calculations
   - Cutler ahead/behind detection
   - Case-insensitive name matching
   - Edge cases (empty results, missing data)

2. **TestAdaptiveTiming** (8 tests)
   - Standard timing (53-67 seconds)
   - Initial accelerated timing (14-37 seconds, 1-4 rounds)
   - Accelerated timing (7-16 seconds, 5-9 rounds)
   - Super accelerated timing (3-10 seconds, 10+ rounds)
   - Counter reset logic

3. **TestLeadBackoff** (6 tests)
   - Backoff trigger conditions
   - Exponential multiplier progression
   - Maximum delay cap (300 seconds)
   - Backoff reset when lead drops

4. **TestParallelThreadManagement** (6 tests)
   - First parallel thread trigger (20 rounds)
   - Second parallel thread trigger (30 rounds)
   - Thread start/stop conditions
   - Thread lifecycle management

5. **TestCommandLineArguments** (7 tests)
   - `--debug` flag parsing
   - `--start-threads` argument (1, 2, 3)
   - `--lead-threshold` argument (default and custom)
   - Combined argument parsing

6. **TestThreadSafety** (2 tests)
   - Concurrent counter increments
   - Concurrent backoff updates
   - Lock-based synchronization

7. **TestStartThreadsLogic** (3 tests)
   - Initialization with 1 thread (behind_count = 0)
   - Initialization with 2 threads (behind_count = 20)
   - Initialization with 3 threads (behind_count = 30)

8. **TestTimingRanges** (5 tests)
   - Standard timing range validation
   - Initial accelerated timing range validation
   - Accelerated timing range validation
   - Super accelerated timing range validation
   - Maximum backoff delay validation

9. **TestEdgeCases** (4 tests)
   - Invalid percentage handling
   - Missing HTML elements
   - Insufficient results
   - Cutler not in first place

10. **TestDebugPrint** (2 tests)
    - Debug mode enabled
    - Debug mode disabled

11. **TestIntegrationScenarios** (6 tests)
    - Cutler stays ahead scenario
    - Cutler falls behind then catches up
    - Progressive acceleration through all tiers
    - Lead backoff progression
    - Parallel threads start/stop
    - Vote statistics tracking

## What's Tested

### Core Functionality ✅
- [x] Result extraction from HTML
- [x] Cutler ahead/behind detection
- [x] Lead percentage calculation
- [x] All 4 timing tiers (Standard, Initial Accelerated, Accelerated, Super Accelerated)
- [x] Exponential backoff system
- [x] Parallel thread management (20+ and 30+ rounds)
- [x] Command-line argument parsing
- [x] Thread-safe counter operations
- [x] Debug mode functionality

### Edge Cases ✅
- [x] Empty results
- [x] Invalid percentages (negative, >100%)
- [x] Missing HTML elements
- [x] Case-insensitive name matching
- [x] Duplicate name handling
- [x] Insufficient results for lead calculation

### Integration Scenarios ✅
- [x] Complete voting session simulation
- [x] Progressive acceleration through tiers
- [x] Thread lifecycle management
- [x] Statistics tracking accuracy

## What's NOT Tested

The following are intentionally not tested (would require browser automation):

- `submit_vote_selenium()` - Requires actual browser and web page
- `perform_vote_iteration()` - Requires Selenium WebDriver
- `parallel_voting_thread()` - Requires actual voting execution
- `main()` - Requires full integration with web page

These functions are tested manually during actual usage. The test suite focuses on the **core logic** that can be tested in isolation.

## Code Coverage

Current coverage: **~12%** (of total lines)

This is expected because:
- Selenium/browser automation code cannot be tested without a browser
- Main loop and integration code requires actual web page interaction
- **100% of testable core logic is covered**

### Well-Tested Functions

- `extract_voting_results()` - 100% coverage
- `is_cutler_ahead()` - 100% coverage
- `get_cutler_lead_percentage()` - 100% coverage
- `print_top_results()` - 100% coverage
- `debug_print()` - 100% coverage
- All timing logic - 100% coverage
- All parallel thread management logic - 100% coverage
- All backoff logic - 100% coverage

## Adding New Tests

When adding new functionality:

1. **Add unit tests** for new functions
2. **Add integration tests** for new scenarios
3. **Update this document** with new test classes
4. **Run full test suite** before committing

### Test Template

```python
class TestNewFeature(unittest.TestCase):
    """Test new feature functionality."""
    
    def setUp(self):
        """Reset state before each test."""
        # Reset relevant global variables
    
    def test_feature_basic_case(self):
        """Test basic functionality."""
        # Test implementation
    
    def test_feature_edge_case(self):
        """Test edge case handling."""
        # Test implementation
```

## Continuous Integration

The test suite is designed to run in CI/CD pipelines:

```bash
# Exit code 0 on success, 1 on failure
python3 -m pytest test_vote.py -v
```

## Troubleshooting

### Tests Fail After Code Changes

1. Check that global state is reset in `setUp()` methods
2. Verify that test data matches expected format
3. Ensure all imports are correct
4. Check for floating-point precision issues (use `assertAlmostEqual`)

### Coverage Report Shows Low Coverage

- This is expected for Selenium/browser code
- Focus on ensuring core logic functions have high coverage
- Manual testing covers browser automation

## Dependencies

Test suite requires:
- `pytest>=7.4.0` (test runner)
- `pytest-cov>=4.1.0` (coverage reporting)
- `unittest` (standard library, used by pytest)

Install with:
```bash
pip install -r requirements.txt
```

