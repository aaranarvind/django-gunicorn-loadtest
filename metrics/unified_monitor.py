#!/usr/bin/env python3
"""
Unified Worker + Container Monitoring & ECS Scaling Intelligence

Combines:
  - uWSGI worker metrics (utilization, CPU, memory per worker)
  - Container-level metrics (CPU, memory, process count)
  - CloudWatch integration for historical analysis
  - ECS scaling recommendations

This tool identifies bottlenecks: are workers the issue or the container itself?
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


class UnifiedMonitor:
    """Combine worker and container metrics for holistic monitoring."""

    def __init__(self, base_url: str = 'http://localhost:8000'):
        self.base_url = base_url.rstrip('/')
        self.metrics_url = f"{self.base_url}/api/metrics/"

        # Import monitor classes
        from metrics.monitor import WorkerUtilizationMonitor
        from metrics.container_metrics import ContainerMetricsCollector

        self.worker_monitor = WorkerUtilizationMonitor(base_url)
        self.container_collector = ContainerMetricsCollector()

    def collect(self) -> Dict[str, Any]:
        """Collect both worker and container metrics."""
        return {
            'timestamp': datetime.now().isoformat(),
            'workers': self.worker_monitor.fetch_metrics(),
            'container': self.container_collector.collect_all(),
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze collected metrics and identify bottlenecks."""
        analysis = {
            'timestamp': data['timestamp'],
            'worker_metrics': None,
            'container_metrics': data.get('container', {}),
            'bottleneck': 'UNKNOWN',
            'health_status': 'UNKNOWN',
            'recommendations': [],
        }

        # Analyze worker metrics
        if data.get('workers'):
            worker_analysis = self.worker_monitor.analyze_utilization(data['workers'])
            worker_rec = self.worker_monitor.get_scaling_recommendation(worker_analysis)
            analysis['worker_metrics'] = worker_analysis
            analysis['worker_recommendation'] = worker_rec

        # Analyze container metrics
        container = data.get('container', {})
        analysis['container_health'] = self._analyze_container(container)

        # Identify bottleneck
        analysis['bottleneck'] = self._identify_bottleneck(analysis)

        # Generate recommendations
        analysis['recommendations'] = self._generate_recommendations(analysis)

        # Overall health
        analysis['health_status'] = self._determine_health_status(analysis)

        return analysis

    def _analyze_container(self, container: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze container-level resource utilization."""
        health = {
            'cpu': {'status': 'UNKNOWN', 'warning': None},
            'memory': {'status': 'UNKNOWN', 'warning': None},
            'processes': {'status': 'UNKNOWN', 'warning': None},
            'network': {'status': 'OK'},
        }

        # CPU analysis
        cpu = container.get('cpu', {})
        if cpu.get('available'):
            cpu_pct = cpu.get('cpu_percent', 0)
            if cpu_pct > 80:
                health['cpu']['status'] = '🔴 HIGH'
                health['cpu']['warning'] = f"Container CPU at {cpu_pct:.1f}%"
            elif cpu_pct > 50:
                health['cpu']['status'] = '🟡 MODERATE'
            else:
                health['cpu']['status'] = '🟢 LOW'

        # Memory analysis
        mem = container.get('memory', {})
        if mem.get('available'):
            mem_pct = mem.get('usage_percent')
            if mem_pct and mem_pct > 85:
                health['memory']['status'] = '🔴 CRITICAL'
                health['memory']['warning'] = f"Memory at {mem_pct:.1f}% of limit"
            elif mem_pct and mem_pct > 70:
                health['memory']['status'] = '🟡 HIGH'
            else:
                health['memory']['status'] = '🟢 HEALTHY'

        # Process analysis
        procs = container.get('processes', {})
        if procs.get('available'):
            fd_pct = procs.get('fd_utilization_percent', 0)
            if fd_pct > 80:
                health['processes']['status'] = '🟡 WATCH'
                health['processes']['warning'] = f"FD usage at {fd_pct:.1f}%"
            else:
                health['processes']['status'] = '✅ GOOD'

        return health

    def _identify_bottleneck(self, analysis: Dict[str, Any]) -> str:
        """
        Identify whether the bottleneck is:
        - WORKERS: High worker utilization but low container CPU
        - CONTAINER: High container CPU/memory despite low worker util
        - BALANCED: Both are heavily utilized
        - HEALTHY: Neither is a bottleneck
        """
        worker_metrics = analysis.get('worker_metrics', {})
        container_metrics = analysis.get('container_health', {})

        worker_util = worker_metrics.get('utilization_percent', 0)
        container_cpu_status = container_metrics.get('cpu', {}).get('status', '')
        container_mem_status = container_metrics.get('memory', {}).get('status', '')

        # Extract numeric CPU usage
        cpu_data = analysis['container_metrics'].get('cpu', {})
        container_cpu_pct = cpu_data.get('cpu_percent', 0)

        if worker_util > 85 and container_cpu_pct > 70:
            return '🟠 BALANCED_LOAD'
        elif worker_util > 85 and container_cpu_pct < 50:
            return '⚠️  WORKER_BOTTLENECK'
        elif worker_util < 30 and container_cpu_pct > 60:
            return '⚠️  CONTAINER_OVERHEAD'
        elif '🔴' in str(container_mem_status):
            return '🔴 MEMORY_CRITICAL'
        else:
            return '✅ HEALTHY'

    def _generate_recommendations(self, analysis: Dict[str, Any]) -> list:
        """Generate actionable recommendations."""
        recommendations = []
        bottleneck = analysis['bottleneck']
        worker_metrics = analysis.get('worker_metrics', {})
        container = analysis.get('container_metrics', {})

        if 'WORKER_BOTTLENECK' in bottleneck:
            recommendations.append({
                'priority': 'HIGH',
                'category': 'Scaling',
                'action': 'SCALE_UP_WORKERS',
                'reason': f"Workers {worker_metrics.get('utilization_percent', 0):.1f}% utilized but container has resource headroom",
                'steps': [
                    'Increase UWSGI_PROCESSES in docker-compose.yml',
                    'Redeploy ECS task',
                    'Monitor worker utilization with metrics endpoint',
                ],
            })

        if 'CONTAINER_OVERHEAD' in bottleneck:
            recommendations.append({
                'priority': 'MEDIUM',
                'category': 'Optimization',
                'action': 'REDUCE_WORKER_COUNT',
                'reason': f"Workers only {worker_metrics.get('utilization_percent', 0):.1f}% utilized but container CPU high",
                'steps': [
                    'Profile workers for memory leaks',
                    'Reduce UWSGI_PROCESSES',
                    'Check for background tasks or imports',
                ],
            })

        if 'MEMORY_CRITICAL' in bottleneck:
            mem = container.get('memory', {})
            recommendations.append({
                'priority': 'CRITICAL',
                'category': 'Resource',
                'action': 'INCREASE_MEMORY',
                'reason': f"Container memory {mem.get('usage_percent', 0):.1f}% of limit",
                'steps': [
                    'Increase ECS task memory in AWS console',
                    'Or reduce UWSGI_PROCESSES',
                    'Check for memory leaks in workers',
                ],
            })

        if 'BALANCED_LOAD' in bottleneck:
            recommendations.append({
                'priority': 'LOW',
                'category': 'Monitoring',
                'action': 'MAINTAIN',
                'reason': 'System is operating at healthy utilization levels',
                'steps': [
                    'Continue monitoring current configuration',
                    'Scale horizontally if more capacity needed',
                ],
            })

        # Check for network concerns
        net = container.get('network', {})
        if net.get('available') and net.get('total_rx_mb', 0) > 1000:
            recommendations.append({
                'priority': 'INFO',
                'category': 'Monitoring',
                'action': 'MONITOR_NETWORK',
                'reason': f"High network I/O: {net.get('total_rx_mb', 0):.2f} MB RX",
                'steps': [
                    'Check if this is expected for your workload',
                    'Monitor network bandwidth costs',
                ],
            })

        return recommendations

    def _determine_health_status(self, analysis: Dict[str, Any]) -> str:
        """Determine overall system health."""
        bottleneck = analysis['bottleneck']
        container_health = analysis.get('container_health', {})

        if 'CRITICAL' in bottleneck or 'MEMORY_CRITICAL' in bottleneck:
            return '🔴 CRITICAL'
        elif any('🔴' in str(v).get('status', '') for v in container_health.values()):
            return '🟠 WARNING'
        elif 'BOTTLENECK' in bottleneck or 'LOAD' in bottleneck:
            return '🟡 CAUTION'
        else:
            return '🟢 HEALTHY'


class ConfigGenerator:
    """Generate CloudFormation/ECS configuration based on recommendations."""

    @staticmethod
    def generate_ecs_task_definition(
        base_workers: int = 5,
        memory_mb: int = 1024,
        cpu_units: int = 512,
        recommended_workers: int = None,
    ) -> Dict[str, Any]:
        """Generate recommended ECS task configuration."""
        return {
            'containerDefinitions': [
                {
                    'name': 'uwsgi-app',
                    'image': 'your-registry/django-app:latest',
                    'memory': memory_mb,
                    'cpu': cpu_units,
                    'environment': [
                        {
                            'name': 'UWSGI_PROCESSES',
                            'value': str(recommended_workers or base_workers),
                        },
                        {
                            'name': 'UWSGI_THREADS',
                            'value': '1',
                        },
                    ],
                    'portMappings': [
                        {'containerPort': 8000, 'protocol': 'tcp'},
                        {'containerPort': 9191, 'protocol': 'tcp'},  # stats
                    ],
                }
            ],
            'execution_role_arn': 'arn:aws:iam::ACCOUNT:role/ecsTaskExecutionRole',
            'task_role_arn': 'arn:aws:iam::ACCOUNT:role/ecsTaskRole',
        }


def print_analysis_report(analysis: Dict[str, Any]):
    """Print a formatted analysis report."""
    print("\n" + "=" * 100)
    print(f"UNIFIED MONITORING ANALYSIS - {analysis['timestamp']}")
    print("=" * 100)

    # Overall health
    print(f"\n📊 OVERALL STATUS: {analysis['health_status']}")
    print(f"   Bottleneck: {analysis['bottleneck']}")

    # Worker metrics
    if analysis['worker_metrics']:
        wm = analysis['worker_metrics']
        print(f"\n👷 WORKER METRICS:")
        print(f"   Status: {wm['status']}")
        print(f"   Active: {wm['active_workers']} / {wm['total_workers']}")
        print(f"   Utilization: {wm['utilization_percent']:.1f}%")
        print(f"   Avg Response Time: {wm['avg_response_time']:.4f}s")

    # Container metrics
    container = analysis['container_metrics']
    if container.get('cpu', {}).get('available'):
        cpu = container['cpu']
        print(f"\n🔴 CONTAINER CPU:")
        print(f"   Usage: {cpu['cpu_percent']:.2f}%")
        print(f"   CPUs: {cpu.get('num_cpus', 1)}")

    if container.get('memory', {}).get('available'):
        mem = container['memory']
        print(f"\n💾 CONTAINER MEMORY:")
        print(f"   Current: {mem['current_mb']:.2f} MB")
        if mem.get('limit_mb'):
            print(f"   Limit: {mem['limit_mb']:.2f} MB")
            print(f"   Usage: {mem.get('usage_percent', 0):.2f}%")

    # Container health
    print(f"\n🏥 CONTAINER HEALTH:")
    for component, health in analysis['container_health'].items():
        status = health.get('status', 'UNKNOWN')
        print(f"   {component.upper()}: {status}")
        if health.get('warning'):
            print(f"         ⚠️  {health['warning']}")

    # Recommendations
    if analysis['recommendations']:
        print(f"\n💡 RECOMMENDATIONS:")
        for i, rec in enumerate(analysis['recommendations'], 1):
            print(f"\n   [{i}] {rec['action']} ({rec['priority']})")
            print(f"       Category: {rec['category']}")
            print(f"       Reason: {rec['reason']}")
            print(f"       Steps:")
            for step in rec['steps']:
                print(f"         - {step}")

    print("\n" + "=" * 100 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Unified Worker + Container Monitoring',
    )
    parser.add_argument(
        '--url',
        default='http://localhost:8000',
        help='Base URL of Django app',
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=10,
        help='Collection interval (seconds)',
    )
    parser.add_argument(
        '--count',
        type=int,
        help='Number of iterations',
    )
    parser.add_argument(
        '--output',
        help='JSON file for metrics export',
    )
    parser.add_argument(
        '--one-shot',
        action='store_true',
        help='Collect once and exit',
    )

    args = parser.parse_args()

    monitor = UnifiedMonitor(base_url=args.url)

    try:
        iteration = 0
        while args.count is None or iteration < args.count:
            data = monitor.collect()
            analysis = monitor.analyze(data)

            print_analysis_report(analysis)

            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(analysis, f, indent=2)

            if args.one_shot:
                break

            iteration += 1
            if iteration < (args.count or float('inf')):
                time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\nMonitor stopped")
        sys.exit(0)


if __name__ == '__main__':
    main()
