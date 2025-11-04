#!/usr/bin/env python3
"""
Thread Performance Benchmarking Tool

This script measures voting performance at different thread counts to identify
optimal thread count and diminishing returns point.

Usage:
    python3 benchmark_threads.py --threads 1,2,3,4,5 --duration 300
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
metrics = {
    'votes_submitted': 0,
    'votes_failed': 0,
    'vote_times': [],  # Time taken for each vote
    'memory_usage': [],  # Memory usage over time
    'cpu_usage': [],  # CPU usage over time
    'errors': [],  # Error messages
    'lock': threading.Lock()
}

# Performance tracking per thread
thread_stats = defaultdict(lambda: {
    'votes': 0,
    'failures': 0,
    'total_time': 0.0,
    'min_time': float('inf'),
    'max_time': 0.0
})

def collect_system_metrics():
    """Collect system resource usage metrics."""
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 / 1024  # MB
    cpu_percent = process.cpu_percent(interval=0.1)
    
    with metrics['lock']:
        metrics['memory_usage'].append(memory_mb)
        metrics['cpu_usage'].append(cpu_percent)
    
    return memory_mb, cpu_percent

def benchmark_voting_thread(thread_id, duration, target_time):
    """Run voting in a thread and collect metrics."""
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
    """Run benchmark with specified number of threads."""
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
    """Print formatted benchmark results."""
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
    """Compare results across different thread counts and identify optimal."""
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
    """Main benchmarking function."""
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

