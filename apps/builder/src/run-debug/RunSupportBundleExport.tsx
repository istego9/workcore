import { Button, Card, Group, Stack, Text } from '@mantine/core';
import type { RunLedgerRecord, RunRecord } from '../api';
import { buildRunSupportBundle, formatSupportBundle, type RunDebugModel } from './model';

type RunSupportBundleExportProps = {
  run: RunRecord;
  ledgerEntries: RunLedgerRecord[];
  model: RunDebugModel;
  loading?: boolean;
  onExported?: (bundle: ReturnType<typeof buildRunSupportBundle>) => void;
};

const downloadBundle = (filename: string, body: string) => {
  const blob = new Blob([body], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
};

export function RunSupportBundleExport({
  run,
  ledgerEntries,
  model,
  loading = false,
  onExported
}: RunSupportBundleExportProps) {
  const handleExport = () => {
    const bundle = buildRunSupportBundle({
      run,
      ledgerEntries,
      model,
      docsLinks: ['/docs/api/reference.md', '/docs/architecture/runtime.md']
    });
    const fileName = `run-${run.run_id}-support-bundle.json`;
    downloadBundle(fileName, formatSupportBundle(bundle));
    onExported?.(bundle);
  };

  return (
    <Card withBorder radius="sm" padding="sm">
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          Support bundle export
        </Text>
        <Text size="xs" c="dimmed">
          Exported JSON includes run summary, normalized timeline, attempts, retry/rerun chronology, last-good output,
          and a bounded ledger slice with redaction.
        </Text>
        <Text size="xs" c="dimmed">
          Redaction removes secrets, credentials, auth headers/signatures, inline artifact body fields, and heavy binary
          fields such as image_base64 while preserving artifact_ref references.
        </Text>
        <Group justify="flex-start">
          <Button size="xs" variant="light" onClick={handleExport} loading={loading}>
            Export support bundle
          </Button>
          <Text size="xs" c="dimmed">
            Entries in bundle ledger: {Math.min(ledgerEntries.length, 500)} / {ledgerEntries.length}
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}
