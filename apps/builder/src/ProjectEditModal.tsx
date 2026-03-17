import { Button, Group, Modal, Select, Stack, Text, TextInput } from '@mantine/core';

type ProjectEditModalProps = {
  opened: boolean;
  loading: boolean;
  projectName: string;
  workflowOptions: Array<{ value: string; label: string }>;
  defaultChatWorkflowId: string;
  onClose: () => void;
  onProjectNameChange: (value: string) => void;
  onDefaultChatWorkflowChange: (value: string) => void;
  onSave: () => void;
};

export function ProjectEditModal({
  opened,
  loading,
  projectName,
  workflowOptions,
  defaultChatWorkflowId,
  onClose,
  onProjectNameChange,
  onDefaultChatWorkflowChange,
  onSave
}: ProjectEditModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} title="Edit project" centered size="sm">
      <Stack gap="sm">
        <TextInput
          label="Project name"
          value={projectName}
          onChange={(event) => onProjectNameChange(event.currentTarget.value)}
          data-testid="edit-project-name-input"
        />
        <Select
          label="Default chat workflow"
          placeholder={workflowOptions.length ? 'Select published workflow' : 'No published workflows in project'}
          value={defaultChatWorkflowId || null}
          data={workflowOptions}
          onChange={(value) => onDefaultChatWorkflowChange(value || '')}
          clearable
          searchable
          nothingFoundMessage="No workflows"
          data-testid="edit-project-default-chat-workflow"
        />
        <Text size="xs" c="dimmed">
          Project chat currently serves {defaultChatWorkflowId || 'no workflow selected'}.
        </Text>
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={onSave} loading={loading} data-testid="edit-project-confirm">
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
