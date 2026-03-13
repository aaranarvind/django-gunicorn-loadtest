#!/usr/bin/env python3
"""
Real-time uWSGI Worker Utilization Monitor

Monitors worker health, identifies under/over-utilization, and provides
actionable insights for container scaling decisions in ECS.

Features:
  - Fetches metrics from /api/metrics/ endpoint
  - Terminal dashboard with live updates
  - Utilization analysis (under-utilized < 50%, over-utilized > 80%)
  - Container resource recommendations
  - Export to JSON for ECS scaling policies
"""
import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


class WorkerUtilizationMonitor:
    """Fetch and analyze worker metrics."""

    def __init__(self, base_url: str = 'http://localhost:8000'):
        self.base_url = base_url.rstrip('/')
        self.metrics_url = f"{self.base_url}/api/metrics/"
        self.history: List[Dict[str, Any]] = []
        self.max_history = 100

    def fetch_metrics(self) -> Optional[Dict[str, Any]]:
        """Get current worker metrics from the application."""
        try:
            response = requests.get(self.metrics_url, timeout=5)
            response.raise_for_status()
            metrics = response.json()
            metrics['fetch_time'] = time.time()
            self.history.append(metrics)
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
            return metrics
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch metrics: {e}")
            return None

    def analyze_utilization(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify workers as under-utilized or over-utilized.
        Returns analysis with recommendations.
        """
        active = metrics['active_workers']
        total = metrics['total_workers_seen']
        util_pct = metrics['utilization_percent']

        analysis = {
            'timestamp': datetime.fromtimestamp(metrics['timestamp']).isoformat(),
            'total_workers': total,
            'active_workers': active,
            'idle_workers': metrics['idle_workers'],
            'utilization_percent': util_pct,
            'total_requests': metrics['total_requests'],
            'avg_response_time': metrics['avg_recent_response_time'],
            'status': 'UNKNOWN',
            'recommendation': '',
            'worker_analysis': {},
        }

        # Overall utilization classification
        if util_pct < 30:
            analysis['status'] = '⬇️  UNDER-UTILIZED'
            analysis['recommendation'] = (
                f'Only {util_pct:.1f}% utilized. Consider reducing worker count '
                f'or scaling down ECS task CPU/memory.'
            )
        elif util_pct < 50:
            analysis['status'] = '📉 UNDER-SERVED'
            analysis['recommendation'] = (
                f'{util_pct:.1f}% utilized. Capacity available for more load. '
                'Monitor before scaling.'
            )
        elif util_pct <= 80:
            analysis['status'] = '✅ OPTIMAL'
            analysis['recommendation'] = (
                f'{util_pct:.1f}% utilized. Healthy utilization level. '
                'Good balance of efficiency and headroom.'
            )
        else:
            analysis['status'] = '⚠️  OVER-UTILIZED'
            analysis['recommendation'] = (
                f'{util_pct:.1f}% utilized! Consider increasing worker count '
                f'or scaling up ECS task.'
            )

        # Per-worker analysis
        for pid, worker in metrics.get('workers', {}).items():
            worker_util = (
                100.0 if worker['active'] else 0.0
            )
            worker_analysis = {
                'pid': int(pid),
                'active': worker['active'],
                'request_count': worker['request_count'],
                'avg_response_time': worker['avg_response_time'],
                'cpu_percent': worker['cpu_percent'],
                'memory_mb': worker['memory_mb'],
                'status': '🟢 ACTIVE' if worker['active'] else '⚪ IDLE',
            }

            # Classify individual workers
            if worker['cpu_percent'] > 80:
                worker_analysis['cpu_status'] = '🔴 HIGH'
            elif worker['cpu_percent'] > 50:
                worker_analysis['cpu_status'] = '🟡 MODERATE'
            else:
                worker_analysis['cpu_status'] = '🟢 LOW'

            analysis['worker_analysis'][pid] = worker_analysis

        return analysis

    def get_scaling_recommendation(
        self,
        analysis: Dict[str, Any],
        workload_type: str = 'mixed'
    ) -> Dict[str, Any]:
        """
        Provide ECS scaling recommendations based on utilization patterns.
        """
        util = analysis['utilization_percent']
        active = analysis['active_workers']
        total = analysis['total_workers']
        avg_resp_time = analysis['avg_response_time']

        recommendation = {
            'current_workers': total,
            'scaling_action': 'MAINTAIN',
            'target_workers': total,
            'cpu_target_percent': 70,
            'memory_reserve_percent': 20,
            'rationale': '',
        }

        # Scaling logic
        if util > 90:
            recommendation['scaling_action'] = 'SCALE_UP'
            recommendation['target_workers'] = min(
                total + max(2, int(total * 0.25)),
                total * 2
            )
            recommendation['rationale'] = (
                f'Utilization at {util:.1f}%. Recommend increasing workers '
                f'to {recommendation["target_workers"]} to handle spike.'
            )
        elif util < 20:
            recommendation['scaling_action'] = 'SCALE_DOWN'
            recommendation['target_workers'] = max(
                2,
                int(total * 0.6)
            )
            recommendation['rationale'] = (
                f'Utilization at {util:.1f}%. Many idle workers. '
                f'Can reduce to {recommendation["target_workers"]} workers.'
            )
        elif util < 50:
            recommendation['scaling_action'] = 'MONITOR'
            recommendation['rationale'] = (
                f'Utilization at {util:.1f}%. Acceptable but has headroom. '
                'Maintain current level and monitor for trends.'
            )
        else:
            recommendation['rationale'] = (
                f'Utilization at {util:.1f}%. Healthy operating level.'
            )

        # Response time considerations
        if avg_resp_time > 5.0:
            recommendation['priority'] = 'HIGH'
            recommendation['rationale'] += (
                f' Response time {avg_resp_time:.2f}s is high - '
                'may indicate CPU contention.'
            )

        return recommendation


class TerminalDashboard:
    """Display metrics in a terminal-friendly format."""

    @staticmethod
    def clear_screen():
        """Clear terminal screen (ANSI)."""
        print('\033c', end='')

    @staticmethod
    def print_header(title: str, width: int = 80):
        """Print a formatted header."""
        print("\n" + "=" * width)
        print(f"  {title}".ljust(width - 1))
        print("=" * width)

    @staticmethod
    def print_metric_row(label: str, value: Any, unit: str = '', width: int = 80):
        """Print a formatted metric row."""
        value_str = f"{value}{unit}"
        print(f"  {label:<35} {value_str:>40}")

    @staticmethod
    def print_worker_row(
        pid: int,
        status: str,
        requests: int,
        avg_time: float,
        cpu: float,
        mem: float,
        width: int = 80
    ):
        """Print a worker status row."""
        row = (
            f"  PID {pid:<6} {status:<12} "
            f"Req:{requests:<5} Avg:{avg_time:.3f}s "
            f"CPU:{cpu:.1f}% Mem:{mem:.1f}MB"
        )
        print(row[:width])

    @staticmethod
    def print_analysis(analysis: Dict[str, Any], width: int = 80):
        """Print worker analysis summary."""
        TerminalDashboard.print_header("📊 WORKER ANALYSIS", width)
        TerminalDashboard.print_metric_row(
            "Status",
            analysis['status'],
            width=width
        )
        TerminalDashboard.print_metric_row(
            "Utilization",
            f"{analysis['utilization_percent']:.1f}%",
            width=width
        )
        TerminalDashboard.print_metric_row(
            "Active Workers",
            f"{analysis['active_workers']} / {analysis['total_workers']}",
            width=width
        )
        TerminalDashboard.print_metric_row(
            "Total Requests",
            analysis['total_requests'],
            width=width
        )
        TerminalDashboard.print_metric_row(
            "Avg Response Time",
            f"{analysis['avg_response_time']:.4f}s",
            width=width
        )
        print()

    @staticmethod
    def print_recommendation(rec: Dict[str, Any], width: int = 80):
        """Print scaling recommendation."""
        TerminalDashboard.print_header("📈 SCALING RECOMMENDATION", width)
        TerminalDashboard.print_metric_row(
            "Action",
            rec['scaling_action'],
            width=width
        )
        TerminalDashboard.print_metric_row(
            "Target Workers",
            rec['target_workers'],
            width=width
        )
        TerminalDashboard.print_metric_row(
            "Target CPU Util %",
            f"{rec['cpu_target_percent']}%",
            width=width
        )
        print(f"\n  Rationale:\n  {rec['rationale']}\n")

    @staticmethod
    def print_workers(workers: Dict[str, Dict[str, Any]], width: int = 80):
        """Print detailed worker status."""
        TerminalDashboard.print_header("🔧 WORKER DETAILS", width)
        print(f"  {'PID':<8} {'Status':<12} {'Requests':<8} "
              f"{'Avg Time':<10} {'CPU':<8} {'Memory':<10}")
        print("  " + "-" * (width - 4))

        for pid, w in sorted(workers.items(), key=lambda x: int(x[0])):
            TerminalDashboard.print_worker_row(
                int(pid),
                w['status'],
                w['request_count'],
                w['avg_response_time'],
                w['cpu_percent'],
                w['memory_mb'],
                width=width
            )

    @staticmethod
    def print_insights(analysis: Dict[str, Any], width: int = 80):
        """Print health insights and warnings."""
        TerminalDashboard.print_header("💡 INSIGHTS", width)

        insights = []

        # High CPU workers
        high_cpu_workers = [
            (pid, w['cpu_percent'])
            for pid, w in analysis['worker_analysis'].items()
            if w['cpu_percent'] > 80
        ]
        if high_cpu_workers:
            pids = ', '.join(str(pid) for pid, _ in high_cpu_workers)
            insights.append(f"🔴 High CPU workers: PID {pids}")

        # High memory workers
        high_mem_workers = [
            (pid, w['memory_mb'])
            for pid, w in analysis['worker_analysis'].items()
            if w['memory_mb'] > 500
        ]
        if high_mem_workers:
            pids = ', '.join(str(pid) for pid, _ in high_mem_workers)
            insights.append(f"🟠 High memory workers: PID {pids}")

        # Idle workers
        idle_workers = [
            pid for pid, w in analysis['worker_analysis'].items()
            if not w['active']
        ]
        if idle_workers and len(idle_workers) >= analysis['total_workers'] * 0.5:
            insights.append(
                f"⚪ Many idle workers ({len(idle_workers)}/{analysis['total_workers']})"
            )

        # Slow responses
        slow_workers = [
            (pid, w['avg_response_time'])
            for pid, w in analysis['worker_analysis'].items()
            if w['avg_response_time'] > 2.0
        ]
        if slow_workers:
            pids = ', '.join(str(pid) for pid, _ in slow_workers)
            insights.append(f"🐌 Slow workers: PID {pids}")

        if not insights:
            insights.append("✅ All systems operating normally")

        for insight in insights:
            print(f"  {insight}")
        print()


def monitor_loop(
    monitor: WorkerUtilizationMonitor,
    interval: int = 5,
    count: Optional[int] = None,
    output_file: Optional[str] = None,
):
    """
    Continuously monitor and display metrics.

    Args:
        monitor: The monitor instance
        interval: Update interval in seconds
        count: Number of iterations (None for infinite)
        output_file: Optional JSON file to write results
    """
    iteration = 0

    try:
        while count is None or iteration < count:
            metrics = monitor.fetch_metrics()

            if metrics:
                analysis = monitor.analyze_utilization(metrics)
                recommendation = monitor.get_scaling_recommendation(analysis)

                # Display dashboard
                TerminalDashboard.clear_screen()
                TerminalDashboard.print_analysis(analysis)
                TerminalDashboard.print_recommendation(recommendation)
                TerminalDashboard.print_workers(analysis['worker_analysis'])
                TerminalDashboard.print_insights(analysis)

                # Update timestamp
                print(f"  Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Update interval: {interval}s | Press Ctrl+C to exit\n")

                # Export if requested
                if output_file:
                    with open(output_file, 'w') as f:
                        json.dump(
                            {
                                'analysis': analysis,
                                'recommendation': recommendation,
                                'timestamp': datetime.now().isoformat(),
                            },
                            f, indent=2
                        )
                    logger.info(f"Metrics exported to {output_file}")
            else:
                print("Failed to fetch metrics. Retrying...")

            iteration += 1
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n👋 Monitor stopped by user")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description='Real-time uWSGI Worker Utilization Monitor',
    )
    parser.add_argument(
        '--url',
        default='http://localhost:8000',
        help='Base URL of Django application (default: http://localhost:8000)',
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        help='Update interval in seconds (default: 5)',
    )
    parser.add_argument(
        '--count',
        type=int,
        default=None,
        help='Number of updates before exiting (default: infinite)',
    )
    parser.add_argument(
        '--output',
        help='JSON file to write metrics (for integration with other tools)',
    )
    parser.add_argument(
        '--one-shot',
        action='store_true',
        help='Fetch metrics once and exit (useful for scripting)',
    )

    args = parser.parse_args()

    monitor = WorkerUtilizationMonitor(base_url=args.url)

    if args.one_shot:
        metrics = monitor.fetch_metrics()
        if metrics:
            analysis = monitor.analyze_utilization(metrics)
            recommendation = monitor.get_scaling_recommendation(analysis)

            output = {
                'status': 'success',
                'analysis': analysis,
                'recommendation': recommendation,
                'timestamp': datetime.now().isoformat(),
            }
            print(json.dumps(output, indent=2))
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(output, f, indent=2)
        else:
            print("Failed to fetch metrics", file=sys.stderr)
            sys.exit(1)
    else:
        monitor_loop(
            monitor,
            interval=args.interval,
            count=args.count,
            output_file=args.output,
        )


if __name__ == '__main__':
    main()
