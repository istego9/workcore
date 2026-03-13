import {
  Badge,
  Button,
  Card,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import type { SimulationExecutionResult } from './model';

type SimulationSource = 'canned' | 'last_good' | 'manual';

type WorkflowSimulationPanelProps = {
  source: SimulationSource;
  onSourceChange: (value: SimulationSource) => void;
  manualCasesJson: string;
  onManualCasesJsonChange: (value: string) => void;
  manualJsonError: string | null;
  selectedCasesCount: number;
  running: boolean;
  result: SimulationExecutionResult | null;
  errorMessage: string | null;
  hasLastGoodCases: boolean;
  onRun: () => void;
};

const toPercent = (value: number) => `${Math.round(value * 100)}%`;

export function WorkflowSimulationPanel({
  source,
  onSourceChange,
  manualCasesJson,
  onManualCasesJsonChange,
  manualJsonError,
  selectedCasesCount,
  running,
  result,
  errorMessage,
  hasLastGoodCases,
  onRun,
}: WorkflowSimulationPanelProps) {
  return (
    <Card withBorder radius="md" data-testid="release-stage-simulate">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text fw={600}>Simulate</Text>
          <Badge
            color={
              result?.status === 'passed' ? 'teal' : result?.status === 'failed' ? 'red' : 'gray'
            }
            variant="light"
          >
            {result?.status === 'passed'
              ? 'Passed'
              : result?.status === 'failed'
                ? 'Failed'
                : 'Not run'}
          </Badge>
        </Group>
        <Select
          label="Case source"
          value={source}
          data={[
            { value: 'canned', label: 'Canned cases' },
            {
              value: 'last_good',
              label: hasLastGoodCases ? 'Last known good cases' : 'Last known good cases (none found)',
            },
            { value: 'manual', label: 'Manual cases JSON' },
          ]}
          allowDeselect={false}
          onChange={(value) => onSourceChange((value as SimulationSource) || 'canned')}
        />
        {source === 'manual' && (
          <Textarea
            label="Manual cases"
            description='JSON array of cases. Example: [{"message_text":"start","expected_workflow_id":"wf_1"}]'
            value={manualCasesJson}
            minRows={6}
            onChange={(event) => onManualCasesJsonChange(event.currentTarget.value)}
            error={manualJsonError || undefined}
            data-testid="release-simulation-manual-json"
          />
        )}
        <Group justify="space-between" align="center">
          <Badge variant="outline" color="gray">
            Cases {selectedCasesCount}
          </Badge>
          <Button
            size="xs"
            loading={running}
            onClick={onRun}
            disabled={selectedCasesCount === 0}
            data-testid="release-simulation-run"
          >
            Run simulation
          </Button>
        </Group>
        {errorMessage && (
          <Text size="sm" c="red">
            {errorMessage}
          </Text>
        )}
        {result && result.status !== 'not_run' && (
          <Stack gap="xs">
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
              <Badge variant="outline" color="gray">
                Total {result.total_cases}
              </Badge>
              <Badge variant="outline" color="teal">
                Passed {result.passed_cases}
              </Badge>
              <Badge variant="outline" color="red">
                Failed {result.failed_cases}
              </Badge>
              <Badge variant="outline" color="indigo">
                Confidence {toPercent(result.metrics.average_confidence)}
              </Badge>
            </SimpleGrid>
            <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
              <Badge variant="light" color="gray">
                Action accuracy {toPercent(result.metrics.action_accuracy)}
              </Badge>
              <Badge variant="light" color="gray">
                Workflow accuracy {toPercent(result.metrics.workflow_accuracy)}
              </Badge>
              <Badge variant="light" color="gray">
                Exact match {toPercent(result.metrics.exact_match_rate)}
              </Badge>
            </SimpleGrid>
            {result.typed_failures.length > 0 && (
              <Stack gap={4}>
                {result.typed_failures.slice(0, 8).map((failure) => (
                  <Text key={failure} size="xs" c="red">
                    {failure}
                  </Text>
                ))}
              </Stack>
            )}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
