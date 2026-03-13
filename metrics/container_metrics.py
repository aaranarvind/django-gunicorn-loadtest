#!/usr/bin/env python3
"""
ECS Container Metrics Collector

Monitors container-level resource utilization:
  - CPU usage from /proc/stat (cgroup v1/v2)
  - Memory usage from /proc/meminfo or cgroup
  - Disk I/O from /proc/diskstats
  - Network I/O from /proc/net/dev
  - Process count
  - Open file descriptors

Useful for identifying whether the container itself or workers within
are the bottleneck for performance.
"""
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


class ContainerMetricsCollector:
    """Collect container-level resource metrics from cgroups and /proc."""

    def __init__(self):
        self.cgroup_v2 = Path('/sys/fs/cgroup')
        self.cgroup_v1_base = Path('/sys/fs/cgroup')
        self.proc_base = Path('/proc')
        self.prev_cpu_stats: Optional[Dict[str, int]] = None
        self.prev_time = time.time()
        self._detect_cgroup_version()

    def _detect_cgroup_version(self):
        """Detect if system uses cgroups v1 or v2."""
        cgroup_path = Path('/proc/self/cgroup')
        if not cgroup_path.exists():
            logger.warning("cgroup info not available")
            return

        try:
            content = cgroup_path.read_text()
            # v2 has format: "0::<subsystem>:..."
            # v1 has format: "1:<subsystem>:<path>"
            if '0::' in content:
                logger.info("Using cgroups v2")
                self.version = 2
            else:
                logger.info("Using cgroups v1")
                self.version = 1
        except Exception as e:
            logger.warning(f"Could not detect cgroup version: {e}")
            self.version = 1

    def get_cpu_usage(self) -> Dict[str, Any]:
        """
        Get CPU usage as percentage.
        Works with both cgroups v1 and v2.
        """
        try:
            if self.version == 2:
                return self._get_cpu_v2()
            else:
                return self._get_cpu_v1()
        except Exception as e:
            logger.error(f"Failed to get CPU usage: {e}")
            return {
                'available': False,
                'error': str(e),
            }

    def _get_cpu_v2(self) -> Dict[str, Any]:
        """Get CPU metrics from cgroups v2."""
        cpu_stat_path = self.cgroup_v2 / 'cpu.stat'
        cpu_max_path = self.cgroup_v2 / 'cpu.max'

        if not cpu_stat_path.exists():
            return {'available': False, 'reason': 'cpu.stat not found'}

        try:
            # Read CPU usage and limits
            cpu_stat = {}
            for line in cpu_stat_path.read_text().strip().split('\n'):
                if line:
                    key, value = line.split()
                    cpu_stat[key] = int(value)

            # Read CPU quota and period
            if cpu_max_path.exists():
                max_line = cpu_max_path.read_text().strip()
                if max_line != 'max':
                    quota, period = max(line.split())
                    quota = int(quota)
                    period = int(period)
                else:
                    quota = None
                    period = None
            else:
                quota = period = None

            # Calculate CPU percentage
            current_time = time.time()
            time_delta = current_time - self.prev_time

            if self.prev_cpu_stats and time_delta > 0:
                cpu_delta = (
                    cpu_stat.get('usage_usec', 0) -
                    self.prev_cpu_stats.get('usage_usec', 0)
                ) / 1_000_000  # Convert to seconds

                # CPU percentage: (CPU delta) / (time delta) / (cpu cores) * 100
                num_cpus = os.cpu_count() or 1
                cpu_pct = (cpu_delta / time_delta) / num_cpus * 100
            else:
                cpu_pct = 0.0

            self.prev_cpu_stats = cpu_stat.copy()
            self.prev_time = current_time

            return {
                'available': True,
                'usage_us': cpu_stat.get('usage_usec', 0),
                'user_us': cpu_stat.get('user_usec', 0),
                'system_us': cpu_stat.get('system_usec', 0),
                'cpu_percent': round(cpu_pct, 2),
                'cpu_quota': quota,
                'cpu_period': period,
                'num_cpus': num_cpus,
            }
        except Exception as e:
            logger.error(f"Error reading cgroup v2 CPU: {e}")
            return {'available': False, 'error': str(e)}

    def _get_cpu_v1(self) -> Dict[str, Any]:
        """Get CPU metrics from cgroups v1."""
        cpu_stat_path = (
            self.cgroup_v1_base / 'cpuacct' / 'cpuacct.usage'
        )
        cpu_max_path = (
            self.cgroup_v1_base / 'cpu' / 'cpu.max'
        )

        if not cpu_stat_path.exists():
            return {'available': False, 'reason': 'cpuacct.usage not found'}

        try:
            usage_ns = int(cpu_stat_path.read_text().strip())

            current_time = time.time()
            time_delta = current_time - self.prev_time

            if self.prev_cpu_stats and time_delta > 0:
                cpu_delta = (
                    (usage_ns - self.prev_cpu_stats.get('usage_ns', 0))
                    / 1_000_000_000
                )  # Convert to seconds

                num_cpus = os.cpu_count() or 1
                cpu_pct = (cpu_delta / time_delta) / num_cpus * 100
            else:
                cpu_pct = 0.0

            self.prev_cpu_stats = {'usage_ns': usage_ns}
            self.prev_time = current_time

            return {
                'available': True,
                'usage_ns': usage_ns,
                'cpu_percent': round(cpu_pct, 2),
                'num_cpus': num_cpus,
            }
        except Exception as e:
            logger.error(f"Error reading cgroup v1 CPU: {e}")
            return {'available': False, 'error': str(e)}

    def get_memory_usage(self) -> Dict[str, Any]:
        """
        Get memory usage from cgroups or /proc/meminfo.
        Returns memory in MB.
        """
        try:
            if self.version == 2:
                return self._get_memory_v2()
            else:
                return self._get_memory_v1()
        except Exception as e:
            logger.error(f"Failed to get memory usage: {e}")
            return {
                'available': False,
                'error': str(e),
            }

    def _get_memory_v2(self) -> Dict[str, Any]:
        """Get memory metrics from cgroups v2."""
        memory_stat_path = self.cgroup_v2 / 'memory.stat'
        memory_max_path = self.cgroup_v2 / 'memory.max'

        if not memory_stat_path.exists():
            return {'available': False, 'reason': 'memory.stat not found'}

        try:
            mem_stat = {}
            for line in memory_stat_path.read_text().strip().split('\n'):
                if line:
                    parts = line.split()
                    if len(parts) == 2:
                        key, value = parts
                        mem_stat[key] = int(value)

            # Get limit
            if memory_max_path.exists():
                max_str = memory_max_path.read_text().strip()
                limit = (
                    int(max_str) if max_str != 'max' else None
                )
            else:
                limit = None

            current_usage = mem_stat.get('anon', 0) + mem_stat.get('file', 0)
            current_mb = current_usage / (1024 * 1024)
            limit_mb = limit / (1024 * 1024) if limit else None

            usage_pct = (
                (current_usage / limit * 100) if limit else None
            )

            return {
                'available': True,
                'current_mb': round(current_mb, 2),
                'limit_mb': round(limit_mb, 2) if limit_mb else None,
                'usage_percent': round(usage_pct, 2) if usage_pct else None,
                'anon_mb': round(mem_stat.get('anon', 0) / (1024 * 1024), 2),
                'file_mb': round(mem_stat.get('file', 0) / (1024 * 1024), 2),
                'slab_mb': round(mem_stat.get('slab', 0) / (1024 * 1024), 2),
            }
        except Exception as e:
            logger.error(f"Error reading cgroup v2 memory: {e}")
            return {'available': False, 'error': str(e)}

    def _get_memory_v1(self) -> Dict[str, Any]:
        """Get memory metrics from cgroups v1."""
        memory_limit_path = (
            self.cgroup_v1_base / 'memory' / 'memory.limit_in_bytes'
        )
        memory_usage_path = (
            self.cgroup_v1_base / 'memory' / 'memory.usage_in_bytes'
        )

        if not memory_usage_path.exists():
            return {'available': False, 'reason': 'memory.usage_in_bytes not found'}

        try:
            usage_bytes = int(memory_usage_path.read_text().strip())
            usage_mb = usage_bytes / (1024 * 1024)

            if memory_limit_path.exists():
                limit_bytes = int(memory_limit_path.read_text().strip())
                limit_mb = limit_bytes / (1024 * 1024)
                usage_pct = (usage_bytes / limit_bytes * 100)
            else:
                limit_mb = None
                usage_pct = None

            return {
                'available': True,
                'current_mb': round(usage_mb, 2),
                'limit_mb': round(limit_mb, 2) if limit_mb else None,
                'usage_percent': round(usage_pct, 2) if usage_pct else None,
            }
        except Exception as e:
            logger.error(f"Error reading cgroup v1 memory: {e}")
            return {'available': False, 'error': str(e)}

    def get_process_stats(self) -> Dict[str, Any]:
        """Get process and file descriptor statistics."""
        try:
            # Count processes
            process_count = len(list(Path('/proc').glob('*/stat')))

            # Count open file descriptors for our process
            fd_path = Path(f'/proc/{os.getpid()}/fd')
            if fd_path.exists():
                fd_count = len(list(fd_path.iterdir()))
                fd_limit = int(
                    (Path(f'/proc/{os.getpid()}/limits')
                     .read_text().split('\n')[1]
                     .split()[-2])
                )
            else:
                fd_count = 0
                fd_limit = 0

            return {
                'available': True,
                'total_processes': process_count,
                'current_pid_fds': fd_count,
                'fd_limit': fd_limit,
                'fd_utilization_percent': (
                    round(fd_count / fd_limit * 100, 2) if fd_limit > 0 else 0
                ),
            }
        except Exception as e:
            logger.error(f"Failed to get process stats: {e}")
            return {'available': False, 'error': str(e)}

    def get_network_stats(self) -> Dict[str, Any]:
        """Get network I/O statistics."""
        try:
            net_dev = Path('/proc/net/dev')
            if not net_dev.exists():
                return {'available': False, 'reason': '/proc/net/dev not found'}

            stats = {
                'interfaces': {},
                'total_rx_bytes': 0,
                'total_tx_bytes': 0,
            }

            for line in net_dev.read_text().split('\n')[2:]:
                if not line.strip():
                    continue

                # Parse: iface:rx_bytes rx_packets rx_errors ... tx_bytes tx_packets ...
                parts = re.split('[: ]+', line.strip())
                if len(parts) >= 10:
                    iface = parts[0]
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])

                    stats['interfaces'][iface] = {
                        'rx_bytes': rx_bytes,
                        'tx_bytes': tx_bytes,
                    }

                    stats['total_rx_bytes'] += rx_bytes
                    stats['total_tx_bytes'] += tx_bytes

            stats['available'] = True
            stats['total_rx_mb'] = round(stats['total_rx_bytes'] / (1024 * 1024), 2)
            stats['total_tx_mb'] = round(stats['total_tx_bytes'] / (1024 * 1024), 2)

            return stats
        except Exception as e:
            logger.error(f"Failed to get network stats: {e}")
            return {'available': False, 'error': str(e)}

    def collect_all(self) -> Dict[str, Any]:
        """Collect all container metrics."""
        return {
            'timestamp': datetime.now().isoformat(),
            'container_id': os.environ.get('HOSTNAME', 'unknown'),
            'cpu': self.get_cpu_usage(),
            'memory': self.get_memory_usage(),
            'processes': self.get_process_stats(),
            'network': self.get_network_stats(),
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Collect ECS container resource metrics',
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        help='Collection interval in seconds (default: 5)',
    )
    parser.add_argument(
        '--count',
        type=int,
        default=None,
        help='Number of collections (default: infinite)',
    )
    parser.add_argument(
        '--output',
        help='JSON file to write metrics',
    )
    parser.add_argument(
        '--one-shot',
        action='store_true',
        help='Collect once and exit',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Verbose output',
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    collector = ContainerMetricsCollector()

    try:
        iteration = 0
        while args.count is None or iteration < args.count:
            metrics = collector.collect_all()

            print("\n" + "=" * 80)
            print(f"Container Metrics - {metrics['timestamp']}")
            print("=" * 80)

            # CPU
            cpu = metrics['cpu']
            if cpu.get('available'):
                print(f"\n🔴 CPU:")
                print(f"  Usage: {cpu.get('cpu_percent', 0):.2f}%")
                print(f"  User: {cpu.get('user_us', 0) / 1_000_000:.2f}s")
                print(f"  System: {cpu.get('system_us', 0) / 1_000_000:.2f}s")
                print(f"  CPUs: {cpu.get('num_cpus', 1)}")
                if cpu.get('cpu_quota'):
                    print(f"  Quota: {cpu.get('cpu_quota')} us / {cpu.get('cpu_period')} us")

            # Memory
            mem = metrics['memory']
            if mem.get('available'):
                print(f"\n💾 Memory:")
                print(f"  Current: {mem.get('current_mb', 0):.2f} MB")
                if mem.get('limit_mb'):
                    print(f"  Limit: {mem.get('limit_mb', 0):.2f} MB")
                    print(f"  Usage: {mem.get('usage_percent', 0):.2f}%")
                if mem.get('anon_mb'):
                    print(f"  Anon: {mem.get('anon_mb', 0):.2f} MB")
                if mem.get('file_mb'):
                    print(f"  File: {mem.get('file_mb', 0):.2f} MB")

            # Processes
            procs = metrics['processes']
            if procs.get('available'):
                print(f"\n⚙️  Processes:")
                print(f"  Total: {procs.get('total_processes', 0)}")
                print(f"  Open FDs: {procs.get('current_pid_fds', 0)} / {procs.get('fd_limit', 0)}")
                if procs.get('fd_utilization_percent', 0) > 0:
                    print(f"  FD Usage: {procs.get('fd_utilization_percent', 0):.2f}%")

            # Network
            net = metrics['network']
            if net.get('available'):
                print(f"\n🌐 Network:")
                print(f"  RX: {net.get('total_rx_mb', 0):.2f} MB")
                print(f"  TX: {net.get('total_tx_mb', 0):.2f} MB")

            # Export
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(metrics, f, indent=2)

            if args.one_shot:
                break

            iteration += 1
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\nStopped by user")
        sys.exit(0)


if __name__ == '__main__':
    main()
