#!/usr/bin/env python3
"""
Thread Performance Benchmarking Tool

This script measures voting performance at different thread counts to identify
optimal thread count and the point where diminishing returns occur.

The benchmark tool:
- Tests voting performance with 1 to N threads
- Measures throughput (votes per minute)
- Tracks resource usage (memory, CPU)
- Calculates per-thread efficiency
- Identifies where adding more threads provides <10% improvement
- Provides recommendations for optimal thread count

Metrics Collected:
- Votes per minute (overall throughput)
- Votes per thread per minute (efficiency)
- Success rate (percentage of successful votes)
- Average/median vote time
- Memory usage (average and peak)
- CPU usage (average and peak)
- Error count

Usage:
    python3 benchmark_threads.py --threads 1,2,3,4,5 --duration 300
    
    --threads: Comma-separated list of thread counts to test
    --duration: Duration in seconds to run each benchmark (default: 300 = 5 minutes)

Dependencies:
- psutil: System resource monitoring (optional but recommended)
- vote: The voting module to benchmark
"""

import argparse
import time
import threading
import psutil
import sys
from collections import defaultdict
from datetime import datetime
import statistics

# Import the voting module
import vote

# Global metrics collection
# This dictionary stores aggregate metrics across all benchmark threads.
# All access is protected by the 'lock' to ensure thread safety.
metrics = {
    'votes_submitted': 0,      # Count of successful votes
    'votes_failed': 0,         # Count of failed votes
    'vote_times': [],          # List of time taken for each vote (in seconds)
    'memory_usage': [],        # List of memory usage samples (in MB)
    'cpu_usage': [],           # List of CPU usage samples (as percentage)
    'errors': [],              # List of error messages encountered
    'lock': threading.Lock()   # Thread-safe lock for accessing metrics
}

# Performance tracking per thread
# This dictionary tracks individual thread performance statistics.
# Key: thread_id (int), Value: dict with performance metrics
# Each thread's stats include:
#   - votes: Number of successful votes
#   - failures: Number of failed votes
#   - total_time: Sum of all vote times for this thread
#   - min_time: Minimum vote time observed
#   - max_time: Maximum vote time observed
thread_stats = defaultdict(lambda: {
    'votes': 0,
    'failures': 0,
    'total_time': 0.0,
    'min_time': float('inf'),
    'max_time': 0.0
})

def collect_system_metrics():
    """
    Collect system resource usage metrics for the current process.
    
    This function uses psutil to gather real-time resource usage statistics
    including memory consumption and CPU utilization. The metrics are stored
    in the global metrics dictionary for later analysis.
    
    Returns:
        tuple: (memory_mb, cpu_percent) where:
            - memory_mb (float): Memory usage in megabytes (RSS - Resident Set Size)
            - cpu_percent (float): CPU usage as a percentage (0-100)
    
    Note:
        This function is thread-safe and appends metrics to global lists
        protected by a lock.
    """
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 / 1024  # MB
    cpu_percent = process.cpu_percent(interval=0.1)
    
    with metrics['lock']:
        metrics['memory_usage'].append(memory_mb)
        metrics['cpu_usage'].append(cpu_percent)
    
    return memory_mb, cpu_percent

def benchmark_voting_thread(thread_id, duration, target_time):
    """
    Run voting in a thread and collect performance metrics.
    
    This function runs a voting loop in a separate thread for the specified
    duration, collecting metrics on vote success, timing, and failures.
    All metrics are stored in thread-safe global data structures.
    
    Args:
        thread_id (int): Unique identifier for this benchmark thread
        duration (float): Duration in seconds to run the benchmark
        target_time (float): Start time of the benchmark (for synchronization)
    
    Returns:
        None: This function runs in a loop and updates global metrics
    
    Note:
        - Uses Super Accelerated timing (3-10 seconds) between votes
        - Thread-safe metrics collection using locks
        - Handles exceptions gracefully and records them in metrics
        - Stops when duration expires or shutdown_flag is set
    """
    start_time = time.time()
    thread_stats[thread_id] = {
        'votes': 0,
        'failures': 0,
        'total_time': 0.0,
        'min_time': float('inf'),
        'max_time': 0.0,
        'start_time': start_time
    }
    
    print(f"[Thread-{thread_id}] Starting benchmark...")
    
    while (time.time() - start_time) < duration and not vote.shutdown_flag:
        vote_start = time.time()
        
        try:
            # Perform vote iteration
            success, results, cutler_ahead = vote.perform_vote_iteration(thread_id=f"Bench-{thread_id}")
            
            vote_time = time.time() - vote_start
            
            with metrics['lock']:
                if success:
                    metrics['votes_submitted'] += 1
                    metrics['vote_times'].append(vote_time)
                    thread_stats[thread_id]['votes'] += 1
                else:
                    metrics['votes_failed'] += 1
                    thread_stats[thread_id]['failures'] += 1
                
                thread_stats[thread_id]['total_time'] += vote_time
                thread_stats[thread_id]['min_time'] = min(thread_stats[thread_id]['min_time'], vote_time)
                thread_stats[thread_id]['max_time'] = max(thread_stats[thread_id]['max_time'], vote_time)
        
        except Exception as e:
            with metrics['lock']:
                metrics['votes_failed'] += 1
                metrics['errors'].append(f"Thread-{thread_id}: {str(e)}")
                thread_stats[thread_id]['failures'] += 1
        
        # Wait before next vote (using super accelerated timing for benchmarking)
        wait_time = vote.random.randint(3, 10)
        time.sleep(wait_time)
    
    print(f"[Thread-{thread_id}] Completed benchmark")

def run_benchmark(num_threads, duration_seconds):
    """
    Run a complete benchmark test with the specified number of threads.
    
    This function orchestrates a benchmark run by:
    1. Resetting all metrics and vote module state
    2. Starting a resource monitoring thread
    3. Launching N voting threads (where N = num_threads)
    4. Collecting metrics during the benchmark
    5. Calculating aggregate statistics
    6. Returning comprehensive results
    
    Args:
        num_threads (int): Number of voting threads to run concurrently
        duration_seconds (int): Duration in seconds to run the benchmark
    
    Returns:
        dict: Dictionary containing comprehensive benchmark results with keys:
            - num_threads (int): Number of threads tested
            - duration (float): Actual elapsed time
            - total_votes (int): Total vote attempts
            - votes_submitted (int): Successful votes
            - votes_failed (int): Failed votes
            - success_rate (float): Percentage of successful votes
            - votes_per_minute (float): Overall throughput
            - votes_per_thread_per_minute (float): Per-thread efficiency
            - avg_vote_time (float): Average time per vote in seconds
            - median_vote_time (float): Median time per vote in seconds
            - avg_memory_mb (float): Average memory usage in MB
            - max_memory_mb (float): Peak memory usage in MB
            - avg_cpu_percent (float): Average CPU usage percentage
            - max_cpu_percent (float): Peak CPU usage percentage
            - errors (int): Number of errors encountered
            - thread_efficiency (list): Per-thread performance breakdown
    """
    print(f"\n{'='*70}")
    print(f"BENCHMARK: {num_threads} Thread(s) for {duration_seconds} seconds")
    print(f"{'='*70}\n")
    
    # Reset metrics
    global metrics, thread_stats
    metrics = {
        'votes_submitted': 0,
        'votes_failed': 0,
        'vote_times': [],
        'memory_usage': [],
        'cpu_usage': [],
        'errors': [],
        'lock': threading.Lock()
    }
    thread_stats = defaultdict(lambda: {
        'votes': 0,
        'failures': 0,
        'total_time': 0.0,
        'min_time': float('inf'),
        'max_time': 0.0
    })
    
    # Reset vote module state
    vote.vote_count = 0
    vote.consecutive_behind_count = 0
    vote.shutdown_flag = False
    
    # Start monitoring thread
    monitoring_active = threading.Event()
    
    def monitor_resources():
        """Monitor system resources during benchmark."""
        while not monitoring_active.is_set():
            collect_system_metrics()
            time.sleep(2)  # Sample every 2 seconds
    
    monitor_thread = threading.Thread(target=monitor_resources, daemon=True)
    monitor_thread.start()
    
    # Start voting threads
    threads = []
    start_time = time.time()
    
    for i in range(num_threads):
        thread = threading.Thread(
            target=benchmark_voting_thread,
            args=(i, duration_seconds, start_time),
            daemon=True
        )
        threads.append(thread)
        thread.start()
        time.sleep(0.5)  # Stagger thread starts slightly
    
    # Wait for all threads to complete or duration expires
    for thread in threads:
        thread.join(timeout=duration_seconds + 10)
    
    # Stop monitoring
    monitoring_active.set()
    
    # Calculate final metrics
    elapsed_time = time.time() - start_time
    
    with metrics['lock']:
        total_votes = metrics['votes_submitted'] + metrics['votes_failed']
        success_rate = (metrics['votes_submitted'] / total_votes * 100) if total_votes > 0 else 0
        votes_per_minute = (metrics['votes_submitted'] / elapsed_time * 60) if elapsed_time > 0 else 0
        
        avg_vote_time = statistics.mean(metrics['vote_times']) if metrics['vote_times'] else 0
        median_vote_time = statistics.median(metrics['vote_times']) if metrics['vote_times'] else 0
        
        avg_memory = statistics.mean(metrics['memory_usage']) if metrics['memory_usage'] else 0
        max_memory = max(metrics['memory_usage']) if metrics['memory_usage'] else 0
        
        avg_cpu = statistics.mean(metrics['cpu_usage']) if metrics['cpu_usage'] else 0
        max_cpu = max(metrics['cpu_usage']) if metrics['cpu_usage'] else 0
    
    # Calculate per-thread metrics
    thread_efficiency = []
    for thread_id, stats in thread_stats.items():
        if stats['votes'] > 0:
            avg_thread_time = stats['total_time'] / stats['votes']
            thread_efficiency.append({
                'thread_id': thread_id,
                'votes': stats['votes'],
                'failures': stats['failures'],
                'avg_time': avg_thread_time,
                'min_time': stats['min_time'],
                'max_time': stats['max_time']
            })
    
    return {
        'num_threads': num_threads,
        'duration': elapsed_time,
        'total_votes': total_votes,
        'votes_submitted': metrics['votes_submitted'],
        'votes_failed': metrics['votes_failed'],
        'success_rate': success_rate,
        'votes_per_minute': votes_per_minute,
        'votes_per_thread_per_minute': votes_per_minute / num_threads if num_threads > 0 else 0,
        'avg_vote_time': avg_vote_time,
        'median_vote_time': median_vote_time,
        'avg_memory_mb': avg_memory,
        'max_memory_mb': max_memory,
        'avg_cpu_percent': avg_cpu,
        'max_cpu_percent': max_cpu,
        'errors': len(metrics['errors']),
        'thread_efficiency': thread_efficiency
    }

def print_results(results):
    """
    Print formatted benchmark results to stdout.
    
    Displays a comprehensive summary of benchmark results including
    performance metrics, resource usage, and per-thread statistics
    in a human-readable format.
    
    Args:
        results (dict): Benchmark results dictionary from run_benchmark()
            Must contain all keys returned by run_benchmark()
    
    Returns:
        None: This function only prints output
    """
    print(f"\n{'='*70}")
    print(f"RESULTS: {results['num_threads']} Thread(s)")
    print(f"{'='*70}")
    print(f"Duration:                    {results['duration']:.1f} seconds")
    print(f"Total vote attempts:          {results['total_votes']}")
    print(f"Successful votes:             {results['votes_submitted']}")
    print(f"Failed votes:                 {results['votes_failed']}")
    print(f"Success rate:                {results['success_rate']:.1f}%")
    print(f"\nPerformance:")
    print(f"  Votes per minute:           {results['votes_per_minute']:.2f}")
    print(f"  Votes per thread/min:       {results['votes_per_thread_per_minute']:.2f}")
    print(f"  Average vote time:          {results['avg_vote_time']:.2f} seconds")
    print(f"  Median vote time:           {results['median_vote_time']:.2f} seconds")
    print(f"\nResource Usage:")
    print(f"  Average memory:             {results['avg_memory_mb']:.1f} MB")
    print(f"  Peak memory:                {results['max_memory_mb']:.1f} MB")
    print(f"  Average CPU:                {results['avg_cpu_percent']:.1f}%")
    print(f"  Peak CPU:                   {results['max_cpu_percent']:.1f}%")
    print(f"  Errors encountered:         {results['errors']}")
    
    if results['thread_efficiency']:
        print(f"\nPer-Thread Performance:")
        for thread_info in results['thread_efficiency']:
            print(f"  Thread-{thread_info['thread_id']}:")
            print(f"    Votes: {thread_info['votes']}, Failures: {thread_info['failures']}")
            print(f"    Avg time: {thread_info['avg_time']:.2f}s, "
                  f"Range: {thread_info['min_time']:.2f}s - {thread_info['max_time']:.2f}s")
    
    print(f"{'='*70}\n")

def compare_results(all_results):
    """
    Compare benchmark results across different thread counts.
    
    This function performs comparative analysis of multiple benchmark runs
    to identify:
    - Best overall throughput (votes per minute)
    - Best per-thread efficiency
    - Diminishing returns points (where adding threads provides <10% improvement)
    - Recommended optimal thread count
    
    Args:
        all_results (list): List of result dictionaries from run_benchmark()
            Each dictionary should contain results for a different thread count.
            Results should be sorted by thread count for best analysis.
    
    Returns:
        None: This function prints analysis to stdout
    
    Note:
        The function identifies diminishing returns by comparing sequential
        thread counts and flagging when improvement drops below 10%.
    """
    print(f"\n{'='*70}")
    print("COMPARATIVE ANALYSIS")
    print(f"{'='*70}\n")
    
    # Sort by thread count
    sorted_results = sorted(all_results, key=lambda x: x['num_threads'])
    
    # Print comparison table
    print(f"{'Threads':<10} {'Votes/min':<12} {'Votes/thread/min':<18} {'Success %':<12} {'Avg Mem (MB)':<15} {'Peak CPU %':<12}")
    print("-" * 80)
    
    for r in sorted_results:
        print(f"{r['num_threads']:<10} {r['votes_per_minute']:<12.2f} {r['votes_per_thread_per_minute']:<18.2f} "
              f"{r['success_rate']:<12.1f} {r['avg_memory_mb']:<15.1f} {r['max_cpu_percent']:<12.1f}")
    
    print("\n" + "="*70)
    print("ANALYSIS")
    print("="*70)
    
    # Find optimal thread count (highest votes/min with good efficiency)
    best_throughput = max(sorted_results, key=lambda x: x['votes_per_minute'])
    best_efficiency = max(sorted_results, key=lambda x: x['votes_per_thread_per_minute'])
    
    print(f"\nHighest Throughput: {best_throughput['num_threads']} threads")
    print(f"  → {best_throughput['votes_per_minute']:.2f} votes/minute")
    print(f"  → {best_throughput['success_rate']:.1f}% success rate")
    
    print(f"\nBest Per-Thread Efficiency: {best_efficiency['num_threads']} threads")
    print(f"  → {best_efficiency['votes_per_thread_per_minute']:.2f} votes/thread/minute")
    
    # Identify diminishing returns
    print(f"\nDiminishing Returns Analysis:")
    print(f"  (Looking for where adding threads stops improving throughput)\n")
    
    for i in range(1, len(sorted_results)):
        prev = sorted_results[i-1]
        curr = sorted_results[i]
        
        improvement = curr['votes_per_minute'] - prev['votes_per_minute']
        improvement_pct = (improvement / prev['votes_per_minute'] * 100) if prev['votes_per_minute'] > 0 else 0
        
        thread_increase = curr['num_threads'] - prev['num_threads']
        efficiency_change = curr['votes_per_thread_per_minute'] - prev['votes_per_thread_per_minute']
        
        if improvement_pct < 10 and thread_increase > 0:
            print(f"  ⚠️  {prev['num_threads']} → {curr['num_threads']} threads:")
            print(f"     Only {improvement_pct:.1f}% improvement ({improvement:.2f} votes/min)")
            print(f"     Efficiency dropped by {efficiency_change:.2f} votes/thread/min")
            print(f"     → Diminishing returns detected!")
            print()
        elif improvement_pct >= 10:
            print(f"  ✅ {prev['num_threads']} → {curr['num_threads']} threads:")
            print(f"     {improvement_pct:.1f}% improvement ({improvement:.2f} votes/min)")
            print()
    
    # Recommendations
    print(f"\n{'='*70}")
    print("RECOMMENDATIONS")
    print(f"{'='*70}")
    
    # Find sweet spot (good balance of throughput and efficiency)
    sweet_spot = None
    for r in sorted_results:
        if r['success_rate'] >= 90 and r['votes_per_thread_per_minute'] > 0:
            if sweet_spot is None or r['votes_per_minute'] > sweet_spot['votes_per_minute']:
                sweet_spot = r
    
    if sweet_spot:
        print(f"\nRecommended Thread Count: {sweet_spot['num_threads']} threads")
        print(f"  → {sweet_spot['votes_per_minute']:.2f} votes/minute")
        print(f"  → {sweet_spot['success_rate']:.1f}% success rate")
        print(f"  → {sweet_spot['avg_memory_mb']:.1f} MB average memory")
        print(f"  → Good balance of throughput and resource usage")
    
    print(f"\n{'='*70}\n")

def main():
    """
    Main entry point for the benchmarking tool.
    
    This function:
    1. Parses command-line arguments (thread counts, duration)
    2. Validates arguments and checks for required dependencies
    3. Runs benchmarks for each specified thread count
    4. Collects and compares results
    5. Displays recommendations
    
    Command-line Arguments:
        --threads: Comma-separated list of thread counts (e.g., "1,2,3,4,5")
        --duration: Duration in seconds for each benchmark (default: 300)
        --skip-existing: Skip threads that already have results (unused currently)
    
    Returns:
        None: Exits with code 0 on success, 1 on error
    
    Note:
        The function handles KeyboardInterrupt gracefully and will display
        results for completed benchmarks before exiting.
    """
    parser = argparse.ArgumentParser(
        description='Benchmark voting performance at different thread counts'
    )
    parser.add_argument(
        '--threads',
        type=str,
        default='1,2,3,4,5',
        help='Comma-separated list of thread counts to test (e.g., "1,2,3,4,5")'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=300,
        help='Duration in seconds to run each benchmark (default: 300 = 5 minutes)'
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip threads that already have results'
    )
    
    args = parser.parse_args()
    
    # Parse thread counts
    try:
        thread_counts = [int(x.strip()) for x in args.threads.split(',')]
        thread_counts = sorted(set(thread_counts))  # Remove duplicates and sort
    except ValueError:
        print("Error: Invalid thread counts format. Use comma-separated integers (e.g., '1,2,3,4,5')")
        sys.exit(1)
    
    if not thread_counts or any(t < 1 for t in thread_counts):
        print("Error: Thread counts must be positive integers")
        sys.exit(1)
    
    print(f"\n{'='*70}")
    print("VOTING PERFORMANCE BENCHMARK")
    print(f"{'='*70}")
    print(f"Testing thread counts: {thread_counts}")
    print(f"Duration per test: {args.duration} seconds ({args.duration/60:.1f} minutes)")
    print(f"Total estimated time: {len(thread_counts) * args.duration / 60:.1f} minutes")
    print(f"{'='*70}\n")
    
    # Check for psutil
    try:
        import psutil
    except ImportError:
        print("Warning: psutil not installed. Resource metrics will be limited.")
        print("Install with: pip install psutil")
        print("\nContinuing without detailed resource metrics...\n")
    
    all_results = []
    
    for num_threads in thread_counts:
        try:
            result = run_benchmark(num_threads, args.duration)
            all_results.append(result)
            print_results(result)
            
            # Brief pause between benchmarks
            if num_threads != thread_counts[-1]:
                print("Waiting 10 seconds before next benchmark...\n")
                time.sleep(10)
        
        except KeyboardInterrupt:
            print("\n\nBenchmark interrupted by user")
            if all_results:
                print("\nComparing results so far...")
                compare_results(all_results)
            sys.exit(0)
        except Exception as e:
            print(f"\nError running benchmark with {num_threads} threads: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Compare all results
    if len(all_results) > 1:
        compare_results(all_results)
    
    print("\nBenchmark complete!")

if __name__ == '__main__':
    main()

