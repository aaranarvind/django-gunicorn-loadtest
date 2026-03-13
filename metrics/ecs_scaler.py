#!/usr/bin/env python3
"""
ECS Auto-Scaling Handler

Monitors worker/container metrics and automatically scales ECS tasks
based on utilization patterns.

Can be run as:
1. Scheduled task (every 5 minutes)
2. Response to CloudWatch alarms
3. Event-driven from metrics exports
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import boto3

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


class ECSAutoScaler:
    """Handle ECS task scaling based on monitoring recommendations."""

    def __init__(
        self,
        cluster_name: str,
        service_name: str,
        region: str = 'ap-south-1',
        min_tasks: int = 1,
        max_tasks: int = 10,
        dry_run: bool = False,
    ):
        self.cluster_name = cluster_name
        self.service_name = service_name
        self.region = region
        self.min_tasks = min_tasks
        self.max_tasks = max_tasks
        self.dry_run = dry_run

        self.ecs = boto3.client('ecs', region_name=region)
        self.cloudwatch = boto3.client('cloudwatch', region_name=region)

        logger.info(
            f"ECS Auto-Scaler initialized "
            f"(cluster={cluster_name}, service={service_name}, "
            f"min={min_tasks}, max={max_tasks})"
        )

    def get_current_task_count(self) -> int:
        """Get current number of running tasks."""
        try:
            response = self.ecs.describe_services(
                cluster=self.cluster_name,
                services=[self.service_name],
            )
            if response['services']:
                return response['services'][0]['runningCount']
        except Exception as e:
            logger.error(f"Failed to get task count: {e}")
        return 0

    def scale_to_count(self, desired_count: int) -> bool:
        """Scale ECS service to desired task count."""
        current = self.get_current_task_count()

        # Validate bounds
        scaled_count = max(self.min_tasks, min(self.max_tasks, desired_count))

        if scaled_count == current:
            logger.info(f"No scaling needed (current={current})")
            return True

        if self.dry_run:
            logger.info(
                f"[DRY-RUN] Would scale from {current} to {scaled_count} tasks"
            )
            return True

        try:
            logger.info(f"Scaling from {current} to {scaled_count} tasks...")
            self.ecs.update_service(
                cluster=self.cluster_name,
                service=self.service_name,
                desiredCount=scaled_count,
            )
            logger.info(f"✅ Scaled to {scaled_count} tasks")
            return True
        except Exception as e:
            logger.error(f"Failed to scale: {e}")
            return False

    def update_task_definition(
        self,
        uwsgi_processes: int,
        memory_mb: Optional[int] = None,
        cpu_units: Optional[int] = None,
    ) -> bool:
        """
        Update ECS task definition with new worker process count.
        This requires creating a new task definition revision.
        """
        try:
            # Get current task definition
            response = self.ecs.describe_task_definition(
                taskDefinition=f"{self.service_name}:1"
            )
            current_def = response['taskDefinition']

            # Create new revision with updated environment
            new_def = {
                'family': current_def['family'],
                'taskRoleArn': current_def.get('taskRoleArn'),
                'executionRoleArn': current_def.get('executionRoleArn'),
                'containerDefinitions': current_def['containerDefinitions'],
                'memory': memory_mb or current_def.get('memory', 1024),
                'cpu': cpu_units or current_def.get('cpu', 512),
            }

            # Update environment variable
            for container in new_def['containerDefinitions']:
                env = container.get('environment', [])
                # Find or create UWSGI_PROCESSES
                found = False
                for var in env:
                    if var['name'] == 'UWSGI_PROCESSES':
                        var['value'] = str(uwsgi_processes)
                        found = True
                        break
                if not found:
                    env.append({'name': 'UWSGI_PROCESSES', 'value': str(uwsgi_processes)})
                container['environment'] = env

            if self.dry_run:
                logger.info(
                    f"[DRY-RUN] Would register new task def with UWSGI_PROCESSES={uwsgi_processes}"
                )
                return True

            # Register new revision
            response = self.ecs.register_task_definition(**new_def)
            new_task_def_arn = response['taskDefinition']['taskDefinitionArn']
            logger.info(f"✅ Registered new task definition: {new_task_def_arn}")

            # Update service to use new definition
            self.ecs.update_service(
                cluster=self.cluster_name,
                service=self.service_name,
                taskDefinition=new_task_def_arn,
                forceNewDeployment=True,
            )
            logger.info("✅ Updated service to use new task definition")
            return True

        except Exception as e:
            logger.error(f"Failed to update task definition: {e}")
            return False

    def create_scaling_alarm(self, metric_name: str, threshold: float):
        """Create CloudWatch alarm for auto-scaling."""
        try:
            alarm_name = f"{self.service_name}-{metric_name}-alarm"
            self.cloudwatch.put_metric_alarm(
                AlarmName=alarm_name,
                MetricName=metric_name,
                Namespace='UWSGIWorkers',
                Statistic='Average',
                Period=300,  # 5 minutes
                EvaluationPeriods=2,
                Threshold=threshold,
                ComparisonOperator='GreaterThanThreshold',
                AlarmActions=[
                    f'arn:aws:autoscaling:{self.region}:ACCOUNT:scalingPolicy/...'
                ],
            )
            logger.info(f"✅ Created alarm: {alarm_name}")
        except Exception as e:
            logger.error(f"Failed to create alarm: {e}")


class ScalingDecisionEngine:
    """Parse monitoring output and make scaling decisions."""

    def __init__(self, history_minutes: int = 30):
        self.history_minutes = history_minutes
        self.history_file = Path('/tmp/scaling_history.json')
        self._load_history()

    def _load_history(self):
        """Load scaling decision history."""
        if self.history_file.exists():
            try:
                with open(self.history_file) as f:
                    self.history = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load history: {e}")
                self.history = []
        else:
            self.history = []

    def _save_history(self):
        """Save scaling decision history."""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save history: {e}")

    def should_scale(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Determine if scaling should happen based on analysis.
        Returns scaling action or None.
        """
        recommendations = analysis.get('recommendations', [])

        # Look for scaling recommendations
        for rec in recommendations:
            action = rec.get('action', '')
            priority = rec.get('priority', '')

            if action == 'SCALE_UP':
                # Check if we've scaled up recently
                if self._scaled_recently('up', minutes=15):
                    logger.info("Skipping scale-up (already scaled recently)")
                    continue
                return {
                    'action': 'scale_up',
                    'target_tasks': None,  # Auto-calculate
                    'reason': rec.get('reason'),
                }

            elif action == 'SCALE_DOWN':
                # Check if we've scaled down recently
                if self._scaled_recently('down', minutes=15):
                    logger.info("Skipping scale-down (already scaled recently)")
                    continue
                return {
                    'action': 'scale_down',
                    'target_tasks': None,  # Auto-calculate
                    'reason': rec.get('reason'),
                }

        return None

    def _scaled_recently(self, direction: str, minutes: int) -> bool:
        """Check if we've scaled in the given direction recently."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        for event in self.history[-10:]:  # Check last 10 events
            if event.get('action') == f'scale_{direction}':
                event_time = datetime.fromisoformat(event.get('timestamp', ''))
                if event_time > cutoff:
                    return True
        return False

    def record_scaling(self, action: str, result: bool, reason: str = ''):
        """Record a scaling decision."""
        self.history.append({
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'success': result,
            'reason': reason,
        })
        self._save_history()


def analyze_file(filepath: str) -> Optional[Dict[str, Any]]:
    """Load and parse analysis file."""
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load analysis file: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='ECS Auto-Scaling Handler',
    )
    parser.add_argument(
        'analysis_file',
        nargs='?',
        help='JSON analysis file from unified_monitor (if omitted, will run monitor)',
    )
    parser.add_argument(
        '--cluster',
        default='default',
        help='ECS cluster name',
    )
    parser.add_argument(
        '--service',
        required=True,
        help='ECS service name',
    )
    parser.add_argument(
        '--min-tasks',
        type=int,
        default=1,
        help='Minimum tasks to maintain',
    )
    parser.add_argument(
        '--max-tasks',
        type=int,
        default=10,
        help='Maximum tasks to scale to',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate actions without making changes',
    )
    parser.add_argument(
        '--url',
        default='http://localhost:8000',
        help='Django app URL (if running monitor)',
    )

    args = parser.parse_args()

    # Load analysis
    if args.analysis_file:
        analysis = analyze_file(args.analysis_file)
    else:
        # Run unified monitor
        logger.info("Running unified monitor...")
        from metrics.unified_monitor import UnifiedMonitor
        monitor = UnifiedMonitor(base_url=args.url)
        data = monitor.collect()
        analysis = monitor.analyze(data)

    if not analysis:
        logger.error("Failed to get analysis")
        sys.exit(1)

    # Initialize auto-scaler
    scaler = ECSAutoScaler(
        cluster_name=args.cluster,
        service_name=args.service,
        min_tasks=args.min_tasks,
        max_tasks=args.max_tasks,
        dry_run=args.dry_run,
    )

    # Make scaling decision
    decision_engine = ScalingDecisionEngine()
    scaling_action = decision_engine.should_scale(analysis)

    if scaling_action:
        logger.info(f"Scaling decision: {scaling_action['action']}")
        logger.info(f"Reason: {scaling_action['reason']}")

        # Calculate target
        current_count = scaler.get_current_task_count()
        if scaling_action['action'] == 'scale_up':
            target = min(current_count + 2, args.max_tasks)
        else:
            target = max(current_count - 1, args.min_tasks)

        logger.info(f"Current: {current_count}, Target: {target}")

        # Execute scaling
        result = scaler.scale_to_count(target)
        decision_engine.record_scaling(
            scaling_action['action'],
            result,
            scaling_action['reason'],
        )
    else:
        logger.info("No scaling action needed")

    # Print current state
    logger.info(f"Status: {analysis.get('health_status')}")
    logger.info(f"Bottleneck: {analysis.get('bottleneck')}")


if __name__ == '__main__':
    main()
