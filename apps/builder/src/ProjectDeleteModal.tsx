import { Button, Group, Modal, Stack, Text } from '@mantine/core';

type ProjectDeleteModalProps = {
  opened: boolean;
  loading: boolean;
  projectLabel: string;
  onClose: () => void;
  onConfirm: () => void;
};

export function ProjectDeleteModal({
  opened,
  loading,
  projectLabel,
  onClose,
  onConfirm
}: ProjectDeleteModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} title="Delete project?" centered size="sm">
      <Stack gap="sm">
        <Text size="sm">
          Delete project <b>{projectLabel}</b>?
        </Text>
        <Text size="sm" c="dimmed">
          This action cannot be undone. Project with workflows cannot be deleted.
        </Text>
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button color="red" onClick={onConfirm} loading={loading} data-testid="delete-project-confirm">
            Delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
