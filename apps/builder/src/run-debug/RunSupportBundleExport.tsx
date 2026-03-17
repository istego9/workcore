import { Button, Card, Group, Stack, Text } from '@mantine/core';
import { API_BASE, type RunLedgerRecord, type RunRecord } from '../api';
import {
  buildRunSupportBundle,
  formatSupportBundle,
  type RunDebugModel,
  type RunSupportLedgerSummary
} from './model';

type RunSupportBundleExportProps = {
  run: RunRecord;
  ledgerEntries: RunLedgerRecord[];
  model: RunDebugModel;
  ledgerSummary?: RunSupportLedgerSummary;
  ledgerLimit?: number;
  loading?: boolean;
  onExported?: (bundle: ReturnType<typeof buildRunSupportBundle>) => void;
};

const toAbsoluteDocLink = (path: string): string => {
  try {
    return new URL(path, API_BASE).toString();
  } catch {
    return path;
  }
};

const DEFAULT_DOC_LINKS = [toAbsoluteDocLink('/openapi.yaml'), toAbsoluteDocLink('/workflow-authoring-guide')];
const DEFAULT_BUNDLE_LEDGER_LIMIT = 5000;

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
  ledgerSummary,
  ledgerLimit = DEFAULT_BUNDLE_LEDGER_LIMIT,
  loading = false,
  onExported
}: RunSupportBundleExportProps) {
  const available = Math.max(ledgerSummary?.ledger_entries_available || ledgerEntries.length, ledgerEntries.length);
  const availableExact = ledgerSummary?.ledger_entries_available_exact ?? true;
  const included = Math.min(ledgerEntries.length, Math.max(1, Math.floor(ledgerLimit)));
  const bundleTruncated = (ledgerSummary?.ledger_truncated ?? false) || included < available;

  const handleExport = () => {
    const bundle = buildRunSupportBundle({
      run,
      ledgerEntries,
      model,
      ledgerLimit,
      ledgerSummary,
      docsLinks: DEFAULT_DOC_LINKS
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
          and an explicitly annotated ledger slice with redaction/completeness metadata.
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
            Entries in bundle ledger: {included} / {available}
            {!availableExact ? '+' : ''}
          </Text>
        </Group>
        {bundleTruncated && (
          <Text size="xs" c="yellow">
            Export is truncated. Use `ledger_truncated`, `ledger_entries_included`, and `ledger_entries_available` fields
            inside the bundle for support escalation context.
          </Text>
        )}
      </Stack>
    </Card>
  );
}
