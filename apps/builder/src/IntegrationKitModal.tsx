import { Anchor, Button, CopyButton, Divider, Group, Modal, Stack, Text, TextInput } from '@mantine/core';

type IntegrationKitModalProps = {
  opened: boolean;
  links: {
    integrationKitMarkdown: string;
    integrationKitJson: string;
    integrationTestUi: string;
    integrationTestJson: string;
    validateDraft: string;
    openapi: string;
    apiReference: string;
    workflowAuthoringGuide: string;
    workflowDraftSchema: string;
    workflowExportSchema: string;
  };
  onClose: () => void;
};

export function IntegrationKitModal({ opened, links, onClose }: IntegrationKitModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} title="Agent integration kit" centered size="lg">
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          Share this URL with external agents. It includes links to OpenAPI, API reference, workflow authoring guide,
          and JSON schemas.
        </Text>
        <Group align="flex-end" wrap="nowrap">
          <TextInput label="Shareable URL" value={links.integrationKitMarkdown} readOnly style={{ flex: 1 }} />
          <CopyButton value={links.integrationKitMarkdown}>
            {({ copied, copy }) => (
              <Button variant="light" onClick={copy}>
                {copied ? 'Copied' : 'Copy'}
              </Button>
            )}
          </CopyButton>
          <Button component="a" href={links.integrationKitMarkdown} target="_blank" rel="noopener noreferrer">
            Open
          </Button>
        </Group>
        <Divider />
        <Stack gap={6}>
          <Text size="sm" fw={600}>
            Resources
          </Text>
          <Anchor href={links.integrationKitJson} target="_blank" rel="noopener noreferrer">
            JSON bundle
          </Anchor>
          <Anchor href={links.integrationTestUi} target="_blank" rel="noopener noreferrer">
            Integration test UI
          </Anchor>
          <Anchor href={links.integrationTestJson} target="_blank" rel="noopener noreferrer">
            Integration test JSON report
          </Anchor>
          <Anchor href={links.validateDraft} target="_blank" rel="noopener noreferrer">
            Draft validator endpoint
          </Anchor>
          <Anchor href={links.openapi} target="_blank" rel="noopener noreferrer">
            OpenAPI contract
          </Anchor>
          <Anchor href={links.apiReference} target="_blank" rel="noopener noreferrer">
            API reference
          </Anchor>
          <Anchor href={links.workflowAuthoringGuide} target="_blank" rel="noopener noreferrer">
            Workflow authoring guide
          </Anchor>
          <Anchor href={links.workflowDraftSchema} target="_blank" rel="noopener noreferrer">
            Workflow draft JSON schema
          </Anchor>
          <Anchor href={links.workflowExportSchema} target="_blank" rel="noopener noreferrer">
            Workflow export JSON schema
          </Anchor>
        </Stack>
      </Stack>
    </Modal>
  );
}
