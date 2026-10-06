import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError } from "../../api/client";
import { createProject } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import type {
  ProjectSetupContactInput,
  ProjectSetupIdentifierInput,
  ProjectSetupRequirementInput,
} from "../../api/types";
import { queryClient } from "../../lib/queryClient";

type Editable<T> = T & { key: number };

export function NewProjectPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [identifiers, setIdentifiers] = useState<Array<Editable<ProjectSetupIdentifierInput>>>([]);
  const [contacts, setContacts] = useState<Array<Editable<ProjectSetupContactInput>>>([]);
  const [requirements, setRequirements] = useState<Array<Editable<ProjectSetupRequirementInput>>>([]);
  const [nextKey, setNextKey] = useState(1);
  const setup = useMutation({
    mutationFn: createProject,
    onSuccess: (workspace) => {
      queryClient.setQueryData(queryKeys.projectWorkspace(workspace.project.id), workspace);
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      navigate(`/projects/${workspace.project.id}`, { replace: true });
    },
  });

  function key() {
    const value = nextKey;
    setNextKey((current) => current + 1);
    return value;
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setup.mutate({
      name: name.trim(),
      identifiers: identifiers.map((item) => ({
        identifier_type: item.identifier_type,
        display_value: item.display_value,
      })),
      contacts: contacts.map((item) => ({
        email: item.email,
        display_name: item.display_name,
        role: item.role?.trim() || null,
      })),
      requirements: requirements.map((item) => ({
        name: item.name,
        description: item.description?.trim() || null,
        expected_date: item.expected_date || null,
      })),
    });
  }

  return (
    <article className="setup-page">
      <Link className="back-link" to="/projects">Projects</Link>
      <header className="page-header setup-header">
        <div className="setup-title"><h1>New project</h1><span>Setup</span></div>
      </header>

      <form className="setup-form" onSubmit={submit}>
        <section className="form-section" aria-labelledby="project-identity-title">
          <div className="form-section-heading">
            <h2 id="project-identity-title">Project identity</h2>
            <p>Required</p>
          </div>
          <div className="form-section-content"><label className="field field-wide">
              <span>Project name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} required />
            </label></div>
        </section>

        <SetupCollection
          title="Matching identifiers"
          description="Optional external references used for matching."
          addLabel="Add identifier"
          empty="No identifiers added."
          onAdd={() => setIdentifiers((items) => [...items, { key: key(), identifier_type: "", display_value: "" }])}
          items={identifiers.map((item, index) => (
            <div className="form-register-row identifier-input-row" key={item.key}>
              <label className="field"><span>Type</span><input value={item.identifier_type} onChange={(event) => setIdentifiers((items) => update(items, index, "identifier_type", event.target.value))} required /></label>
              <label className="field"><span>Value</span><input value={item.display_value} onChange={(event) => setIdentifiers((items) => update(items, index, "display_value", event.target.value))} required /></label>
              <RemoveButton onClick={() => setIdentifiers((items) => remove(items, index))} label="Remove identifier" />
            </div>
          ))}
        />

        <SetupCollection
          title="Trusted contacts"
          description="Known senders used as identity evidence."
          addLabel="Add contact"
          empty="No trusted contacts added."
          onAdd={() => setContacts((items) => [...items, { key: key(), email: "", display_name: "", role: "" }])}
          items={contacts.map((item, index) => (
            <div className="form-register-row contact-input-row" key={item.key}>
              <label className="field"><span>Email</span><input type="email" value={item.email} onChange={(event) => setContacts((items) => update(items, index, "email", event.target.value))} required /></label>
              <label className="field"><span>Name</span><input value={item.display_name} onChange={(event) => setContacts((items) => update(items, index, "display_name", event.target.value))} required /></label>
              <label className="field"><span>Role (optional)</span><input value={item.role ?? ""} onChange={(event) => setContacts((items) => update(items, index, "role", event.target.value))} /></label>
              <RemoveButton onClick={() => setContacts((items) => remove(items, index))} label="Remove contact" />
            </div>
          ))}
        />

        <SetupCollection
          title="Initial requirements"
          description="Created as OPEN."
          addLabel="Add requirement"
          empty="No initial requirements added."
          onAdd={() => setRequirements((items) => [...items, { key: key(), name: "", description: "", expected_date: "" }])}
          items={requirements.map((item, index) => (
            <div className="form-register-row requirement-input-row" key={item.key}>
              <label className="field"><span>Requirement</span><input value={item.name} onChange={(event) => setRequirements((items) => update(items, index, "name", event.target.value))} required /></label>
              <label className="field"><span>Expected date (optional)</span><input type="date" value={item.expected_date ?? ""} onChange={(event) => setRequirements((items) => update(items, index, "expected_date", event.target.value))} /></label>
              <RemoveButton onClick={() => setRequirements((items) => remove(items, index))} label="Remove requirement" />
              <label className="field requirement-description-field"><span>Description (optional)</span><input value={item.description ?? ""} onChange={(event) => setRequirements((items) => update(items, index, "description", event.target.value))} /></label>
            </div>
          ))}
        />

        {setup.isError ? (
          <p className="form-error" role="alert">
            {setup.error instanceof ApiError && setup.error.kind === "conflict"
              ? "Project setup conflicts with existing configuration."
              : "The project could not be created."}
          </p>
        ) : null}
        <div className="form-actions"><p>Project, identifiers, contacts, and requirements are created together.</p>
          <div>
          <Link className="secondary-button button-link" to="/projects">Cancel</Link>
          <button className="primary-button" type="submit" disabled={setup.isPending}>
            {setup.isPending ? "Creating project" : "Create project"}
          </button>
          </div>
        </div>
      </form>
    </article>
  );
}

function SetupCollection({ title, description, addLabel, empty, onAdd, items }: {
  title: string;
  description: string;
  addLabel: string;
  empty: string;
  onAdd: () => void;
  items: React.ReactNode[];
}) {
  return (
    <section className="form-section">
      <div className="form-section-heading"><h2>{title}</h2><p>{description}</p></div>
      <div className="form-section-content collection-content">
        <div className="collection-toolbar">{items.length ? <span>{items.length} added</span> : <span>{empty}</span>}<button className="secondary-button" type="button" onClick={onAdd}>{addLabel}</button></div>
        {items.length ? <div className="form-register">{items}</div> : null}
      </div>
    </section>
  );
}

function RemoveButton({ onClick, label }: { onClick: () => void; label: string }) {
  return <button className="text-button remove-button" type="button" onClick={onClick}>{label}</button>;
}

function update<T, K extends keyof T>(items: T[], index: number, field: K, value: T[K]): T[] {
  return items.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item);
}

function remove<T>(items: T[], index: number): T[] {
  return items.filter((_, itemIndex) => itemIndex !== index);
}
