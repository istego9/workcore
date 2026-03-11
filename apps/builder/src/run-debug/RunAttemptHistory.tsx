import { Badge, Button, Card, CopyButton, Divider, Group, SimpleGrid, Stack, Text } from '@mantine/core';
import { JsonPreviewCard } from './JsonPreviewCard';
import { RunAttemptDiffCard } from './RunAttemptDiffCard';
import { formatTimestamp, nodeStatusBadgeColor, type RunAttemptGroup } from './model';

type RunAttemptHistoryProps = {
  nodeAttempts: RunAttemptGroup[];
  onRerunNode?: (nodeId: string) => void;
  rerunLoadingNodeId?: string | null;
};

export function RunAttemptHistory({
  nodeAttempts,
  onRerunNode,
  rerunLoadingNodeId = null
}: RunAttemptHistoryProps) {
  if (nodeAttempts.length === 0) {
    return (
      <Text size="xs" c="dimmed">
        No node attempts found for this run.
      </Text>
    );
  }

  return (
    <Stack gap="sm">
      {nodeAttempts.map((group) => (
        <Card key={group.nodeId} withBorder radius="sm" padding="sm">
          <Stack gap="xs">
            <Group justify="space-between" align="center">
              <Stack gap={2}>
                <Text size="sm" fw={600}>
                  {group.nodeId}
                </Text>
                <Text size="xs" c="dimmed">
                  {group.attempts.length} attempt{group.attempts.length === 1 ? '' : 's'}
                </Text>
              </Stack>
              {onRerunNode && (
                <Button
                  size="xs"
                  variant="light"
                  loading={rerunLoadingNodeId === group.nodeId}
                  onClick={() => onRerunNode(group.nodeId)}
                >
                  Rerun node
                </Button>
              )}
            </Group>

            {group.attempts.map((attempt, attemptIndex) => (
              <Stack key={`${group.nodeId}-attempt-${attempt.attempt}`} gap="xs">
                {attemptIndex > 0 && <Divider />}
                <Card withBorder radius="sm" padding="sm">
                  <Stack gap="xs">
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={4}>
                        <Group gap={6} wrap="wrap">
                          <Badge variant="outline" color="gray">
                            Attempt {attempt.attempt}
                          </Badge>
                          {attempt.transition !== 'initial' && (
                            <Badge
                              variant="light"
                              color={attempt.transition === 'auto_retry' ? 'orange' : 'blue'}
                            >
                              {attempt.transition === 'auto_retry' ? 'Auto retry' : 'Manual rerun'}
                            </Badge>
                          )}
                          <Badge variant="light" color={nodeStatusBadgeColor(attempt.status)}>
                            {attempt.status}
                          </Badge>
                        </Group>
                        <Group gap={6} wrap="wrap">
                          {attempt.startedAt && (
                            <Text size="xs" c="dimmed">
                              Started {formatTimestamp(attempt.startedAt)}
                            </Text>
                          )}
                          {attempt.completedAt && (
                            <Text size="xs" c="dimmed">
                              Finished {formatTimestamp(attempt.completedAt)}
                            </Text>
                          )}
                        </Group>
                      </Stack>
                      {attempt.traceId && (
                        <CopyButton value={String(attempt.traceId)}>
                          {({ copied, copy }) => (
                            <Button size="compact-xs" variant="light" onClick={copy}>
                              {copied ? 'Trace copied' : 'Copy trace_id'}
                            </Button>
                          )}
                        </CopyButton>
                      )}
                    </Group>

                    {attempt.lastError !== undefined && attempt.lastError !== null && attempt.lastError !== '' && (
                      <Text size="xs" c="red" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
                        {typeof attempt.lastError === 'string'
                          ? attempt.lastError
                          : JSON.stringify(attempt.lastError, null, 2)}
                      </Text>
                    )}

                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                      <JsonPreviewCard title="Output" value={attempt.output} emptyLabel="No output" maxHeight={160} />
                      <JsonPreviewCard title="Usage" value={attempt.usage} emptyLabel="No usage" maxHeight={160} />
                    </SimpleGrid>
                  </Stack>
                </Card>

                {attemptIndex > 0 && (
                  <RunAttemptDiffCard
                    previousAttempt={group.attempts[attemptIndex - 1]}
                    nextAttempt={group.attempts[attemptIndex]}
                  />
                )}
              </Stack>
            ))}
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}
