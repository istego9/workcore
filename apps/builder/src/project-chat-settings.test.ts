import { describe, expect, it } from 'vitest';
import { buildProjectChatWorkflowOptions, getProjectChatWorkflowLabel, getProjectDefaultChatWorkflowId } from './project-chat-settings';

describe('project chat settings helpers', () => {
  it('reads the configured default chat workflow id from project settings', () => {
    expect(
      getProjectDefaultChatWorkflowId({
        project_id: 'proj_1',
        project_name: 'Project 1',
        tenant_id: 'local',
        settings: { default_chat_workflow_id: ' wf_chat ' },
        created_at: '',
        updated_at: ''
      })
    ).toBe('wf_chat');
  });

  it('prefers workflow name when rendering the project chat workflow label', () => {
    const project = {
      project_id: 'proj_1',
      project_name: 'Project 1',
      tenant_id: 'local',
      settings: { default_chat_workflow_id: 'wf_chat' },
      created_at: '',
      updated_at: ''
    };
    const workflows = [
      {
        workflow_id: 'wf_chat',
        project_id: 'proj_1',
        name: 'Support Chat',
        description: null,
        active_version_id: 'wfv_1',
        created_at: '',
        updated_at: ''
      }
    ];

    expect(getProjectChatWorkflowLabel(project, workflows)).toBe('Support Chat');
  });

  it('builds published workflow options and keeps the current unavailable value visible', () => {
    const workflows = [
      {
        workflow_id: 'wf_b',
        project_id: 'proj_1',
        name: 'Beta Chat',
        description: null,
        active_version_id: 'wfv_b',
        created_at: '',
        updated_at: ''
      },
      {
        workflow_id: 'wf_a',
        project_id: 'proj_1',
        name: 'Alpha Chat',
        description: null,
        active_version_id: 'wfv_a',
        created_at: '',
        updated_at: ''
      },
      {
        workflow_id: 'wf_draft',
        project_id: 'proj_1',
        name: 'Draft Only',
        description: null,
        active_version_id: null,
        created_at: '',
        updated_at: ''
      }
    ];

    expect(buildProjectChatWorkflowOptions('proj_1', workflows)).toEqual([
      { value: 'wf_a', label: 'Alpha Chat (wf_a)' },
      { value: 'wf_b', label: 'Beta Chat (wf_b)' }
    ]);

    expect(buildProjectChatWorkflowOptions('proj_1', workflows, 'wf_missing')[0]).toEqual({
      value: 'wf_missing',
      label: 'wf_missing (unavailable)'
    });
  });
});
