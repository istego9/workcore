import { Badge, Card, Divider, Group, Stack, Text } from '@mantine/core';
import {
  formatTimestamp,
  nodeStatusBadgeColor,
  type RunAttemptGroup,
  type RunTimelineEvent,
  runStatusBadgeColor
} from './model';

type RunTimelineProps = {
  runTimeline: RunTimelineEvent[];
  nodeAttempts: RunAttemptGroup[];
};

const renderEventRow = (event: RunTimelineEvent) => (
  <Group key={event.id} justify="space-between" align="flex-start" wrap="nowrap">
    <Stack gap={2}>
      <Text size="sm" fw={500}>
        {event.message}
      </Text>
      <Group gap={6} wrap="wrap">
        <Text size="xs" c="dimmed">
          {formatTimestamp(event.timestamp)}
        </Text>
        {event.nodeId && (
          <Badge variant="outline" color="gray">
            {event.nodeId}
          </Badge>
        )}
        {typeof event.attempt === 'number' && (
          <Badge variant="outline" color="gray">
            Attempt {event.attempt}
          </Badge>
        )}
      </Group>
    </Stack>
    <Badge
      variant="light"
      color={event.scope === 'run' ? runStatusBadgeColor(event.status) : nodeStatusBadgeColor(event.status)}
    >
      {event.status}
    </Badge>
  </Group>
);

export function RunTimeline({ runTimeline, nodeAttempts }: RunTimelineProps) {
  return (
    <Stack gap="sm">
      <Text size="xs" c="dimmed">
        Grouped deterministically by run, then node, then attempt.
      </Text>

      <Card withBorder radius="sm" padding="sm">
        <Stack gap="xs">
          <Text size="sm" fw={600}>
            Run events
          </Text>
          {runTimeline.length === 0 ? (
            <Text size="xs" c="dimmed">
              No run-level events in ledger.
            </Text>
          ) : (
            runTimeline.map((event, index) => (
              <Stack key={event.id} gap={6}>
                {index > 0 && <Divider />}
                {renderEventRow(event)}
              </Stack>
            ))
          )}
        </Stack>
      </Card>

      {nodeAttempts.length === 0 ? (
        <Text size="xs" c="dimmed">
          No node timeline events available.
        </Text>
      ) : (
        nodeAttempts.map((group) => (
          <Card key={group.nodeId} withBorder radius="sm" padding="sm">
            <Stack gap="xs">
              <Group justify="space-between" align="center">
                <Text size="sm" fw={600}>
                  Node {group.nodeId}
                </Text>
                <Badge variant="outline" color="gray">
                  Attempts {group.attempts.length}
                </Badge>
              </Group>
              {group.attempts.map((attempt) => (
                <Card key={`${group.nodeId}-attempt-${attempt.attempt}`} withBorder radius="sm" padding="sm">
                  <Stack gap="xs">
                    <Group justify="space-between" align="center">
                      <Group gap={6}>
                        <Badge variant="outline" color="gray">
                          Attempt {attempt.attempt}
                        </Badge>
                        {attempt.transition !== 'initial' && (
                          <Badge variant="light" color={attempt.transition === 'auto_retry' ? 'orange' : 'blue'}>
                            {attempt.transition === 'auto_retry' ? 'Auto retry' : 'Manual rerun'}
                          </Badge>
                        )}
                      </Group>
                      <Badge color={nodeStatusBadgeColor(attempt.status)} variant="light">
                        {attempt.status}
                      </Badge>
                    </Group>
                    {attempt.timeline.length === 0 ? (
                      <Text size="xs" c="dimmed">
                        No ledger events captured for this attempt.
                      </Text>
                    ) : (
                      attempt.timeline.map(renderEventRow)
                    )}
                  </Stack>
                </Card>
              ))}
            </Stack>
          </Card>
        ))
      )}
    </Stack>
  );
}
