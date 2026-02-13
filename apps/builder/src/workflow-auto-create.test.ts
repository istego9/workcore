import { shouldAutoCreateWorkflow } from './workflow-auto-create';

describe('shouldAutoCreateWorkflow', () => {
  it('returns false for webdriver test runs', () => {
    expect(shouldAutoCreateWorkflow('', false, true)).toBe(false);
  });

  it('returns false when a workflow is already loaded', () => {
    expect(shouldAutoCreateWorkflow('wf_12345678', false, false)).toBe(false);
  });

  it('returns false after an auto-created workflow was already created', () => {
    expect(shouldAutoCreateWorkflow('', true, false)).toBe(false);
  });

  it('returns true only for empty non-test initial state', () => {
    expect(shouldAutoCreateWorkflow('', false, false)).toBe(true);
  });
});
