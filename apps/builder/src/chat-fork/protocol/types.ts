export type ChatRole = 'user' | 'assistant' | 'system';

export type ChatContent = {
  type?: string;
  text?: string;
};

export type ChatAttachmentRef = {
  id: string;
  name?: string;
  mime_type?: string;
};

export type ChatKitUserInput = {
  content: Array<{ type: 'input_text' | 'input_tag'; text: string }>;
  attachments: ChatAttachmentRef[];
  quoted_text?: string | null;
  inference_options?: Record<string, unknown>;
};

export type ChatKitAction = {
  action_type?: string;
  type?: string;
  payload?: Record<string, unknown>;
};

export type ThreadCreateRequest = {
  type: 'threads.create';
  metadata?: Record<string, unknown>;
  params: {
    input: ChatKitUserInput;
  };
};

export type AddUserMessageRequest = {
  type: 'threads.add_user_message';
  metadata?: Record<string, unknown>;
  params: {
    thread_id: string;
    input: ChatKitUserInput;
  };
};

export type CustomActionRequest = {
  type: 'threads.custom_action';
  metadata?: Record<string, unknown>;
  params: {
    thread_id: string;
    item_id: string | null;
    action: ChatKitAction;
  };
};

export type InputTranscribeRequest = {
  type: 'input.transcribe';
  metadata?: Record<string, unknown>;
  params: {
    audio_base64: string;
    mime_type: string;
  };
};

export type ChatKitRequest =
  | ThreadCreateRequest
  | AddUserMessageRequest
  | CustomActionRequest
  | InputTranscribeRequest;

export type TranscriptionResult = {
  text: string;
};

export type WidgetActionPayload = {
  type?: string;
  action_type?: string;
  payload?: Record<string, unknown>;
};

export type WidgetComponent = {
  id?: string;
  key?: string;
  type: string;
  children?: WidgetComponent[];
  value?: string;
  label?: string;
  name?: string;
  placeholder?: string;
  required?: boolean;
  submit?: boolean;
  style?: string;
  data?: Array<Record<string, string | number>>;
  series?: Array<Record<string, unknown>>;
  xAxis?: string | Record<string, unknown>;
  onClickAction?: WidgetActionPayload;
  onSubmitAction?: WidgetActionPayload;
  columns?: Array<{ key: string; label: string; align?: 'left' | 'center' | 'right' }>;
  rows?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type WidgetRoot = {
  type: string;
  children?: WidgetComponent[];
  [key: string]: unknown;
};

export type ThreadItem = {
  id: string;
  type: string;
  created_at?: string;
  thread_id?: string;
  content?: ChatContent[];
  widget?: WidgetRoot;
  [key: string]: unknown;
};

export type ChatKitStreamEvent = {
  type: string;
  thread?: { id: string; metadata?: Record<string, unknown> };
  item?: ThreadItem;
  item_id?: string;
  update?: Record<string, unknown>;
  text?: string;
  message?: string;
  level?: string;
  stream_options?: Record<string, unknown>;
  [key: string]: unknown;
};
