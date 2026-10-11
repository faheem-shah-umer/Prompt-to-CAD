const examplePrompt = 'Create a three-part spindle assembly. A mounting base is 80 by 60 by 8 mm with 3 mm vertical corner fillets and four 6 mm through holes on a 52 mm bolt circle. A separate 16 mm diameter spindle is 32 mm tall and rests on top of the base. Above it, make a separate 24 mm tall grip lofted through circles with diameters 16 mm at the bottom, 28 mm at the middle, and 16 mm at the top. All parts share the Z axis. Keep the spindle and grip positions linked to the base thickness and spindle height. Add contact and coaxial relationships.';

interface Props {
  value: string;
  busy: boolean;
  available: boolean;
  editing: boolean;
  selectedName?: string;
  onChange: (value: string) => void;
  onCreate: () => void;
}

export default function PromptForm({ value, busy, available, editing, selectedName, onChange, onCreate }: Props) {
  const canCreate = available && !busy && value.trim().length >= 5;
  const label = editing ? 'Apply change' : 'Create';
  return <form className="prompt-form" onSubmit={event => { event.preventDefault(); if (canCreate) onCreate(); }}>
    <p className="editor-intro">{editing ? selectedName ? `Describe what to change in ${selectedName}.` : 'Describe what to change across the assembly.' : 'Describe a part or multiple connected parts.'}</p>
    <label className="sr-only" htmlFor="part-description">{editing ? 'Explain Your Change' : 'Explain Our Idea'}</label>
    <textarea id="part-description" value={value} rows={8} minLength={5} maxLength={editing ? 8000 : 4000} disabled={busy}
      placeholder={editing ? selectedName ? 'Make this part taller, add a bore, round its edges…' : 'Add a component, move a part, change how parts connect…' : 'What should your design look like? Explain its shapes, sizes and how the parts connect…'}
      onChange={event => onChange(event.target.value)}
      onKeyDown={event => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
          event.preventDefault();
          if (canCreate) onCreate();
        }
      }} />
    <div className="editor-meta"><button className="text-button" type="button" disabled={busy} onClick={() => onChange(editing ? selectedName ? 'Add a 1 mm fillet to the top edges of this part.' : 'Increase the spindle height to 48 mm and keep the grip touching its top.' : examplePrompt)}>Use an example</button><span>{value.length.toLocaleString()} / {editing ? '8,000' : '4,000'}</span></div>
    <button className="create-button" type="submit" disabled={!canCreate}>{busy ? <><span className="spinner" aria-hidden="true" /> Working…</> : <><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m12 3 9 5v9l-9 5-9-5V8l9-5Z" /><path d="m3 8 9 5 9-5M12 13v9" /></svg>{label}</>}</button>
    <p className="create-shortcut"><kbd>Ctrl</kbd> + <kbd>Enter</kbd> to {editing ? 'apply' : 'create'}</p>
  </form>;
}
