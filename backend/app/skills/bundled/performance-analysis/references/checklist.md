# Performance analysis checklist

## Measure
- Define workload, concurrency, data size, warmup, and latency objectives.
- Capture baseline p50, p95, p99, throughput, errors, and resource usage.

## Diagnose
- Separate provider latency, queueing, application work, database time, and tool execution.
- Inspect traces and profiles before changing code.
- Check whether caching or batching changes correctness, isolation, or freshness.

## Verify
- Compare before and after under the same workload.
- Include cold-start and failure behavior, not only best-case averages.
- Reject optimizations that hide errors or weaken safety checks.
