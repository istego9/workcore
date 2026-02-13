export const shouldAutoCreateWorkflow = (
  workflowId: string,
  autoCreatedAlready: boolean,
  isTestEnv: boolean
) => {
  if (isTestEnv) return false;
  if (workflowId) return false;
  return !autoCreatedAlready;
};
