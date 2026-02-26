import {
  Badge,
  Box,
  Button,
  Card,
  Divider,
  Group,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title
} from '@mantine/core';
import { useEffect, useMemo, useRef, useState } from 'react';
import { streamRequest, transcribeInput, type ChatKitClientOptions } from './api/chatkit-client';
import type { ChatKitRequest, ThreadItem, WidgetActionPayload } from './protocol/types';
import { applyStreamEvent, createEmptyThreadState, type ThreadState } from './state/thread-store';
import { useSttRecorder } from './stt/useSttRecorder';
import { WidgetRenderer } from './widgets/WidgetRenderer';

const inferRootHost = (hostname: string) => {
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') {
    return 'localhost';
  }
  if (hostname.startsWith('builder.')) return hostname.slice('builder.'.length);
  if (hostname.startsWith('api.')) return hostname.slice('api.'.length);
  if (hostname.startsWith('chatkit.')) return hostname.slice('chatkit.'.length);
  return hostname;
};

const inferDefaultApiUrl = () => {
  const rootHost = inferRootHost(window.location.hostname);
  const chatkitHost = rootHost === 'localhost' ? 'chatkit.localhost' : `chatkit.${rootHost}`;
  const port = window.location.port ? `:${window.location.port}` : '';
  return `${window.location.protocol}//${chatkitHost}${port}/chatkit`;
};

const contentText = (item: ThreadItem): string => {
  if (!Array.isArray(item.content)) return '';
  return item.content
    .map((part) => (typeof part?.text === 'string' ? part.text : ''))
    .filter(Boolean)
    .join('\n')
    .trim();
};

const isWidgetItem = (item: ThreadItem): boolean => item.type === 'widget' && Boolean(item.widget);

export default function App() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const embed = params.get('embed') === '1';
  const autoConnect = params.get('auto') === '1' || embed;
  const autoStart = params.get('auto_start') === '1';

  const [apiUrl, setApiUrl] = useState(params.get('api_url') || inferDefaultApiUrl());
  const [domainKey, setDomainKey] = useState(params.get('domain_key') || '');
  const [workflowId, setWorkflowId] = useState(params.get('workflow_id') || '');
  const [workflowVersionId, setWorkflowVersionId] = useState(params.get('workflow_version_id') || '');
  const [projectId, setProjectId] = useState(params.get('project_id') || '');
  const [authToken, setAuthToken] = useState(params.get('auth_token') || '');
  const [tenantId, setTenantId] = useState(params.get('tenant_id') || 'local');
  const [threadState, setThreadState] = useState<ThreadState>(() => createEmptyThreadState());
  const [composerValue, setComposerValue] = useState('');
  const [status, setStatus] = useState('Idle');
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const autoStartTriggeredRef = useRef(false);

  const clientOptions = useMemo<ChatKitClientOptions>(
    () => ({
      apiUrl: apiUrl.trim(),
      authToken: authToken.trim() || undefined,
      tenantId: tenantId.trim() || 'local'
    }),
    [apiUrl, authToken, tenantId]
  );

  const requestMetadata = useMemo(() => {
    const metadata: Record<string, unknown> = {};
    if (workflowId.trim()) metadata.workflow_id = workflowId.trim();
    if (workflowVersionId.trim()) metadata.workflow_version_id = workflowVersionId.trim();
    if (projectId.trim()) metadata.project_id = projectId.trim();
    if (domainKey.trim()) metadata.domain_key = domainKey.trim();
    return metadata;
  }, [workflowId, workflowVersionId, projectId, domainKey]);

  const applyEvent = (event: Parameters<typeof applyStreamEvent>[1]) => {
    setThreadState((prev) => applyStreamEvent(prev, event));
  };

  const runStreamingRequest = async (request: ChatKitRequest): Promise<void> => {
    setBusy(true);
    try {
      await streamRequest(request, clientOptions, applyEvent);
      setStatus('Connected');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Request failed');
      throw err;
    } finally {
      setBusy(false);
    }
  };

  const handleConnect = () => {
    if (!clientOptions.apiUrl) {
      setStatus('API URL is required');
      return;
    }
    if (!workflowId.trim()) {
      setStatus('Workflow ID is required');
      return;
    }
    setConnected(true);
    setStatus('Connected');
  };

  const sendUserMessage = async (rawText: string) => {
    const text = rawText;
    if (!connected) {
      setStatus('Connect first');
      return;
    }
    if (!workflowId.trim()) {
      setStatus('Workflow ID is required');
      return;
    }
    if (busy) return;

    const contentTextValue = text;
    if (!contentTextValue.trim() && !autoStart) {
      setStatus('Message is empty');
      return;
    }

    const input = {
      content: [{ type: 'input_text' as const, text: contentTextValue }],
      attachments: []
    };

    if (!threadState.threadId) {
      await runStreamingRequest({
        type: 'threads.create',
        metadata: requestMetadata,
        params: { input }
      });
      return;
    }

    await runStreamingRequest({
      type: 'threads.add_user_message',
      metadata: requestMetadata,
      params: {
        thread_id: threadState.threadId,
        input
      }
    });
  };

  const handleSend = async () => {
    const text = composerValue;
    if (!text.trim()) {
      setStatus('Message is empty');
      return;
    }
    setComposerValue('');
    try {
      await sendUserMessage(text);
    } catch {
      setComposerValue(text);
    }
  };

  const handleWidgetAction = async (action: WidgetActionPayload, payload?: Record<string, unknown>) => {
    if (!threadState.threadId) {
      setStatus('Thread is not initialized');
      return;
    }
    const actionType = action.action_type || action.type;
    if (!actionType) {
      setStatus('Widget action has no type');
      return;
    }

    const basePayload = typeof action.payload === 'object' && action.payload ? action.payload : {};
    const nextPayload = {
      ...basePayload,
      ...(payload || {})
    };

    await runStreamingRequest({
      type: 'threads.custom_action',
      metadata: requestMetadata,
      params: {
        thread_id: threadState.threadId,
        item_id: null,
        action: {
          action_type: actionType,
          type: actionType,
          payload: nextPayload
        }
      }
    });
  };

  const stt = useSttRecorder(async ({ audioBase64, mimeType }) => {
    if (!connected) {
      throw new Error('Connect first');
    }
    const result = await transcribeInput(
      {
        type: 'input.transcribe',
        metadata: requestMetadata,
        params: {
          audio_base64: audioBase64,
          mime_type: mimeType
        }
      },
      clientOptions
    );
    const transcript = (result.text || '').trim();
    if (!transcript) return;
    setComposerValue((prev) => (prev ? `${prev} ${transcript}` : transcript));
    setStatus('Speech transcribed');
  });

  useEffect(() => {
    if (autoConnect && workflowId.trim()) {
      handleConnect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!autoStart || !connected || autoStartTriggeredRef.current) return;
    if (threadState.threadId) return;
    autoStartTriggeredRef.current = true;
    void sendUserMessage(' ');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, connected, threadState.threadId]);

  const orderedItems = threadState.items;
  const latestProgress = threadState.progress[threadState.progress.length - 1];
  const latestError = threadState.errors[threadState.errors.length - 1] || stt.error;

  return (
    <Stack gap="sm" p={embed ? 0 : 'md'} h="100vh">
      {!embed && (
        <Card withBorder radius="md" padding="sm">
          <Stack gap="xs">
            <Group grow>
              <TextInput label="API URL" value={apiUrl} onChange={(e) => setApiUrl(e.currentTarget.value)} />
              <TextInput label="Domain key" value={domainKey} onChange={(e) => setDomainKey(e.currentTarget.value)} />
              <TextInput
                label="Tenant ID"
                value={tenantId}
                onChange={(e) => setTenantId(e.currentTarget.value)}
              />
            </Group>
            <Group grow>
              <TextInput
                label="Workflow ID"
                value={workflowId}
                onChange={(e) => setWorkflowId(e.currentTarget.value)}
              />
              <TextInput
                label="Workflow version"
                value={workflowVersionId}
                onChange={(e) => setWorkflowVersionId(e.currentTarget.value)}
              />
              <TextInput label="Project ID" value={projectId} onChange={(e) => setProjectId(e.currentTarget.value)} />
            </Group>
            <Group align="end" justify="space-between">
              <TextInput
                style={{ flex: 1 }}
                label="Auth token"
                type="password"
                value={authToken}
                onChange={(e) => setAuthToken(e.currentTarget.value)}
              />
              <Button onClick={handleConnect}>Connect</Button>
            </Group>
          </Stack>
        </Card>
      )}

      <Card withBorder radius="md" padding="sm">
        <Group justify="space-between" align="center">
          <Group gap="xs">
            <Badge color={connected ? 'teal' : 'gray'} variant="light">
              {connected ? 'Connected' : 'Disconnected'}
            </Badge>
            <Badge color="gray" variant="outline">
              {threadState.threadId || 'No thread'}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {latestProgress || status}
          </Text>
        </Group>
        {latestError && (
          <Text mt="xs" size="sm" c="red">
            {latestError}
          </Text>
        )}
      </Card>

      <Card withBorder radius="md" padding="sm" style={{ flex: 1, minHeight: 0 }}>
        <Stack gap="xs" h="100%">
          <Title order={5}>Thread</Title>
          <Divider />
          <ScrollArea style={{ flex: 1 }}>
            <Stack gap="sm" pr="xs">
              {orderedItems.length === 0 && (
                <Text size="sm" c="dimmed">
                  No messages yet.
                </Text>
              )}
              {orderedItems.map((item) => {
                if (item.type === 'user_message') {
                  return (
                    <Card key={item.id} radius="md" padding="sm" withBorder style={{ alignSelf: 'flex-end', maxWidth: '86%' }}>
                      <Text size="sm">{contentText(item)}</Text>
                    </Card>
                  );
                }

                if (item.type === 'assistant_message') {
                  return (
                    <Card key={item.id} radius="md" padding="sm" withBorder style={{ maxWidth: '90%' }}>
                      <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                        {contentText(item)}
                      </Text>
                    </Card>
                  );
                }

                if (isWidgetItem(item) && item.widget) {
                  return (
                    <Box key={item.id}>
                      <WidgetRenderer widget={item.widget} onAction={handleWidgetAction} />
                    </Box>
                  );
                }

                return (
                  <Card key={item.id} radius="md" padding="sm" withBorder>
                    <Text size="xs" c="dimmed">
                      {item.type}
                    </Text>
                    <Text size="xs" style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                      {JSON.stringify(item, null, 2)}
                    </Text>
                  </Card>
                );
              })}
            </Stack>
          </ScrollArea>
          <Divider />
          <Group align="flex-end" wrap="nowrap">
            <Textarea
              style={{ flex: 1 }}
              minRows={2}
              maxRows={6}
              value={composerValue}
              onChange={(event) => setComposerValue(event.currentTarget.value)}
              placeholder="Type a message"
            />
            <Stack gap={6}>
              <Button
                variant={stt.isRecording ? 'filled' : 'light'}
                color={stt.isRecording ? 'red' : 'blue'}
                onClick={() => void stt.toggle()}
                loading={stt.isBusy}
              >
                {stt.isRecording ? 'Stop Mic' : 'Mic'}
              </Button>
              <Button onClick={() => void handleSend()} disabled={busy || !composerValue.trim()}>
                Send
              </Button>
            </Stack>
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}
