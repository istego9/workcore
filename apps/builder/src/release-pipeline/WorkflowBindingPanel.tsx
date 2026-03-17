import { Badge, Button, Card, Group, Stack, Text } from '@mantine/core';

type WorkflowBindingPanelProps = {
  projectId: string;
  projectName: string;
  chatBound: boolean;
  routingBound: boolean;
  routingReadbackStatus: 'checking' | 'bound' | 'not_bound' | 'readback_failed';
  routingDefinitionUpdatedAt?: string | null;
  observedDirectRuns: number;
  projectsUsingWorkflow: Array<{ project_id: string; project_name: string }>;
  projectsUsageLoading: boolean;
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
  routingReadbackStatus,
  routingDefinitionUpdatedAt,
  observedDirectRuns,
  projectsUsingWorkflow,
  projectsUsageLoading,
  loadingChatBind,
  loadingRoutingBind,
  onBindChat,
  onBindRouting,
}: WorkflowBindingPanelProps) {
  const routingBadge = (() => {
    if (routingReadbackStatus === 'bound') {
      return { color: 'teal', variant: 'light' as const, label: 'Routing definition bound' };
    }
    if (routingReadbackStatus === 'readback_failed') {
      return { color: 'red', variant: 'light' as const, label: 'Routing readback failed' };
    }
    if (routingReadbackStatus === 'checking') {
      return { color: 'blue', variant: 'outline' as const, label: 'Routing definition checking' };
    }
    return { color: 'gray', variant: 'outline' as const, label: 'Routing definition not bound' };
  })();

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
          <Badge variant={routingBadge.variant} color={routingBadge.color} data-testid="release-routing-readback-status">
            {routingBadge.label}
          </Badge>
          <Badge variant="outline" color="gray">
            Observed direct runs {observedDirectRuns}
          </Badge>
          <Badge variant="outline" color="gray" data-testid="release-bind-project-usage-count">
            Projects using workflow {projectsUsingWorkflow.length}
          </Badge>
          {projectsUsageLoading && (
            <Badge variant="outline" color="blue">
              Refreshing usage
            </Badge>
          )}
        </Group>
        {routingDefinitionUpdatedAt && routingBound && (
          <Text size="xs" c="dimmed">
            Routing definition confirmed by API readback at {routingDefinitionUpdatedAt}.
          </Text>
        )}
        {routingReadbackStatus === 'readback_failed' && (
          <Text size="xs" c="red">
            Builder could not confirm routing state from the API. Observed direct runs remain diagnostic only and do not
            close the Bind stage.
          </Text>
        )}
        {routingReadbackStatus === 'not_bound' && observedDirectRuns > 0 && (
          <Text size="xs" c="dimmed">
            Direct runs were observed, but Bind remains open until workflow-definition readback succeeds.
          </Text>
        )}
        {projectsUsingWorkflow.length > 0 && (
          <Group gap="xs" wrap="wrap">
            {projectsUsingWorkflow.slice(0, 8).map((project) => (
              <Badge key={project.project_id} variant="light" color="teal">
                {project.project_name} ({project.project_id})
              </Badge>
            ))}
            {projectsUsingWorkflow.length > 8 && (
              <Badge variant="outline" color="gray">
                +{projectsUsingWorkflow.length - 8} more
              </Badge>
            )}
          </Group>
        )}
        {projectsUsingWorkflow.length === 0 && !projectsUsageLoading && (
          <Text size="xs" c="dimmed">
            No projects currently use this workflow as default chat workflow.
          </Text>
        )}
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
