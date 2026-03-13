import { Badge, Card, Group, Stack, Text } from '@mantine/core';
import type { WorkflowDiffSummary } from './model';

type WorkflowVersionDiffProps = {
  diff: WorkflowDiffSummary | null;
  loading: boolean;
};

const listPreview = (items: string[], limit = 6) => {
  if (!items.length) return 'None';
  const preview = items.slice(0, limit).join(', ');
  const rest = items.length - limit;
  return rest > 0 ? `${preview} (+${rest} more)` : preview;
};

export function WorkflowVersionDiff({ diff, loading }: WorkflowVersionDiffProps) {
  return (
    <Card withBorder radius="md" data-testid="release-stage-diff">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text fw={600}>Diff</Text>
          <Badge
            color={diff?.has_changes ? 'yellow' : diff ? 'teal' : 'gray'}
            variant="light"
          >
            {loading ? 'Loading' : diff?.has_changes ? 'Changes detected' : 'No changes'}
          </Badge>
        </Group>
        {loading ? (
          <Text size="sm" c="dimmed">
            Loading published versions...
          </Text>
        ) : !diff ? (
          <Text size="sm" c="dimmed">
            Diff unavailable.
          </Text>
        ) : (
          <Stack gap={6}>
            <Group gap="xs" wrap="wrap">
              <Badge variant="outline" color="gray">
                Baseline {diff.baseline_version_id || 'none'}
              </Badge>
              <Badge variant="outline" color="gray">
                Candidate {diff.candidate_fingerprint}
              </Badge>
            </Group>
            <Text size="sm">Node additions: {listPreview(diff.node_additions)}</Text>
            <Text size="sm">Node removals: {listPreview(diff.node_removals)}</Text>
            <Text size="sm">Edge additions: {listPreview(diff.edge_additions)}</Text>
            <Text size="sm">Edge removals: {listPreview(diff.edge_removals)}</Text>
            <Text size="sm">
              Config changes: {diff.config_changes.length ? `${diff.config_changes.length} nodes` : 'None'}
            </Text>
            <Text size="sm">Routing/policy changes: {listPreview(diff.routing_policy_changes)}</Text>
            <Text size="sm">Affected bindings: {listPreview(diff.affected_bindings)}</Text>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
