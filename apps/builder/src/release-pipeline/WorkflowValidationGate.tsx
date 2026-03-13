import { Badge, Button, Card, Group, Stack, Text } from '@mantine/core';
import type { ValidationGateSummary } from './model';

type WorkflowValidationGateProps = {
  summary: ValidationGateSummary;
  lastRunAt: string | null;
  onRerun: () => void;
  onFocusNode: (nodeId: string) => void;
};

const formatTimestamp = (value: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

export function WorkflowValidationGate({
  summary,
  lastRunAt,
  onRerun,
  onFocusNode,
}: WorkflowValidationGateProps) {
  return (
    <Card withBorder radius="md" data-testid="release-stage-validate">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text fw={600}>Validate</Text>
          <Badge color={summary.passed ? 'teal' : 'red'} variant="light">
            {summary.passed ? 'Passed' : 'Blocked'}
          </Badge>
        </Group>
        <Group gap="xs" wrap="wrap">
          <Badge variant="outline" color={summary.blocking_issues.length ? 'red' : 'gray'}>
            Blocking {summary.blocking_issues.length}
          </Badge>
          <Badge variant="outline" color={summary.warnings.length ? 'yellow' : 'gray'}>
            Warnings {summary.warnings.length}
          </Badge>
          {lastRunAt && (
            <Badge variant="light" color="gray">
              Last run {formatTimestamp(lastRunAt)}
            </Badge>
          )}
        </Group>
        <Button size="xs" variant="light" onClick={onRerun} data-testid="release-validate-rerun">
          Re-run validation
        </Button>
        {summary.blocking_issues.length > 0 && (
          <Stack gap={6}>
            {summary.blocking_issues.slice(0, 6).map((issue) => (
              <Card key={issue.id} withBorder radius="sm" padding="sm">
                <Stack gap={6}>
                  <Text size="sm">{issue.message}</Text>
                  {issue.nodeId && (
                    <Button size="xs" variant="subtle" onClick={() => onFocusNode(issue.nodeId!)} w="fit-content">
                      Focus node {issue.nodeId}
                    </Button>
                  )}
                </Stack>
              </Card>
            ))}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
