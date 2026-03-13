import { Badge, Button, Card, Group, Stack, Text } from '@mantine/core';

type WorkflowBindingPanelProps = {
  projectId: string;
  projectName: string;
  chatBound: boolean;
  routingBound: boolean;
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
  observedDirectRuns,
  projectsUsingWorkflow,
  projectsUsageLoading,
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
          <Badge variant="outline" color="gray" data-testid="release-bind-project-usage-count">
            Projects using workflow {projectsUsingWorkflow.length}
          </Badge>
          {projectsUsageLoading && (
            <Badge variant="outline" color="blue">
              Refreshing usage
            </Badge>
          )}
        </Group>
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
