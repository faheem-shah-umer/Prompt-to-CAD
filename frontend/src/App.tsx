import { useEffect, useRef, useState } from 'react';
import { checkHealth, checkLLM, createProject, editProject, importProject, listProjects, moveRevision, openProject } from './api';
import type { CadProject, ComponentResult, EditableDesign, LLMStatus, ProjectOperation, ProjectSummary } from './api';
import CadViewer from './components/CadViewer';
import PromptForm from './components/PromptForm';

const number = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 3 });
const readable = (text: string) => text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '');
const EMPTY_PARTS: ComponentResult[] = [];
const checkLabels: Record<string, string> = {
  all_components_valid: 'All component solids valid', relationships_pass: 'Assembly relationships',
  no_unexpected_intersections: 'No unexpected interference', step_roundtrip_valid: 'STEP preserves separate parts',
  brep_valid: 'Valid CAD solid', one_solid: 'One connected body', positive_volume: 'Positive volume',
  feature_history_valid: 'Feature history rebuilt', expected_dimensions_match: 'Specified overall dimensions',
};

export default function App() {
  const [prompt, setPrompt] = useState('');
  const [project, setProject] = useState<CadProject>();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const [status, setStatus] = useState<LLMStatus>();
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState('');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState<ProjectOperation>();
  const [lastSeconds, setLastSeconds] = useState<number>();
  const [saved, setSaved] = useState<ProjectSummary[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [projectListError, setProjectListError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const submitting = useRef(false);

  useEffect(() => {
    let active = true;
    setConnecting(true);
    Promise.all([checkHealth(), checkLLM()]).then(([, value]) => {
      if (active) { setStatus(value); setConnected(true); setConnecting(false); }
    }).catch(() => {
      if (active) { setConnected(false); setConnecting(false); }
    });
    return () => { active = false; };
  }, [connectionAttempt]);

  const parts = project?.components ?? EMPTY_PARTS;
  const selected = parts.find(part => part.id === selectedId);
  const definition = project?.design.components.find(part => part.id === selectedId);
  const available = connected && status?.configured === true;
  const blocked = attempt && !attempt.project;
  const modelName = status?.model.split('/').pop() || 'Model';
  const checks = selected?.validation.checks ?? project?.validation.checks;
  const assumptions = project?.assumptions ?? [];
  const scope = selected ? selected.name : 'Assembly';

  function selectPart(id: string | null) {
    if (busy || id === selectedId) return;
    setSelectedId(id);
    if (id) setHiddenIds(ids => ids.filter(item => item !== id));
    setPrompt('');
    setAttempt(undefined);
    setError('');
  }

  function acceptProject(value: CadProject, keepSelection = false) {
    setProject(value);
    if (!keepSelection || !value.components.some(part => part.id === selectedId)) setSelectedId(null);
    if (!keepSelection) setHiddenIds([]);
    else setHiddenIds(ids => ids.filter(id => value.components.some(part => part.id === id)));
    setPrompt('');
    setAttempt(undefined);
  }

  function newProject() {
    if (busy) return;
    setProject(undefined);
    setSelectedId(null);
    setHiddenIds([]);
    setPrompt('');
    setAttempt(undefined);
    setError('');
    setLastSeconds(undefined);
  }

  async function operation(label: string, action: () => Promise<void>) {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setBusyLabel(label);
    setError('');
    setAttempt(undefined);
    try { await action(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'The project operation failed.'); }
    finally { submitting.current = false; setBusy(false); setBusyLabel(''); }
  }

  async function createOrEdit() {
    if (!available || prompt.trim().length < 5) return;
    const description = prompt.trim();
    await operation(project ? `Updating ${scope}…` : 'Creating project…', async () => {
      const result = project ? await editProject(project, description, selectedId) : await createProject(description);
      setLastSeconds(result.seconds);
      if (result.project) acceptProject(result.project, Boolean(project));
      else setAttempt(result);
    });
  }

  async function showProjects() {
    if (busy) return;
    dialog.current?.showModal();
    setLoadingProjects(true);
    setProjectListError('');
    try { setSaved(await listProjects()); }
    catch (reason) { setProjectListError(reason instanceof Error ? reason.message : 'Saved projects could not be loaded.'); }
    finally { setLoadingProjects(false); }
  }

  async function loadSaved(id: string) {
    dialog.current?.close();
    await operation('Opening saved project…', async () => {
      acceptProject(await openProject(id));
      setLastSeconds(undefined);
    });
  }

  async function loadFile(file: File) {
    dialog.current?.close();
    await operation('Rebuilding editable project…', async () => {
      if (file.size > 2_000_000) throw new Error('Editable project files must be smaller than 2 MB.');
      let design: EditableDesign;
      try { design = JSON.parse(await file.text()) as EditableDesign; }
      catch { throw new Error('This is not a valid JSON project file. Choose a saved .cad.json file.'); }
      acceptProject(await importProject(design));
      setLastSeconds(undefined);
    });
  }

  async function history(direction: 'undo' | 'redo') {
    if (!project) return;
    await operation(direction === 'undo' ? 'Restoring previous revision…' : 'Restoring next revision…', async () => {
      acceptProject(await moveRevision(project, direction), true);
      setLastSeconds(undefined);
    });
  }

  const workspaceStatus = busy ? busyLabel : connecting ? 'Connecting to the CAD engine…'
    : !connected ? 'CAD engine offline' : error ? project ? 'Request failed · Saved revision retained' : 'Request failed'
    : blocked ? 'More detail needed before this change can be saved'
    : project ? `Saved · Revision ${project.revision_number} · ${selected ? `Editing ${selected.name}` : 'Editing assembly'}`
    : available ? 'Ready · Describe a part or an assembly' : 'Configure your LLM to create from an idea';

  return <div className="app-shell">
    <header className="app-commandbar">
      <div className="brand"><img src="/app-icon.png" alt="" className="brand-icon" /><div><span>Prompt to CAD</span><small>Parametric design workspace</small></div></div>
      <div className="document-actions">
        <button className="quiet-button new-button" type="button" disabled={busy} onClick={newProject}><span aria-hidden="true">＋</span> New</button>
        <button className="quiet-button" type="button" disabled={busy || !connected} onClick={() => void showProjects()}>Open</button>
        <span className="toolbar-divider" />
        <button className="quiet-button" type="button" disabled={busy || !project?.can_undo} onClick={() => void history('undo')}>↶ Undo</button>
        <button className="quiet-button" type="button" disabled={busy || !project?.can_redo} onClick={() => void history('redo')}>↷ Redo</button>
      </div>
      <div className="engine-indicator" title={status?.model}><span className={`connection-dot ${available ? 'connected' : ''}`} aria-hidden="true" /><span>{connecting ? 'Connecting…' : `${status?.provider ?? 'LLM'} · ${modelName}`}</span></div>
    </header>

    <main className="workspace">
      <aside className="idea-panel" aria-label="Idea editor and parts">
        <div className="panel-heading"><h1>{project ? 'Explain Your Change' : 'Explain Our Idea'}</h1><span className="panel-tag">{project ? 'EDIT' : 'CREATE'}</span></div>
        {project && <div className="edit-scope"><span>Editing</span><strong title={scope}>{scope}</strong>{selected && <button type="button" className="text-button" disabled={busy} onClick={() => selectPart(null)}>Assembly</button>}</div>}
        <PromptForm value={prompt} busy={busy} available={available} editing={Boolean(project)} selectedName={selected?.name}
          onChange={value => { setPrompt(value); setError(''); setAttempt(undefined); }} onCreate={() => void createOrEdit()} />
        {(!connected && !connecting || status && !status.configured) && <div className="feedback" role="alert">
          <p>{connected ? status?.message : 'The CAD engine could not be reached. Reopen the application or retry.'}</p>
          <button className="text-button" type="button" onClick={() => setConnectionAttempt(value => value + 1)}>Retry connection</button>
        </div>}
        {error && <div className="feedback" role="alert"><h2>Could not save this change</h2><p>{readable(error)}</p>{project && <p>Your saved design is still available.</p>}</div>}
        {blocked && <div className="feedback clarification" role="status">
          <h2>{attempt.plan.status === 'needs_input' ? 'A little more detail' : 'Modelling capability needed'}</h2>
          <p>{readable(attempt.plan.description)}</p>
          {attempt.plan.questions.length > 0 && <ul>{attempt.plan.questions.map((question, index) => <li key={index}>{readable(question)}</li>)}</ul>}
          <p className="feedback-action">Update your request and try again.</p>
        </div>}
        {project ? <section className="parts-tree" aria-label="Components">
          <div className="tree-heading"><h2>Components</h2><span>{parts.length}</span></div>
          <button type="button" className={`assembly-row ${!selectedId ? 'selected' : ''}`} disabled={busy}
            aria-pressed={!selectedId} onClick={() => selectPart(null)}>◇ <span>{project.name}</span></button>
          <ul>{parts.map(part => <li key={part.id} className={`part-row ${selectedId === part.id ? 'selected' : ''} ${hiddenIds.includes(part.id) ? 'hidden' : ''}`}>
            <button type="button" className="part-select" disabled={busy} aria-pressed={selectedId === part.id}
              onClick={() => selectPart(part.id)}><span className="part-swatch" style={{ background: part.color }} /><span>{part.name}</span></button>
            <button className="visibility-button" type="button" disabled={busy} aria-label={`${hiddenIds.includes(part.id) ? 'Show' : 'Hide'} ${part.name}`}
              onClick={() => setHiddenIds(ids => ids.includes(part.id) ? ids.filter(id => id !== part.id) : [...ids, part.id])}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />{hiddenIds.includes(part.id) && <path d="m3 3 18 18" />}
              </svg>
            </button>
          </li>)}</ul>
          <p>Click a part here or in 3D to edit it.</p>
        </section> : <div className="scope-note"><span className="section-label">Modelling tools</span><p>Sketch · Extrude · Revolve · Sweep · Loft<br />Booleans · Fillet · Chamfer · Patterns · Thread</p><small>Describe separate parts and how they connect. Unspecified sizes may be estimated and listed for review.</small></div>}
      </aside>

      <section className="model-panel" aria-label="3D workspace">
        <div className="viewport-toolbar"><div className="document-name"><span className="document-dot" aria-hidden="true" /><h2 title={project?.name}>{project?.name ?? 'Untitled project'}</h2></div><span className="model-status">{project ? `Saved · R${project.revision_number}` : 'No project yet'}</span></div>
        <CadViewer documentId={project?.project_id} parts={parts} selectedId={selectedId} hiddenIds={hiddenIds} busy={busy} onSelect={selectPart} />
        <div className="model-footer"><span>{project ? `${parts.length} ${parts.length === 1 ? 'component' : 'components'} · ${project.validation.dimensions_mm.map(number).join(' × ')} mm` : 'Parametric solids · Separate components · Editable projects'}</span>{lastSeconds !== undefined && <span>{lastSeconds.toFixed(2)} s</span>}</div>
        <div className={`workflow ${busy ? 'running' : ''} ${project ? 'complete' : ''}`} aria-busy={busy}>
          <div className="workflow-heading"><span className="section-label">Description to CAD</span><span>{busy ? 'Working…' : project ? 'Revision saved' : 'Create your first project'}</span></div>
          <ol className="workflow-steps" aria-label="Creation workflow">{['Interpret', 'Parameters', 'Feature history', 'Verify', 'Save & export'].map((step, index) => <li key={step}><span className="step-marker">{project && !busy ? '✓' : index + 1}</span><span>{step}</span></li>)}</ol>
        </div>
      </section>

      <aside className="inspector" aria-label="Design inspector">
        <div className="panel-heading"><h2>{selected ? 'Selected Part' : 'Project Inspector'}</h2><span className="panel-tag">{selected ? 'PART' : 'ASSEMBLY'}</span></div>
        <div className="inspector-content">
          {project ? <>
            <section className="inspector-section">
              <h3>{selected?.name ?? project.name}</h3>
              <p className="part-description">{selected ? `Component ID: ${selected.id}` : readable(project.summary)}</p>
              <dl className="property-list">
                {(selected ? selected.validation.local_dimensions_mm : project.validation.dimensions_mm).map((size, index) => <div key={index}><dt>{['X extent', 'Y extent', 'Z extent'][index]}</dt><dd>{number(size)} <span>mm</span></dd></div>)}
                <div><dt>Volume</dt><dd>{number(selected?.validation.volume_mm3 ?? project.validation.volume_mm3)} <span>mm³</span></dd></div>
              </dl>
              <p className="review-note">Measured {selected ? 'in the part’s local coordinates' : 'across the assembly'}. Review sizes and assumptions before manufacture.</p>
            </section>
            {selected && definition && <>
              <section className="inspector-section">
                <h3>Parameters</h3><dl className="property-list parameter-list">{Object.entries(selected.parameters).map(([key, value]) => <div key={key}><dt title={key}>{key.replaceAll('_', ' ')}</dt><dd>{number(value)}</dd></div>)}</dl>
                {!Object.keys(selected.parameters).length && <p className="part-description">This part uses values directly in its features.</p>}
                <p className="review-note">Ask for a change to update these values.</p>
                <details className="feature-details"><summary>Placement & expressions</summary><pre>{JSON.stringify({ parameters: definition.parameters, placement: definition.placement }, null, 2)}</pre></details>
              </section>
              <section className="inspector-section"><h3>Feature History</h3><ol className="feature-list">{definition.features.map((feature, index) => <li key={feature.id}><details><summary><span className="feature-index">{index + 1}</span><span><strong>{feature.type.replaceAll('_', ' ')}</strong><small>{feature.id}</small></span><span className="check-pass">✓</span></summary><pre>{JSON.stringify(feature, null, 2)}</pre></details></li>)}</ol></section>
            </>}
            {!selected && project.design.relationships.length > 0 && <section className="inspector-section"><h3>Assembly Relationships</h3><ul className="relationship-list">{project.design.relationships.map(relation => <li key={relation.id}><span className="check-pass">✓</span><div><strong>{relation.type}</strong><small>{relation.component_a} ↔ {relation.component_b}</small></div></li>)}</ul><p className="review-note">Placements are defined by parameters; declared relationships are checked after rebuilding.</p></section>}
            {assumptions.length > 0 && <section className="inspector-section"><div className="assumptions"><h4>Review assumptions</h4><ul>{assumptions.map((text, index) => <li key={index}>{readable(text)}</li>)}</ul></div></section>}
            <section className="inspector-section verification"><h3>Geometry checks <span className="verified-count">{Object.values(checks ?? {}).filter(Boolean).length} passed</span></h3><ul>{Object.entries(checks ?? {}).map(([key, passed]) => <li key={key}><span className={passed ? 'check-pass' : 'check-fail'}>{passed ? '✓' : '×'}</span>{checkLabels[key] ?? key.replaceAll('_', ' ')}</li>)}</ul>{project.validation.warnings.map(warning => <p className="review-note" key={warning}>{warning}</p>)}</section>
            <section className="inspector-section"><h3>Revisions</h3><ol className="revision-list">{project.history.map((revision, index) => <li key={revision.revision_id} className={revision.revision_id === project.revision_id ? 'current' : ''}><span>R{index + 1}</span><div><p>{readable(revision.summary)}</p><small>{new Date(revision.saved_at).toLocaleString()}</small></div></li>)}</ol></section>
          </> : <div className="inspector-empty"><h3>An editable design</h3><p>Each part keeps its own parameters and construction steps. Select it to inspect its history and request a change.</p><p>Projects save automatically after geometry and STEP checks pass. Use Open to continue a saved project.</p><p>Assembly checks cover contact, aligned axes and unexpected interference.</p></div>}
        </div>
        <div className="exports"><span className="section-label">Save & export</span><div className="export-buttons">{project ? <><a href={project.downloads.step} download>STEP <span>↓</span></a><a href={project.downloads.stl} download>STL <span>↓</span></a></> : <><button disabled>STEP ↓</button><button disabled>STL ↓</button></>}</div>{project ? <div className="export-links"><a className="report-link" href={project.downloads.project} download>Editable project ↓</a><a className="report-link" href={project.downloads.report} download>Verification ↓</a></div> : <p>STEP for CAD · JSON to retain feature history</p>}</div>
      </aside>
    </main>

    <footer className="statusbar"><span className="workspace-status" role="status"><span className={`connection-dot ${connected ? 'connected' : ''}`} aria-hidden="true" />{workspaceStatus}</span><div><span>mm</span><span>CAD on CPU</span></div></footer>
    <dialog className="project-dialog" ref={dialog}>
      <div className="dialog-heading"><div><img src="/app-icon.png" alt="" /><h2>Open a project</h2></div><button type="button" className="quiet-button" onClick={() => dialog.current?.close()}>Close</button></div>
      <p className="dialog-intro">Continue a saved design with its parts, parameters and feature history.</p>
      {loadingProjects ? <p className="dialog-note" role="status">Loading saved projects…</p> : projectListError ? <p className="dialog-note" role="alert">{projectListError}</p> : saved.length ? <ul className="saved-projects">{saved.map(item => <li key={item.project_id}><button type="button" onClick={() => void loadSaved(item.project_id)}><span><strong>{item.name}</strong><small>{new Date(item.updated_at).toLocaleString()}</small></span><span aria-hidden="true">↗</span></button></li>)}</ul> : <p className="dialog-note">No saved projects yet. Create your first design or open an editable project file.</p>}
      <div className="dialog-footer"><button className="quiet-button" type="button" onClick={() => fileInput.current?.click()}>Open .cad.json file</button><p>STEP import is planned for a later milestone.</p></div>
    </dialog>
    <input ref={fileInput} className="sr-only" type="file" accept=".json,.cad.json,application/json" aria-label="Open editable project file" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void loadFile(file); }} />
  </div>;
}
