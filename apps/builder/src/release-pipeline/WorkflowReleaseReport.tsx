import { Badge, Button, Card, Group, Stack, Text } from '@mantine/core';
import type { ReleaseReport } from './model';

type WorkflowReleaseReportProps = {
  report: ReleaseReport;
  onExport: () => void;
};

export function WorkflowReleaseReport({ report, onExport }: WorkflowReleaseReportProps) {
  return (
    <Card withBorder radius="md" data-testid="release-stage-report">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text fw={600}>Release report</Text>
          <Button size="xs" variant="light" onClick={onExport} data-testid="release-report-export">
            Export JSON
          </Button>
        </Group>
        <Group gap="xs" wrap="wrap">
          <Badge variant="outline" color="gray">
            Workflow {report.workflow_id}
          </Badge>
          <Badge variant="outline" color="gray">
            Candidate {report.candidate_version_id}
          </Badge>
          <Badge variant="outline" color="gray">
            Published {report.published_version_id || 'none'}
          </Badge>
        </Group>
        <Group gap="xs" wrap="wrap">
          <Badge variant={report.validation_result.passed ? 'light' : 'outline'} color={report.validation_result.passed ? 'teal' : 'red'}>
            Validation {report.validation_result.passed ? 'pass' : 'fail'}
          </Badge>
          <Badge variant={report.simulation_result.status === 'passed' ? 'light' : 'outline'} color={report.simulation_result.status === 'passed' ? 'teal' : 'yellow'}>
            Simulation {report.simulation_result.status}
          </Badge>
          <Badge variant={report.smoke_result.status === 'success' ? 'light' : 'outline'} color={report.smoke_result.status === 'success' ? 'teal' : 'yellow'}>
            Smoke {report.smoke_result.status}
          </Badge>
        </Group>
        <Text size="xs" c="dimmed">
          Includes validation/simulation/diff/bind/smoke summaries, timestamps, run IDs, and correlation IDs.
        </Text>
      </Stack>
    </Card>
  );
}
