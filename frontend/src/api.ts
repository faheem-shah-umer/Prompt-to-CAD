export interface PlateSpec {
  description?: string;
  units: 'mm';
  length: number;
  width: number;
  thickness: number;
  hole_diameter: number;
  hole_centres: [number, number][];
}

export interface ValidationReport {
  passed: boolean;
  checks: Record<string, boolean>;
  dimensions_mm: number[];
  volume_mm3: number;
  measured_holes: { centre_xy_mm: number[]; diameter_mm: number }[];
  step_roundtrip?: ValidationReport;
}

export interface ModelResult {
  model_id: string;
  specification: PlateSpec;
  validation: ValidationReport;
  downloads: { step: string; stl: string; report: string };
}

export const exampleSpec: PlateSpec = {
  units: 'mm',
  length: 80,
  width: 50,
  thickness: 6,
  hole_diameter: 6,
  hole_centres: [[-25, -15], [25, -15], [-25, 15], [25, 15]],
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail.map((error: { msg: string }) => error.msg.replace(/^Value error, /, '')).join(' ')
      : typeof detail === 'string' ? detail : 'The CAD request failed.';
    throw new Error(message);
  }
  return data as T;
}

export function checkHealth() {
  return request<{ status: string }>('/health');
}

export function createModel(specification: PlateSpec) {
  return request<ModelResult>('/models', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(specification),
  });
}

export interface LLMStatus {
  provider: string;
  model: string;
  configured: boolean;
  message: string;
}

export interface PlanningResult {
  provider: string;
  model: string;
  seconds: number;
  interpretation: {
    status: 'ready' | 'needs_input' | 'unsupported';
    description: string;
    questions: string[];
    assumptions: string[];
  };
  specification: PlateSpec | null;
}

export interface GenerationResult {
  plan: PlanningResult;
  model: ModelResult | null;
  seconds: number;
}

export function createFromIdea(prompt: string) {
  return request<GenerationResult>('/generations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });
}

export function checkLLM() {
  return request<LLMStatus>('/llm');
}

export function interpretPrompt(prompt: string) {
  return request<PlanningResult>('/plans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });
}

export interface FeatureDefinition {
  id: string;
  type: string;
  [key: string]: unknown;
}

export interface ComponentDefinition {
  id: string;
  name: string;
  color: string;
  parameters: Record<string, number | string>;
  features: FeatureDefinition[];
  attachment?: { parent: string; axis: 'X' | 'Y' | 'Z'; side: -1 | 1; offset: (number | string)[]; gap: number | string } | null;
  placement: { translation: (number | string)[]; rotation: (number | string)[] };
  expected_size: (number | string)[] | null;
}

export interface EditableDesign {
  schema_version: 1;
  name: string;
  units: 'mm';
  parameters: Record<string, number | string>;
  components: ComponentDefinition[];
  relationships: { id: string; type: 'coaxial' | 'contact' | 'distance'; component_a: string; component_b: string }[];
  allowed_intersections: [string, string][];
}

export interface ComponentResult {
  id: string;
  name: string;
  color: string;
  parameters: Record<string, number>;
  features: { id: string; type: string; passed: boolean; volume_mm3?: number }[];
  preview_url: string;
  validation: {
    passed: boolean;
    checks: Record<string, boolean>;
    dimensions_mm: number[];
    local_dimensions_mm: number[];
    bounds_mm: number[][];
    volume_mm3: number;
    solid_count: number;
  };
}

export interface CadProject {
  project_id: string;
  revision_id: string;
  name: string;
  created_at: string;
  saved_at: string;
  summary: string;
  assumptions: string[];
  revision_number: number;
  revision_count: number;
  can_undo: boolean;
  can_redo: boolean;
  design: EditableDesign;
  components: ComponentResult[];
  validation: {
    passed: boolean;
    checks: Record<string, boolean>;
    dimensions_mm: number[];
    volume_mm3: number;
    solid_count: number;
    relationships: { id: string; type: string; passed: boolean; distance_mm?: number; axis_distance_mm?: number }[];
    warnings: string[];
    parameter_dependencies: Record<string, string[]>;
    component_dependencies: Record<string, string[]>;
  };
  downloads: { step: string; stl: string; project: string; report: string };
  history: { revision_id: string; saved_at: string; summary: string }[];
}

export interface ProjectSummary {
  project_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectOperation {
  plan: { status: 'ready' | 'needs_input' | 'unsupported'; description: string; questions: string[]; assumptions: string[] };
  project: CadProject | null;
  inference: { provider: string; model: string; seconds: number; strategy?: string; requests?: number; repairs?: number };
  seconds: number;
}

const post = <T,>(path: string, data: unknown) => request<T>(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
});

export const listProjects = () => request<ProjectSummary[]>('/projects');
export const openProject = (id: string) => request<CadProject>(`/projects/${id}`);
export const createProject = (prompt: string) => post<ProjectOperation>('/projects', { prompt });
export const importProject = (design: EditableDesign) => post<CadProject>('/projects/from-spec', design);
export const editProject = (project: CadProject, prompt: string, selectedId: string | null) =>
  post<ProjectOperation>(`/projects/${project.project_id}/edits`, {
    prompt, selected_component_id: selectedId, base_revision_id: project.revision_id,
  });
export const moveRevision = (project: CadProject, direction: 'undo' | 'redo') =>
  post<CadProject>(`/projects/${project.project_id}/${direction}`, { base_revision_id: project.revision_id });

export interface DesignJob {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: 'planning' | 'components' | 'editing' | 'verifying' | 'repairing' | 'exporting' | 'completed' | 'failed';
  message: string;
  components_completed: number;
  components_total: number;
  requests_used: number;
  elapsed_seconds: number;
  diagnostics_url: string;
  error: { message: string; http_status: number } | null;
  result: ProjectOperation | null;
}

export async function generateDesign(prompt: string, project: CadProject | undefined, selectedId: string | null,
                                     onProgress: (job: DesignJob) => void) {
  let job = await post<DesignJob>('/design-jobs', {
    prompt, project_id: project?.project_id ?? null,
    base_revision_id: project?.revision_id ?? null, selected_component_id: project ? selectedId : null,
  });
  while (true) {
    onProgress(job);
    if (job.status === 'failed') throw new Error(job.error?.message ?? 'The design could not be constructed.');
    if (job.status === 'completed') {
      if (!job.result) throw new Error('The generation finished without a result.');
      return job.result;
    }
    await new Promise<void>(resolve => window.setTimeout(resolve, 1200));
    job = await request<DesignJob>(`/design-jobs/${job.job_id}`);
  }
}
