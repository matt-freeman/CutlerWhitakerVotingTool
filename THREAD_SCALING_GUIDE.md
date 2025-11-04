# Thread Scaling and Performance Guide

## Overview

This guide helps you determine the optimal number of threads for your voting script and identify where diminishing returns occur.

## Key Factors Affecting Performance

### 1. **I/O Bound Nature**
- Voting is primarily **I/O-bound** (waiting for network, page loads, browser rendering)
- More threads can help until you hit resource limits
- CPU usage is typically low (<50% per thread)

### 2. **Resource Constraints**

#### Memory
- Each Chrome browser instance uses **100-500 MB** of RAM
- **Formula**: `Total Memory = Thread Count × ~300 MB + Base (~200 MB)`
- Example: 5 threads ≈ 1.7 GB, 10 threads ≈ 3.2 GB

#### CPU
- Each thread uses CPU for:
  - Browser rendering (even headless)
  - JavaScript execution
  - HTML parsing
- Typical: **5-15% CPU per thread** when active

#### Network Bandwidth
- Concurrent HTTP requests to the same server
- Server may throttle/rate limit high concurrency
- Typical: **<1 Mbps per thread**

### 3. **Server-Side Limits**
- **Rate Limiting**: Server may block/throttle too many requests
- **IP-based Detection**: Too many concurrent requests from same IP may trigger anti-bot measures
- **Connection Limits**: Server may limit concurrent connections per IP

### 4. **Thread Management Overhead**
- **Lock Contention**: Shared resources (`_counter_lock`, `_parallel_voting_lock`)
- **Context Switching**: OS overhead switching between threads
- **Python GIL**: Less relevant for I/O-bound operations (Selenium releases GIL)

## Using the Benchmark Tool

### Installation

```bash
# Install additional dependency
pip install psutil
```

### Basic Usage

```bash
# Test 1, 2, 3, 4, and 5 threads for 5 minutes each
python3 benchmark_threads.py --threads 1,2,3,4,5 --duration 300

# Quick test (2 minutes per thread count)
python3 benchmark_threads.py --threads 1,2,3 --duration 120

# Comprehensive test (10 minutes per thread count)
python3 benchmark_threads.py --threads 1,2,3,4,5,6,7,8 --duration 600
```

### Understanding the Output

The benchmark measures:

1. **Throughput**
   - `Votes per minute`: Total voting speed
   - `Votes per thread/min`: Efficiency per thread

2. **Reliability**
   - `Success rate`: Percentage of successful votes
   - `Failed votes`: Number of failures

3. **Performance**
   - `Average vote time`: How long each vote takes
   - `Median vote time`: Typical vote duration

4. **Resource Usage**
   - `Average memory`: RAM usage over time
   - `Peak memory`: Maximum RAM usage
   - `Average CPU`: CPU usage over time
   - `Peak CPU`: Maximum CPU usage

5. **Diminishing Returns Detection**
   - Compares improvement between thread counts
   - Flags when adding threads provides <10% improvement
   - Shows efficiency degradation

### Example Output Analysis

```
Threads    Votes/min    Votes/thread/min    Success %    Avg Mem (MB)    Peak CPU %
1          2.5          2.50                98.5         350             12
2          4.8          2.40                97.2         650             24
3          6.9          2.30                95.8         950             36
4          8.2          2.05                94.1         1250            48
5          8.5          1.70                92.3         1550            60
```

**Analysis:**
- **1→2 threads**: 92% improvement (2.5 → 4.8 votes/min) ✅
- **2→3 threads**: 44% improvement (4.8 → 6.9 votes/min) ✅
- **3→4 threads**: 19% improvement (6.9 → 8.2 votes/min) ⚠️
- **4→5 threads**: 4% improvement (8.2 → 8.5 votes/min) ❌ **Diminishing returns!**

**Recommendation**: 3-4 threads is optimal

## Signs of Diminishing Returns

Watch for these indicators:

### 1. **Throughput Plateaus**
- Adding threads doesn't increase votes/min significantly
- Example: 5 threads = 8.5 votes/min, 6 threads = 8.6 votes/min (<2% improvement)

### 2. **Efficiency Drops**
- `Votes per thread/min` decreases as threads increase
- Example: 3 threads = 2.30, 4 threads = 2.05, 5 threads = 1.70

### 3. **Success Rate Declines**
- More failures as threads increase
- Example: 3 threads = 95.8%, 4 threads = 94.1%, 5 threads = 92.3%

### 4. **Resource Usage Spikes**
- Memory or CPU usage becomes excessive
- Example: 5 threads = 1.5 GB, 6 threads = 1.8 GB (20% increase for minimal gain)

### 5. **Error Rate Increases**
- More errors/timeouts with more threads
- Server may be rate limiting or blocking

## Optimal Thread Count Guidelines

Based on typical scenarios:

### **Conservative (2-3 threads)**
- Good for: Stable, long-running operations
- Low resource usage
- High success rate
- Best when: Memory is limited or server is strict

### **Balanced (4-5 threads)**
- Good for: Most scenarios
- Good throughput/efficiency balance
- Moderate resource usage
- Best when: You want good speed without excessive resources

### **Aggressive (6-8 threads)**
- Good for: Catching up quickly when far behind
- Maximum throughput
- High resource usage
- Best when: You have plenty of RAM/CPU and need speed

### **Not Recommended (>8 threads)**
- Likely hitting diminishing returns
- High risk of rate limiting
- Resource usage may be problematic
- Success rate may drop significantly

## Testing Strategy

### 1. **Start Small, Scale Up**
```bash
# Test 1-3 threads first
python3 benchmark_threads.py --threads 1,2,3 --duration 300

# If results look good, test more
python3 benchmark_threads.py --threads 4,5,6 --duration 300
```

### 2. **Test Under Real Conditions**
- Run benchmarks when you actually need to vote (during active polling)
- Server behavior may differ during peak times
- Test during both quiet and busy periods

### 3. **Monitor Resource Usage**
- Watch system monitor during benchmarks
- Check for memory pressure, CPU throttling
- Monitor network activity

### 4. **Test Different Durations**
- Short tests (2-5 min): Quick validation
- Medium tests (5-10 min): Good balance
- Long tests (15-30 min): Catch memory leaks, long-term stability

## Implementation Considerations

### Current Design (Hard-coded thresholds)

Your current implementation uses fixed thresholds:
- **20 rounds behind**: Start 2nd thread
- **30 rounds behind**: Start 3rd thread

### Scaling to More Threads

If you want to support more threads dynamically, consider:

```python
# Example: Dynamic thread scaling based on behind count
THREAD_THRESHOLDS = {
    20: 2,   # 2 threads at 20+ rounds
    30: 3,   # 3 threads at 30+ rounds
    40: 4,   # 4 threads at 40+ rounds
    50: 5,   # 5 threads at 50+ rounds
}

# In main loop:
for threshold, max_threads in sorted(THREAD_THRESHOLDS.items()):
    if current_behind_count >= threshold:
        # Start threads up to max_threads
        ...
```

### Alternative: Configurable Thread Count

Add command-line argument:
```bash
python3 vote.py --max-threads 5
```

This would:
- Start with 1 thread
- Scale up to `--max-threads` based on behind count
- Use thresholds: 20, 30, 40, 50, etc.

## Recommendations

1. **Run the benchmark** to find your optimal thread count
2. **Start conservative** (2-3 threads) and scale up if needed
3. **Monitor during actual use** - benchmarks may not reflect real-world conditions
4. **Watch for rate limiting** - if you see increased failures, reduce threads
5. **Consider server response** - some servers are more tolerant than others

## Expected Results

Based on typical I/O-bound workloads:

- **1 thread**: Baseline (2-3 votes/min typical)
- **2 threads**: ~80-95% improvement over 1 thread
- **3 threads**: ~50-70% improvement over 2 threads
- **4 threads**: ~20-40% improvement over 3 threads
- **5+ threads**: Diminishing returns likely (<10% improvement per thread)

**Your actual results may vary** based on:
- Network latency
- Server response time
- Your system resources
- Server rate limiting policies

## Troubleshooting

### High Failure Rate
- **Reduce thread count** - may be hitting rate limits
- **Increase wait times** - may be too aggressive
- **Check network** - may have connectivity issues

### High Memory Usage
- **Reduce thread count** - each thread uses significant RAM
- **Check for memory leaks** - monitor over long runs
- **Close other applications** - free up system resources

### Low CPU Usage
- **Normal for I/O-bound** - CPU waiting on network/disk
- **Not a problem** - means threads are efficient
- **If CPU is too low (<10%)** - may indicate network/server issues

## Next Steps

1. **Run the benchmark** with your typical thread counts
2. **Analyze results** to find optimal point
3. **Implement dynamic scaling** based on your findings
4. **Monitor in production** to validate benchmark results


