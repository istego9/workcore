import { Anchor, Badge, Button, Card, Group, Stack, Text } from '@mantine/core';
import type { SmokeResultSummary } from './model';

type WorkflowSmokeRunnerProps = {
  smoke: SmokeResultSummary | null;
  loading: boolean;
  runDetailsUrl: string | null;
  onRunSmoke: () => void;
  onOpenRunDebug: () => void;
};

const smokeColor = (status: SmokeResultSummary['status'] | null) => {
  if (status === 'success') return 'teal';
  if (status === 'failed') return 'red';
  if (status === 'running' || status === 'timeout') return 'yellow';
  return 'gray';
};

export function WorkflowSmokeRunner({
  smoke,
  loading,
  runDetailsUrl,
  onRunSmoke,
  onOpenRunDebug,
}: WorkflowSmokeRunnerProps) {
  const status = smoke?.status || 'not_started';
  return (
    <Card withBorder radius="md" data-testid="release-stage-smoke">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text fw={600}>Smoke</Text>
          <Badge color={smokeColor(status)} variant="light">
            {status}
          </Badge>
        </Group>
        <Button size="xs" loading={loading} onClick={onRunSmoke} data-testid="release-smoke-run">
          Run smoke test
        </Button>
        {smoke?.run_id && (
          <Group gap="xs" wrap="wrap">
            <Badge variant="outline" color="gray">
              Run {smoke.run_id}
            </Badge>
            {smoke.correlation_id && (
              <Badge variant="outline" color="gray">
                Correlation {smoke.correlation_id}
              </Badge>
            )}
          </Group>
        )}
        <Group gap="xs" wrap="wrap">
          <Button
            size="xs"
            variant="light"
            onClick={onOpenRunDebug}
            disabled={!smoke?.run_id}
            data-testid="release-open-run-debug"
          >
            Open Run Debug
          </Button>
          {runDetailsUrl && (
            <Anchor href={runDetailsUrl} target="_blank" rel="noopener noreferrer" size="xs">
              Open run details
            </Anchor>
          )}
        </Group>
        {smoke?.typed_errors.length ? (
          <Stack gap={4}>
            {smoke.typed_errors.slice(0, 6).map((error) => (
              <Text key={error} size="xs" c="red">
                {error}
              </Text>
            ))}
          </Stack>
        ) : null}
      </Stack>
    </Card>
  );
}
