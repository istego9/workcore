import { Badge, Card, Group, SimpleGrid, Stack, Text } from '@mantine/core';
import { buildAttemptDiff, type RunAttemptRecord } from './model';
import { JsonPreviewCard } from './JsonPreviewCard';

type RunAttemptDiffCardProps = {
  previousAttempt: RunAttemptRecord;
  nextAttempt: RunAttemptRecord;
};

export function RunAttemptDiffCard({ previousAttempt, nextAttempt }: RunAttemptDiffCardProps) {
  const diff = buildAttemptDiff(previousAttempt, nextAttempt);
  if (!diff) return null;

  return (
    <Card withBorder radius="sm" padding="sm">
      <Stack gap="xs">
        <Group justify="space-between" align="center">
          <Text size="xs" fw={600}>
            Attempt diff {diff.fromAttempt} → {diff.toAttempt}
          </Text>
          <Badge color="grape" variant="light">
            {diff.changes.length} change{diff.changes.length === 1 ? '' : 's'}
          </Badge>
        </Group>
        {diff.changes.map((change) => (
          <SimpleGrid key={change.field} cols={{ base: 1, sm: 2 }} spacing="sm">
            <JsonPreviewCard
              title={`${change.field} (before)`}
              value={change.before}
              emptyLabel="No value"
              maxHeight={160}
            />
            <JsonPreviewCard
              title={`${change.field} (after)`}
              value={change.after}
              emptyLabel="No value"
              maxHeight={160}
            />
          </SimpleGrid>
        ))}
      </Stack>
    </Card>
  );
}
