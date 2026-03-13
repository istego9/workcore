import { Badge, Button, Card, Group, Stack, Text } from '@mantine/core';

type WorkflowBindingPanelProps = {
  projectId: string;
  projectName: string;
  chatBound: boolean;
  routingBound: boolean;
  observedDirectRuns: number;
  loadingChatBind: boolean;
  loadingRoutingBind: boolean;
  onBindChat: () => void;
  onBindRouting: () => void;
};

export function WorkflowBindingPanel({
  projectId,
  projectName,
  chatBound,
  routingBound,
  observedDirectRuns,
  loadingChatBind,
  loadingRoutingBind,
  onBindChat,
  onBindRouting,
}: WorkflowBindingPanelProps) {
  return (
    <Card withBorder radius="md" data-testid="release-stage-bind">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text fw={600}>Bind</Text>
          <Badge color={chatBound || routingBound ? 'teal' : 'yellow'} variant="light">
            {chatBound || routingBound ? 'Bound' : 'Pending'}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed">
          Project {projectName} ({projectId})
        </Text>
        <Group gap="xs" wrap="wrap">
          <Badge variant={chatBound ? 'light' : 'outline'} color={chatBound ? 'teal' : 'gray'}>
            Default chat {chatBound ? 'bound' : 'not bound'}
          </Badge>
          <Badge variant={routingBound ? 'light' : 'outline'} color={routingBound ? 'teal' : 'gray'}>
            Routing definition {routingBound ? 'updated' : 'unknown'}
          </Badge>
          <Badge variant="outline" color="gray">
            Observed direct runs {observedDirectRuns}
          </Badge>
        </Group>
        <Group gap="xs" wrap="wrap">
          <Button
            size="xs"
            variant="light"
            loading={loadingChatBind}
            onClick={onBindChat}
            data-testid="release-bind-chat"
          >
            Bind as project chat workflow
          </Button>
          <Button
            size="xs"
            variant="light"
            loading={loadingRoutingBind}
            onClick={onBindRouting}
            data-testid="release-bind-routing"
          >
            Upsert routing definition
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
