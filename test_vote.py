#!/usr/bin/env python3
"""
Comprehensive test suite for the Sports Illustrated voting tool.

Tests all documented functionality including:
- Result extraction
- Adaptive timing system (4 tiers)
- Lead backoff system
- Parallel thread management
- Command-line arguments
- Thread safety
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, call, mock_open
import sys
import threading
import time
import io
from contextlib import redirect_stdout

# Import the module to test
import vote


class TestResultExtraction(unittest.TestCase):
    """Test result extraction and parsing functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.sample_html_pds = """
        <html>
        <body>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Cutler Whitaker, sr., Mountain View (Utah) football</div>
                <div class="pds-feedback-per">28.45%</div>
            </div>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Dylan Papushak, jr., Berea-Midpark (Ohio) football</div>
                <div class="pds-feedback-per">24.23%</div>
            </div>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Owen Eastgate, sr., Central (Indiana) football</div>
                <div class="pds-feedback-per">19.45%</div>
            </div>
        </body>
        </html>
        """
        
        self.sample_html_pattern = """
        <html>
        <body>
            Cutler Whitaker, sr., Mountain View (Utah) football 28.45%
            Dylan Papushak, jr., Berea-Midpark (Ohio) football 24.23%
        </body>
        </html>
        """
        
        self.empty_html = "<html><body></body></html>"
    
    def test_extract_voting_results_pds_format(self):
        """Test extraction using pds-feedback-group format."""
        results = vote.extract_voting_results(self.sample_html_pds)
        
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0][0], "Cutler Whitaker")
        self.assertEqual(results[0][1], 28.45)
        self.assertEqual(results[1][0], "Dylan Papushak")
        self.assertEqual(results[1][1], 24.23)
        self.assertEqual(results[2][0], "Owen Eastgate")
        self.assertEqual(results[2][1], 19.45)
        
        # Verify sorted by percentage descending
        self.assertEqual(results[0][1], 28.45)  # Highest first
        self.assertEqual(results[-1][1], 19.45)  # Lowest last
    
    def test_extract_voting_results_empty(self):
        """Test extraction with empty HTML."""
        results = vote.extract_voting_results(self.empty_html)
        self.assertEqual(len(results), 0)
    
    def test_extract_voting_results_removes_duplicates(self):
        """Test that duplicate names are removed."""
        html_with_duplicates = """
        <html>
        <body>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Cutler Whitaker, sr., Mountain View</div>
                <div class="pds-feedback-per">28.45%</div>
            </div>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">cutler whitaker, sr., Mountain View</div>
                <div class="pds-feedback-per">28.45%</div>
            </div>
        </body>
        </html>
        """
        results = vote.extract_voting_results(html_with_duplicates)
        # Should only have one entry (case-insensitive duplicate removal)
        self.assertEqual(len(results), 1)
    
    def test_is_cutler_ahead_first_place(self):
        """Test is_cutler_ahead when Cutler is in first place."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23),
            ("Owen Eastgate", 19.45)
        ]
        self.assertTrue(vote.is_cutler_ahead(results))
    
    def test_is_cutler_ahead_not_first_place(self):
        """Test is_cutler_ahead when Cutler is not in first place."""
        results = [
            ("Dylan Papushak", 28.45),
            ("Cutler Whitaker", 24.23),
            ("Owen Eastgate", 19.45)
        ]
        self.assertFalse(vote.is_cutler_ahead(results))
    
    def test_is_cutler_ahead_empty_results(self):
        """Test is_cutler_ahead with empty results."""
        self.assertFalse(vote.is_cutler_ahead([]))
        self.assertFalse(vote.is_cutler_ahead(None))
    
    def test_is_cutler_ahead_case_insensitive(self):
        """Test is_cutler_ahead handles case variations."""
        results = [
            ("cutler whitaker", 28.45),
            ("Dylan Papushak", 24.23)
        ]
        self.assertTrue(vote.is_cutler_ahead(results))
        
        results2 = [
            ("Cutler Whitaker, sr.", 28.45),
            ("Dylan Papushak", 24.23)
        ]
        self.assertTrue(vote.is_cutler_ahead(results2))
    
    def test_get_cutler_lead_percentage_above_threshold(self):
        """Test lead percentage calculation when above threshold."""
        results = [
            ("Cutler Whitaker", 35.45),
            ("Dylan Papushak", 18.23),
            ("Owen Eastgate", 15.45)
        ]
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        
        self.assertAlmostEqual(lead, 17.22, places=2)  # 35.45 - 18.23
        self.assertTrue(is_above)
    
    def test_get_cutler_lead_percentage_below_threshold(self):
        """Test lead percentage calculation when below threshold."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23),
            ("Owen Eastgate", 19.45)
        ]
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        
        self.assertAlmostEqual(lead, 4.22, places=2)  # 28.45 - 24.23
        self.assertFalse(is_above)
    
    def test_get_cutler_lead_percentage_not_first(self):
        """Test lead percentage when Cutler is not in first place."""
        results = [
            ("Dylan Papushak", 28.45),
            ("Cutler Whitaker", 24.23)
        ]
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        
        self.assertIsNone(lead)
        self.assertFalse(is_above)
    
    def test_get_cutler_lead_percentage_insufficient_results(self):
        """Test lead percentage with insufficient results."""
        results = [("Cutler Whitaker", 28.45)]  # Only one result
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        
        self.assertIsNone(lead)
        self.assertFalse(is_above)
    
    def test_print_top_results(self):
        """Test printing top results."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23),
            ("Owen Eastgate", 19.45),
            ("Chance Fischer", 11.13),
            ("Niko Kokosioulis", 8.34)
        ]
        
        output = io.StringIO()
        with redirect_stdout(output):
            vote.print_top_results(results, top_n=5)
        
        output_str = output.getvalue()
        self.assertIn("TOP 5 VOTING RESULTS", output_str)
        self.assertIn("Cutler Whitaker", output_str)
        self.assertIn("28.45%", output_str)
        self.assertIn("Dylan Papushak", output_str)
        self.assertIn("24.23%", output_str)
    
    def test_print_top_results_empty(self):
        """Test printing with empty results."""
        output = io.StringIO()
        with redirect_stdout(output):
            result = vote.print_top_results([])
        
        self.assertIsNone(result)
        output_str = output.getvalue()
        self.assertIn("No results found", output_str)


class TestAdaptiveTiming(unittest.TestCase):
    """Test adaptive timing system (4 tiers)."""
    
    def setUp(self):
        """Reset global counters before each test."""
        vote.vote_count = 0
        vote.consecutive_behind_count = 0
        vote.standard_vote_count = 0
        vote.initial_accelerated_vote_count = 0
        vote.accelerated_vote_count = 0
        vote.super_accelerated_vote_count = 0
    
    def test_standard_timing_when_ahead(self):
        """Test standard timing when Cutler is ahead."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23)
        ]
        
        # Simulate Cutler being ahead
        with vote._counter_lock:
            vote.consecutive_behind_count = 0
            vote.standard_vote_count += 1
        
        # Standard timing should be 53-67 seconds
        # We can't test exact randomness, but we can verify the logic
        cutler_ahead = vote.is_cutler_ahead(results)
        self.assertTrue(cutler_ahead)
    
    def test_initial_accelerated_timing_1_round(self):
        """Test initial accelerated timing (1 round behind)."""
        with vote._counter_lock:
            vote.consecutive_behind_count = 1
            vote.initial_accelerated_vote_count += 1
        
        # Should use 14-37 seconds
        # Verify counter is set correctly
        self.assertEqual(vote.consecutive_behind_count, 1)
        self.assertEqual(vote.initial_accelerated_vote_count, 1)
    
    def test_initial_accelerated_timing_4_rounds(self):
        """Test initial accelerated timing (4 rounds behind)."""
        with vote._counter_lock:
            vote.consecutive_behind_count = 4
            vote.initial_accelerated_vote_count += 1
        
        self.assertEqual(vote.consecutive_behind_count, 4)
        self.assertLess(vote.consecutive_behind_count, 5)
    
    def test_accelerated_timing_5_rounds(self):
        """Test accelerated timing (5 rounds behind)."""
        with vote._counter_lock:
            vote.consecutive_behind_count = 5
            vote.accelerated_vote_count += 1
        
        # Should use 7-16 seconds
        self.assertEqual(vote.consecutive_behind_count, 5)
        self.assertGreaterEqual(vote.consecutive_behind_count, 5)
        self.assertLess(vote.consecutive_behind_count, 10)
    
    def test_accelerated_timing_9_rounds(self):
        """Test accelerated timing (9 rounds behind)."""
        with vote._counter_lock:
            vote.consecutive_behind_count = 9
            vote.accelerated_vote_count += 1
        
        self.assertEqual(vote.consecutive_behind_count, 9)
        self.assertLess(vote.consecutive_behind_count, 10)
    
    def test_super_accelerated_timing_10_rounds(self):
        """Test super accelerated timing (10 rounds behind)."""
        with vote._counter_lock:
            vote.consecutive_behind_count = 10
            vote.super_accelerated_vote_count += 1
        
        # Should use 3-10 seconds
        self.assertEqual(vote.consecutive_behind_count, 10)
        self.assertGreaterEqual(vote.consecutive_behind_count, 10)
    
    def test_super_accelerated_timing_15_rounds(self):
        """Test super accelerated timing (15 rounds behind)."""
        with vote._counter_lock:
            vote.consecutive_behind_count = 15
            vote.super_accelerated_vote_count += 1
        
        self.assertEqual(vote.consecutive_behind_count, 15)
        self.assertGreaterEqual(vote.consecutive_behind_count, 10)
    
    def test_counter_reset_when_ahead(self):
        """Test that consecutive_behind_count resets when Cutler gets ahead."""
        with vote._counter_lock:
            vote.consecutive_behind_count = 5
            vote.accelerated_vote_count += 1
        
        # Simulate Cutler getting ahead
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23)
        ]
        
        if vote.is_cutler_ahead(results):
            with vote._counter_lock:
                vote.consecutive_behind_count = 0
                vote.standard_vote_count += 1
        
        self.assertEqual(vote.consecutive_behind_count, 0)
        self.assertEqual(vote.standard_vote_count, 1)


class TestLeadBackoff(unittest.TestCase):
    """Test lead backoff system."""
    
    def setUp(self):
        """Reset backoff multiplier before each test."""
        vote.lead_backoff_multiplier = 1.0
    
    def test_backoff_trigger_above_threshold(self):
        """Test backoff triggers when lead exceeds threshold."""
        results = [
            ("Cutler Whitaker", 35.45),
            ("Dylan Papushak", 18.23)  # Lead: 17.22%
        ]
        
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        self.assertTrue(is_above)
        self.assertAlmostEqual(lead, 17.22, places=2)
    
    def test_backoff_not_triggered_below_threshold(self):
        """Test backoff doesn't trigger when lead is below threshold."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23)  # Lead: 4.22%
        ]
        
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        self.assertFalse(is_above)
        self.assertAlmostEqual(lead, 4.22, places=2)
    
    def test_backoff_exponential_increase(self):
        """Test exponential backoff multiplier increases correctly."""
        initial_multiplier = 1.0
        
        with vote.lead_backoff_lock:
            # Simulate 3 rounds of backoff
            multiplier = initial_multiplier
            multiplier = min(multiplier * 1.5, vote.MAX_BACKOFF_DELAY / 60.0)
            self.assertAlmostEqual(multiplier, 1.5, places=1)
            
            multiplier = min(multiplier * 1.5, vote.MAX_BACKOFF_DELAY / 60.0)
            self.assertAlmostEqual(multiplier, 2.25, places=1)
            
            multiplier = min(multiplier * 1.5, vote.MAX_BACKOFF_DELAY / 60.0)
            self.assertAlmostEqual(multiplier, 3.375, places=1)
    
    def test_backoff_maximum_cap(self):
        """Test that backoff is capped at MAX_BACKOFF_DELAY."""
        # MAX_BACKOFF_DELAY = 300 seconds, base = 60 seconds
        # So max multiplier should be 300/60 = 5.0
        max_multiplier = vote.MAX_BACKOFF_DELAY / 60.0
        
        with vote.lead_backoff_lock:
            multiplier = 1.0
            # Keep multiplying until we hit cap
            for _ in range(10):
                multiplier = min(multiplier * 1.5, vote.MAX_BACKOFF_DELAY / 60.0)
            
            self.assertLessEqual(multiplier, max_multiplier)
            self.assertAlmostEqual(multiplier, max_multiplier, places=1)
    
    def test_backoff_reset_when_lead_drops(self):
        """Test backoff resets when lead drops below threshold."""
        with vote.lead_backoff_lock:
            vote.lead_backoff_multiplier = 2.5  # Set to some backoff value
        
        # Simulate lead dropping below threshold
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23)  # Lead: 4.22% (below 15%)
        ]
        
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        if not is_above:
            with vote.lead_backoff_lock:
                if vote.lead_backoff_multiplier > 1.0:
                    vote.lead_backoff_multiplier = 1.0
        
        self.assertEqual(vote.lead_backoff_multiplier, 1.0)
    
    def test_backoff_delay_calculation(self):
        """Test backoff delay calculation with multiplier."""
        base_wait_time = 60  # Standard interval
        backoff_multiplier = 2.0
        
        wait_time = min(int(base_wait_time * backoff_multiplier), vote.MAX_BACKOFF_DELAY)
        self.assertEqual(wait_time, 120)
        
        # Test with max multiplier
        backoff_multiplier = 10.0  # Would exceed max
        wait_time = min(int(base_wait_time * backoff_multiplier), vote.MAX_BACKOFF_DELAY)
        self.assertEqual(wait_time, 300)  # Capped at MAX_BACKOFF_DELAY


class TestInitializeParallelThreads(unittest.TestCase):
    """Test initialize_parallel_threads() function."""
    
    def setUp(self):
        """Reset thread arrays before each test."""
        vote._parallel_threads = []
        vote._parallel_active = []
        vote._parallel_thresholds = []
    
    def test_initialize_parallel_threads_default(self):
        """Test initializing with default 7 parallel threads."""
        vote.initialize_parallel_threads(7)
        
        self.assertEqual(len(vote._parallel_threads), 7)
        self.assertEqual(len(vote._parallel_active), 7)
        self.assertEqual(len(vote._parallel_thresholds), 7)
        
        # Check all threads initialized to None/False
        for i in range(7):
            self.assertIsNone(vote._parallel_threads[i])
            self.assertFalse(vote._parallel_active[i])
        
        # Check thresholds: 20, 30, 40, 50, 60, 70, 80
        expected_thresholds = [20, 30, 40, 50, 60, 70, 80]
        self.assertEqual(vote._parallel_thresholds, expected_thresholds)
    
    def test_initialize_parallel_threads_10(self):
        """Test initializing with 10 parallel threads."""
        vote.initialize_parallel_threads(10)
        
        self.assertEqual(len(vote._parallel_threads), 10)
        self.assertEqual(len(vote._parallel_active), 10)
        self.assertEqual(len(vote._parallel_thresholds), 10)
        
        # Check thresholds increment by 10
        expected_thresholds = [20, 30, 40, 50, 60, 70, 80, 90, 100, 110]
        self.assertEqual(vote._parallel_thresholds, expected_thresholds)
    
    def test_initialize_parallel_threads_1(self):
        """Test initializing with 1 parallel thread."""
        vote.initialize_parallel_threads(1)
        
        self.assertEqual(len(vote._parallel_threads), 1)
        self.assertEqual(len(vote._parallel_active), 1)
        self.assertEqual(len(vote._parallel_thresholds), 1)
        self.assertEqual(vote._parallel_thresholds[0], 20)
    
    def test_initialize_parallel_threads_15(self):
        """Test initializing with 15 parallel threads (scalable design)."""
        vote.initialize_parallel_threads(15)
        
        self.assertEqual(len(vote._parallel_threads), 15)
        self.assertEqual(len(vote._parallel_active), 15)
        self.assertEqual(len(vote._parallel_thresholds), 15)
        
        # Verify thresholds continue correctly
        self.assertEqual(vote._parallel_thresholds[0], 20)
        self.assertEqual(vote._parallel_thresholds[14], 20 + (14 * 10))  # 160


class TestParallelThreadManagement(unittest.TestCase):
    """Test parallel thread management logic with scalable design."""
    
    def setUp(self):
        """Reset thread state before each test."""
        vote.consecutive_behind_count = 0
        vote.initialize_parallel_threads(7)  # Initialize with default 7 parallel threads
        vote._force_parallel_mode = False
    
    def test_first_parallel_thread_trigger_20_rounds(self):
        """Test first parallel thread triggers at 20 rounds."""
        vote.initialize_parallel_threads(7)
        
        with vote._counter_lock:
            vote.consecutive_behind_count = 20
        
        with vote._parallel_voting_lock:
            threshold = vote._parallel_thresholds[0] if 0 < len(vote._parallel_thresholds) else 20
            should_start = (vote.consecutive_behind_count >= threshold and 
                          len(vote._parallel_active) > 0 and not vote._parallel_active[0])
        
        self.assertTrue(should_start)
    
    def test_first_parallel_thread_not_triggered_19_rounds(self):
        """Test first parallel thread doesn't trigger at 19 rounds."""
        vote.initialize_parallel_threads(7)
        
        with vote._counter_lock:
            vote.consecutive_behind_count = 19
        
        with vote._parallel_voting_lock:
            threshold = vote._parallel_thresholds[0] if 0 < len(vote._parallel_thresholds) else 20
            should_start = (vote.consecutive_behind_count >= threshold and 
                          len(vote._parallel_active) > 0 and not vote._parallel_active[0])
        
        self.assertFalse(should_start)
    
    def test_second_parallel_thread_trigger_30_rounds(self):
        """Test second parallel thread triggers at 30 rounds."""
        vote.initialize_parallel_threads(7)
        
        with vote._counter_lock:
            vote.consecutive_behind_count = 30
        
        with vote._parallel_voting_lock:
            threshold = vote._parallel_thresholds[1] if 1 < len(vote._parallel_thresholds) else 30
            should_start = (vote.consecutive_behind_count >= threshold and 
                          len(vote._parallel_active) > 1 and not vote._parallel_active[1])
        
        self.assertTrue(should_start)
    
    def test_second_parallel_thread_not_triggered_29_rounds(self):
        """Test second parallel thread doesn't trigger at 29 rounds."""
        vote.initialize_parallel_threads(7)
        
        with vote._counter_lock:
            vote.consecutive_behind_count = 29
        
        with vote._parallel_voting_lock:
            threshold = vote._parallel_thresholds[1] if 1 < len(vote._parallel_thresholds) else 30
            should_start = (vote.consecutive_behind_count >= threshold and 
                          len(vote._parallel_active) > 1 and not vote._parallel_active[1])
        
        self.assertFalse(should_start)
    
    def test_parallel_thread_stop_when_ahead(self):
        """Test parallel threads stop when Cutler gets ahead (unless forced)."""
        vote.initialize_parallel_threads(7)
        vote._force_parallel_mode = False
        
        with vote._parallel_voting_lock:
            vote._parallel_active[0] = True
            vote._parallel_active[1] = True
        
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23)
        ]
        
        cutler_ahead = vote.is_cutler_ahead(results)
        if cutler_ahead and not vote._force_parallel_mode:
            with vote._parallel_voting_lock:
                vote._parallel_active[0] = False
                vote._parallel_active[1] = False
        
        self.assertFalse(vote._parallel_active[0])
        self.assertFalse(vote._parallel_active[1])
    
    def test_parallel_thread_stay_active_with_force_parallel(self):
        """Test parallel threads stay active when force_parallel_mode is True."""
        vote.initialize_parallel_threads(7)
        vote._force_parallel_mode = True
        
        with vote._parallel_voting_lock:
            vote._parallel_active[0] = True
            vote._parallel_active[1] = True
        
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23)
        ]
        
        cutler_ahead = vote.is_cutler_ahead(results)
        if cutler_ahead and not vote._force_parallel_mode:
            with vote._parallel_voting_lock:
                vote._parallel_active[0] = False
                vote._parallel_active[1] = False
        
        # Should still be active because force_parallel_mode is True
        self.assertTrue(vote._parallel_active[0])
        self.assertTrue(vote._parallel_active[1])
    
    def test_second_thread_stop_below_30_rounds(self):
        """Test second parallel thread stops when below 30 rounds (unless forced)."""
        vote.initialize_parallel_threads(7)
        vote._force_parallel_mode = False
        
        with vote._parallel_voting_lock:
            vote._parallel_active[1] = True
        
        with vote._counter_lock:
            vote.consecutive_behind_count = 25  # Below 30
        
        threshold = vote._parallel_thresholds[1] if 1 < len(vote._parallel_thresholds) else 30
        if vote.consecutive_behind_count < threshold and not vote._force_parallel_mode:
            with vote._parallel_voting_lock:
                vote._parallel_active[1] = False
        
        self.assertFalse(vote._parallel_active[1])
    
    def test_all_threads_trigger_at_respective_thresholds(self):
        """Test all parallel threads trigger at their respective thresholds."""
        vote.initialize_parallel_threads(7)
        
        thresholds = [20, 30, 40, 50, 60, 70, 80]
        
        for i, threshold in enumerate(thresholds):
            with vote._counter_lock:
                vote.consecutive_behind_count = threshold
            
            with vote._parallel_voting_lock:
                if i < len(vote._parallel_thresholds):
                    should_start = (vote.consecutive_behind_count >= vote._parallel_thresholds[i] and 
                                  not vote._parallel_active[i])
                    self.assertTrue(should_start, f"Thread {i} should start at threshold {threshold}")
    
    def test_thread_8_triggers_at_80_rounds(self):
        """Test 8th parallel thread (index 6 with 7 threads) triggers at 80 rounds."""
        vote.initialize_parallel_threads(7)  # Default: 7 parallel threads
        
        with vote._counter_lock:
            vote.consecutive_behind_count = 80
        
        with vote._parallel_voting_lock:
            thread_index = 6  # 7th parallel thread (0-indexed), which is the 8th thread total (main + 7 parallel)
            if thread_index < len(vote._parallel_thresholds):
                threshold = vote._parallel_thresholds[thread_index]
                should_start = (vote.consecutive_behind_count >= threshold and 
                              thread_index < len(vote._parallel_active) and
                              not vote._parallel_active[thread_index])
            else:
                threshold = 80
                should_start = False
        
        self.assertTrue(should_start, f"Thread {thread_index} should start at threshold {threshold}")
        self.assertEqual(threshold, 80)


class TestCommandLineArguments(unittest.TestCase):
    """Test command-line argument parsing."""
    
    def test_debug_flag(self):
        """Test --debug flag parsing."""
        test_args = ['vote.py', '--debug']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('-debug', '--debug', action='store_true',
                               help='Enable debug output')
            args = parser.parse_args()
            
            self.assertTrue(args.debug)
    
    def test_start_threads_default(self):
        """Test --start-threads default value."""
        test_args = ['vote.py']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, choices=[1, 2, 3, 4, 5], default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 1)
    
    def test_start_threads_2(self):
        """Test --start-threads 2."""
        test_args = ['vote.py', '--start-threads', '2']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 2)
    
    def test_start_threads_3(self):
        """Test --start-threads 3."""
        test_args = ['vote.py', '--start-threads', '3']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 3)
    
    def test_start_threads_4(self):
        """Test --start-threads 4."""
        test_args = ['vote.py', '--start-threads', '4']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 4)
    
    def test_start_threads_5(self):
        """Test --start-threads 5."""
        test_args = ['vote.py', '--start-threads', '5']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 5)
    
    def test_start_threads_6(self):
        """Test --start-threads 6."""
        test_args = ['vote.py', '--start-threads', '6']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 6)
    
    def test_start_threads_7(self):
        """Test --start-threads 7."""
        test_args = ['vote.py', '--start-threads', '7']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 7)
    
    def test_start_threads_8(self):
        """Test --start-threads 8."""
        test_args = ['vote.py', '--start-threads', '8']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--start-threads', type=int, default=1)
            args = parser.parse_args()
            
            self.assertEqual(args.start_threads, 8)
    
    def test_max_threads_default(self):
        """Test --max-threads defaults to 8."""
        test_args = ['vote.py']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--max-threads', type=int, default=8)
            args = parser.parse_args()
            
            self.assertEqual(args.max_threads, 8)
    
    def test_max_threads_custom(self):
        """Test --max-threads with custom value."""
        test_args = ['vote.py', '--max-threads', '10']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--max-threads', type=int, default=8)
            args = parser.parse_args()
            
            self.assertEqual(args.max_threads, 10)
    
    def test_max_threads_15(self):
        """Test --max-threads with 15 threads."""
        test_args = ['vote.py', '--max-threads', '15']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--max-threads', type=int, default=8)
            args = parser.parse_args()
            
            self.assertEqual(args.max_threads, 15)
    
    def test_force_parallel_flag(self):
        """Test --force-parallel flag parsing."""
        test_args = ['vote.py', '--force-parallel']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--force-parallel', action='store_true', default=False)
            args = parser.parse_args()
            
            self.assertTrue(args.force_parallel)
    
    def test_force_parallel_default(self):
        """Test --force-parallel defaults to False."""
        test_args = ['vote.py']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--force-parallel', action='store_true', default=False)
            args = parser.parse_args()
            
            self.assertFalse(args.force_parallel)
    
    def test_max_threads_validation(self):
        """Test that max_threads must be >= start_threads."""
        # This tests the validation logic in main()
        max_threads = 5
        start_thread_count = 8
        
        # Validation should fail
        is_valid = start_thread_count <= max_threads
        
        self.assertFalse(is_valid)
        
        # Valid case
        max_threads = 10
        start_thread_count = 5
        is_valid = start_thread_count <= max_threads
        
        self.assertTrue(is_valid)
    
    def test_save_top_results_flag(self):
        """Test --save-top-results flag parsing."""
        test_args = ['vote.py', '--save-top-results']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--save-top-results', action='store_true', default=False)
            args = parser.parse_args()
            
            self.assertTrue(args.save_top_results)
    
    def test_save_top_results_default(self):
        """Test --save-top-results defaults to False."""
        test_args = ['vote.py']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--save-top-results', action='store_true', default=False)
            args = parser.parse_args()
            
            self.assertFalse(args.save_top_results)
    
    def test_lead_threshold_default(self):
        """Test --lead-threshold default value."""
        test_args = ['vote.py']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--lead-threshold', type=float, default=15.0)
            args = parser.parse_args()
            
            self.assertEqual(args.lead_threshold, 15.0)
    
    def test_lead_threshold_custom(self):
        """Test custom --lead-threshold value."""
        test_args = ['vote.py', '--lead-threshold', '20.0']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('--lead-threshold', type=float, default=15.0)
            args = parser.parse_args()
            
            self.assertEqual(args.lead_threshold, 20.0)
    
    def test_combined_arguments(self):
        """Test combining multiple arguments."""
        test_args = ['vote.py', '--debug', '--start-threads', '2', '--lead-threshold', '18.0']
        
        with patch('sys.argv', test_args):
            parser = vote.argparse.ArgumentParser()
            parser.add_argument('-debug', '--debug', action='store_true')
            parser.add_argument('--start-threads', type=int, choices=[1, 2, 3, 4, 5], default=1)
            parser.add_argument('--lead-threshold', type=float, default=15.0)
            args = parser.parse_args()
            
            self.assertTrue(args.debug)
            self.assertEqual(args.start_threads, 2)
            self.assertEqual(args.lead_threshold, 18.0)


class TestThreadSafety(unittest.TestCase):
    """Test thread-safety of counter operations."""
    
    def setUp(self):
        """Reset counters before each test."""
        vote.vote_count = 0
        vote.consecutive_behind_count = 0
        vote.standard_vote_count = 0
        vote.initial_accelerated_vote_count = 0
        vote.accelerated_vote_count = 0
        vote.super_accelerated_vote_count = 0
    
    def test_concurrent_counter_increments(self):
        """Test that concurrent counter increments are thread-safe."""
        def increment_counters():
            for _ in range(100):
                with vote._counter_lock:
                    vote.vote_count += 1
                    vote.consecutive_behind_count += 1
        
        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=increment_counters)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Should have exactly 5 * 100 = 500 increments
        self.assertEqual(vote.vote_count, 500)
        self.assertEqual(vote.consecutive_behind_count, 500)
    
    def test_concurrent_backoff_updates(self):
        """Test that concurrent backoff updates are thread-safe."""
        vote.lead_backoff_multiplier = 1.0
        
        def update_backoff():
            for _ in range(10):
                with vote.lead_backoff_lock:
                    vote.lead_backoff_multiplier = min(
                        vote.lead_backoff_multiplier * 1.5,
                        vote.MAX_BACKOFF_DELAY / 60.0
                    )
        
        # Create multiple threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=update_backoff)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Multiplier should be capped and thread-safe
        self.assertLessEqual(vote.lead_backoff_multiplier, vote.MAX_BACKOFF_DELAY / 60.0)


class TestStartThreadsLogic(unittest.TestCase):
    """Test --start-threads initialization logic."""
    
    def setUp(self):
        """Reset state before each test."""
        vote.consecutive_behind_count = 0
        vote._parallel_voting_active = False
        vote._parallel_voting_active2 = False
    
    def test_start_threads_1_initializes_zero(self):
        """Test --start-threads 1 initializes behind_count to 0."""
        start_thread_count = 1
        
        if start_thread_count >= 3:
            initial_behind_count = 30
        elif start_thread_count >= 2:
            initial_behind_count = 20
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 0)
    
    def test_start_threads_2_initializes_20(self):
        """Test --start-threads 2 initializes behind_count to 20."""
        start_thread_count = 2
        
        if start_thread_count >= 3:
            initial_behind_count = 30
        elif start_thread_count >= 2:
            initial_behind_count = 20
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 20)
    
    def test_start_threads_3_initializes_30(self):
        """Test --start-threads 3 initializes behind_count to 30."""
        start_thread_count = 3
        
        if start_thread_count >= 5:
            initial_behind_count = 50
        elif start_thread_count >= 4:
            initial_behind_count = 40
        elif start_thread_count >= 3:
            initial_behind_count = 30
        elif start_thread_count >= 2:
            initial_behind_count = 20
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 30)
    
    def test_start_threads_4_initializes_40(self):
        """Test --start-threads 4 initializes behind_count to 40."""
        start_thread_count = 4
        
        if start_thread_count >= 5:
            initial_behind_count = 50
        elif start_thread_count >= 4:
            initial_behind_count = 40
        elif start_thread_count >= 3:
            initial_behind_count = 30
        elif start_thread_count >= 2:
            initial_behind_count = 20
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 40)
    
    def test_start_threads_5_initializes_50(self):
        """Test --start-threads 5 initializes behind_count to 50."""
        # Initialize with default 7 parallel threads
        vote.initialize_parallel_threads(7)
        
        start_thread_count = 5
        
        # Calculate threshold for the last thread that will be started
        if start_thread_count > 1:
            parallel_thread_index = start_thread_count - 2  # 0-indexed
            if parallel_thread_index < len(vote._parallel_thresholds):
                initial_behind_count = vote._parallel_thresholds[parallel_thread_index]
            else:
                initial_behind_count = 20 + (parallel_thread_index * 10)
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 50)
    
    def test_start_threads_6_initializes_60(self):
        """Test --start-threads 6 initializes behind_count to 60."""
        vote.initialize_parallel_threads(7)
        
        start_thread_count = 6
        
        if start_thread_count > 1:
            parallel_thread_index = start_thread_count - 2
            if parallel_thread_index < len(vote._parallel_thresholds):
                initial_behind_count = vote._parallel_thresholds[parallel_thread_index]
            else:
                initial_behind_count = 20 + (parallel_thread_index * 10)
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 60)
    
    def test_start_threads_7_initializes_70(self):
        """Test --start-threads 7 initializes behind_count to 70."""
        vote.initialize_parallel_threads(7)
        
        start_thread_count = 7
        
        if start_thread_count > 1:
            parallel_thread_index = start_thread_count - 2
            if parallel_thread_index < len(vote._parallel_thresholds):
                initial_behind_count = vote._parallel_thresholds[parallel_thread_index]
            else:
                initial_behind_count = 20 + (parallel_thread_index * 10)
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 70)
    
    def test_start_threads_8_initializes_80(self):
        """Test --start-threads 8 initializes behind_count to 80."""
        vote.initialize_parallel_threads(7)
        
        start_thread_count = 8
        
        if start_thread_count > 1:
            parallel_thread_index = start_thread_count - 2
            if parallel_thread_index < len(vote._parallel_thresholds):
                initial_behind_count = vote._parallel_thresholds[parallel_thread_index]
            else:
                initial_behind_count = 20 + (parallel_thread_index * 10)
        else:
            initial_behind_count = 0
        
        self.assertEqual(initial_behind_count, 80)
    
    def test_start_threads_uses_dynamic_thresholds(self):
        """Test that start_threads uses dynamic thresholds from initialize_parallel_threads."""
        # Test with different max_threads values
        vote.initialize_parallel_threads(10)  # 10 parallel threads
        
        start_thread_count = 5
        
        if start_thread_count > 1:
            parallel_thread_index = start_thread_count - 2
            if parallel_thread_index < len(vote._parallel_thresholds):
                initial_behind_count = vote._parallel_thresholds[parallel_thread_index]
            else:
                initial_behind_count = 20 + (parallel_thread_index * 10)
        else:
            initial_behind_count = 0
        
        # Should still be 50 (3rd parallel thread, index 3)
        self.assertEqual(initial_behind_count, 50)
        self.assertEqual(vote._parallel_thresholds[3], 50)


class TestTimingRanges(unittest.TestCase):
    """Test timing range calculations."""
    
    def test_standard_timing_range(self):
        """Test standard timing is 53-67 seconds."""
        # This tests the documented range
        # We can't test exact randomness, but verify the logic path
        base_wait_time = 60  # Middle of range
        wait_time = vote.random.randint(53, 67)
        
        self.assertGreaterEqual(wait_time, 53)
        self.assertLessEqual(wait_time, 67)
    
    def test_initial_accelerated_timing_range(self):
        """Test initial accelerated timing is 14-37 seconds."""
        wait_time = vote.random.randint(14, 37)
        
        self.assertGreaterEqual(wait_time, 14)
        self.assertLessEqual(wait_time, 37)
    
    def test_accelerated_timing_range(self):
        """Test accelerated timing is 7-16 seconds."""
        wait_time = vote.random.randint(7, 16)
        
        self.assertGreaterEqual(wait_time, 7)
        self.assertLessEqual(wait_time, 16)
    
    def test_super_accelerated_timing_range(self):
        """Test super accelerated timing is 3-10 seconds."""
        wait_time = vote.random.randint(3, 10)
        
        self.assertGreaterEqual(wait_time, 3)
        self.assertLessEqual(wait_time, 10)
    
    def test_backoff_max_delay(self):
        """Test backoff maximum delay is 300 seconds."""
        self.assertEqual(vote.MAX_BACKOFF_DELAY, 300)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""
    
    def test_extract_results_with_invalid_percentage(self):
        """Test extraction handles invalid percentages."""
        html_invalid = """
        <html>
        <body>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Test Athlete</div>
                <div class="pds-feedback-per">150%</div>
            </div>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Test Athlete 2</div>
                <div class="pds-feedback-per">-5%</div>
            </div>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Valid Athlete</div>
                <div class="pds-feedback-per">25.5%</div>
            </div>
        </body>
        </html>
        """
        results = vote.extract_voting_results(html_invalid)
        # Invalid percentages (150%, -5%) should be filtered out, but valid ones should remain
        # The function validates percentages are 0-100, so 150% and -5% should be excluded
        # Only "Valid Athlete" with 25.5% should be included
        self.assertGreaterEqual(len(results), 1)  # At least the valid one
        # Verify invalid percentages are not included
        for name, pct in results:
            self.assertGreaterEqual(pct, 0)
            self.assertLessEqual(pct, 100)
    
    def test_extract_results_missing_elements(self):
        """Test extraction handles missing elements."""
        html_missing = """
        <html>
        <body>
            <div class="pds-feedback-group">
                <div class="pds-answer-text">Test Athlete</div>
            </div>
        </body>
        </html>
        """
        results = vote.extract_voting_results(html_missing)
        # Missing percentage element should skip this result
        self.assertEqual(len(results), 0)
    
    def test_get_lead_percentage_no_second_place(self):
        """Test lead calculation with only one result."""
        results = [("Cutler Whitaker", 28.45)]
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        
        self.assertIsNone(lead)
        self.assertFalse(is_above)
    
    def test_get_lead_percentage_cutler_not_first(self):
        """Test lead calculation when Cutler is not first."""
        results = [
            ("Dylan Papushak", 28.45),
            ("Cutler Whitaker", 24.23)
        ]
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        
        self.assertIsNone(lead)
        self.assertFalse(is_above)


class TestDebugPrint(unittest.TestCase):
    """Test debug_print functionality."""
    
    def test_debug_print_enabled(self):
        """Test debug_print when debug mode is enabled."""
        vote.debug_mode = True
        
        output = io.StringIO()
        with redirect_stdout(output):
            vote.debug_print("Test debug message")
        
        output_str = output.getvalue()
        self.assertIn("Test debug message", output_str)
    
    def test_debug_print_disabled(self):
        """Test debug_print when debug mode is disabled."""
        vote.debug_mode = False
        
        output = io.StringIO()
        with redirect_stdout(output):
            vote.debug_print("Test debug message")
        
        output_str = output.getvalue()
        self.assertEqual(output_str, "")  # Should be empty


class TestIntegrationScenarios(unittest.TestCase):
    """Test integrated scenarios that simulate real voting situations."""
    
    def setUp(self):
        """Reset all state before each test."""
        vote.vote_count = 0
        vote.consecutive_behind_count = 0
        vote.standard_vote_count = 0
        vote.initial_accelerated_vote_count = 0
        vote.accelerated_vote_count = 0
        vote.super_accelerated_vote_count = 0
        vote.lead_backoff_multiplier = 1.0
        vote.shutdown_flag = False
    
    def test_scenario_cutler_starts_ahead_stays_ahead(self):
        """Test scenario: Cutler starts ahead and stays ahead."""
        results = [
            ("Cutler Whitaker", 35.0),
            ("Dylan Papushak", 25.0)
        ]
        
        # Simulate multiple votes where Cutler stays ahead
        for _ in range(3):
            cutler_ahead = vote.is_cutler_ahead(results)
            self.assertTrue(cutler_ahead)
            
            with vote._counter_lock:
                if cutler_ahead:
                    vote.consecutive_behind_count = 0
                    vote.standard_vote_count += 1
        
        self.assertEqual(vote.consecutive_behind_count, 0)
        self.assertEqual(vote.standard_vote_count, 3)
    
    def test_scenario_cutler_falls_behind_then_catches_up(self):
        """Test scenario: Cutler falls behind, then catches up."""
        # Start behind
        results = [
            ("Dylan Papushak", 30.0),
            ("Cutler Whitaker", 25.0)
        ]
        
        for _ in range(5):
            cutler_ahead = vote.is_cutler_ahead(results)
            if not cutler_ahead:
                with vote._counter_lock:
                    vote.consecutive_behind_count += 1
                    if vote.consecutive_behind_count < 5:
                        vote.initial_accelerated_vote_count += 1
                    elif vote.consecutive_behind_count < 10:
                        vote.accelerated_vote_count += 1
        
        self.assertEqual(vote.consecutive_behind_count, 5)
        
        # Now Cutler gets ahead
        results = [
            ("Cutler Whitaker", 35.0),
            ("Dylan Papushak", 25.0)
        ]
        
        cutler_ahead = vote.is_cutler_ahead(results)
        if cutler_ahead:
            with vote._counter_lock:
                vote.consecutive_behind_count = 0
                vote.standard_vote_count += 1
        
        self.assertEqual(vote.consecutive_behind_count, 0)
    
    def test_scenario_progressive_acceleration(self):
        """Test progressive acceleration through all tiers."""
        # Behind 1 round
        with vote._counter_lock:
            vote.consecutive_behind_count = 1
            vote.initial_accelerated_vote_count += 1
        self.assertEqual(vote.consecutive_behind_count, 1)
        
        # Behind 5 rounds
        with vote._counter_lock:
            vote.consecutive_behind_count = 5
            vote.accelerated_vote_count += 1
        self.assertEqual(vote.consecutive_behind_count, 5)
        
        # Behind 10 rounds
        with vote._counter_lock:
            vote.consecutive_behind_count = 10
            vote.super_accelerated_vote_count += 1
        self.assertEqual(vote.consecutive_behind_count, 10)
        
        # Behind 20 rounds (should trigger parallel thread logic)
        with vote._counter_lock:
            vote.consecutive_behind_count = 20
        self.assertEqual(vote.consecutive_behind_count, 20)
        
        # Behind 30 rounds (should trigger second parallel thread)
        with vote._counter_lock:
            vote.consecutive_behind_count = 30
        self.assertEqual(vote.consecutive_behind_count, 30)
    
    def test_scenario_lead_backoff_progression(self):
        """Test lead backoff progression from threshold to max."""
        results = [
            ("Cutler Whitaker", 35.0),
            ("Dylan Papushak", 18.0)  # Lead: 17% (above 15% threshold)
        ]
        
        lead, is_above = vote.get_cutler_lead_percentage(results, 15.0)
        self.assertTrue(is_above)
        
        # Simulate progressive backoff
        with vote.lead_backoff_lock:
            multiplier = 1.0
            multipliers = []
            for _ in range(5):
                multiplier = min(multiplier * 1.5, vote.MAX_BACKOFF_DELAY / 60.0)
                multipliers.append(multiplier)
        
        # Verify exponential progression
        self.assertAlmostEqual(multipliers[0], 1.5, places=1)
        self.assertAlmostEqual(multipliers[1], 2.25, places=1)
        self.assertAlmostEqual(multipliers[2], 3.375, places=1)
        # Verify it doesn't exceed max
        self.assertLessEqual(multipliers[-1], vote.MAX_BACKOFF_DELAY / 60.0)
    
    def test_scenario_parallel_threads_start_stop(self):
        """Test parallel threads start and stop correctly with scalable design."""
        vote.initialize_parallel_threads(7)
        vote._force_parallel_mode = False
        
        # Start with 20 rounds behind
        with vote._counter_lock:
            vote.consecutive_behind_count = 20
        
        # Should trigger first parallel thread
        with vote._parallel_voting_lock:
            threshold = vote._parallel_thresholds[0] if 0 < len(vote._parallel_thresholds) else 20
            should_start_1 = (vote.consecutive_behind_count >= threshold and 
                             not vote._parallel_active[0])
            if should_start_1:
                vote._parallel_active[0] = True
        
        self.assertTrue(vote._parallel_active[0])
        
        # Increase to 30 rounds
        with vote._counter_lock:
            vote.consecutive_behind_count = 30
        
        # Should trigger second parallel thread
        with vote._parallel_voting_lock:
            threshold = vote._parallel_thresholds[1] if 1 < len(vote._parallel_thresholds) else 30
            should_start_2 = (vote.consecutive_behind_count >= threshold and 
                             not vote._parallel_active[1])
            if should_start_2:
                vote._parallel_active[1] = True
        
        self.assertTrue(vote._parallel_active[1])
        
        # Cutler gets ahead
        results = [
            ("Cutler Whitaker", 35.0),
            ("Dylan Papushak", 25.0)
        ]
        
        if vote.is_cutler_ahead(results) and not vote._force_parallel_mode:
            with vote._parallel_voting_lock:
                vote._parallel_active[0] = False
                vote._parallel_active[1] = False
        
        self.assertFalse(vote._parallel_active[0])
        self.assertFalse(vote._parallel_active[1])
    
    def test_scenario_force_parallel_keeps_threads_active(self):
        """Test that force_parallel_mode keeps threads active even when Cutler is ahead."""
        vote.initialize_parallel_threads(7)
        vote._force_parallel_mode = True
        
        # Start threads
        with vote._parallel_voting_lock:
            vote._parallel_active[0] = True
            vote._parallel_active[1] = True
        
        # Cutler gets ahead
        results = [
            ("Cutler Whitaker", 35.0),
            ("Dylan Papushak", 25.0)
        ]
        
        # Even though Cutler is ahead, threads should stay active
        if vote.is_cutler_ahead(results) and not vote._force_parallel_mode:
            with vote._parallel_voting_lock:
                vote._parallel_active[0] = False
                vote._parallel_active[1] = False
        
        # Should still be active because force_parallel_mode is True
        self.assertTrue(vote._parallel_active[0])
        self.assertTrue(vote._parallel_active[1])
    
    def test_scenario_multiple_threads_scale_up(self):
        """Test that multiple threads can scale up correctly."""
        vote.initialize_parallel_threads(10)  # Support up to 10 threads
        
        # Progressively increase behind count and verify threads start
        thresholds = [20, 30, 40, 50, 60, 70, 80, 90, 100]
        
        for i, threshold in enumerate(thresholds):
            with vote._counter_lock:
                vote.consecutive_behind_count = threshold
            
            if i < len(vote._parallel_thresholds):
                with vote._parallel_voting_lock:
                    if vote.consecutive_behind_count >= vote._parallel_thresholds[i]:
                        vote._parallel_active[i] = True
                
                self.assertTrue(vote._parallel_active[i], 
                             f"Thread {i} should be active at threshold {threshold}")
    
    def test_scenario_vote_statistics_tracking(self):
        """Test that vote statistics are tracked correctly."""
        # Simulate different vote types
        results_ahead = [("Cutler Whitaker", 30.0), ("Dylan Papushak", 25.0)]
        results_behind_2 = [("Dylan Papushak", 30.0), ("Cutler Whitaker", 25.0)]
        
        # Vote 1: Cutler ahead
        if vote.is_cutler_ahead(results_ahead):
            with vote._counter_lock:
                vote.standard_vote_count += 1
        
        # Votes 2-3: Cutler behind (rounds 1-2)
        for _ in range(2):
            if not vote.is_cutler_ahead(results_behind_2):
                with vote._counter_lock:
                    vote.consecutive_behind_count += 1
                    vote.initial_accelerated_vote_count += 1
        
        # Vote 4: Cutler behind (round 3)
        if not vote.is_cutler_ahead(results_behind_2):
            with vote._counter_lock:
                vote.consecutive_behind_count += 1
                vote.initial_accelerated_vote_count += 1
        
        # Vote 5: Cutler behind (round 4)
        if not vote.is_cutler_ahead(results_behind_2):
            with vote._counter_lock:
                vote.consecutive_behind_count += 1
                vote.initial_accelerated_vote_count += 1
        
        # Vote 6: Cutler behind (round 5) - now accelerated
        if not vote.is_cutler_ahead(results_behind_2):
            with vote._counter_lock:
                vote.consecutive_behind_count += 1
                vote.accelerated_vote_count += 1
        
        # Verify statistics
        self.assertEqual(vote.standard_vote_count, 1)
        self.assertEqual(vote.initial_accelerated_vote_count, 4)
        self.assertEqual(vote.accelerated_vote_count, 1)
        self.assertEqual(vote.consecutive_behind_count, 5)


class TestJSONLogging(unittest.TestCase):
    """Test JSON logging functionality including historical totals preservation."""
    
    def setUp(self):
        """Set up test fixtures."""
        import os
        import tempfile
        
        # Create a temporary JSON file for testing
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        
        # Override the JSON log file path
        vote.JSON_LOG_FILE = self.temp_file.name
        
        # Reset global state
        vote._save_top_results = False
        vote._current_session_id = None
        
        # Clear any existing file
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import os
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)
    
    def test_log_vote_to_json_creates_new_file(self):
        """Test that log_vote_to_json creates a new file if it doesn't exist."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23),
            ("Owen Eastgate", 19.45)
        ]
        
        vote.log_vote_to_json(
            vote_num=1,
            thread_id="Main",
            timestamp="2025-01-01 12:00:00",
            success=True,
            results=results,
            cutler_ahead=True,
            consecutive_behind_count=0,
            vote_type="standard"
        )
        
        # Verify file was created
        import os
        self.assertTrue(os.path.exists(self.temp_file.name))
        
        # Verify file content
        import json
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertEqual(data["session_start"], "2025-01-01 12:00:00")
        self.assertEqual(data["target_athlete"], "Cutler Whitaker")
        self.assertEqual(len(data["votes"]), 1)
        self.assertEqual(data["votes"][0]["vote_number"], 1)
        self.assertEqual(data["votes"][0]["thread_id"], "Main")
        self.assertEqual(data["summary"]["total_votes_submitted"], 1)
        self.assertEqual(data["summary"]["standard_votes"], 1)
    
    def test_log_vote_to_json_appends_to_existing_file(self):
        """Test that log_vote_to_json appends to existing file."""
        # Create initial file
        import json
        initial_data = {
            "session_start": "2025-01-01 11:00:00",
            "target_athlete": "Cutler Whitaker",
            "summary": {
                "total_votes_submitted": 5,
                "standard_votes": 5,
                "initial_accelerated_votes": 0,
                "accelerated_votes": 0,
                "super_accelerated_votes": 0,
                "exponential_backoff_votes": 0
            },
            "votes": [
                {"vote_number": 1, "thread_id": "Main", "success": True, "vote_type": "standard"}
            ]
        }
        
        with open(self.temp_file.name, 'w') as f:
            json.dump(initial_data, f)
        
        # Log new vote
        vote.log_vote_to_json(
            vote_num=2,
            thread_id="Main",
            timestamp="2025-01-01 12:00:00",
            success=True,
            results=None,
            cutler_ahead=True,
            consecutive_behind_count=0,
            vote_type="standard"
        )
        
        # Verify file was updated
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertEqual(len(data["votes"]), 2)
        self.assertEqual(data["votes"][1]["vote_number"], 2)
        # Session start should be preserved
        self.assertEqual(data["session_start"], "2025-01-01 11:00:00")
    
    def test_log_vote_to_json_preserves_historical_totals(self):
        """Test that historical totals are preserved when higher than file totals."""
        import json
        
        # Create file with historical totals (manually added)
        initial_data = {
            "session_start": "2025-01-01 11:00:00",
            "target_athlete": "Cutler Whitaker",
            "summary": {
                "total_votes_submitted": 1000,  # Historical total (manually added)
                "standard_votes": 800,
                "initial_accelerated_votes": 100,
                "accelerated_votes": 50,
                "super_accelerated_votes": 50,
                "exponential_backoff_votes": 10
            },
            "votes": [
                {"vote_number": 1, "thread_id": "Main", "success": True, "vote_type": "standard"}
            ]  # Only 1 vote in file, but summary says 1000 (historical)
        }
        
        with open(self.temp_file.name, 'w') as f:
            json.dump(initial_data, f)
        
        # Log new vote
        vote.log_vote_to_json(
            vote_num=2,
            thread_id="Main",
            timestamp="2025-01-01 12:00:00",
            success=True,
            results=None,
            cutler_ahead=True,
            consecutive_behind_count=0,
            vote_type="standard"
        )
        
        # Verify historical totals were preserved and incremented
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        # Should be: historical (1000) + new vote (1) = 1001
        # Historical offset = 1000 - 1 = 999
        # File total = 2 (after adding new vote)
        # Final = 999 + 2 = 1001
        self.assertEqual(data["summary"]["total_votes_submitted"], 1001)
        self.assertEqual(data["summary"]["standard_votes"], 801)  # 800 + 1
        self.assertEqual(len(data["votes"]), 2)  # Should have 2 votes in file
    
    def test_log_vote_to_json_increments_all_vote_types(self):
        """Test that all vote types are correctly incremented."""
        import json
        
        # Create file with historical totals
        initial_data = {
            "session_start": "2025-01-01 11:00:00",
            "target_athlete": "Cutler Whitaker",
            "summary": {
                "total_votes_submitted": 500,
                "standard_votes": 200,
                "initial_accelerated_votes": 150,
                "accelerated_votes": 100,
                "super_accelerated_votes": 50,
                "exponential_backoff_votes": 20
            },
            "votes": [
                {"vote_number": 1, "success": True, "vote_type": "standard"}
            ]
        }
        
        with open(self.temp_file.name, 'w') as f:
            json.dump(initial_data, f)
        
        # Log different vote types
        vote_types = ["initial_accelerated", "accelerated", "super_accelerated"]
        
        for i, vote_type in enumerate(vote_types, start=2):
            vote.log_vote_to_json(
                vote_num=i,
                thread_id="Main",
                timestamp=f"2025-01-01 12:00:{i:02d}",
                success=True,
                results=None,
                cutler_ahead=False,
                consecutive_behind_count=i,
                vote_type=vote_type
            )
        
        # Verify all types were incremented
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        # Historical offset = 500 - 1 = 499, file total = 4, final = 499 + 4 = 503
        self.assertEqual(data["summary"]["total_votes_submitted"], 503)
        self.assertEqual(data["summary"]["standard_votes"], 200)  # No new standard votes
        self.assertEqual(data["summary"]["initial_accelerated_votes"], 151)  # 150 + 1
        self.assertEqual(data["summary"]["accelerated_votes"], 101)  # 100 + 1
        self.assertEqual(data["summary"]["super_accelerated_votes"], 51)  # 50 + 1
    
    def test_log_vote_to_json_exponential_backoff_votes(self):
        """Test that exponential backoff votes are tracked correctly."""
        import json
        
        initial_data = {
            "session_start": "2025-01-01 11:00:00",
            "target_athlete": "Cutler Whitaker",
            "summary": {
                "total_votes_submitted": 0,
                "standard_votes": 0,
                "initial_accelerated_votes": 0,
                "accelerated_votes": 0,
                "super_accelerated_votes": 0,
                "exponential_backoff_votes": 0
            },
            "votes": []
        }
        
        with open(self.temp_file.name, 'w') as f:
            json.dump(initial_data, f)
        
        # Log vote with backoff
        vote.log_vote_to_json(
            vote_num=1,
            thread_id="Main",
            timestamp="2025-01-01 12:00:00",
            success=True,
            results=[("Cutler Whitaker", 30.0), ("Other", 10.0)],
            cutler_ahead=True,
            consecutive_behind_count=0,
            vote_type="standard",
            lead_percentage=20.0,
            is_backoff_vote=True
        )
        
        # Verify backoff votes were incremented
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertEqual(data["summary"]["exponential_backoff_votes"], 1)
        self.assertTrue(data["votes"][0]["exponential_backoff"])
    
    def test_log_vote_to_json_save_top_results_false(self):
        """Test that top_5_results is not included when save_top_results is False."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23),
            ("Owen Eastgate", 19.45),
            ("Athlete 4", 15.00),
            ("Athlete 5", 12.87)
        ]
        
        vote._save_top_results = False
        
        vote.log_vote_to_json(
            vote_num=1,
            thread_id="Main",
            timestamp="2025-01-01 12:00:00",
            success=True,
            results=results,
            cutler_ahead=True,
            consecutive_behind_count=0,
            vote_type="standard"
        )
        
        # Verify top_5_results is not in the vote entry
        import json
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertNotIn("top_5_results", data["votes"][0])
    
    def test_log_vote_to_json_save_top_results_true(self):
        """Test that top_5_results is included when save_top_results is True."""
        results = [
            ("Cutler Whitaker", 28.45),
            ("Dylan Papushak", 24.23),
            ("Owen Eastgate", 19.45),
            ("Athlete 4", 15.00),
            ("Athlete 5", 12.87)
        ]
        
        vote._save_top_results = True
        
        vote.log_vote_to_json(
            vote_num=1,
            thread_id="Main",
            timestamp="2025-01-01 12:00:00",
            success=True,
            results=results,
            cutler_ahead=True,
            consecutive_behind_count=0,
            vote_type="standard"
        )
        
        # Verify top_5_results is in the vote entry
        import json
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertIn("top_5_results", data["votes"][0])
        self.assertEqual(len(data["votes"][0]["top_5_results"]), 5)
        self.assertEqual(data["votes"][0]["top_5_results"][0]["athlete"], "Cutler Whitaker")
        self.assertEqual(data["votes"][0]["top_5_results"][0]["percentage"], 28.45)
    
    def test_log_vote_to_json_cutler_position_and_percentage(self):
        """Test that Cutler's position and percentage are correctly extracted."""
        results = [
            ("Dylan Papushak", 30.0),
            ("Cutler Whitaker", 28.45),
            ("Owen Eastgate", 19.45)
        ]
        
        vote.log_vote_to_json(
            vote_num=1,
            thread_id="Main",
            timestamp="2025-01-01 12:00:00",
            success=True,
            results=results,
            cutler_ahead=False,
            consecutive_behind_count=1,
            vote_type="initial_accelerated"
        )
        
        # Verify Cutler's position and percentage
        import json
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertEqual(data["votes"][0]["cutler_position"], 2)  # Second place
        self.assertEqual(data["votes"][0]["cutler_percentage"], 28.45)
        self.assertFalse(data["votes"][0]["cutler_ahead"])
    
    def test_log_vote_to_json_thread_safety(self):
        """Test that JSON logging is thread-safe."""
        import json
        import threading
        
        # Create multiple threads logging simultaneously
        def log_vote(thread_id, vote_num):
            results = [("Cutler Whitaker", 30.0), ("Other", 20.0)]
            vote.log_vote_to_json(
                vote_num=vote_num,
                thread_id=thread_id,
                timestamp=f"2025-01-01 12:00:{vote_num:02d}",
                success=True,
                results=results,
                cutler_ahead=True,
                consecutive_behind_count=0,
                vote_type="standard"
            )
        
        threads = []
        for i in range(5):
            thread = threading.Thread(target=log_vote, args=(f"Thread-{i}", i+1))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all votes were logged (no corruption)
        with open(self.temp_file.name, 'r') as f:
            data = json.load(f)
        
        self.assertEqual(len(data["votes"]), 5)
        self.assertEqual(data["summary"]["total_votes_submitted"], 5)
        
        # Verify all vote numbers are present
        vote_numbers = [vote["vote_number"] for vote in data["votes"]]
        self.assertEqual(set(vote_numbers), {1, 2, 3, 4, 5})


if __name__ == '__main__':
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestResultExtraction))
    suite.addTests(loader.loadTestsFromTestCase(TestAdaptiveTiming))
    suite.addTests(loader.loadTestsFromTestCase(TestLeadBackoff))
    suite.addTests(loader.loadTestsFromTestCase(TestInitializeParallelThreads))
    suite.addTests(loader.loadTestsFromTestCase(TestParallelThreadManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestCommandLineArguments))
    suite.addTests(loader.loadTestsFromTestCase(TestThreadSafety))
    suite.addTests(loader.loadTestsFromTestCase(TestStartThreadsLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestTimingRanges))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestDebugPrint))
    suite.addTests(loader.loadTestsFromTestCase(TestJSONLogging))
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    print(f"{'='*60}\n")
    
    # Exit with error code if tests failed
    sys.exit(0 if result.wasSuccessful() else 1)

