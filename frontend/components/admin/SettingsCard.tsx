"use client";

import { useCallback, useEffect, useState } from "react";
import { Explain } from "@/components/admin/Explain";
import { ApiError, getJSON, type SettingRow, type SettingsView, sendJSON } from "@/lib/api";
import { settingMore } from "@/lib/adminHelp";

const SOURCE: Record<SettingRow["source"], string> = {
  default: "default",
  config: "config.yaml",
  local: "set here",
  env: "env",
};

type Draft = Record<string, string>;
const asText = (v: string | number) => String(v);

function parse(row: SettingRow, text: string): string | number {
  return row.control === "int" ? Number.parseInt(text, 10) : row.control === "float" ? Number(text) : text;
}

function Control({ row, value, onChange }: { row: SettingRow; value: string; onChange: (v: string) => void }) {
  const id = `set-${row.key}`;
  if (row.control === "choice")
    return (
      <select id={id} value={value} disabled={!row.editable} onChange={(e) => onChange(e.target.value)}>
        {(row.options ?? [asText(row.value)]).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  return (
    <input
      id={id}
      type={row.control === "text" ? "text" : "number"}
      inputMode={row.control === "text" ? undefined : "decimal"}
      min={row.min ?? undefined}
      max={row.max ?? undefined}
      step={row.control === "float" ? 0.01 : 1}
      value={value}
      disabled={!row.editable}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** Retrieval and answer settings, saved to config.local.yaml; applies from the next question. */
export function SettingsCard() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [note, setNote] = useState<{ group: string; text: string; bad?: boolean } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);

  const adopt = useCallback((v: SettingsView) => {
    setView(v);
    setDraft(Object.fromEntries(v.groups.flatMap((g) => g.rows.map((r) => [r.key, asText(r.value)]))));
  }, []);

  useEffect(() => {
    getJSON<SettingsView>("/admin/settings")
      .then(adopt)
      .catch(() => setLoadError(true));
  }, [adopt]);

  async function save(group: string, changes: Record<string, string | number | null>) {
    setSaving(group);
    setNote(null);
    setErrors({});
    try {
      adopt(await sendJSON<SettingsView>("PUT", "/admin/settings", changes));
      setNote({ group, text: "Saved. The next question uses these settings." });
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.detail && typeof e.detail === "object")
        setErrors(e.detail as Record<string, string>);
      else setNote({ group, text: (e as Error).message, bad: true });
    } finally {
      setSaving(null);
    }
  }

  if (loadError) return <p className="notice bad">Couldn&apos;t load the settings.</p>;
  if (!view) return <p className="muted">Reading the settings…</p>;

  return (
    <>
      {view.groups.map((g) => {
        const dirty = g.rows.filter((r) => r.editable && draft[r.key] !== asText(r.value));
        return (
          <section key={g.name} className="admin-card" aria-labelledby={`g-${g.name}`}>
            <header className="admin-card-head">
              <h2 id={`g-${g.name}`}>Settings · {g.name}</h2>
              <span className="admin-actions">
                {note?.group === g.name && (
                  <span className={`action-note${note.bad ? " bad" : ""}`}>{note.text}</span>
                )}
                <button
                  type="button"
                  className="quiet-btn"
                  disabled={dirty.length === 0 || saving !== null}
                  onClick={() => save(g.name, Object.fromEntries(dirty.map((r) => [r.key, parse(r, draft[r.key])])))}
                >
                  {saving === g.name ? "Saving…" : "Save changes"}
                </button>
              </span>
            </header>
            <dl className="kv settings">
              {g.rows.map((r) => (
                <div key={r.key} className="setting">
                  <dt>
                    <label htmlFor={`set-${r.key}`}>{r.label}</label>
                    <span className={`source ${r.source}`}>
                      {r.source === "env" ? `env: ${r.locked_by}` : SOURCE[r.source]}
                    </span>
                  </dt>
                  <dd>
                    <Control row={r} value={draft[r.key] ?? ""} onChange={(v) => setDraft({ ...draft, [r.key]: v })} />
                    {r.source === "local" && (
                      <button
                        type="button"
                        className="text-btn"
                        disabled={saving !== null}
                        onClick={() => save(g.name, { [r.key]: null })}
                      >
                        Reset
                      </button>
                    )}
                    <span className="help">{r.locked_by ? `Set by ${r.locked_by}; change it there.` : r.help}</span>
                    <Explain more={settingMore[r.key]} />
                    {errors[r.key] && <span className="field-error">{errors[r.key]}</span>}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        );
      })}
      <details className="admin-card readonly">
        <summary>Fixed settings</summary>
        <dl className="kv settings">
          {view.readonly.map((r) => (
            <div key={r.key} className="setting">
              <dt>{r.key}</dt>
              <dd>
                <code>{r.value}</code>
                <span className="help">{r.reason}</span>
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </>
  );
}
