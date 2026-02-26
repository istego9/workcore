import { Badge, Box, Button, Card, Divider, Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { useMemo, useState } from 'react';
import type { WidgetActionPayload, WidgetComponent, WidgetRoot } from '../protocol/types';
import { DataTable } from './extensions/DataTable';
import { NivoChart } from './extensions/NivoChart';

type WidgetRendererProps = {
  widget: WidgetRoot;
  onAction: (action: WidgetActionPayload, payload?: Record<string, unknown>) => void;
};

type FormScope = {
  values: Record<string, string>;
  setValue: (key: string, value: string) => void;
};

const collectInputDefaults = (children: WidgetComponent[] | undefined): Record<string, string> => {
  const values: Record<string, string> = {};
  (children || []).forEach((child) => {
    if (child.type === 'Input' && typeof child.name === 'string' && child.name) {
      const defaultValue = child.defaultValue;
      values[child.name] = typeof defaultValue === 'string' ? defaultValue : '';
    }
  });
  return values;
};

type FormBlockProps = {
  component: WidgetComponent;
  onAction: (action: WidgetActionPayload, payload?: Record<string, unknown>) => void;
  renderChild: (component: WidgetComponent, form?: FormScope) => JSX.Element;
};

function FormBlock({ component, onAction, renderChild }: FormBlockProps) {
  const defaults = useMemo(() => collectInputDefaults(component.children), [component.children]);
  const [values, setValues] = useState<Record<string, string>>(defaults);
  const formScope: FormScope = {
    values,
    setValue: (key, value) => setValues((prev) => ({ ...prev, [key]: value }))
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!component.onSubmitAction) return;
        onAction(component.onSubmitAction, { input: values });
      }}
    >
      <Stack gap="xs">{(component.children || []).map((child, index) => renderChild(child, formScope))}</Stack>
    </form>
  );
}

export function WidgetRenderer({ widget, onAction }: WidgetRendererProps) {
  const renderComponent = (component: WidgetComponent, form?: FormScope): JSX.Element => {
    const key = component.id || component.key || `${component.type}-${Math.random().toString(16).slice(2, 6)}`;

    if (component.type === 'Text') {
      return (
        <Text key={key} size="sm">
          {String(component.value || '')}
        </Text>
      );
    }

    if (component.type === 'Markdown') {
      return (
        <Text key={key} size="sm" style={{ whiteSpace: 'pre-wrap' }}>
          {String(component.value || '')}
        </Text>
      );
    }

    if (component.type === 'Title') {
      return (
        <Title key={key} order={5}>
          {String(component.value || '')}
        </Title>
      );
    }

    if (component.type === 'Divider') {
      return <Divider key={key} />;
    }

    if (component.type === 'Input') {
      const name = typeof component.name === 'string' ? component.name : '';
      const value = name && form ? form.values[name] || '' : '';
      return (
        <TextInput
          key={key}
          value={value}
          onChange={(event) => {
            if (!form || !name) return;
            form.setValue(name, event.currentTarget.value);
          }}
          placeholder={typeof component.placeholder === 'string' ? component.placeholder : name}
          required={Boolean(component.required)}
        />
      );
    }

    if (component.type === 'Button') {
      const action = component.onClickAction;
      const submit = Boolean(component.submit);
      return (
        <Button
          key={key}
          type={submit ? 'submit' : 'button'}
          variant={component.style === 'secondary' ? 'light' : 'filled'}
          onClick={() => {
            if (submit || !action) return;
            onAction(action);
          }}
        >
          {typeof component.label === 'string' ? component.label : 'Action'}
        </Button>
      );
    }

    if (component.type === 'Row') {
      return (
        <Group key={key} gap="xs" align="center">
          {(component.children || []).map((child) => renderComponent(child, form))}
        </Group>
      );
    }

    if (component.type === 'Col' || component.type === 'Box') {
      return (
        <Stack key={key} gap="xs">
          {(component.children || []).map((child) => renderComponent(child, form))}
        </Stack>
      );
    }

    if (component.type === 'Form') {
      return <FormBlock key={key} component={component} onAction={onAction} renderChild={renderComponent} />;
    }

    if (component.type === 'Chart') {
      return <NivoChart key={key} component={component} />;
    }

    if (component.type === 'DataTable') {
      return <DataTable key={key} component={component} />;
    }

    return (
      <Card key={key} withBorder radius="md" padding="sm">
        <Stack gap={4}>
          <Badge size="xs" color="yellow" variant="light">
            Unsupported widget component
          </Badge>
          <Text size="xs" c="dimmed">
            {component.type}
          </Text>
          <Text size="xs" style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
            {JSON.stringify(component, null, 2)}
          </Text>
        </Stack>
      </Card>
    );
  };

  if (widget.type === 'Card') {
    return (
      <Card withBorder radius="md" padding="md">
        <Stack gap="sm">{(widget.children || []).map((child) => renderComponent(child))}</Stack>
      </Card>
    );
  }

  if (widget.type === 'ListView') {
    return (
      <Stack gap="sm">
        {(widget.children || []).map((child, index) => (
          <Box key={child.id || `list-item-${index}`}>{renderComponent(child)}</Box>
        ))}
      </Stack>
    );
  }

  return (
    <Card withBorder radius="md" padding="sm">
      <Stack gap={4}>
        <Badge size="xs" color="yellow" variant="light">
          Unsupported widget root
        </Badge>
        <Text size="xs" c="dimmed">
          {widget.type}
        </Text>
      </Stack>
    </Card>
  );
}
