import { Button, Card, CopyButton, Group, ScrollArea, Stack, Text } from '@mantine/core';
import { formatJson, hasContent } from './model';

type JsonPreviewCardProps = {
  title: string;
  value: unknown;
  emptyLabel?: string;
  maxHeight?: number;
  withCopy?: boolean;
};

export function JsonPreviewCard({
  title,
  value,
  emptyLabel = 'No data',
  maxHeight = 200,
  withCopy = false
}: JsonPreviewCardProps) {
  const visible = hasContent(value);

  return (
    <Card withBorder radius="sm" padding="sm">
      <Stack gap={6}>
        <Group justify="space-between" align="center" wrap="nowrap">
          <Text size="xs" fw={600}>
            {title}
          </Text>
          <Group gap={6}>
            {!visible && (
              <Text size="xs" c="dimmed">
                {emptyLabel}
              </Text>
            )}
            {visible && withCopy && (
              <CopyButton value={formatJson(value)}>
                {({ copied, copy }) => (
                  <Button size="compact-xs" variant="light" onClick={copy}>
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                )}
              </CopyButton>
            )}
          </Group>
        </Group>
        {visible && (
          <ScrollArea.Autosize mah={maxHeight}>
            <Text
              component="pre"
              fz="xs"
              ff="monospace"
              style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
            >
              {formatJson(value)}
            </Text>
          </ScrollArea.Autosize>
        )}
      </Stack>
    </Card>
  );
}
